"""Embedder interface and implementations.

MiniLMEmbedder   real model (sentence-transformers), loaded lazily, once per process.
HashingEmbedder  deterministic bag-of-words hashing, with no model download. Used in unit
                 tests and CI, and as a fallback. It has no semantics: paraphrases with
                 different words will NOT match. Tests that need meaning use the
                 `model` marker.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
from abc import ABC, abstractmethod
from typing import Any, ClassVar, cast

import numpy as np

from app.config import Settings
from app.p4_contracts import Vector

log = logging.getLogger(__name__)


def l2_normalise(m: np.ndarray) -> Vector:
    m = np.asarray(m, dtype=np.float32)
    if m.ndim == 1:
        m = m.reshape(1, -1)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return cast(Vector, (m / norms).astype(np.float32))


class Embedder(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def encode(self, texts: list[str]) -> Vector:
        """Return an (n, d) float32 array with L2-normalised rows."""

    def encode_one(self, text: str) -> Vector:
        return cast(Vector, self.encode([text])[0])

    def warm_up(self) -> None:
        self.encode(["warm up"])


class MiniLMEmbedder(Embedder):
    """Lazy singleton per model name, so the model is loaded only once."""

    _instances: ClassVar[dict[str, MiniLMEmbedder]] = {}
    _class_lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model: Any = None
        self._load_lock = threading.Lock()

    @classmethod
    def instance(cls, model_name: str) -> MiniLMEmbedder:
        with cls._class_lock:
            if model_name not in cls._instances:
                cls._instances[model_name] = cls(model_name)
            return cls._instances[model_name]

    @property
    def name(self) -> str:
        return self._model_name

    def _ensure_loaded(self) -> Any:
        if self._model is None:
            with self._load_lock:
                if self._model is None:
                    from sentence_transformers import SentenceTransformer

                    log.info("loading embedding model %s", self._model_name)
                    self._model = SentenceTransformer(self._model_name, device="cpu")
        return self._model

    def encode(self, texts: list[str]) -> Vector:
        model = self._ensure_loaded()
        out = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
        return l2_normalise(out)


class HashingEmbedder(Embedder):
    _TOKEN = re.compile(r"[a-z0-9]+")

    def __init__(self, dim: int = 512) -> None:
        if dim <= 0:
            raise ValueError("dim must be positive")
        self._dim = dim

    @property
    def name(self) -> str:
        return f"hashing-{self._dim}"

    def _bucket(self, token: str) -> int:
        digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
        return int.from_bytes(digest, "little") % self._dim

    def encode(self, texts: list[str]) -> Vector:
        m = np.zeros((len(texts), self._dim), dtype=np.float32)
        for row, text in enumerate(texts):
            tokens = self._TOKEN.findall(text.lower())
            for tok in tokens:
                m[row, self._bucket(tok)] += 1.0
            for a, b in zip(tokens, tokens[1:], strict=False):  # bigrams add some word order
                m[row, self._bucket(f"{a}_{b}")] += 0.5
        return l2_normalise(m)


def build_embedder(settings: Settings) -> Embedder:
    if settings.EMBEDDER_BACKEND == "hashing":
        return HashingEmbedder(settings.HASHING_EMBEDDER_DIM)
    return MiniLMEmbedder.instance(settings.EMBEDDING_MODEL)
