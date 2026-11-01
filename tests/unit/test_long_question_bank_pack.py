"""大题库内容包与稳定 ID 的离线回归。"""
from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "content" / "long_question_packs" / "pilot_20261018.json"


def load_pack() -> dict:
    return json.loads(PACK.read_text(encoding="utf-8"))


def test_pack_has_two_distinct_items_per_knowledge_point():
    items = load_pack()["items"]
    counts = Counter(item["kp_code"] for item in items)
    assert counts and all(value == 2 for value in counts.values())
    for kp_code in counts:
        pair = [item for item in items if item["kp_code"] == kp_code]
        assert pair[0]["slug"] != pair[1]["slug"]
        assert pair[0]["stem"] != pair[1]["stem"]
        assert pair[0]["role"] != pair[1]["role"]


def test_every_item_has_complete_answer_and_metadata():
    for item in load_pack()["items"]:
        assert len(item["solution_steps"]) >= 3
        assert item["answer"].strip()
        assert item["objective"].strip()
        assert item["key_points"] and item["common_errors"] and item["scope"]
        assert item["review"]["review_status"] in {
            "AUTO_CHECKED_REFERENCE_ONLY", "PENDING_HUMAN_REVIEW"}
        assert item["review"]["answer_checked"] == (
            item["review"]["review_status"] == "AUTO_CHECKED_REFERENCE_ONLY")


def test_offline_validator_passes():
    result = subprocess.run(
        [sys.executable, "scripts/validate_long_question_pack.py"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"failed": 0' in result.stdout


def test_stable_question_ids_are_deterministic_and_unique():
    from backend.services.long_question_bank import Pack, stable_question_id

    pack = Pack.load(PACK)
    first = [stable_question_id(pack.batch_key, item) for item in pack.items]
    second = [stable_question_id(pack.batch_key, item) for item in pack.items]
    assert first == second
    assert len(set(first)) == len(first)
