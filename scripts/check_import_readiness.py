#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""入库就绪检查：50 题内容包 / 39 PASS 筛选 / 稳定 ID / 脚本与参数。

只读，不连接数据库。输出 JSON + Markdown。
"""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
PACKS = [
    ("pilot", "pilot_20261018.json", "docs/long-question-triage-pilot-20261018.json"),
    ("os01", "os_batch01_20261018.json", "docs/long-question-triage-os01-20261018.json"),
    ("ds01", "ds_batch01_20261018.json", "docs/long-question-triage-ds01-20261018.json"),
    ("co01", "co_batch01_20261018.json", "docs/long-question-triage-co01-20261018.json"),
    ("cn01", "cn_batch01_20261018.json", "docs/long-question-triage-cn01-20261018.json"),
]


def main() -> int:
    inventory = {}
    with (ROOT / "docs/long-question-inventory-20261018.csv").open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            inventory[row["知识点ID（稳定code）"]] = row

    summary = {"packs": [], "pass_total": 0, "review_total": 0,
               "stable_ids": {}, "per_kp_pass": Counter(), "errors": []}
    for tag, filename, triage_path in PACKS:
        pack_path = ROOT / "content/long_question_packs" / filename
        if not pack_path.exists():
            summary["errors"].append(f"missing_pack:{filename}")
            continue
        pack = json.loads(pack_path.read_text(encoding="utf-8"))
        triage = json.loads((ROOT / triage_path).read_text(encoding="utf-8"))
        verdicts = {row["slug"]: row["verdict"] for row in triage.get("results", [])}
        pass_items = [item for item in pack["items"] if verdicts.get(item["slug"]) == "PASS"]
        review_items = [item for item in pack["items"] if verdicts.get(item["slug"]) != "PASS"]
        for item in pass_items:
            if item["kp_code"] not in inventory:
                summary["errors"].append(f"kp_missing:{item['slug']}")
            elif inventory[item["kp_code"]]["适合大题"] != "是":
                summary["errors"].append(f"kp_not_suitable:{item['slug']}")
            key = f"long-question-bank:{pack['batch_key']}:{item['slug']}"
            qid = str(uuid5(NAMESPACE_URL, key))
            if qid in summary["stable_ids"]:
                summary["errors"].append(f"duplicate_stable_id:{qid}")
            summary["stable_ids"][qid] = {"pack": tag, "slug": item["slug"]}
            summary["per_kp_pass"][item["kp_code"]] += 1
        summary["packs"].append({
            "tag": tag, "pack": str(pack_path.relative_to(ROOT)),
            "batch_key": pack["batch_key"], "sha256": hashlib.sha256(pack_path.read_bytes()).hexdigest(),
            "questions": len(pack["items"]), "pass": len(pass_items), "review": len(review_items),
            "pass_slugs": [item["slug"] for item in pass_items],
            "review_slugs": [item["slug"] for item in review_items],
        })
        summary["pass_total"] += len(pass_items)
        summary["review_total"] += len(review_items)

    required = ["scripts/import_long_question_bank.py", "scripts/verify_long_question_bank.py",
                "scripts/run_long_question_import.ps1", "scripts/check_database_target.py",
                "scripts/long_question_db_report.py"]
    summary["files_present"] = {path: (ROOT / path).exists() for path in required}
    ps1 = (ROOT / "scripts/run_long_question_import.ps1").read_text(encoding="utf-8")
    summary["ps1_tokens"] = {
        "reject_kaoyan": 'database -eq "kaoyan"' in ps1,
        "require_test": '*_test' in ps1,
        "db_identity_check": "check_database_target.py" in ps1,
        "verdict_filter": "--verdicts" in ps1,
        "include_review": "-IncludeReview" in ps1,
        "dry_run": "--dry-run" in ps1,
        "confirm_database": "--confirm-database" in ps1,
        "second_pass": ps1.count("第二次导入") >= 1,
        "exercise_count": "--exercise-count" in ps1,
        "closure_report": "long-question-import-closure" in ps1,
    }
    summary["per_kp_pass"] = dict(summary["per_kp_pass"])
    summary["kps_with_zero_pass"] = sorted(
        code for code, row in inventory.items()
        if row["适合大题"] == "是" and code not in summary["per_kp_pass"])
    summary["status"] = "PASS" if (
        not summary["errors"] and summary["pass_total"] == 39 and summary["review_total"] == 11
        and all(summary["files_present"].values()) and all(summary["ps1_tokens"].values())
    ) else "FAIL"

    out = ROOT / "docs/long-question-import-readiness-20261018.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 入库就绪检查（39 PASS / 11 REVIEW）", "",
             f"- 状态：**{summary['status']}**",
             f"- PASS：**{summary['pass_total']}**　REVIEW：**{summary['review_total']}**",
             f"- 稳定 ID 唯一：**{len(summary['stable_ids']) == summary['pass_total']}**", "",
             "| 批次 | 题数 | PASS | REVIEW | 包 SHA-256（前 12 位） |",
             "|---|---:|---:|---:|---|"]
    for pack in summary["packs"]:
        lines.append(f"| {pack['tag']} | {pack['questions']} | {pack['pass']} | {pack['review']} | {pack['sha256'][:12]} |")
    lines += ["", "## 脚本检查", ""]
    lines += [f"- {name}: {'OK' if ok else 'MISSING'}" for name, ok in summary["ps1_tokens"].items()]
    if summary["errors"]:
        lines += ["", "## 错误", ""] + [f"- {error}" for error in summary["errors"]]
    (ROOT / "docs/long-question-import-readiness-20261018.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("status", "pass_total", "review_total",
                      "files_present", "ps1_tokens", "errors")}, ensure_ascii=False, indent=2))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
