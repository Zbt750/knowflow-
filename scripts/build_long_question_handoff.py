#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 Codex 入库交接包：50 道新题 + 33 道历史 public auto-verified 长题。

输出目录：handoff/long-question-final-20261018/
不连接数据库，不改题目内容。
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "handoff" / "long-question-final-20261018"
PACKS = [
    ("pilot", "pilot_20261018.json", "docs/long-question-triage-pilot-20261018.json"),
    ("os01", "os_batch01_20261018.json", "docs/long-question-triage-os01-20261018.json"),
    ("ds01", "ds_batch01_20261018.json", "docs/long-question-triage-ds01-20261018.json"),
    ("co01", "co_batch01_20261018.json", "docs/long-question-triage-co01-20261018.json"),
    ("cn01", "cn_batch01_20261018.json", "docs/long-question-triage-cn01-20261018.json"),
    ("math02", "math_batch02_20261018.json", "docs/long-question-triage-math02-20261018.json"),
    ("cs40802", "cs408_batch02_20261018.json", "docs/long-question-triage-cs40802-20261018.json"),
    ("math03", "math_batch03_20261018.json", "docs/long-question-triage-math03-20261018.json"),
    ("cs40803", "cs408_batch03_20261018.json", "docs/long-question-triage-cs40803-20261018.json"),
    ("math04", "math_batch04_20261018.json", "docs/long-question-triage-math04-20261018.json"),
    ("math05", "math_batch05_20261018.json", "docs/long-question-triage-math05-20261018.json"),
    ("cs40804", "cs408_batch04_20261018.json", "docs/long-question-triage-cs40804-20261018.json"),
    ("api", "api_generated_20261018.json", "docs/long-question-triage-api-20261018.json"),
]
HISTORY = ROOT / "storage/quality-audits/project-repair-20261018/large-questions"
HISTORY_SPECS = HISTORY / "reviewed-original-long-specs.json"
HISTORY_RESULTS = HISTORY / "intake-results.json"
HISTORY_OWNER = HISTORY / "owner.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def trigrams(text: str) -> set[str]:
    t = re.sub(r"\s+", "", text or "")
    return {t[i:i + 3] for i in range(max(0, len(t) - 2))}


def similarity(a: str, b: str) -> float:
    ta, tb = trigrams(a), trigrams(b)
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def load_inventory():
    rows = {}
    with (ROOT / "docs/long-question-inventory-20261018.csv").open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            rows[row["知识点ID（稳定code）"]] = row
    return rows


def infer_type(spec: dict, kp_code: str) -> str:
    answer = str(spec.get("answer", ""))
    if kp_code.startswith("cs408.ds."):
        return "subjective"
    if kp_code.startswith("cs408.") and not re.search(r"\d", answer):
        return "subjective"
    return "calculation"


def build_new_items(inventory):
    items, manifest = [], []
    for tag, filename, triage_path in PACKS:
        pack_path = ROOT / "content/long_question_packs" / filename
        if not pack_path.exists():
            continue
        pack = json.loads(pack_path.read_text(encoding="utf-8"))
        if not pack.get("items"):
            continue
        if not (ROOT / triage_path).exists():
            continue
        triage = json.loads((ROOT / triage_path).read_text(encoding="utf-8"))
        verdicts = {row["slug"]: row for row in triage.get("results", [])}
        for item in pack["items"]:
            verdict = verdicts.get(item["slug"], {}).get("verdict", "UNKNOWN")
            key = f"long-question-bank:{pack['batch_key']}:{item['slug']}"
            stable_id = str(uuid5(NAMESPACE_URL, key))
            enriched = dict(item)
            enriched.update({
                "stable_id": stable_id,
                "import_key": key,
                "pack": tag,
                "batch_key": pack["batch_key"],
                "pack_file": str(pack_path.relative_to(ROOT)),
                "content_review": verdict,
                "personal_practice_eligible": True,
                "public_formal_status": "not_qualified_no_auto_review_event",
                "public_formal_reason": (
                    "尚未在目标库生成 QuestionAutoReviewEvent；证明/主观/多问计算题缺少 bounded grader"
                    if item["question_type"] in {"proof", "subjective"}
                    else "尚未运行公共自动审核；当前按个人 AI 练习入库"
                ),
                "source": "ai_generated_original",
                "identity_label": item.get("identity_label", "原创题"),
            })
            items.append(enriched)
            manifest.append({
                "stable_id": stable_id, "kind": "new_content", "pack": tag,
                "batch_key": pack["batch_key"], "slug": item["slug"],
                "kp_code": item["kp_code"], "title": item["title"],
                "question_type": item["question_type"], "difficulty": item["difficulty"],
                "content_review": verdict,
                "personal_practice_eligible": True,
                "public_formal_status": enriched["public_formal_status"],
                "source": "ai_generated_original",
                "file": str(pack_path.relative_to(ROOT)),
                "pack_sha256": sha256(pack_path),
            })
    return items, manifest


