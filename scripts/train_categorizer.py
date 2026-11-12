"""Train the categorizer and evaluate it on a held-out stratified split.

Run:  python -m scripts.train_categorizer [--backend minilm|hashing]
Outputs: models/categorizer.joblib, docs/metrics/categorizer.{json,md}
"""

from __future__ import annotations

import argparse
from pathlib import Path

from app.intelligence.categorizer import save_categorizer, train_logreg
from app.intelligence.text import incident_text
from scripts._common import embedder_for, read_jsonl, write_metrics


def main(argv: list[str] | None = None) -> None:
    from sklearn.metrics import classification_report, confusion_matrix
    from sklearn.model_selection import train_test_split

    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=Path("data/synthetic_incidents.jsonl"))
    ap.add_argument("--out", type=Path, default=Path("models/categorizer.joblib"))
    ap.add_argument("--backend", choices=["minilm", "hashing"], default=None)
    ap.add_argument("--test-size", type=float, default=0.25)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args(argv)

    rows = read_jsonl(args.data)
    texts = [incident_text(r["title"], r["description"]) for r in rows]
    labels = [r["category"] for r in rows]

    embedder = embedder_for(args.backend)
    x = embedder.encode(texts)
    x_tr, x_te, y_tr, y_te = train_test_split(
        x, labels, test_size=args.test_size, stratify=labels, random_state=args.seed
    )
    model = train_logreg(x_tr, y_tr, args.seed)
    save_categorizer(model, args.out, embedder.name)

    pred = model.predict(x_te)
    classes = sorted(set(labels))
    report = classification_report(y_te, pred, labels=classes, output_dict=True, zero_division=0)
    cm = confusion_matrix(y_te, pred, labels=classes).tolist()

    md = [f"# Categorizer metrics (synthetic data, held-out {args.test_size:.0%})", "",
          f"Embedder: `{embedder.name}`  Train: {len(y_tr)}  Test: {len(y_te)}  Seed: {args.seed}",
          "", "| Class | Precision | Recall | F1 | Support |", "|---|---|---|---|---|"]
    for c in classes:
        r = report[c]
        md.append(f"| {c} | {r['precision']:.3f} | {r['recall']:.3f} | "
                  f"{r['f1-score']:.3f} | {int(r['support'])} |")
    md += ["", f"Macro F1: **{report['macro avg']['f1-score']:.3f}**  "
               f"Accuracy: **{report['accuracy']:.3f}**", "",
           "Confusion matrix (rows = true, cols = predicted, order as above):", "", "```"]
    md += [" ".join(f"{v:4d}" for v in row) for row in cm] + ["```", ""]

    write_metrics("categorizer", {
        "embedder": embedder.name, "seed": args.seed, "classes": classes,
        "report": report, "confusion_matrix": cm,
    }, "\n".join(md))
    print(f"saved model to {args.out}")


if __name__ == "__main__":
    main()
