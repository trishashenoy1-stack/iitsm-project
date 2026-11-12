from __future__ import annotations

import numpy as np
import pytest

from app.intelligence.embedder import HashingEmbedder
from app.intelligence.resolution import ResolutionIndex, ResolutionSuggester, ResolvedEntry

EMB = HashingEmbedder(256)


def _entry(i: int, text: str, category: str, fix: str) -> ResolvedEntry:
    return ResolvedEntry(f"INC{i}", EMB.encode_one(text), category, fix)


@pytest.mark.case(id="TC-P4-19", category="boundary",
                  desc="Resolution suggester with an empty history",
                  expected="Returns an empty list, no error")
def test_empty_history() -> None:
    s = ResolutionSuggester(ResolutionIndex(), k=3, min_sim=0.1)
    assert s.suggest("INC1", EMB.encode_one("anything"), None) == []


def test_top_k_and_threshold() -> None:
    idx = ResolutionIndex()
    idx.rebuild([
        _entry(1, "payment gateway down checkout fails", "Application", "restart gateway"),
        _entry(2, "payment gateway timeout checkout", "Application", "raise pool size"),
        _entry(3, "printer paper jam", "Hardware", "clear tray"),
        _entry(4, "payment gateway down", "Application", "   "),  # empty text: not indexed
    ])
    assert len(idx) == 3
    hits = idx.query(EMB.encode_one("payment gateway down checkout"), k=5, min_sim=0.3)
    assert [h.incident_id for h in hits] == ["INC1", "INC2"]


def test_prefers_same_category_and_excludes_self() -> None:
    idx = ResolutionIndex()
    v = EMB.encode_one("disk full")
    idx.rebuild([ResolvedEntry("INC1", v, "Storage", "a"),
                 ResolvedEntry("INC2", v, "Hardware", "b")])
    hits = idx.query(v, k=2, min_sim=0.5, category="Hardware", exclude_id="INC9")
    assert [h.incident_id for h in hits] == ["INC2", "INC1"]
    assert idx.query(v, k=2, min_sim=0.5, exclude_id="INC1")[0].incident_id == "INC2"


def test_add_replaces_existing() -> None:
    idx = ResolutionIndex()
    v = np.ones(4, dtype=np.float32) / 2
    idx.add(ResolvedEntry("INC1", v, None, "first"))
    idx.add(ResolvedEntry("INC1", v, None, "second"))
    assert len(idx) == 1 and idx.query(v, 1, 0.0)[0].resolution_text == "second"
