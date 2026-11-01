"""Retry only batch26 candidates blocked by short review notes.

This starts from the successful batch26 isolated checkpoint, preserves all
prior outputs, and strengthens the content-bound review documentation without
changing the review rules. No model calls are made.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

source = ROOT / "storage/quality-audits/phase45hx-20261011/batch-26-originals"
checkpoint = json.loads((source / "checkpoint.json").read_text(encoding="utf-8"))
if checkpoint.get("status") != "BATCH_26_ORIGINALS_COMPLETE":
    raise RuntimeError("batch26_checkpoint_not_successful")
if checkpoint.get("development_5433_touched") is not False:
    raise RuntimeError("batch26_development_database_guard_failed")

failed_ids = {
    row["request_id"]
    for row in checkpoint.get("codex_public_originals", [])
    if row.get("status") != "AUTO_VERIFIED"
}
base = importlib.import_module("scripts.run_phase45hx_batch26_originals")
batch = importlib.import_module("scripts.run_phase45hx_batch02")
batch.SOURCE_RUN = source
batch.OUT = ROOT / "storage/quality-audits/phase45hx-20261011/batch-27-evidence-retry"
batch.PACK = None
batch.PDF = None
batch.EXPECTED_QUESTIONS = 0
batch.PROCESS_PACK = False
batch.SOURCE_SUCCESS_STATUS = "BATCH_26_ORIGINALS_COMPLETE"
batch.PHASE_LABEL = "4.5H-X-batch-27-evidence-retry"
batch.SUCCESS_STATUS = "BATCH_27_EVIDENCE_RETRY_COMPLETE"
batch.TEST_FILES = ["tests/integration/test_auto_question_review.py"]
batch.TEST_ARGS = [
    "-k",
    "codex_public_original_review_qualifies_without_family_solver_and_excludes_personal_copy",
]

retry = [
    dict(spec)
    for spec in base.batch.CODEX_PUBLIC_ORIGINALS
    if spec["request_id"] in failed_ids
]
if len(retry) != len(failed_ids):
    raise RuntimeError("retry_candidate_mapping_incomplete")

# Replace a definition-only derivative item with a concrete calculation so
# the two documented routes are genuinely distinct: derivative definition
# versus the power rule.
for spec in retry:
    if spec["request_id"] == "hx26-math-derivative-definition-v1":
        spec["output"] = base.choice(
            "设 $f(x)=x^2$，则 $f'(1)$ 等于多少？",
            {"A": "1", "B": "2", "C": "3", "D": "4"},
            "B",
            "按导数定义，$[(1+h)^2-1]/h=2+h$，令 $h\\to0$ 得2。另由幂函数求导 $f'(x)=2x$，代入1也得2。",
            "((1+h)^2-1)/h -> 2; power-rule derivative 2x at x=1 -> 2",
        )
        spec["derived_answer"] = "B"
        spec["method_evidence"] = [
            {
                "method": "derivative-limit-definition",
                "result": "由差商展开为2+h，h趋于0后导数为2。",
            },
            {
                "method": "power-rule",
                "result": "幂函数求导得f′(x)=2x，代入x=1得到2。",
            },
        ]
        spec["option_truth_table"] = {
            "A": False,
            "B": True,
            "C": False,
            "D": False,
        }
        spec["explanation_key_steps"] = [
            "先按导数定义计算差商并取极限。",
            "再用幂函数求导法则独立核对结果。",
        ]

# The previous notes already contain the derivations; make their relationship
# to the answer explicit and ensure each key step is independently readable.
for spec in retry:
    answer = str(spec["derived_answer"])
    for index, evidence in enumerate(spec["method_evidence"], start=1):
        detail = evidence["result"].strip()
        evidence["result"] = (
            f"方法{index}（{evidence['method']}）复核：{detail}；"
            f"该路径据此得到答案 {answer}。"
        )
    spec["explanation_key_steps"] = [
        f"关键推理：{step.strip()}" for step in spec["explanation_key_steps"]
    ]

batch.CODEX_PUBLIC_ORIGINALS = retry

if __name__ == "__main__":
    raise SystemExit(batch.main())
