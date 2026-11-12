"""Auto-categorization: embeddings -> LogisticRegression.

SklearnCategorizer  trained model loaded from joblib.
NullCategorizer     Null Object used when the model file is missing or broken; it never
                    suggests anything, and the app keeps running.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app.p4_contracts import Vector

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CategorySuggestion:
    category: str
    confidence: float


class Categorizer(ABC):
    @property
    @abstractmethod
    def enabled(self) -> bool: ...

    @abstractmethod
    def predict(self, vector: Vector) -> CategorySuggestion | None: ...


class NullCategorizer(Categorizer):
    def __init__(self, reason: str) -> None:
        self.reason = reason

    @property
    def enabled(self) -> bool:
        return False

    def predict(self, vector: Vector) -> CategorySuggestion | None:
        return None


class SklearnCategorizer(Categorizer):
    def __init__(self, model: Any, min_confidence: float, embedder_name: str | None = None) -> None:
        self._model = model
        self._min_confidence = min_confidence
        self.embedder_name = embedder_name

    @property
    def enabled(self) -> bool:
        return True

    @property
    def classes(self) -> list[str]:
        return [str(c) for c in self._model.classes_]

    def predict(self, vector: Vector) -> CategorySuggestion | None:
        proba = self._model.predict_proba(np.asarray(vector).reshape(1, -1))[0]
        idx = int(np.argmax(proba))
        confidence = float(proba[idx])
        if confidence < self._min_confidence:
            return None
        return CategorySuggestion(str(self._model.classes_[idx]), confidence)


def train_logreg(x: np.ndarray, y: list[str], seed: int) -> Any:
    from sklearn.linear_model import LogisticRegression

    model = LogisticRegression(class_weight="balanced", max_iter=2000, random_state=seed)
    model.fit(x, y)
    return model


def save_categorizer(model: Any, path: Path, embedder_name: str) -> None:
    import joblib

    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "embedder": embedder_name}, path)


def load_categorizer(
    path: Path, min_confidence: float, expected_embedder: str | None = None
) -> Categorizer:
    if not path.exists():
        log.warning("categorizer model not found at %s; auto-categorization disabled", path)
        return NullCategorizer(f"model file missing: {path}")
    try:
        import joblib

        bundle = joblib.load(path)
        embedder = bundle.get("embedder")
        if expected_embedder and embedder and embedder != expected_embedder:
            log.warning("categorizer trained with %s but app uses %s; disabled",
                        embedder, expected_embedder)
            return NullCategorizer(f"embedder mismatch: {embedder} != {expected_embedder}")
        return SklearnCategorizer(bundle["model"], min_confidence, embedder)
    except Exception as exc:
        log.warning("failed to load categorizer from %s: %r; disabled", path, exc)
        return NullCategorizer(f"load failed: {exc!r}")
