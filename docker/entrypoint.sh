#!/bin/sh
set -e

alembic upgrade head

# Train the categorizer inside the image if no artifact is mounted/committed.
if [ ! -f models/categorizer.joblib ] && [ -f data/synthetic_incidents.jsonl ]; then
  python -m scripts.train_categorizer || echo "entrypoint: categorizer training failed; feature will disable itself"
fi

if [ "${SEED_ON_START:-false}" = "true" ]; then
  python -m scripts.seed || echo "entrypoint: seed failed; starting without demo data"
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
