"""IntelligenceListener: an Observer on P1's domain.events.EventBus.

IncidentCreated                       -> embed + store, link duplicates, suggest a category
StatusChanged(new_status=RESOLVED)    -> add to the resolution index

Every step is isolated: a failure is logged and recorded in FeatureRegistry, and the
remaining steps still run. The work runs off the request path (a single-worker
executor), so it cannot slow down or break incident creation.

TIMING (G18): P1's factory publishes IncidentCreated inside create(), before P2 has
saved the incident. Handlers here load the incident by id, so they need the event
delivered after commit. Until P2 confirms that, `_load` retries briefly.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Protocol

from app.intelligence.categorizer import Categorizer
from app.intelligence.duplicates import DuplicateDetector
from app.intelligence.embedder import Embedder
from app.intelligence.features import FeatureRegistry
from app.intelligence.resolution import ResolutionIndex, ResolvedEntry
from app.intelligence.text import incident_text
from app.p4_contracts import (
    PENDING_P2_UnitOfWork,
    UnitOfWorkFactory,
    Vector,
    category_name_of,
    title_of,
)
from domain.enums import Status
from domain.events import EventBus, IncidentCreated, StatusChanged

log = logging.getLogger(__name__)

PENDING_G18_LOAD_RETRIES = 3
PENDING_G18_RETRY_DELAY_SECONDS = 0.2


class Executor(Protocol):
    def submit(self, fn: Callable[..., Any], /, *args: Any) -> Any: ...


class InlineExecutor:
    """Runs work immediately in the caller's thread (tests, INTELLIGENCE_ASYNC=false)."""

    def submit(self, fn: Callable[..., Any], /, *args: Any) -> Future[Any]:
        fut: Future[Any] = Future()
        try:
            fut.set_result(fn(*args))
        except BaseException as exc:
            fut.set_exception(exc)
        return fut


def make_executor(async_mode: bool) -> Executor:
    if async_mode:
        return ThreadPoolExecutor(max_workers=1, thread_name_prefix="p4-intel")
    return InlineExecutor()


class IntelligenceListener:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        embedder: Embedder,
        detector: DuplicateDetector,
        categorizer: Categorizer,
        index: ResolutionIndex,
        features: FeatureRegistry,
        executor: Executor,
        retry_delay: float = PENDING_G18_RETRY_DELAY_SECONDS,
    ) -> None:
        self._uow_factory = uow_factory
        self._embedder = embedder
        self._detector = detector
        self._categorizer = categorizer
        self._index = index
        self._features = features
        self._executor = executor
        self._retry_delay = retry_delay

    def subscribe(self, bus: EventBus) -> None:
        bus.subscribe(IncidentCreated, self.on_created)
        bus.subscribe(StatusChanged, self.on_status_changed)

    # --- event handlers (called synchronously by the bus) -----------------------
    def on_created(self, event: IncidentCreated) -> None:
        self._executor.submit(self._guarded, self.handle_created, event.incident_id)

    def on_status_changed(self, event: StatusChanged) -> None:
        if event.new_status == Status.RESOLVED:
            self._executor.submit(self._guarded, self.handle_resolved, event.incident_id)

    def _guarded(self, fn: Callable[[str], None], incident_id: str) -> None:
        try:
            fn(incident_id)
        except Exception:
            log.exception("intelligence handler %s failed for %s", fn.__name__, incident_id)

    def _load(self, uow: PENDING_P2_UnitOfWork, incident_id: str) -> Any:
        for attempt in range(PENDING_G18_LOAD_RETRIES):
            try:
                return uow.incidents.get(incident_id)
            except Exception:  # PENDING_P2: narrow to IncidentNotFoundError
                if attempt == PENDING_G18_LOAD_RETRIES - 1:
                    raise
                time.sleep(self._retry_delay)
        raise AssertionError("unreachable")

    # --- work ---------------------------------------------------------------------
    def handle_created(self, incident_id: str) -> None:
        uow = self._uow_factory()
        try:
            incident = self._load(uow, incident_id)
            vec = self._step_embed(uow, incident)
            self._step_duplicates(uow, incident, vec)
            self._step_categorize(uow, incident, vec)
            uow.commit()
        except Exception:
            uow.rollback()
            raise
        finally:
            uow.close()

    def handle_resolved(self, incident_id: str) -> None:
        uow = self._uow_factory()
        try:
            incident = self._load(uow, incident_id)
            text = (incident.resolution or "").strip()
            if not text:
                return
            vec = uow.embeddings.get_many([incident_id]).get(incident_id)
            if vec is None:
                vec = self._embedder.encode_one(
                    incident_text(title_of(incident), incident.description)
                )
            self._index.add(ResolvedEntry(incident_id, vec, category_name_of(incident), text))
            self._features.record_ok(FeatureRegistry.RESOLUTIONS, "indexed")
        except Exception as exc:
            self._features.record_error(FeatureRegistry.RESOLUTIONS, exc)
            raise
        finally:
            uow.close()

    def _step_embed(self, uow: PENDING_P2_UnitOfWork, incident: Any) -> Vector | None:
        text = incident_text(title_of(incident), incident.description)
        if not text:
            return None
        try:
            vec = self._embedder.encode_one(text)
            uow.embeddings.save(incident.incident_id, vec)
            self._features.record_ok(FeatureRegistry.EMBEDDINGS, "encoded")
            return vec
        except Exception as exc:
            log.exception("embedding failed for %s", incident.incident_id)
            self._features.record_error(FeatureRegistry.EMBEDDINGS, exc)
            return None

    def _step_duplicates(
        self, uow: PENDING_P2_UnitOfWork, incident: Any, vec: Vector | None
    ) -> None:
        try:
            since = incident.PENDING_G13_created_at - self._detector.config.window
            candidates = [
                c for c in uow.incidents.open_since(since, exclude_id=incident.incident_id)
                if c.incident_id != incident.incident_id
            ]
            vectors = uow.embeddings.get_many([c.incident_id for c in candidates])
            for m in self._detector.find_matches(incident, vec, candidates, vectors):
                uow.intelligence.link_related(incident.incident_id, m.other_id, m.score)
                self._features.record_ok(FeatureRegistry.DUPLICATES, f"linked_{m.reason.value}")
        except Exception as exc:
            log.exception("duplicate detection failed for %s", incident.incident_id)
            self._features.record_error(FeatureRegistry.DUPLICATES, exc)

    def _step_categorize(
        self, uow: PENDING_P2_UnitOfWork, incident: Any, vec: Vector | None
    ) -> None:
        if vec is None or not self._categorizer.enabled:
            return
        try:
            suggestion = self._categorizer.predict(vec)
            if suggestion is None:
                self._features.record_ok(FeatureRegistry.CATEGORIZER, "low_confidence")
                return
            # P1's Category names are UPPERCASE.
            uow.intelligence.set_suggested_category(
                incident.incident_id, suggestion.category.upper(), suggestion.confidence
            )
            self._features.record_ok(FeatureRegistry.CATEGORIZER, "suggested")
        except Exception as exc:
            log.exception("categorization failed for %s", incident.incident_id)
            self._features.record_error(FeatureRegistry.CATEGORIZER, exc)
