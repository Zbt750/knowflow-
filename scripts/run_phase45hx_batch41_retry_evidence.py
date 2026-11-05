"""Batch 41: retry three batch40 candidates with adequately documented checks."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE = ROOT / "storage/quality-audits/phase45hx-20261011/batch-40-third-supply"
checkpoint = json.loads((SOURCE / "checkpoint.json").read_text(encoding="utf-8"))
if checkpoint.get("status") != "BATCH_40_THIRD_SUPPLY_COMPLETE":
    raise RuntimeError("batch40_checkpoint_not_successful")
if checkpoint.get("development_5433_touched") is not False:
    raise RuntimeError("batch40_development_database_guard_failed")

base = importlib.import_module("scripts.run_phase45hx_batch26_originals")
batch = importlib.import_module("scripts.run_phase45hx_batch02")
batch.SOURCE_RUN = SOURCE
batch.OUT = ROOT / "storage/quality-audits/phase45hx-20261011/batch-41-retry-evidence"
batch.PACK = None
batch.PDF = None
batch.EXPECTED_QUESTIONS = 0
batch.PROCESS_PACK = False
batch.SOURCE_SUCCESS_STATUS = "BATCH_40_THIRD_SUPPLY_COMPLETE"
batch.PHASE_LABEL = "4.5H-X-batch-41-retry-evidence"
batch.SUCCESS_STATUS = "BATCH_41_RETRY_EVIDENCE_COMPLETE"
batch.TEST_FILES = ["tests/integration/test_auto_question_review.py"]
batch.TEST_ARGS = ["-k", "codex_public_original_review_qualifies_without_family_solver_and_excludes_personal_copy"]
batch.CODEX_PUBLIC_ORIGINALS = []

TARGETS = {
    "math.exam.7d287abb612e",
    "cs408.cn.topic.e09a336289ea",
    "cs408.co.topic.0efeb18eeae7",
}
eligible = {
    row["node_code"]: row
    for row in checkpoint["after_inventory"]["candidates"]
    if row.get("eligible_question_count") == 2 and ".family." not in row["node_code"]
}
if not TARGETS.issubset(eligible):
    raise RuntimeError(f"batch41_nodes_not_still_at_two:{sorted(TARGETS-set(eligible))}")


def add(req, node, stem, choices, answer, explanation, method1, result1,
        method2, result2, step1, step2, skills):
    batch.CODEX_PUBLIC_ORIGINALS.append({
        "request_id": req,
        "node_code": node,
        "output": base.choice(stem, {chr(65+i): value for i, value in enumerate(choices)},
                              answer, explanation,
                              f"independent-check:{method1}; {method2} -> {answer}"),
        "derived_answer": answer,
        "method_evidence": [
            {"method": method1, "result": f"路径一：{result1}，据此得到选项 {answer}。"},
            {"method": method2, "result": f"路径二：{result2}，独立复核仍得到选项 {answer}。"},
        ],
        "explanation_key_steps": [f"第一步：{step1}", f"第二步：{step2}"],
        "option_truth_table": {chr(65+i): chr(65+i)==answer for i in range(4)},
        "skill_tags": skills,
    })


add("hx41-math-partial-x", "math.exam.7d287abb612e",
    r"设$z=x^2y+y^3$，求$\partial z/\partial x$在$(x,y)=(2,1)$处的值。",
    ["2", "4", "7", "12"], "B",
    r"对$x$求偏导时将$y$视为常数，$z_x=2xy$，代入$(2,1)$得到4。",
    "partial-derivative-rule", r"逐项求偏导，$x^2y$对$x$的导数是$2xy$，而$y^3$对$x$的偏导为0。",
    "point-substitution", "将给定坐标代入导数式，数值计算为2乘2乘1等于4。",
    "对$x$求偏导并保持$y$不变。", "将$(x,y)=(2,1)$代入$2xy$核对选项。", ["偏导数的概念与计算", "偏导"])
add("hx41-cn-shannon-snr", "cs408.cn.topic.e09a336289ea",
    "按香农公式，带宽4 kHz的理想信道要达到12 kbit/s容量，所需信噪比（线性值）至少是多少？",
    ["3", "7", "8", "15"], "B",
    r"由$C=B\log_2(1+S/N)$，容量与带宽之比为3 bit/s/Hz，故线性信噪比为7。",
    "solve-shannon-equation", "代入香农公式后解得1加信噪比等于2的3次方，所以信噪比为7。",
    "unit-normalized-capacity", "12 kbit/s除以4 kHz得到3 bit/s/Hz，再反算得到信噪比7。",
    "先统一容量和带宽单位并计算频谱效率。", "反解香农公式并确认题目要线性比值。", ["奈奎斯特与香农定理", "香农容量"])
add("hx41-co-unsigned-product", "cs408.co.topic.0efeb18eeae7",
    r"无符号二进制数$1110_2$与$11_2$的乘积是多少？",
    [r"$101010_2$", r"$100110_2$", r"$11110_2$", r"$110011_2$"], "A",
    r"$1110_2=14$、$11_2=3$，乘积42，转换为二进制为$101010_2$。",
    "decimal-conversion-check", "两个无符号数分别是十进制14和3，乘积是42，42的二进制表示为101010。",
    "binary-partial-products", r"按位展开得到$1110_2+(1110_2\ll1)=1110_2+11100_2=101010_2$。",
    "将两个二进制因数转成十进制相乘。", "再用二进制部分积独立计算并比较结果。", ["整数乘除运算", "无符号乘法"])

if len(batch.CODEX_PUBLIC_ORIGINALS) != 3:
    raise RuntimeError("batch41_requires_three_retry_candidates")
if {x["node_code"] for x in batch.CODEX_PUBLIC_ORIGINALS} != TARGETS:
    raise RuntimeError("batch41_nodes_not_exactly_the_three_rejected_nodes")

if __name__ == "__main__":
    raise SystemExit(batch.main())
