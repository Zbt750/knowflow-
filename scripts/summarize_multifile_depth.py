"""Summarize actual browser answers plus explicit human source-audit findings; no judge calls."""
from __future__ import annotations

import json
import math
import re
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "eval/reports"


def main() -> None:
    batches = [json.loads((REPORTS / f"multifile-depth-{name}.json").read_text(encoding="utf-8")) for name in ("actual", "probes", "edges")]
    cases = [case for batch in batches for case in batch["cases"]]
    assert len(cases) == 60 and len({case["id"] for case in cases}) == 60
    incomplete = {"cross-math", "probe-cross-repeat", "probe-cross-reversed", "probe-cross-equal", "probe-cross-shorthand", "probe-follow-start", "probe-follow-retry"}
    audit = []
    for case in cases:
        notes = []
        if case["id"] in incomplete:
            status = "incomplete_multifile_task"
            notes.append("未完成用户要求的两文件内容及文件内例题比较；不是接口失败。")
        elif case["id"] == "table-weighted":
            status = "unsupported_detail"
            notes.append("84%正确，但原文只写样本数，回答无依据改写成20人/30人/50人。")
        elif case["id"] == "edge-title-typo":
            status = "clarification_instead_of_answer"
            notes.append("讲义误写讲议时返回补充文件名；没有编造，但没帮助识别已说明的错别字。")
        else:
            status = "no_material_issue_found_in_source_audit"
        if case["id"] == "probe-follow-retry":
            notes.append("取到两份文件但各只有一处范围/误区证据，没有例题；常识段称驻点是极值点必要条件，遗漏可导、内点等前提。")
        if case["id"] == "equivalent-cancellation":
            notes.append("自动规则误判：LaTeX -\\frac16 与 -1/6 等价；人工已确认正确。")
        if case["id"] == "edge-summary-limit":
            notes.append(f"汉字计数{len(re.findall(r'[\u4e00-\u9fff]',case['answer']))}，满足不超过150汉字；238字符包括字母/引用等。")
        if case["id"] == "acceptance-colloquial":
            notes.append("简短一点仍输出1542字符，内容正确，长度自适应有体验改进空间；不是硬字数违规。")
        cards = (case.get("citations") or {}).get("citations", [])
        labels = {card["label"] for card in cards}
        used = set(re.findall(r"\[(C\d+)\]", case["answer"]))
        last = next((message for message in reversed(case.get("saved") or []) if message["role"] == "assistant"), None)
        audit.append({"id": case["id"], "question": case["question"], "status": status, "notes": notes, "elapsed_ms": case["elapsed_ms"], "cited_files": sorted({card["material_title"] for card in cards}), "unmapped_citation_labels": sorted(used-labels), "persisted_exactly": bool(last and last["content"] == case["answer"] and last["status"] == "completed"), "transport_error": case["stream_error"]})
    seconds = sorted(case["elapsed_ms"]/1000 for case in cases)
    counts = {status: sum(row["status"] == status for row in audit) for status in sorted({row["status"] for row in audit})}
    summary = {
        "method": "真实Chrome前端、真实上传与检索、当前DeepSeek模型；原文事实检查及人工逐条复核。不是新RAGAS分数，不是通用准确率。",
        "case_count": len(cases), "audit_counts": counts,
        "transport_errors": sum(bool(row["transport_error"]) for row in audit),
        "persistence_mismatches": sum(not row["persisted_exactly"] for row in audit),
        "citation_mapping_errors": sum(bool(row["unmapped_citation_labels"]) for row in audit),
        "browser_errors": [error for batch in batches for error in batch["browser_errors"]],
        "latency_seconds": {"mean": round(statistics.mean(seconds), 2), "median": round(statistics.median(seconds), 2), "p95_nearest_rank": round(seconds[math.ceil(len(seconds)*.95)-1], 2), "max": round(max(seconds), 2), "over_10_seconds": sum(s>10 for s in seconds), "over_30_seconds": sum(s>30 for s in seconds)},
        "immediate_clarifications_or_scope_notices": [case["id"] for case in cases if case["elapsed_ms"] < 1000],
        "limitations": ["没有独立外部裁判或新增RAGAS评分", "引用编号存在不代表每条语义都忠实，样本单位偏差是反例", "单批一次采样不证明长期稳定率", "八份Markdown资料；未覆盖扫描PDF、DOCX、超大语料库或并发压力", "时延为发送到完整SSE终态及保存检查，不是首token时延，不能据此定位慢在检索或模型", "失败测评未自动修复业务代码"],
    }
    (REPORTS / "multifile-depth-audit.json").write_text(json.dumps({"summary": summary, "cases": audit}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
