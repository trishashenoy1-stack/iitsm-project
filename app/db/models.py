"""SQLAlchemy tables (P2).

These are persistence records, not the domain model. Repositories map between these
rows and P1's classes in domain/, so no business rule lives here.

The ``incident_events`` table is the audit trail AND the source the repository rebuilds
incidents from (see app/persistence/replay.py). Columns on ``incidents`` that repeat
what the events say (status, SLA times) are a read model kept in step on every commit,
so lists, filters and reports can run as plain SQL.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class UtcDateTime(TypeDecorator):
    """Always timezone-aware UTC. SQLite drops the offset, so it is put back on read."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime written to the database")
        value = value.astimezone(UTC)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class UserRecord(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), index=True)
    # Level in the escalation chain: 1 team lead, 2 system admin, 3 IT manager.
    escalation_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utc_now)

    technician: Mapped[TechnicianRecord | None] = relationship(
        back_populates="user", uselist=False, lazy="joined"
    )


class TechnicianRecord(Base):
    __tablename__ = "technician_profiles"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    experience_years: Mapped[int] = mapped_column(Integer, default=0)
    max_workload: Mapped[int] = mapped_column(Integer, default=5)
    available: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped[UserRecord] = relationship(back_populates="technician")


class ServiceRecord(Base):
    __tablename__ = "services"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    criticality: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class CategoryRecord(Base):
    __tablename__ = "categories"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class SlaPolicyRecord(Base):
    __tablename__ = "sla_policies"

    priority: Mapped[str] = mapped_column(String(2), primary_key=True)
    response_minutes: Mapped[int] = mapped_column(Integer)
    resolution_minutes: Mapped[int] = mapped_column(Integer)


class SettingRecord(Base):
    """Small runtime settings: active assignment strategy, round-robin pointer."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)


class IncidentRecord(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    number: Mapped[int] = mapped_column(Integer, unique=True)
    description: Mapped[str] = mapped_column(Text)
    reporter_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id"), index=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    impact: Mapped[str] = mapped_column(String(8))
    urgency: Mapped[str] = mapped_column(String(8))
    affected_users: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), index=True)
    # Natural key for seed data, so seeding twice creates nothing new.
    seed_key: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)

    # ---- read model, rewritten from the domain object on every commit ----
    status: Mapped[str] = mapped_column(String(16), index=True)
    priority: Mapped[str] = mapped_column(String(2), index=True)
    technician_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    info_request: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feedback_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_target_seconds: Mapped[int] = mapped_column(Integer)
    resolution_target_seconds: Mapped[int] = mapped_column(Integer)
    responded_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    paused_seconds: Mapped[int] = mapped_column(Integer, default=0)
    response_breached: Mapped[bool] = mapped_column(Boolean, default=False)
    resolution_breached: Mapped[bool] = mapped_column(Boolean, default=False)
    escalation_level: Mapped[int] = mapped_column(Integer, default=0)
    last_escalated_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    escalation_exhausted: Mapped[bool] = mapped_column(Boolean, default=False)
    suggested_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    suggested_category_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utc_now)

    __table_args__ = (Index("ix_incidents_status_priority", "status", "priority"),)


class IncidentEventRecord(Base):
    """One audit entry. Append-only: the ORM refuses updates and deletes (see below)."""

    __tablename__ = "incident_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[str | None] = mapped_column(
        ForeignKey("incidents.id"), nullable=True, index=True
    )
    at: Mapped[datetime] = mapped_column(UtcDateTime(), index=True)
    actor_id: Mapped[str] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(32), index=True)
    description: Mapped[str] = mapped_column(Text)
    previous_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    new_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Internal entries (technician notes) are never shown to employees.
    internal: Mapped[bool] = mapped_column(Boolean, default=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


@event.listens_for(IncidentEventRecord, "before_update")
def _refuse_update(_mapper, _connection, _target):  # type: ignore[no-untyped-def]
    raise PermissionError("Audit entries are append-only and cannot be changed")


@event.listens_for(IncidentEventRecord, "before_delete")
def _refuse_delete(_mapper, _connection, _target):  # type: ignore[no-untyped-def]
    raise PermissionError("Audit entries are append-only and cannot be deleted")


class IncidentLinkRecord(Base):
    """A possible duplicate found by P4's detector. Suggested, never merged."""

    __tablename__ = "incident_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_a: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)
    incident_b: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)
    score: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utc_now, index=True)

    __table_args__ = (UniqueConstraint("incident_a", "incident_b"),)


class EmbeddingRecord(Base):
    __tablename__ = "incident_embeddings"

    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), primary_key=True)
    dim: Mapped[int] = mapped_column(Integer)
    vector: Mapped[bytes] = mapped_column(LargeBinary)


class NotificationRecord(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(16), index=True)
    incident_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    subject: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime())
    read: Mapped[bool] = mapped_column(Boolean, default=False)
