"""Batch 38: retry the single held filesystem free-block question without an asset token."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE = ROOT / "storage/quality-audits/phase45hx-20261011/batch-37-remaining-408"
checkpoint = json.loads((SOURCE / "checkpoint.json").read_text(encoding="utf-8"))
if checkpoint.get("status") != "BATCH_37_REMAINING_408_COMPLETE":
    raise RuntimeError("batch37_checkpoint_not_successful")
if checkpoint.get("development_5433_touched") is not False:
    raise RuntimeError("batch37_development_database_guard_failed")

base = importlib.import_module("scripts.run_phase45hx_batch26_originals")
batch = importlib.import_module("scripts.run_phase45hx_batch02")
batch.SOURCE_RUN = SOURCE
batch.OUT = ROOT / "storage/quality-audits/phase45hx-20261011/batch-38-asset-guard-retry"
batch.PACK = None
batch.PDF = None
batch.EXPECTED_QUESTIONS = 0
batch.PROCESS_PACK = False
batch.SOURCE_SUCCESS_STATUS = "BATCH_37_REMAINING_408_COMPLETE"
batch.PHASE_LABEL = "4.5H-X-batch-38-asset-guard-retry"
batch.SUCCESS_STATUS = "BATCH_38_ASSET_GUARD_RETRY_COMPLETE"
batch.TEST_FILES = ["tests/integration/test_auto_question_review.py"]
batch.TEST_ARGS = ["-k", "codex_public_original_review_qualifies_without_family_solver_and_excludes_personal_copy"]
batch.CODEX_PUBLIC_ORIGINALS = []
node_code = "cs408.os.topic.02e11d34761a"
remaining = {
    row["node_code"]: row
    for row in checkpoint["after_inventory"]["candidates"]
    if row.get("eligible_question_count") == 1 and ".family." not in row["node_code"]
    and row["node_code"] != "cs408.os.topic.28afec2a802b"
}
if set(remaining) != {node_code}:
    raise RuntimeError(f"unexpected_remaining_single_question_nodes:{sorted(remaining)}")

answer = "B"
batch.CODEX_PUBLIC_ORIGINALS.append({
    "request_id": "hx38-os-free-block-index-retry",
    "node_code": node_code,
    "output": base.choice(
        "文件系统按块号递增保存空闲状态标志，编码约定为1=空闲、0=已分配；标志序列为 [1,0,1,1,0]，下标0对应块号0。哪些块当前空闲？",
        {"A": "块1、块4", "B": "块0、块2、块3", "C": "块0、块1、块2", "D": "块2、块3、块4"},
        answer,
        "序列下标0、2、3的标志为1，其余为0，因此空闲块号为0、2、3。",
        "independent-check:indexed-free-state; enumerate-one-bits -> B",
    ),
    "derived_answer": answer,
    "method_evidence": [
        {"method": "indexed-state-lookup", "result": "按题设下标映射读取状态：0、2、3位置为1，得到B。"},
        {"method": "one-bit-enumeration", "result": "逐位枚举所有空闲标志下标为0、2、3，与B一致。"},
    ],
    "explanation_key_steps": [
        "第一步：按题设确定下标与块号相同且1表示空闲。",
        "第二步：列出序列中值为1的下标0、2、3。",
    ],
    "option_truth_table": {"A": False, "B": True, "C": False, "D": False},
    "skill_tags": ["文件系统全局结构", "空闲块状态管理", "位序列索引"],
})

if __name__ == "__main__":
    raise SystemExit(batch.main())
