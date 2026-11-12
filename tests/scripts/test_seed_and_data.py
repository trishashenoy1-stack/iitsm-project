from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from scripts.gen_synthetic import main as gen_main
from scripts.seed import PENDING_P2_apply_seed_plan, build_seed_plan


def test_seed_plan_is_deterministic_and_relative(t0: datetime) -> None:
    a, b = build_seed_plan(t0), build_seed_plan(t0)
    assert a == b
    keys = [i.key for i in a.incidents]
    assert len(keys) == len(set(keys)), "incident natural keys must be unique"
    later = build_seed_plan(t0 + timedelta(days=1))
    assert later.incidents[0].created_at - a.incidents[0].created_at == timedelta(days=1)
    assert len(a.sla_policies) == len(a.services) * 4


def test_seed_plan_rejects_naive_time() -> None:
    with pytest.raises(ValueError):
        build_seed_plan(datetime(2026, 11, 12))


@pytest.mark.case(id="TC-P4-20", category="normal",
                  desc="Seed script run twice", expected="No duplicate rows")
@pytest.mark.integration
def test_seed_twice_no_duplicates(t0: datetime) -> None:
    try:
        PENDING_P2_apply_seed_plan(build_seed_plan(t0))
        PENDING_P2_apply_seed_plan(build_seed_plan(t0))
    except NotImplementedError:
        pytest.skip("PENDING_P2: seed writer needs P2's models")
    # PENDING_P2: then count rows per table and compare to the plan sizes.


def test_gen_synthetic_reproducible(tmp_path: Path) -> None:
    gen_main(["--per-category", "5", "--pairs", "30", "--out-dir", str(tmp_path / "a")])
    gen_main(["--per-category", "5", "--pairs", "30", "--out-dir", str(tmp_path / "b")])
    for name in ("synthetic_incidents.jsonl", "duplicate_pairs.jsonl"):
        assert (tmp_path / "a" / name).read_text() == (tmp_path / "b" / name).read_text()
    raw = (tmp_path / "a" / "duplicate_pairs.jsonl").read_text().splitlines()
    pairs = [json.loads(x) for x in raw if x]
    assert {p["kind"] for p in pairs} == {"positive", "hard_negative", "easy_negative"}
    hard = [p for p in pairs if p["kind"] == "hard_negative"]
    assert all(p["a"]["service"] == p["b"]["service"] for p in hard)
