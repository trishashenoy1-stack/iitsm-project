from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest

from app.config import Settings
from app.intelligence.duplicates import (
    Correlator,
    DuplicateConfig,
    DuplicateDetector,
    MatchReason,
)
from app.intelligence.embedder import Embedder, HashingEmbedder, MiniLMEmbedder
from app.intelligence.text import incident_text
from app.p4_contracts import title_of
from tests.fakes.in_memory import EMAIL, FakeIncident, make_incident


def _vecs(emb: Embedder, *incs: FakeIncident) -> dict[str, Any]:
    return {i.incident_id: emb.encode_one(incident_text(title_of(i), i.description))
            for i in incs}


@pytest.fixture
def detector(settings: Settings) -> DuplicateDetector:
    return DuplicateDetector(DuplicateConfig.from_settings(settings))


def _match(detector: DuplicateDetector, emb: Embedder, new: FakeIncident,
           *others: FakeIncident) -> list[Any]:
    vecs = _vecs(emb, new, *others)
    return detector.find_matches(new, vecs[new.incident_id], list(others), vecs)


def _pay(title: str, desc: str, at: datetime, **kw: Any) -> FakeIncident:
    return make_incident(PENDING_G14_title=title, description=desc,
                         PENDING_G13_created_at=at, **kw)


def test_near_identical_text_linked_with_hashing(detector: DuplicateDetector,
                                                 t0: datetime) -> None:
    a = _pay("Payment gateway down", "Checkout fails with errors", t0)
    b = _pay("Payment gateway down", "Checkout fails with errors now", t0 + timedelta(minutes=5))
    assert [m.other_id for m in _match(detector, HashingEmbedder(), b, a)] == [a.incident_id]


def test_works_without_title(detector: DuplicateDetector, t0: datetime) -> None:
    """P1's Incident has no title yet (G14): description alone must still work."""
    a = _pay("", "Payment gateway down, checkout fails with errors", t0)
    b = _pay("", "Payment gateway down, checkout fails with errors", t0 + timedelta(minutes=1))
    assert len(_match(detector, HashingEmbedder(), b, a)) == 1


@pytest.mark.case(id="TC-P4-14", category="boundary",
                  desc="Same text but created outside the duplicate window",
                  expected="Not linked")
def test_outside_window_not_linked(detector: DuplicateDetector, t0: datetime,
                                   settings: Settings) -> None:
    a = _pay("Payment gateway down", "Checkout fails with errors", t0)
    b = _pay("Payment gateway down", "Checkout fails with errors",
             t0 + timedelta(hours=settings.DUP_WINDOW_HOURS, minutes=1))
    assert _match(detector, HashingEmbedder(), b, a) == []


@pytest.mark.case(id="TC-P4-15", category="boundary",
                  desc="Very short description",
                  expected="Similarity skipped; same service + category fallback used")
def test_short_description_uses_fallback(detector: DuplicateDetector, t0: datetime) -> None:
    a = _pay("pay", "down", t0)
    b = _pay("pay", "broken", t0 + timedelta(minutes=1))
    other_service = _pay("pay", "down", t0, service=EMAIL)
    matches = _match(detector, HashingEmbedder(), b, a, other_service)
    assert [(m.other_id, m.reason) for m in matches] == [(a.incident_id, MatchReason.FALLBACK)]


def test_same_service_bonus_applied(detector: DuplicateDetector, settings: Settings) -> None:
    v = HashingEmbedder().encode_one("x y z")
    assert detector.score(v, v, True) == pytest.approx(1.0 + settings.DUP_SAME_SERVICE_BONUS)


def test_correlator_components_and_services() -> None:
    comps = Correlator.components([("A", "B"), ("B", "C"), ("D", "E")])
    assert sorted(len(x) for x in comps) == [2, 3]
    service = {"A": "S1", "B": "S1", "C": "S1", "D": "S2", "E": "S2"}
    by_service = Correlator().clusters_by_service(
        [("A", "B"), ("B", "C"), ("D", "E")], service.__getitem__
    )
    assert by_service["S1"] == [frozenset({"A", "B", "C"})]


# ---- semantic tests: need the real model (pytest -m model) ---------------------------
@pytest.fixture(scope="module")
def minilm() -> Embedder:
    pytest.importorskip("sentence_transformers")
    return MiniLMEmbedder.instance("sentence-transformers/all-MiniLM-L6-v2")


@pytest.mark.model
@pytest.mark.case(id="TC-P4-13", category="normal",
                  desc="Two paraphrased reports of the same outage within the window",
                  expected="Linked as related")
def test_paraphrases_linked(detector: DuplicateDetector, minilm: Embedder, t0: datetime) -> None:
    a = _pay("Payment application unavailable", "Users cannot complete transactions", t0)
    b = _pay("Payment gateway down", "Customers are unable to pay, checkout is failing",
             t0 + timedelta(minutes=3))
    assert [m.other_id for m in _match(detector, minilm, b, a)] == [a.incident_id]


@pytest.mark.model
@pytest.mark.case(id="TC-P4-16", category="business-rule",
                  desc="Unrelated incidents on the same service (hard negative)",
                  expected="Not linked")
def test_hard_negative_not_linked(detector: DuplicateDetector, minilm: Embedder,
                                  t0: datetime) -> None:
    a = _pay("Payment gateway down", "Checkout fails for customers", t0)
    b = _pay("Payment report export wrong",
             "Monthly CSV export of settled payments has wrong totals",
             t0 + timedelta(minutes=3))
    assert _match(detector, minilm, b, a) == []
