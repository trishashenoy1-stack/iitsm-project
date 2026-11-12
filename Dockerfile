# syntax=docker/dockerfile:1
FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/hf
WORKDIR /app

# --- dependencies first (layer cache) -------------------------------------------------
# CPU-only torch: the default wheel pulls CUDA and adds ~2 GB.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch
COPY pyproject.toml ./
RUN python -c "import tomllib; d = tomllib.load(open('pyproject.toml', 'rb'))['project']; \
open('/tmp/req.txt', 'w').write('\n'.join(d['dependencies'] + d['optional-dependencies']['ml']))" \
 && pip install -r /tmp/req.txt

# Download the embedding model at build time so the container runs offline.
ARG EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
RUN python -c "from sentence_transformers import SentenceTransformer as S; S('${EMBEDDING_MODEL}')"
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1

# --- source -----------------------------------------------------------------------
COPY domain ./domain
COPY app ./app
COPY scripts ./scripts
COPY data ./data
COPY models ./models
COPY docker/entrypoint.sh ./entrypoint.sh
# alembic/ + alembic.ini are P2's; copied if present (PENDING_P2). pyproject.toml is
# listed so the glob always has at least one match.
COPY pyproject.toml alembic* ./

RUN useradd --create-home --uid 1000 itsm && chown -R itsm /app /opt/hf
USER itsm
EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
