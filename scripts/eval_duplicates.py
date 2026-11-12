"""Tune DUP_THRESHOLD on the dev split, report precision/recall on the test split.

Run:  python -m scripts.eval_duplicates [--backend minilm|hashing]
Output: docs/metrics/duplicates.{json,md}
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np

from app.config import Settings
from app.intelligence.text import incident_text
from scripts._common import embedder_for, read_jsonl, write_metrics


def prf(scores: np.ndarray, labels: np.ndarray, t: float) -> dict[str, float]:
    pred = scores >= t
    tp = int(np.sum(pred & (labels == 1)))
    fp = int(np.sum(pred & (labels == 0)))
    fn = int(np.sum(~pred & (labels == 1)))
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"threshold": t, "precision": p, "recall": r, "f1": f, "tp": tp, "fp": fp, "fn": fn}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=Path("data/duplicate_pairs.jsonl"))
    ap.add_argument("--backend", choices=["minilm", "hashing"], default=None)
    args = ap.parse_args(argv)

    bonus = Settings().DUP_SAME_SERVICE_BONUS
    pairs = read_jsonl(args.data)
    emb = embedder_for(args.backend)
    va = emb.encode([incident_text(p["a"]["title"], p["a"]["description"]) for p in pairs])
    vb = emb.encode([incident_text(p["b"]["title"], p["b"]["description"]) for p in pairs])
    same = np.array([p["a"]["service"] == p["b"]["service"] for p in pairs])
    scores = np.sum(va * vb, axis=1) + np.where(same, bonus, 0.0)
    labels = np.array([p["label"] for p in pairs])
    split = np.array([p["split"] for p in pairs])
    kinds = np.array([p["kind"] for p in pairs])

    dev, test = split == "dev", split == "test"
    sweep = [prf(scores[dev], labels[dev], round(t, 2)) for t in np.arange(0.30, 1.01, 0.01)]
    best = max(sweep, key=lambda m: (m["f1"], m["precision"]))  # tie -> higher precision
    t = best["threshold"]
    test_m = prf(scores[test], labels[test], t)
    by_kind: dict[str, Any] = {
        k: float(np.mean((scores[test & (kinds == k)] >= t) == (labels[test & (kinds == k)] == 1)))
        for k in ("positive", "hard_negative", "easy_negative") if np.any(test & (kinds == k))
    }

    md = "\n".join([
        "# Duplicate detection metrics (synthetic pairs)", "",
        f"Embedder: `{emb.name}`  Same-service bonus: {bonus}  "
        f"Dev pairs: {int(dev.sum())}  Test pairs: {int(test.sum())}", "",
        f"Threshold chosen on **dev** (max F1, ties -> precision): **{t:.2f}** "
        f"(dev F1 {best['f1']:.3f})", "",
        "| Split | Precision | Recall | F1 |", "|---|---|---|---|",
        f"| test | {test_m['precision']:.3f} | {test_m['recall']:.3f} | {test_m['f1']:.3f} |", "",
        "Accuracy by pair kind (test): " + ", ".join(f"{k} {v:.3f}" for k, v in by_kind.items()),
        "", f"Set `DUP_THRESHOLD={t:.2f}` in config if adopting this result.", "",
    ])
    write_metrics("duplicates", {
        "embedder": emb.name, "bonus": bonus, "chosen_threshold": t,
        "dev_best": best, "test": test_m, "test_accuracy_by_kind": by_kind, "dev_sweep": sweep,
    }, md)


if __name__ == "__main__":
    main()