def build_history_items():
    specs = {row["key"]: row for row in json.loads(HISTORY_SPECS.read_text(encoding="utf-8"))}
    results = json.loads(HISTORY_RESULTS.read_text(encoding="utf-8"))["results"]
    owner = json.loads(HISTORY_OWNER.read_text(encoding="utf-8"))
    selected = [row for row in results if row.get("status") in {"noop", "inserted"} and row.get("node_code")]
    items, manifest = [], []
    per_node = Counter()
    for row in selected:
        spec = specs.get(row["key"])
        if not spec:
            continue
        kp_code = row["node_code"]
        per_node[kp_code] += 1
        role = "basic" if per_node[kp_code] == 1 else "comprehensive"
        item = {
            "stable_id": row["question_id"],
            "existing_version_id": row.get("version_id"),
            "import_key": f"historical-public:{row['key']}",
            "kp_code": kp_code,
            "title": spec.get("topic") or row["key"],
            "question_type": infer_type(spec, kp_code),
            "difficulty": "advanced",
            "estimated_minutes": int(spec.get("estimated_minutes") or 15),
            "role": role,
            "skill_tags": [spec.get("topic") or row["key"]],
            "objective": spec.get("topic") or row["key"],
            "stem": spec.get("stem", ""),
            "answer": spec.get("answer", ""),
            "explanation": spec.get("explanation", ""),
            "verification": spec.get("verification", []),
            "checks": spec.get("checks", []),
            "source": "historical_public_qualified",
            "identity_label": "原创题",
            "history_status": row.get("status"),
            "history_database": owner.get("database"),
            "history_port": owner.get("port"),
            "history_system_identifier": owner.get("system_identifier"),
            "public_formal_status": "public_auto_verified_in_closeout_intake_test",
            "public_formal_reason": (
                "已在 closeout_intake_test 生成 QuestionAutoReviewEvent；"
                "在目标库需按现有 qualify_public_question 流程重新核验/导入"
            ),
            "requires_requalification_on_target": True,
            "metadata_completeness": "historical_spec",
        }
        items.append(item)
        manifest.append({
            "stable_id": row["question_id"], "kind": "historical_public",
            "pack": "history-closeout-20261018", "batch_key": "history-public-33",
            "slug": row["key"], "kp_code": kp_code, "title": item["title"],
            "question_type": item["question_type"], "difficulty": item["difficulty"],
            "content_review": "PASS",
            "personal_practice_eligible": False,
            "public_formal_status": item["public_formal_status"],
            "source": "historical_public_qualified",
            "file": str(HISTORY_SPECS.relative_to(ROOT)),
            "pack_sha256": sha256(HISTORY_SPECS),
        })
    return items, manifest


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    inventory = load_inventory()
    new_items, new_manifest = build_new_items(inventory)
    hist_items, hist_manifest = build_history_items()

    pass_items = [item for item in new_items if item["content_review"] == "PASS"]
    review_items = [item for item in new_items if item["content_review"] == "REVIEW"]
    reject_items = [item for item in new_items if item["content_review"] == "REJECT"]

    # 跨批次近似重复提示（不删除，只标记）
    duplicates = []
    all_content = [(i["stable_id"], i.get("stem", "")) for i in pass_items + review_items + hist_items]
    for index, (sid, stem) in enumerate(all_content):
        for other_id, other_stem in all_content[index + 1:]:
            sim = similarity(stem, other_stem)
            if sim >= 0.80:
                duplicates.append({"a": sid, "b": other_id, "similarity": round(sim, 4)})

    for path, payload in [
        ("questions_pass.json", pass_items),
        ("questions_review.json", review_items),
        ("questions_reject.json", reject_items),
        ("questions_existing_public.json", hist_items),
    ]:
        (OUT / path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest = new_manifest + hist_manifest
    for entry in manifest:
        entry["duplicate_warnings"] = [
            d for d in duplicates if entry["stable_id"] in {d["a"], d["b"]}
        ]
    (OUT / "question_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    # 节点覆盖
    new_pass_by_kp = Counter(i["kp_code"] for i in pass_items)
    new_review_by_kp = Counter(i["kp_code"] for i in review_items)
    hist_by_kp = Counter(i["kp_code"] for i in hist_items)
    coverage = []
    for code, row in inventory.items():
        if row["适合大题"] != "是":
            continue
        existing_dev = int(row["现有有效大题数(采用)"])
        existing_dev_long_total = int(row["在线大题数(审计)"] or 0)
        existing_hist = hist_by_kp.get(code, 0)
        new_pass = new_pass_by_kp.get(code, 0)
        new_review = new_review_by_kp.get(code, 0)
        target = 2
        available = existing_dev + existing_hist + new_pass
        gap = max(0, target - available)
        coverage.append({
            "kp_code": code, "kp_name": row["知识点名称"], "subject": row["学科"],
            "chapter": row["章节"], "existing_dev_formal": existing_dev,
            "existing_dev_long_total": existing_dev_long_total,
            "existing_public_elsewhere": existing_hist, "new_pass": new_pass,
            "new_review": new_review, "target": target,
            "gap_after_available": gap,
            "status": "covered" if gap == 0 else "partial" if available or new_review else "untouched",
        })
    with (OUT / "node_coverage.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(coverage[0]))
        writer.writeheader()
        writer.writerows(coverage)

    counts = {
        "new_items": len(new_items), "pass": len(pass_items), "review": len(review_items),
        "reject": len(reject_items), "historical_public": len(hist_items),
        "covered_nodes_new": len(set(new_pass_by_kp) | set(new_review_by_kp)),
        "covered_nodes_history": len(hist_by_kp),
        "total_available": len(pass_items) + len(hist_items) + sum(
            int(r["现有有效大题数(采用)"]) for r in inventory.values() if r["适合大题"] == "是"),
        "target": 426,
        "remaining_gap": sum(r["gap_after_available"] for r in coverage),
        "duplicates": len(duplicates),
    }

    quality = f"""# 大题库统一审核与交接质量报告

生成时间：{datetime.now().isoformat(timespec="seconds")}

## 数量

| 口径 | 数量 |
|---|---:|
| 新生成题 | {counts['new_items']} |
| 新题内容 PASS | {counts['pass']} |
| 新题 REVIEW | {counts['review']} |
| 新题 REJECT | {counts['reject']} |
| 历史 public auto-verified 长题 | {counts['historical_public']} |
| 目标知识节点 | 213 |
| 目标题量 | 426 |
| 覆盖缺口（按可用题计） | {counts['remaining_gap']} |
| 现有开发库大题总量（含未正式） | {sum(r['existing_dev_long_total'] for r in coverage)} |
| 跨题近似重复（≥0.80） | {counts['duplicates']} |

## 资格区分

- 39 道新题内容 PASS，但全部按 **personal AI 练习** 入库：`bank_scope=personal`，`personal_practice_only`，不自动获得公共正式题资格。
- 33 道历史长题在 `closeout_intake_test` 中已有 `QuestionAutoReviewEvent`（public auto-verified），但不在目标库；需在目标库按现有 `qualify_public_question` 流程重新核验/导入，不能直接假定资格迁移。
- 证明/主观/多问计算题缺少 bounded grader，不能仅凭内容 PASS 写成 `auto_verified`。

## REVIEW

11 道 REVIEW 未发现明确错误，保留待复核；不冒充 PASS。见 `questions_review.json`。

## 风险

- 历史 33 题的 spec 缺少 `key_points/common_errors` 等字段，元数据完整度低于新题；导入前应以 closeout 库中的原始 Question 为准。
- 任何重复 ID 必须按内容哈希核对，不得覆盖。
"""
    (OUT / "quality_report.md").write_text(quality, encoding="utf-8")

    instructions = f"""# Codex 入库交接说明

## 0. 目标

把本目录的题目导入 Windows 宿主机 `D:\\考研跑通项目` 的**已确认目标库**，并完成版本、节点题库、今日学习、作答事件和幂等验证。严禁写入 `kaoyan` 正式开发库，除非用户明确授权并完成备份、权限、迁移检查。

## 1. 交接文件

- `questions_pass.json`：{len(pass_items)} 道新题，内容 PASS，按 personal AI 练习导入。
- `questions_review.json`：{len(review_items)} 道 REVIEW，默认不导入或仅作参考；不得标 PASS。
- `questions_reject.json`：{len(reject_items)} 道（当前为空）。
- `questions_existing_public.json`：{len(hist_items)} 道历史 public auto-verified 长题（来自 closeout_intake_test，需在目标库重新核验/导入）。
- `question_manifest.json`：稳定 ID、节点 code、审核/资格状态、来源、哈希。
- `node_coverage.csv`：213 个适合节点的现有题数、历史可用题、新 PASS/REVIEW、缺口。
- `handoff_manifest.json`：本目录所有文件 SHA-256。

## 2. 先校验

1. 校验 `handoff_manifest.json` 中每个文件的 SHA-256。
2. 校验 `questions_pass.json` 数量为 {len(pass_items)}、稳定 ID 唯一、每个 `kp_code` 在知识树中存在且为可考核叶子。
3. 校验 `questions_existing_public.json` 的 `stable_id/version_id` 与 `closeout_intake_test` 原始记录一致。

## 3. 数据库身份

- 读取项目真实配置，打印 host/port/database；确认目标为隔离库（例如 `kaoyan_test`）。
- 禁止仅凭 `APP_ENV=test` 认定安全；必须核对实例身份、数据库名、迁移版本、备份状态。
- 不得写入 `kaoyan`；不得清库。

## 4. 导入新题（39 PASS）

```powershell
$env:APP_ENV="test"
$env:TEST_DATABASE_URL="postgresql+psycopg://.../kaoyan_test"
python scripts/import_long_question_bank.py --pack content/long_question_packs/pilot_20261018.json --verdicts docs/long-question-triage-pilot-20261018.json --dry-run
# 通过后去掉 --dry-run，加 --confirm-database kaoyan_test
```

或直接：

```powershell
.\\scripts\\run_long_question_import.ps1 -DatabaseUrl "..." -Execute
```

默认只导 39 PASS，不加 `-IncludeReview`。

## 5. 历史 33 道 public 长题

- 不要直接把 `QuestionAutoReviewEvent` 行复制到目标库；事件绑定 question/version/hash/实例。
- 优先从 `closeout_intake_test`（端口 {json.loads(HISTORY_OWNER.read_text(encoding='utf-8')).get('port')}，system_identifier {json.loads(HISTORY_OWNER.read_text(encoding='utf-8')).get('system_identifier')}）导出原始 Question/QuestionVersion，核对内容哈希。
- 在目标库重新插入内容后，按现有 `qualify_public_question()` 流程重新生成审核事件；只有 grading 阶段 PASS 才能成为 public 正式题。
- 过程题/证明题若没有 bounded grader，保留为 personal 或待审核，不得伪造 `auto_verified`。

## 6. 导入后验证

- 每节点题数、QuestionVersion 版本快照哈希、bp 归属、来源字段。
- 节点题库接口可见；加入今日学习；PracticeItem 绑定 QuestionVersion；Attempt/LearningEvent 记录。
- 毕业证据隔离：personal 题不得产生正式毕业证据。
- 第二遍导入验证幂等：题数/版本数不增加；同 ID 内容哈希一致/冲突分别报告。
"""
    (OUT / "codex_import_instructions.md").write_text(instructions, encoding="utf-8")

    # 复制源包，保证交接包自包含
    source_dir = OUT / "source_packs"
    source_dir.mkdir(exist_ok=True)
    for _, filename, _ in PACKS:
        shutil.copy2(ROOT / "content/long_question_packs" / filename, source_dir / filename)
    shutil.copy2(HISTORY_SPECS, source_dir / HISTORY_SPECS.name)
    shutil.copy2(HISTORY_RESULTS, source_dir / HISTORY_RESULTS.name)
    shutil.copy2(HISTORY_OWNER, source_dir / HISTORY_OWNER.name)

    files = sorted(path for path in OUT.rglob("*") if path.is_file() and path.name != "handoff_manifest.json")
    handoff = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "directory": str(OUT.relative_to(ROOT)),
        "counts": counts,
        "files": {str(path.relative_to(OUT)): sha256(path) for path in files},
        "duplicates": duplicates,
    }
    (OUT / "handoff_manifest.json").write_text(
        json.dumps(handoff, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(counts, ensure_ascii=False, indent=2))
    print("handoff ->", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
