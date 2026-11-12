"""PENDING_P2: Postgres-backed integration tests go here once P2's models/session land.

Planned: SchedulerManager.run_now("sla_monitor") against seeded Postgres rows; the
listener pipeline with the real EmbeddingStore; the seed run twice (TC-P4-20).
"""

import pytest


@pytest.mark.integration
def test_PENDING_P2_postgres_available() -> None:
    pytest.skip("PENDING_P2: no SQLAlchemy session/models yet")
