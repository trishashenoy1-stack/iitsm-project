"""FeatureRegistry: which P4 features are live, and if not, why. Shown on a health page."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field, replace
from datetime import datetime

from app.jobs.base import utc_now


@dataclass(frozen=True)
class FeatureStatus:
    name: str
    enabled: bool = True
    reason: str | None = None
    last_error: str | None = None
    last_error_at: datetime | None = None
    last_ok_at: datetime | None = None
    counters: dict[str, int] = field(default_factory=dict)


class FeatureRegistry:
    EMBEDDINGS = "embeddings"
    DUPLICATES = "duplicate_detection"
    CATEGORIZER = "auto_categorization"
    RESOLUTIONS = "suggested_resolution"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._features: dict[str, FeatureStatus] = {}

    def _get(self, name: str) -> FeatureStatus:
        return self._features.get(name, FeatureStatus(name))

    def disable(self, name: str, reason: str) -> None:
        with self._lock:
            self._features[name] = replace(self._get(name), enabled=False, reason=reason)

    def record_ok(self, name: str, counter: str | None = None) -> None:
        with self._lock:
            st = self._get(name)
            counters = dict(st.counters)
            if counter:
                counters[counter] = counters.get(counter, 0) + 1
            self._features[name] = replace(st, last_ok_at=utc_now(), counters=counters)

    def record_error(self, name: str, error: BaseException) -> None:
        with self._lock:
            self._features[name] = replace(
                self._get(name), last_error=repr(error), last_error_at=utc_now()
            )

    def is_enabled(self, name: str) -> bool:
        with self._lock:
            return self._get(name).enabled

    def snapshot(self) -> dict[str, FeatureStatus]:
        with self._lock:
            return dict(self._features)
