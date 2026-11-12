"""Composition root for all P4 components: the only place P4 objects are constructed.

P2's main.py lifespan calls it like this (PENDING_P2: paste into the real main.py):

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings = get_settings()
        bus, clock = EventBus(), SystemClock()      # the same ones P1's factory uses
        app.state.p4 = wire_p4(settings, bus=bus, clock=clock,
                               uow_factory=PENDING_P2_uow_factory)
        yield
        app.state.p4.shutdown()

P2's routes then use:
    app.state.p4.scheduler.run_now("sla_monitor")     # POST /admin/jobs/{name}/run
    app.state.p4.suggest_resolutions(incident_id)     # GET /incidents/{id}/suggestions
    app.state.p4.clusters()                           # GET /reports/clusters (G10)
    app.state.p4.health()                             # GET /health/p4
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from app.config import Settings
from app.intelligence.categorizer import Categorizer, NullCategorizer, load_categorizer
from app.intelligence.duplicates import (
    DuplicateConfig,
    DuplicateDetector,
    PENDING_G10_clusters_for_dashboard,
)
from app.intelligence.embedder import Embedder, HashingEmbedder, build_embedder
from app.intelligence.features import FeatureRegistry
from app.intelligence.listeners import IntelligenceListener, make_executor
from app.intelligence.resolution import (
    ResolutionIndex,
    ResolutionSuggester,
    ResolutionSuggestion,
    ResolvedEntry,
)
from app.intelligence.text import incident_text
from app.jobs.auto_close import build_auto_close
from app.jobs.escalation import build_escalation
from app.jobs.scheduler import SchedulerManager
from app.jobs.sla_monitor import SLAMonitorJob
from app.p4_contracts import UnitOfWorkFactory, category_name_of, title_of
from domain.clock import Clock, SystemClock
from domain.events import EventBus
from domain.sla_monitor import SLAMonitor

log = logging.getLogger(__name__)


@dataclass
class P4Runtime:
    settings: Settings
    uow_factory: UnitOfWorkFactory
    scheduler: SchedulerManager
    features: FeatureRegistry
    embedder: Embedder
    categorizer: Categorizer
    resolution_index: ResolutionIndex
    suggester: ResolutionSuggester
    listener: IntelligenceListener
    clock: Clock

    def suggest_resolutions(self, incident_id: str) -> list[ResolutionSuggestion]:
        uow = self.uow_factory()
        try:
            incident = uow.incidents.get(incident_id)
            vec = uow.embeddings.get_many([incident_id]).get(incident_id)
            if vec is None:
                vec = self.embedder.encode_one(
                    incident_text(title_of(incident), incident.description)
                )
            return self.suggester.suggest(incident_id, vec, category_name_of(incident))
        finally:
            uow.close()

    def clusters(self) -> dict[str, list[frozenset[str]]]:
        uow = self.uow_factory()
        try:
            return PENDING_G10_clusters_for_dashboard(
                uow.incidents, self.clock.now(), timedelta(hours=self.settings.DUP_WINDOW_HOURS)
            )
        finally:
            uow.close()

    def health(self) -> dict[str, Any]:
        return {
            "features": {k: vars(v) for k, v in self.features.snapshot().items()},
            "jobs": {k: vars(v) for k, v in self.scheduler.last_results().items()},
            "resolution_index_size": len(self.resolution_index),
        }

    def shutdown(self) -> None:
        self.scheduler.shutdown()


def _register_jobs(scheduler: SchedulerManager, s: Settings, monitor: SLAMonitor) -> None:
    scheduler.register(
        "sla_monitor",
        lambda uow: SLAMonitorJob(uow.incidents, monitor),
        s.SLA_MONITOR_INTERVAL_SECONDS,
    )
    scheduler.register(
        "escalation",
        lambda uow: build_escalation(uow.incidents, uow.escalation_directory, s),
        s.ESCALATION_INTERVAL_SECONDS,
    )
    scheduler.register(
        "auto_close",
        lambda uow: build_auto_close(uow.incidents, s),
        s.AUTO_CLOSE_INTERVAL_SECONDS,
    )


def _build_embedder(s: Settings, features: FeatureRegistry) -> Embedder:
    embedder = build_embedder(s)
    try:
        embedder.warm_up()
    except Exception as exc:  # model not downloadable / not installed
        log.warning("embedder %s unavailable (%r); falling back to hashing", embedder.name, exc)
        features.disable(FeatureRegistry.EMBEDDINGS, f"{embedder.name} unavailable: {exc!r}")
        embedder = HashingEmbedder(s.HASHING_EMBEDDER_DIM)
    return embedder


def _rebuild_index(index: ResolutionIndex, uow_factory: UnitOfWorkFactory,
                   embedder: Embedder, features: FeatureRegistry) -> None:
    uow = uow_factory()
    try:
        resolved = list(uow.incidents.resolved_with_text())
        stored = uow.embeddings.get_many([i.incident_id for i in resolved])
        entries = []
        for inc in resolved:
            vec = stored.get(inc.incident_id)
            if vec is None:
                vec = embedder.encode_one(incident_text(title_of(inc), inc.description))
            entries.append(ResolvedEntry(
                inc.incident_id, vec, category_name_of(inc), inc.resolution or ""
            ))
        index.rebuild(entries)
        log.info("resolution index rebuilt with %d entries", len(index))
    except Exception as exc:
        log.exception("resolution index rebuild failed")
        features.record_error(FeatureRegistry.RESOLUTIONS, exc)
    finally:
        uow.close()


def wire_p4(
    settings: Settings,
    bus: EventBus,
    uow_factory: UnitOfWorkFactory,
    clock: Clock | None = None,
    start_scheduler: bool = True,
) -> P4Runtime:
    clock = clock or SystemClock()
    features = FeatureRegistry()

    scheduler = SchedulerManager(settings, uow_factory, clock.now)
    _register_jobs(scheduler, settings, SLAMonitor(bus, clock))

    embedder = _build_embedder(settings, features)
    categorizer = load_categorizer(
        settings.CATEGORIZER_MODEL_PATH, settings.CAT_MIN_CONFIDENCE, embedder.name
    )
    if isinstance(categorizer, NullCategorizer):
        features.disable(FeatureRegistry.CATEGORIZER, categorizer.reason)

    index = ResolutionIndex()
    _rebuild_index(index, uow_factory, embedder, features)

    listener = IntelligenceListener(
        uow_factory=uow_factory,
        embedder=embedder,
        detector=DuplicateDetector(DuplicateConfig.from_settings(settings)),
        categorizer=categorizer,
        index=index,
        features=features,
        executor=make_executor(settings.INTELLIGENCE_ASYNC),
    )
    listener.subscribe(bus)

    runtime = P4Runtime(
        settings=settings,
        uow_factory=uow_factory,
        scheduler=scheduler,
        features=features,
        embedder=embedder,
        categorizer=categorizer,
        resolution_index=index,
        suggester=ResolutionSuggester(index, settings.RES_TOP_K, settings.RES_MIN_SIM),
        listener=listener,
        clock=clock,
    )
    if start_scheduler:
        scheduler.start()
    return runtime
