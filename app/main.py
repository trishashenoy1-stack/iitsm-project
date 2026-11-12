"""PENDING_P2: placeholder app so Docker and CI have something to boot on 10 Nov.

P2 owns this file and replaces it with the real app factory. When they do, they paste
in the lifespan snippet from app/p4_wiring.py.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="I-ITSM (PENDING_P2 placeholder)")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": "PENDING_P2_placeholder"}
