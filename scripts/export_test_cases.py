"""Build the testing-chapter table from @pytest.mark.case markers across ALL members' tests.

Run:  python -m scripts.export_test_cases
It runs pytest with `--cases-out` (a hook in tests/conftest.py records each case's
metadata and outcome), then renders docs/testing/cases.md.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path


def render(cases: list[dict[str, str]]) -> str:
    cases = sorted(cases, key=lambda c: c["id"])
    counts = Counter(c["category"] for c in cases)
    passed = sum(c["outcome"] == "passed" for c in cases)
    lines = [
        "# Test cases", "",
        f"{len(cases)} documented cases, {passed} passing. By category: "
        + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())), "",
        "| ID | Category | Description | Expected | Result | Test |",
        "|---|---|---|---|---|---|",
    ]
    for c in cases:
        lines.append(f"| {c['id']} | {c['category']} | {c['desc']} | {c['expected']} | "
                     f"{c['outcome']} | `{c['nodeid']}` |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, default=Path("docs/testing/cases.json"))
    ap.add_argument("--out", type=Path, default=Path("docs/testing/cases.md"))
    args, pytest_args = ap.parse_known_args(argv)  # anything unknown goes to pytest

    args.json.parent.mkdir(parents=True, exist_ok=True)
    code = subprocess.call([sys.executable, "-m", "pytest", "-q",
                            f"--cases-out={args.json}", *pytest_args])
    cases = json.loads(args.json.read_text(encoding="utf-8"))
    args.out.write_text(render(cases), encoding="utf-8")
    print(f"wrote {args.out} ({len(cases)} cases); pytest exit code {code}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
