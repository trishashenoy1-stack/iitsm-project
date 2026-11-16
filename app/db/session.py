"""Engine and session factory (P2).

One engine per process. Sessions are short-lived and always opened through a
UnitOfWork, so routes never touch them directly.
"""

from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def build_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        # In-memory SQLite needs one shared connection, or every session sees an empty DB.
        options: dict[str, object] = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url or url.endswith("sqlite://"):
            options["poolclass"] = StaticPool
        engine = create_engine(url, **options)

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _record):  # type: ignore[no-untyped-def]
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

        return engine
    return create_engine(url, pool_pre_ping=True)


def build_session_factory(engine: Engine) -> sessionmaker:
    # expire_on_commit=False: the API serialises rows after the commit that saved them.
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
