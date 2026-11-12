"""Helpers shared by the training/evaluation scripts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import Settings
from app.intelligence.embedder import Embedder, build_embedder


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def embedder_for(backend: str | None) -> Embedder:
    s = Settings()
    if backend:
        s = s.model_copy(update={"EMBEDDER_BACKEND": backend})
    return build_embedder(s)


def write_metrics(name: str, data: dict[str, Any], markdown: str,
                  out_dir: Path = Path("docs/metrics")) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{name}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    (out_dir / f"{name}.md").write_text(markdown, encoding="utf-8")
    print(f"wrote {out_dir / name}.json/.md")
