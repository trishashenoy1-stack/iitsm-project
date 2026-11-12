# Duplicate detection metrics (synthetic pairs)

Embedder: `sentence-transformers/all-MiniLM-L6-v2`  Same-service bonus: 0.05  Dev pairs: 301  Test pairs: 299

Threshold chosen on **dev** (max F1, ties -> precision): **0.47** (dev F1 0.941)

| Split | Precision | Recall | F1 |
|---|---|---|---|
| test | 0.885 | 0.973 | 0.927 |

Accuracy by pair kind (test): positive 0.973, hard_negative 0.846, easy_negative 1.000

Set `DUP_THRESHOLD=0.47` in config if adopting this result.
