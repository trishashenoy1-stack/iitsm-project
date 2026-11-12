#!/bin/sh
set -e

# PENDING_P2: migrations run once alembic.ini exists.
if [ -f alembic.ini ]; then
  alembic upgrade head
else
  echo "entrypoint: no alembic.ini yet (PENDING_P2), skipping migrations"
fi

# Train the categorizer inside the image if no artifact is mounted/committed.
if [ ! -f models/categorizer.joblib ] && [ -f data/synthetic_incidents.jsonl ]; then
  python -m scripts.train_categorizer || echo "entrypoint: categorizer training failed; feature will disable itself"
fi

if [ "${SEED_ON_START:-false}" = "true" ]; then
  python -m scripts.seed || echo "entrypoint: seed failed (PENDING_P2 writer?)"
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
