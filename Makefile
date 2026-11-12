.PHONY: install test test-all lint data metrics cases seed-dry up down

install:
	pip install -e ".[dev]"

test:
	pytest

test-all:
	pytest -m "integration or model or not integration"

lint:
	ruff check . && mypy

data:
	python -m scripts.gen_synthetic

# BACKEND=hashing for a quick run without the model; the report uses minilm.
metrics: data
	python -m scripts.train_categorizer $(if $(BACKEND),--backend $(BACKEND))
	python -m scripts.eval_duplicates $(if $(BACKEND),--backend $(BACKEND))

cases:
	python -m scripts.export_test_cases

seed-dry:
	python -m scripts.seed --dry-run

up:
	docker compose up --build

down:
	docker compose down
