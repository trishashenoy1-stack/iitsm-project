from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pytest

from app.intelligence.categorizer import (
    NullCategorizer,
    SklearnCategorizer,
    load_categorizer,
    save_categorizer,
    train_logreg,
)
from app.intelligence.embedder import HashingEmbedder

TRAIN = [
    ("wifi network not connecting", "Network"), ("vpn tunnel times out", "Network"),
    ("router down no internet", "Network"), ("network slow packet loss", "Network"),
    ("password reset link missing", "Authentication"), ("account locked out", "Authentication"),
    ("sso login fails", "Authentication"), ("cannot sign in password", "Authentication"),
]


@pytest.fixture
def trained() -> SklearnCategorizer:
    emb = HashingEmbedder(256)
    x = emb.encode([t for t, _ in TRAIN])
    model = train_logreg(x, [c for _, c in TRAIN], seed=0)
    return SklearnCategorizer(model, min_confidence=0.5)


def test_confident_prediction(trained: SklearnCategorizer) -> None:
    v = HashingEmbedder(256).encode_one("vpn network not connecting")
    s = trained.predict(v)
    assert s is not None and s.category == "Network"


@pytest.mark.case(id="TC-P4-17", category="boundary",
                  desc="Categorizer prediction below CAT_MIN_CONFIDENCE",
                  expected="No suggestion is set")
def test_low_confidence_returns_none(trained: SklearnCategorizer) -> None:
    strict = SklearnCategorizer(trained._model, min_confidence=0.999)
    assert strict.predict(HashingEmbedder(256).encode_one("printer toner")) is None


@pytest.mark.case(id="TC-P4-18", category="exception",
                  desc="Categorizer model file missing",
                  expected="App starts; feature disabled; warning logged")
def test_missing_model_disables_feature(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        cat = load_categorizer(tmp_path / "nope.joblib", 0.5)
    assert isinstance(cat, NullCategorizer) and not cat.enabled
    assert cat.predict(np.zeros(8, dtype=np.float32)) is None
    assert "disabled" in caplog.text


def test_corrupt_model_disables_feature(tmp_path: Path) -> None:
    bad = tmp_path / "bad.joblib"
    bad.write_bytes(b"not a joblib file")
    assert isinstance(load_categorizer(bad, 0.5), NullCategorizer)


def test_embedder_mismatch_disables(tmp_path: Path, trained: SklearnCategorizer) -> None:
    path = tmp_path / "m.joblib"
    save_categorizer(trained._model, path, "hashing-256")
    assert load_categorizer(path, 0.5, expected_embedder="hashing-256").enabled
    assert not load_categorizer(path, 0.5, expected_embedder="minilm").enabled
