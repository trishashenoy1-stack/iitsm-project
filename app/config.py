"""Application settings (shared with P2).

P4 owns the block marked "P4". P2 adds its own fields (JWT, CORS, SMTP, ...) to this
same class. Every threshold P4 code uses is read from here; there are no magic numbers in
jobs/ or intelligence/.

Values are starting points to be tuned, not measured results.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- shared -------------------------------------------------------------------
    # PENDING_P2: P2 owns the DB URL format and session setup. The default only exists so
    # unit tests and scripts can build Settings without a .env file.
    DATABASE_URL: str = "sqlite+pysqlite:///:memory:"

    # --- P4: background jobs ------------------------------------------------------
    SCHEDULER_ENABLED: bool = True
    SLA_MONITOR_INTERVAL_SECONDS: int = 30
    # G19: P1's IncidentFactory creates SLATracker with its default warning_ratio=0.8
    # (warn at 80% elapsed, i.e. 20% left) and doesn't read this yet. Ask P1 to pass
    # SLATracker(warning_ratio=1 - SLA_WARNING_FRACTION).
    SLA_WARNING_FRACTION: float = 0.2
    ESCALATION_INTERVAL_SECONDS: int = 60
    ESCALATION_AFTER_MINUTES: dict[str, int] = {"P1": 5, "P2": 15}
    AUTO_CLOSE_INTERVAL_SECONDS: int = 3600
    AUTO_CLOSE_DAYS: int = 3

    # --- P4: intelligence ---------------------------------------------------------
    EMBEDDER_BACKEND: Literal["minilm", "hashing"] = "minilm"
    EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"
    HASHING_EMBEDDER_DIM: int = 512
    INTELLIGENCE_ASYNC: bool = True  # False in tests: listener work runs inline

    DUP_WINDOW_HOURS: int = 24
    DUP_THRESHOLD: float = 0.75
    DUP_SAME_SERVICE_BONUS: float = 0.05
    DUP_MIN_CHARS: int = 15

    CATEGORIZER_MODEL_PATH: Path = Path("models/categorizer.joblib")
    CAT_MIN_CONFIDENCE: float = 0.5

    RES_TOP_K: int = 3
    RES_MIN_SIM: float = 0.6

    # --- P4: data / seed ------------------------------------------------------------
    RANDOM_SEED: int = 42
    SEED_ON_START: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
