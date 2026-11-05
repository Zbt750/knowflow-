"""Retry two batch32 holds with narrower, non-duplicate formulations."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE = ROOT / "storage/quality-audits/phase45hx-20261011/batch-32-second-supply"
checkpoint = json.loads((SOURCE / "checkpoint.json").read_text(encoding="utf-8"))
if checkpoint.get("status") != "BATCH_32_SECOND_SUPPLY_COMPLETE":
    raise RuntimeError("batch32_checkpoint_not_successful")
if checkpoint.get("development_5433_touched") is not False:
    raise RuntimeError("batch32_development_database_guard_failed")

base = importlib.import_module("scripts.run_phase45hx_batch26_originals")
batch = importlib.import_module("scripts.run_phase45hx_batch02")
batch.SOURCE_RUN = SOURCE
batch.OUT = ROOT / "storage/quality-audits/phase45hx-20261011/batch-33-retry-two"
batch.PACK = None
batch.PDF = None
batch.EXPECTED_QUESTIONS = 0
batch.PROCESS_PACK = False
batch.SOURCE_SUCCESS_STATUS = "BATCH_32_SECOND_SUPPLY_COMPLETE"
batch.PHASE_LABEL = "4.5H-X-batch-33-retry-held-items"
batch.SUCCESS_STATUS = "BATCH_33_RETRY_TWO_COMPLETE"
batch.TEST_FILES = ["tests/integration/test_auto_question_review.py"]
batch.TEST_ARGS = ["-k", "codex_public_original_review_qualifies_without_family_solver_and_excludes_personal_copy"]
batch.CODEX_PUBLIC_ORIGINALS = []


def add(req, node, stem, choices, answer, explanation, method1, result1,
        method2, result2, step1, step2, skills):
    batch.CODEX_PUBLIC_ORIGINALS.append({
        "request_id": req,
        "node_code": node,
        "output": base.choice(
            stem, {chr(65 + i): value for i, value in enumerate(choices)},
            answer, explanation, f"independent-check:{method1}; {method2} -> {answer}",
        ),
        "derived_answer": answer,
        "method_evidence": [
            {"method": method1, "result": f"路径一（{method1}）：{result1}；得 {answer}。"},
            {"method": method2, "result": f"路径二（{method2}）：{result2}；复核为 {answer}。"},
        ],
        "explanation_key_steps": [f"第一步：{step1}", f"第二步：{step2}"],
        "option_truth_table": {chr(65 + i): chr(65 + i) == answer for i in range(4)},
        "skill_tags": skills,
    })


add("hx33-408-graph-degree-sum", "cs408.ds.topic.48968798d156",
    "有限简单无向网络各结点的度数之和为 12，则边数为多少？",
    ["3", "6", "12", "24"], "B",
    "握手定理说明无向边在两个端点各贡献1度，度数和等于边数的2倍，所以边数为6。",
    "handshaking-lemma", "度数总和=2|E|，由12=2|E|得|E|=6。",
    "incidence-count", "逐条边计数时每条边恰贡献两个端点关联，12个关联对应6条边。",
    "把各结点度数总和与边关联数联系起来。", "用每条边贡献两个度数核算边数。", ["图基本概念", "度数", "握手定理"])
add("hx33-408-instruction-address-field", "cs408.co.topic.fbea44bd988b",
    "某定长机器指令字长 16 位，其中操作码占 4 位，其余位作为直接地址字段，可表示多少个不同主存地址？",
    ["256", "1024", "4096", "65536"], "C",
    "地址字段宽度为16−4=12位，可编码2¹²=4096个不同地址。",
    "field-width", "地址字段12位，编码数为2的12次方即4096。",
    "address-space", "一个12位二进制字段的不同取值从0到4095，共4096个。",
    "从总指令字长减去操作码位数。", "按剩余地址位数计算编码空间。", ["指令格式", "地址字段", "直接寻址"])

if len(batch.CODEX_PUBLIC_ORIGINALS) != 2 or len({x["node_code"] for x in batch.CODEX_PUBLIC_ORIGINALS}) != 2:
    raise RuntimeError("batch33_must_retry_exactly_two_distinct_items")

if __name__ == "__main__":
    raise SystemExit(batch.main())
