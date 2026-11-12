"""What P4 needs from P1 (domain/) and P2 (persistence), as Protocols and helpers.

PLACEHOLDER CONVENTION
----------------------
Every name starting with ``PENDING_`` is something not delivered yet. ``grep -rn PENDING_``
lists every use. Gap numbers refer to PLACEHOLDERS.md.

    PENDING_P2_*   -> P2's persistence (repositories, unit of work)
    PENDING_Gn_*   -> an agreed or requested addition; rename once it exists

DELIVERED BY P1 (12 Nov) and used directly, no placeholders:
    domain.enums.Status / Priority, domain.events.{EventBus, IncidentCreated,
    StatusChanged, SYSTEM}, domain.sla_monitor.SLAMonitor, domain.clock.{Clock,
    SystemClock, FakeClock}
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt

from domain.enums import Priority, Status

Vector = npt.NDArray[np.float32]

# Statuses where the incident is finished from an SLA / intelligence point of view.
DONE_STATUSES: frozenset[Status] = frozenset({Status.RESOLVED, Status.VERIFIED, Status.CLOSED})
# Statuses where escalation applies (nobody has acknowledged yet).
UNACKNOWLEDGED_STATUSES: frozenset[Status] = frozenset(
    {Status.NEW, Status.CLASSIFIED, Status.ASSIGNED}
)


# ======================================================================================
# P1: the parts of domain.incident.Incident that P4 reads
# ======================================================================================
class IncidentView(Protocol):
    """Structural view of P1's ``Incident``. Repositories return real Incidents."""

    @property
    def incident_id(self) -> str: ...  # e.g. "INC1001"
    @property
    def description(self) -> str: ...
    @property
    def status(self) -> Status: ...
    @property
    def priority(self) -> Priority | None: ...
    @property
    def category(self) -> Any: ...  # domain.category.Category | None (name is UPPERCASE)
    @property
    def service(self) -> Any: ...  # domain.service.ITService (.service_id)
    @property
    def resolution(self) -> str | None: ...
    @property
    def sla(self) -> Any: ...  # domain.sla.SLATracker | None

    # --- requested from P1; not on Incident yet ----------------------------------
    @property
    def PENDING_G14_title(self) -> str | None:
        """G14: Incident has only a description. The embedder uses "title. description"."""
        ...

    @property
    def PENDING_G13_created_at(self) -> datetime:
        """G13: a public creation time (only the SLATracker holds it, privately)."""
        ...

    @property
    def PENDING_G1_resolved_at(self) -> datetime | None:
        """G1: when the incident entered RESOLVED. Auto-close counts from here."""
        ...

    @property
    def PENDING_G15_escalation_level(self) -> int:
        """G15: 0 = assigned technician, 1 = team lead, ... (escalation not built yet)."""
        ...

    @property
    def PENDING_G2_last_escalated_at(self) -> datetime | None: ...


class EscalatableIncident(IncidentView, Protocol):
    def PENDING_G15_escalate(self, to_user_id: str, level: int) -> None:
        """G15: the domain method. It raises if acknowledged and emits IncidentEscalated."""
        ...

    def PENDING_G4_mark_escalation_exhausted(self) -> bool:
        """G4: flag the end of the chain once (emits an event). False if already flagged."""
        ...


class AutoClosableIncident(IncidentView, Protocol):
    def verify(self, actor: Any = None) -> None: ...
    def close(self, actor: Any = None) -> None: ...


def service_id_of(incident: IncidentView) -> str | None:
    svc = incident.service
    return None if svc is None else str(svc.service_id)


def category_name_of(incident: IncidentView) -> str | None:
    cat = incident.category
    return None if cat is None else str(cat.name)


def title_of(incident: IncidentView) -> str:
    return getattr(incident, "PENDING_G14_title", None) or ""


# ======================================================================================
# P2: repositories (return P1 domain Incidents)
# ======================================================================================
class IncidentRepository(Protocol):
    def get(self, incident_id: str) -> Any: ...

    def PENDING_G5_get_for_update(self, incident_id: str) -> Any:
        """G5: load with a row lock (SELECT ... FOR UPDATE), so escalation and
        acknowledgment cannot race."""
        ...

    def open_incidents(self) -> Iterable[Any]:
        """All incidents not in DONE_STATUSES (the SLA monitor checks them all).
        PENDING_P2. Also needs P1's restore() (G16) so they are rebuilt in their state."""
        ...

    def open_since(self, t: datetime, exclude_id: str | None = None) -> Iterable[Any]:
        """Open incidents created at or after t. Used for duplicate detection."""
        ...

    def resolved_with_text(self) -> Iterable[Any]: ...

    def resolved_before(self, t: datetime) -> Iterable[Any]:
        """RESOLVED (not verified) incidents with PENDING_G1_resolved_at < t."""
        ...

    def PENDING_G11_open_unacknowledged(self, priorities: Iterable[Priority]) -> Iterable[Any]:
        """G11: candidates for escalation."""
        ...

    def PENDING_G10_related_links_since(self, t: datetime) -> Iterable[tuple[str, str, float]]:
        """G10: related-incident links created since t, as (a, b, score)."""
        ...


class PENDING_G6_EmbeddingStore(Protocol):
    """G6: persistence for incident embeddings (P2: incident_embeddings table)."""

    def save(self, incident_id: str, vector: Vector) -> None: ...
    def get_many(self, incident_ids: Iterable[str]) -> Mapping[str, Vector]: ...


class IntelligenceSink(Protocol):
    """P2: where intelligence outputs are stored and audited (they are not lifecycle
    transitions, so they don't belong on P1's Incident)."""

    def link_related(self, a: str, b: str, score: float) -> None: ...
    def set_suggested_category(
        self, incident_id: str, category: str, confidence: float
    ) -> None: ...


class EscalationDirectory(Protocol):
    def next_in_chain(self, level: int) -> PENDING_G12_EscalationTarget | None:
        """Next active user above `level` (skips inactive ones). None = end of chain.
        Needs P1 roles TEAM_LEAD / SYSTEM_ADMIN / IT_MANAGER (G17)."""
        ...


class PENDING_G12_EscalationTarget(Protocol):
    """G12: next_in_chain must also return the level it landed on."""

    @property
    def user_id(self) -> str: ...
    @property
    def level(self) -> int: ...


# ======================================================================================
# P2: unit of work (one DB session per job tick / listener call)
# ======================================================================================
class PENDING_P2_UnitOfWork(Protocol):
    incidents: IncidentRepository
    intelligence: IntelligenceSink
    escalation_directory: EscalationDirectory
    embeddings: PENDING_G6_EmbeddingStore

    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...


UnitOfWorkFactory = Callable[[], PENDING_P2_UnitOfWork]
