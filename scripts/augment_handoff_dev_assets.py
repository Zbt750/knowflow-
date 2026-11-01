#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把开发库快照里的 10 道正式长题 + 79 道未正式长题并入全量交接包。

输出：handoff/long-question-full-20261018/
不连接数据库；只读 sealed dump。
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "handoff/long-question-final-20261018"
OUT = ROOT / "handoff/long-question-full-20261018"
SEALED = ROOT / "storage/quality-audits/long-question-supply-20261017/sealed-questions.copy.sql"
LONG = {"calculation", "proof", "subjective", "discussion", "program"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decode(value):
    if value == r"\N":
        return None
    escapes = {"t": "\t", "n": "\n", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "\\": "\\"}
    return re.sub(r"\\([0-7]{1,3}|.)",
                  lambda m: chr(int(m[1], 8)) if m[1][0] in "01234567" else escapes.get(m[1], m[1]),
                  value)


def load_sealed_long():
    columns = None
    rows = []
    for line in SEALED.read_text(encoding="utf-8").splitlines():
        if line.startswith("COPY public.questions ("):
            columns = line.split("(", 1)[1].split(")", 1)[0].split(", ")
            continue
        if columns is None:
            continue
        if line == r"\.":
            break
        values = line.split("\t")
        if len(values) == len(columns):
            rows.append(dict(zip(columns, values)))
    code_by = {}
    for row in rows:
        gc = decode(row.get("grading_config"))
        if not gc:
            continue
        try:
            code = ((json.loads(gc).get("generation") or {}).get("node_code") or "").strip()
        except (ValueError, TypeError):
            code = ""
        if code:
            code_by[row["kp_id"]] = code
    formal, unqualified = [], []
    for row in rows:
        if decode(row["question_type"]) not in LONG:
            continue
        kp_code = code_by.get(row["kp_id"])
        if not kp_code:
            continue
        trust = decode(row["content_trust"])
        item = {
            "stable_id": row["id"],
            "kp_code": kp_code,
            "title": (decode(row["stem"]) or "")[:40].replace("\n", " "),
            "question_type": decode(row["question_type"]),
            "difficulty": decode(row["difficulty"]) or "advanced",
            "estimated_minutes": int(decode(row["estimated_minutes"]) or 15),
            "stem": decode(row["stem"]),
            "answer": decode(row["correct_answer"]),
            "explanation": decode(row["explanation"]),
            "source": "existing_dev_public_formal" if trust == "auto_verified" else "existing_dev_unqualified",
            "already_in_target_db": True,
            "public_formal_status": ("public_auto_verified_in_dev" if trust == "auto_verified"
                                     else "not_public_formal"),
            "content_review": "PASS" if trust == "auto_verified" else "REVIEW",
            "review_reason": (None if trust == "auto_verified" else
                              "开发库已有长题，但未取得 public auto_verified；需复核/资格流程，禁止重复导入"),
            "provenance": decode(row["question_provenance"]),
            "content_trust": trust,
        }
        (formal if trust == "auto_verified" else unqualified).append(item)
    return formal, unqualified


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SRC, OUT, dirs_exist_ok=True)
    formal, unqualified = load_sealed_long()

    review = json.loads((OUT / "questions_review.json").read_text(encoding="utf-8"))
    existing_public = json.loads((OUT / "questions_existing_public.json").read_text(encoding="utf-8"))
    pass_items = json.loads((OUT / "questions_pass.json").read_text(encoding="utf-8"))
    reject = json.loads((OUT / "questions_reject.json").read_text(encoding="utf-8"))
    manifest = json.loads((OUT / "question_manifest.json").read_text(encoding="utf-8"))

    existing_ids = {item["stable_id"] for item in pass_items + review + existing_public}
    added_review = [item for item in unqualified if item["stable_id"] not in existing_ids]
    added_public = [item for item in formal if item["stable_id"] not in existing_ids]
    review.extend(added_review)
    existing_public.extend(added_public)

    for item in added_review:
        manifest.append({
            "stable_id": item["stable_id"], "kind": "existing_dev_unqualified",
            "pack": "sealed-dev-20261017", "batch_key": "existing-dev-review",
            "slug": item["stable_id"], "kp_code": item["kp_code"], "title": item["title"],
            "question_type": item["question_type"], "difficulty": item["difficulty"],
            "content_review": "REVIEW", "personal_practice_eligible": False,
            "public_formal_status": item["public_formal_status"],
            "source": item["source"], "file": str(SEALED.relative_to(ROOT)),
            "pack_sha256": sha256(SEALED), "already_in_target_db": True,
        })
    for item in added_public:
        manifest.append({
            "stable_id": item["stable_id"], "kind": "existing_dev_public_formal",
            "pack": "sealed-dev-20261017", "batch_key": "existing-dev-formal",
            "slug": item["stable_id"], "kp_code": item["kp_code"], "title": item["title"],
            "question_type": item["question_type"], "difficulty": item["difficulty"],
            "content_review": "PASS", "personal_practice_eligible": False,
            "public_formal_status": item["public_formal_status"],
            "source": item["source"], "file": str(SEALED.relative_to(ROOT)),
            "pack_sha256": sha256(SEALED), "already_in_target_db": True,
        })

    for name, payload in [
        ("questions_pass.json", pass_items),
        ("questions_review.json", review),
        ("questions_reject.json", reject),
        ("questions_existing_public.json", existing_public),
        ("question_manifest.json", manifest),
    ]:
        (OUT / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # 覆盖表
    inventory = {}
    with (ROOT / "docs/long-question-inventory-20261018.csv").open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            inventory[row["知识点ID（稳定code）"]] = row
    hist_by_kp = Counter(item["kp_code"] for item in existing_public
                         if item["source"] == "historical_public_qualified")
    dev_formal_by_kp = Counter(item["kp_code"] for item in existing_public
                               if item["source"] == "existing_dev_public_formal")
    dev_unq_by_kp = Counter(item["kp_code"] for item in added_review)
    new_pass_by_kp = Counter(item["kp_code"] for item in pass_items)
    new_review_by_kp = Counter(item["kp_code"] for item in review
                               if item.get("source") == "ai_generated_original")
    coverage = []
    for code, row in inventory.items():
        if row["适合大题"] != "是":
            continue
        existing_dev = int(row["现有有效大题数(采用)"])
        existing_dev_long = int(row["在线大题数(审计)"] or 0)
        hist = hist_by_kp.get(code, 0)
        dev_formal = dev_formal_by_kp.get(code, 0)
        dev_unq = dev_unq_by_kp.get(code, 0)
        new_pass = new_pass_by_kp.get(code, 0)
        new_review = new_review_by_kp.get(code, 0)
        qualified = existing_dev + hist + new_pass  # dev_formal 已含在 existing_dev 中，避免重复计数
        content = qualified + dev_unq + new_review
        coverage.append({
            "kp_code": code, "kp_name": row["知识点名称"], "subject": row["学科"],
            "chapter": row["章节"], "existing_dev_formal": existing_dev,
            "existing_dev_long_total": existing_dev_long,
            "existing_dev_unqualified": dev_unq,
            "existing_public_elsewhere": hist,
            "existing_dev_public_formal_duplicate": dev_formal,
            "new_pass": new_pass, "new_review": new_review, "target": 2,
            "qualified_available": qualified,
            "qualified_gap": max(0, 2 - qualified),
            "content_available": content,
            "content_gap": max(0, 2 - content),
            "qualified_status": "covered" if qualified >= 2 else "partial" if qualified else "none",
            "content_status": "covered" if content >= 2 else "partial" if content else "none",
        })
    with (OUT / "node_coverage.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(coverage[0]))
        writer.writeheader()
        writer.writerows(coverage)

    counts = {
        "new_pass": len(pass_items),
        "new_review": sum(1 for item in review if item.get("source") == "ai_generated_original"),
        "existing_dev_unqualified_review": len(added_review),
        "existing_public": len(existing_public),
        "existing_dev_formal": len(added_public),
        "historical_public": sum(1 for item in existing_public
                                 if item["source"] == "historical_public_qualified"),
        "reject": len(reject),
        "manifest": len(manifest),
        "qualified_gap": sum(row["qualified_gap"] for row in coverage),
        "content_gap": sum(row["content_gap"] for row in coverage),
        "qualified_covered_nodes": sum(row["qualified_status"] == "covered" for row in coverage),
        "content_covered_nodes": sum(row["content_status"] == "covered" for row in coverage),
        "content_partial_nodes": sum(row["content_status"] == "partial" for row in coverage),
        "content_none_nodes": sum(row["content_status"] == "none" for row in coverage),
    }
    quality = f"""# 全量交接包质量报告

生成时间：{datetime.now().isoformat(timespec='seconds')}

## 资产数量

| 类别 | 数量 |
|---|---:|
| 新题 PASS | {counts['new_pass']} |
| 新题 REVIEW | {counts['new_review']} |
| 开发库未正式长题（REVIEW，已在目标库） | {counts['existing_dev_unqualified_review']} |
| 现有 public 正式题（历史 33 + 开发库 10） | {counts['existing_public']} |
| REJECT | {counts['reject']} |
| 统一 manifest 条目 | {counts['manifest']} |
| 合格题缺口（按正式资格计） | {counts['qualified_gap']} |
| 内容缺口（含 REVIEW/未正式长题） | {counts['content_gap']} |

## 覆盖

- 合格覆盖满 2 题的节点：{counts['qualified_covered_nodes']}
- 内容覆盖满 2 题的节点：{counts['content_covered_nodes']}
- 内容部分覆盖节点：{counts['content_partial_nodes']}
- 内容完全空白节点：{counts['content_none_nodes']}

## 资格说明

- 新题 39 PASS 仍是 personal AI 练习；不等于公共正式题。
- 33 道历史 public 长题在 `closeout_intake_test` 已有 auto-review 事件，但不在目标库；需重新核验/资格。
- 10 道开发库 public 正式长题已在目标库，Codex 不应重复导入。
- 79 道开发库未正式长题已在目标库，作为 REVIEW 候选，Codex 应原地复核/资格，不要重复创建。
- 证明/主观/多问计算题缺少 bounded grader，不能写 auto_verified。

## 风险

- 79 道开发库长题的解析/答案来自既有题库，未在本轮逐题重算；只能作为 REVIEW 候选，不能计为 PASS。
- 历史 33 题 spec 元数据不完整，导入前以 closeout 库原始 Question 为准。
"""
    (OUT / "quality_report.md").write_text(quality, encoding="utf-8")

    instructions = f"""# Codex 全量入库交接说明

## 文件

- `questions_pass.json`：{counts['new_pass']} 道新 PASS（personal，导入）。
- `questions_review.json`：{counts['new_review']} 道新 REVIEW + {counts['existing_dev_unqualified_review']} 道开发库未正式长题（已在目标库，原地复核，不要重复导入）。
- `questions_reject.json`：{counts['reject']} 道。
- `questions_existing_public.json`：{counts['historical_public']} 道历史 public（closeout 库，需重新核验）+ {counts['existing_dev_formal']} 道开发库 public 正式长题（已在目标库，不要重复导入）。
- `question_manifest.json`：{counts['manifest']} 条，含稳定 ID/节点 code/来源/资格状态。
- `node_coverage.csv`：213 节点，含合格缺口与内容缺口。

## 导入顺序

1. 校验 `handoff_manifest.json` 哈希与 ID 唯一性。
2. 确认目标库身份、备份、迁移版本；拒绝 `kaoyan`（除非用户明确授权）。
3. 导入 39 道新 PASS：`run_long_question_import.ps1 -Execute`（默认 PASS-only）。
4. 10 道开发库正式长题：已在目标库，核对 ID/内容哈希，不重复创建。
5. 79 道开发库未正式长题：按 `questions_review.json` 中的 `stable_id` 查目标库，原地复核；不要导入副本。
6. 33 道历史 public：从 closeout_intake_test 导出原始 Question/Version，在目标库按 `qualify_public_question` 重新核验；不要复制审核事件。
7. 每步后查节点题数、版本、资格；第二遍幂等。

## 禁止

- 不得把 REVIEW 标 PASS；
- 不得写 `auto_verified` 伪造正式资格；
- 不得重复创建已在目标库的 10/79 题；
- 不得写 `kaoyan`。
"""
    (OUT / "codex_import_instructions.md").write_text(instructions, encoding="utf-8")

    # 机器可读审核记录 + 章节进度
    audit_rows = []
    for group, items in [("pass", pass_items), ("review", review), ("existing_public", existing_public)]:
        for item in items:
            audit_rows.append({
                "group": group, "stable_id": item.get("stable_id"),
                "kp_code": item.get("kp_code"), "source": item.get("source"),
                "question_type": item.get("question_type"),
                "content_review": item.get("content_review", "PASS" if group == "pass" else "REVIEW"),
                "personal_practice_eligible": item.get("personal_practice_eligible"),
                "public_formal_status": item.get("public_formal_status"),
                "reason": item.get("public_formal_reason") or item.get("review_reason"),
            })
    with (OUT / "audit_records.jsonl").open("w", encoding="utf-8") as handle:
        for row in audit_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    from collections import defaultdict
    chapter = defaultdict(lambda: defaultdict(int))
    for row in coverage:
        bucket = chapter[(row["subject"], row["chapter"])]
        bucket["nodes"] += 1
        for key in ("qualified_covered", "qualified_partial", "qualified_none",
                    "content_covered", "content_partial", "content_none"):
            bucket[key] += row[key.replace("qualified_", "qualified_").replace("content_", "content_")] if False else 0
        bucket["qualified_covered"] += row["qualified_status"] == "covered"
        bucket["qualified_partial"] += row["qualified_status"] == "partial"
        bucket["qualified_none"] += row["qualified_status"] == "none"
        bucket["content_covered"] += row["content_status"] == "covered"
        bucket["content_partial"] += row["content_status"] == "partial"
        bucket["content_none"] += row["content_status"] == "none"
        bucket["qualified_gap"] += int(row["qualified_gap"])
        bucket["content_gap"] += int(row["content_gap"])
    chapter_fields = ["subject", "chapter", "nodes", "qualified_covered", "qualified_partial",
                      "qualified_none", "content_covered", "content_partial", "content_none",
                      "qualified_gap", "content_gap"]
    with (OUT / "chapter_progress.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=chapter_fields)
        writer.writeheader()
        for (subject, chapter_name), bucket in sorted(chapter.items()):
            writer.writerow({"subject": subject, "chapter": chapter_name,
                             **{key: bucket.get(key, 0) for key in chapter_fields[2:]}})

    # 重新生成哈希清单
    files = sorted(path for path in OUT.rglob("*") if path.is_file() and path.name != "handoff_manifest.json")
    handoff = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "directory": str(OUT.relative_to(ROOT)),
        "counts": counts,
        "files": {str(path.relative_to(OUT)): sha256(path) for path in files},
    }
    (OUT / "handoff_manifest.json").write_text(
        json.dumps(handoff, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(counts, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
