#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""轻量三级审核：PASS / REVIEW / REJECT。

只消费已有校验结果，不新增逐题验证器：
- REJECT：结构、知识点、数值或重复检查出现硬错误。
- REVIEW：自动验证有限（如证明题）或存在轻微疑点，但未发现明确错误。
- PASS：其余满足基本质量要求的题。
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=Path("content/long_question_packs/pilot_20261018.json"))
    parser.add_argument("--validation", type=Path,
                        default=Path("docs/long-question-pack-validation-20261018.json"))
    parser.add_argument("--inventory", type=Path, default=Path("docs/long-question-inventory-20261018.csv"))
    parser.add_argument("--out", type=Path, default=Path("docs/long-question-triage-pilot-20261018.json"))
    parser.add_argument("--report", type=Path, default=Path("docs/long-question-triage-pilot-20261018.md"))
    args = parser.parse_args()

    pack = json.loads(args.pack.read_text(encoding="utf-8"))
    validation = json.loads(args.validation.read_text(encoding="utf-8"))
    by_slug = {row["slug"]: row for row in validation["results"]}
    inventory = {}
    with args.inventory.open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            inventory[row["知识点ID（稳定code）"]] = row

    results = []
    for item in pack["items"]:
        check = by_slug.get(item["slug"], {})
        hard_errors = list(check.get("errors") or [])
        review = item.get("review") or {}
        reasons = []
        verdict = "PASS"
        if hard_errors:
            verdict = "REJECT"
            reasons.append("硬错误：" + ", ".join(hard_errors))
        else:
            if review.get("review_status") == "PENDING_HUMAN_REVIEW" or not review.get("answer_checked"):
                verdict = "REVIEW"
                reasons.append("自动验证有限（证明题/需人工判断），未发现具体疑点")
            if item.get("difficulty") not in {"medium", "advanced"}:
                verdict = "REVIEW"
                reasons.append("难度偏低，不适合作为考研大题训练")
            if not item.get("verification_steps") and item.get("question_type") not in {"proof"}:
                verdict = "REVIEW"
                reasons.append("缺少可机器复核的数值步骤")
        row = inventory.get(item["kp_code"], {})
        results.append({
            "slug": item["slug"],
            "title": item["title"],
            "kp_code": item["kp_code"],
            "kp_name": row.get("知识点名称", ""),
            "type": item["question_type"],
            "difficulty": item["difficulty"],
            "verdict": verdict,
            "reasons": reasons,
            "checks": {
                "content_complete": not any("stem" in e or "answer" in e or "solution" in e for e in hard_errors),
                "knowledge_point_valid": row.get("适合大题") == "是",
                "answer_check": "auto" if review.get("answer_checked") else "manual_review",
                "in_scope": row.get("适合大题") == "是",
                "duplicate_similarity": check.get("max_similarity"),
                "duplicate_ok": (check.get("max_similarity") or 0) < 0.80,
                "difficulty_ok": item.get("difficulty") in {"medium", "advanced"},
            },
            "review_status": review.get("review_status"),
        })

    counts = {key: sum(1 for row in results if row["verdict"] == key)
              for key in ("PASS", "REVIEW", "REJECT")}
    payload = {"pack": str(args.pack), "items": len(results), "counts": counts, "results": results}
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [f"# 三级审核结果 · {pack.get('batch_key')}", "",
             f"- PASS：**{counts['PASS']}**　REVIEW：**{counts['REVIEW']}**　REJECT：**{counts['REJECT']}**", "",
             "| slug | 知识点 | 题型 | 难度 | 完整性 | 节点 | 答案 | 重复 | 结论 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for row in results:
        c = row["checks"]
        lines.append(
            f"| {row['slug']} | {row['kp_name']} | {row['type']} | {row['difficulty']} "
            f"| {'✓' if c['content_complete'] else '✗'} | {'✓' if c['knowledge_point_valid'] else '✗'} "
            f"| {c['answer_check']} | {c['duplicate_similarity']:.2f} | **{row['verdict']}** |")
    review_rows = [row for row in results if row["verdict"] != "PASS"]
    if review_rows:
        lines += ["", "## 非 PASS 原因", ""]
        for row in review_rows:
            lines.append(f"- `{row['slug']}`（{row['verdict']}）：{'；'.join(row['reasons'])}")
    args.report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"items": len(results), "counts": counts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
