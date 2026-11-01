#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DeepSeek 全量大题生成 worker（Windows 宿主机运行）。

- 读取 handoff/long-question-full-20261018/node_coverage.csv 的逐节点缺口。
- 调用项目现有 backend.chat.service.Provider（复用 .env 的 DeepSeek 配置）。
- 每批生成后写候选包 → validate → triage → 合并到正式 API 包 → 重建交接包。
- 断点续跑：api_progress.json 记录每个节点的完成/失败；不重复生成。
- 预算：--max-calls / --max-cost-cny；达到上限安全退出。
- 不在本文件连接任何数据库。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
HANDOFF = ROOT / "handoff/long-question-full-20261018"
COVERAGE = HANDOFF / "node_coverage.csv"
API_PACK = ROOT / "content/long_question_packs/api_generated_20261018.json"
API_TRIAGE = ROOT / "docs/long-question-triage-api-20261018.json"
API_VALIDATION = ROOT / "docs/long-question-validation-api-20261018.json"
PROGRESS = HANDOFF / "api_progress.json"
CANDIDATE = ROOT / "content/long_question_packs/_api_candidate.json"
BATCH_KEY = "longbank-api-20261018"
LONG_TYPES = {"calculation", "proof", "subjective"}


def env_file() -> dict[str, str]:
    values = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


def load_progress() -> dict:
    if PROGRESS.exists():
        return json.loads(PROGRESS.read_text(encoding="utf-8"))
    return {"batch_key": BATCH_KEY, "nodes": {}, "calls": 0,
            "prompt_tokens": 0, "completion_tokens": 0, "cost_cny": 0.0}


def save_progress(progress: dict):
    progress["updated_at"] = datetime.now().isoformat(timespec="seconds")
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")


def load_api_pack() -> dict:
    if API_PACK.exists():
        return json.loads(API_PACK.read_text(encoding="utf-8"))
    return {"pack_version": "long-question-pack-v1", "batch_key": BATCH_KEY,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "authoring": {"mode": "deepseek_api", "model_calls": 0, "real_model_called": True,
                          "note": "DeepSeek API generated; verified by worker"},
            "items": []}


def coverage_rows(start_code: str | None = None) -> list[dict]:
    import csv
    rows = []
    with COVERAGE.open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if row.get("qualified_gap") and int(row["qualified_gap"]) > 0:
                rows.append(row)
    rows.sort(key=lambda row: (row["kp_code"] != (start_code or ""),
                               row["content_status"] != "none",
                               row["subject"], row["chapter"], row["kp_code"]))
    return rows


def existing_stems() -> list[str]:
    stems = []
    for path in (ROOT / "content/long_question_packs").glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        stems.extend(item.get("stem", "") for item in data.get("items", []) if isinstance(item, dict))
    return stems


def trigrams(text: str) -> set[str]:
    text = re.sub(r"\s+", "", text or "")
    return {text[i:i + 3] for i in range(max(0, len(text) - 2))}


def similarity(a: str, b: str) -> float:
    ta, tb = trigrams(a), trigrams(b)
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def slug_for(kp_code: str, index: int) -> str:
    return "api-" + re.sub(r"[^a-zA-Z0-9]+", "-", kp_code).strip("-") + f"-q{index}"


def build_prompt(node: dict, count: int) -> list[dict]:
    schema = """{
  "questions": [
    {
      "title": "简短主题",
      "question_type": "calculation|proof|subjective",
      "difficulty": "medium|advanced",
      "estimated_minutes": 12,
      "role": "basic|comprehensive",
      "skill_tags": ["标签1","标签2"],
      "objective": "考查目标",
      "stem": "完整题干，包含所有条件和小问",
      "answer": "完整参考答案",
      "final_value": "最终答案（数值/表达式；证明题写结论）",
      "solution_steps": ["步骤1","步骤2","步骤3"],
      "key_points": ["关键定理/公式"],
      "common_errors": ["常见错误"],
      "scope": "适用范围与前提",
      "verification_steps": [{"expression": "可计算的算术表达式", "value": "预期值"}],
      "verification": {"method": "sympy/模拟器/推导", "result": "PASS|REVIEW", "detail": "复核说明"},
      "reference_program": "可选：408 算法的 Python 参考实现（字符串）",
      "reference_output": "可选：参考程序输出"
    }
  ]
}"""
    return [
        {"role": "system", "content": "你是严谨的考研数学二/408 命题人。只输出合法 JSON，不要 Markdown 代码围栏，不要解释。"},
        {"role": "user", "content": (
            f"知识节点：{node['kp_name']}（code={node['kp_code']}，学科={node['subject']}，章节={node['chapter']}）。\n"
            f"请生成 {count} 道中等或偏难的大题，两道题必须考查角度不同，不能只换数字。\n"
            "数学二不得超纲；408 限数据结构/组成原理/操作系统/计算机网络。\n"
            "每题必须条件完整、答案可复核、分步解析完整；不得伪造真题来源；不得使用“如图/如下表/待补”。\n"
            "计算题至少给 2 个可机器计算的 verification_steps；证明/主观题可为空并标 REVIEW。\n"
            f"严格按以下 JSON 结构输出：\n{schema}"
        )},
    ]


def call_provider(messages: list[dict]) -> tuple[str, dict]:
    from backend.chat.service import Provider
    from backend.config import get_settings
    settings = get_settings()
    if not (settings.llm_api_key and settings.llm_base_url and settings.llm_model):
        raise RuntimeError("模型配置不完整")
    provider = Provider(api_key=settings.llm_api_key.get_secret_value(),
                        base_url=settings.llm_base_url, model=settings.llm_model,
                        timeout=settings.llm_timeout_seconds,
                        max_tokens=max(settings.llm_max_output_tokens, 8000))
    text, usage = provider.complete(messages)
    return text, usage or {}


def parse_json(text: str) -> dict:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("no_json_object")
    return json.loads(cleaned[start:end + 1])


def validate_item(item: dict, node: dict, seen: list[str]) -> list[str]:
    errors = []
    for key in ("stem", "answer", "final_value", "solution_steps", "key_points",
                "common_errors", "scope", "objective", "title"):
        if not item.get(key):
            errors.append(f"missing:{key}")
    if item.get("question_type") not in LONG_TYPES:
        errors.append("question_type_invalid")
    if item.get("difficulty") not in {"medium", "advanced"}:
        errors.append("difficulty_too_low")
    if len(item.get("stem", "")) < 30:
        errors.append("stem_too_short")
    if len(item.get("solution_steps") or []) < 3:
        errors.append("solution_steps_too_few")
    if re.search(r"如图|见图|下图|图中|如下表|表\s*\d|待补|待核对|占位|TODO", item.get("stem", "")):
        errors.append("placeholder_or_figure_cue")
    for other in seen:
        if similarity(item.get("stem", ""), other) >= 0.85:
            errors.append("near_duplicate")
            break
    from scripts.validate_long_question_pack import compare_constant
    for step in item.get("verification_steps") or []:
        if not isinstance(step, dict) or set(step) != {"expression", "value"}:
            errors.append("verification_step_format")
        elif compare_constant(step["expression"], step["value"]) == "wrong":
            errors.append("verification_step_wrong")
    if item.get("question_type") == "calculation" and not item.get("verification_steps"):
        errors.append("calculation_requires_verification_steps")
    return errors


def normalize(item: dict, node: dict, index: int) -> dict:
    typ = item.get("question_type")
    steps = item.get("verification_steps") or []
    errors = validate_item(item, node, [])
    status = "PASS"
    reason = ""
    if typ in {"proof", "subjective"}:
        status = "REVIEW"
        reason = "证明/主观/算法设计题自动验证有限，保留人工复核"
    elif errors:
        status = "REVIEW"
        reason = ";".join(errors)
    result = {
        "slug": slug_for(node["kp_code"], index),
        "kp_code": node["kp_code"],
        "title": item.get("title", node["kp_name"])[:80],
        "question_type": typ,
        "difficulty": item.get("difficulty", "advanced"),
        "estimated_minutes": int(item.get("estimated_minutes") or 15),
        "role": item.get("role", "basic" if index == 1 else "comprehensive"),
        "skill_tags": item.get("skill_tags") or [node["kp_name"]],
        "objective": item.get("objective", node["kp_name"]),
        "stem": item.get("stem", ""),
        "answer": item.get("answer", ""),
        "final_value": item.get("final_value", ""),
        "solution_steps": item.get("solution_steps") or [],
        "key_points": item.get("key_points") or [],
        "common_errors": item.get("common_errors") or [],
        "scope": item.get("scope", ""),
        "verification_steps": steps,
        "verification": item.get("verification") or {"method": "model", "result": "REVIEW", "detail": reason},
        "review": {
            "content_valid": not errors,
            "knowledge_point_valid": True,
            "answer_checked": status == "PASS",
            "difficulty_checked": item.get("difficulty") in {"medium", "advanced"},
            "duplicate_checked": "near_duplicate" not in errors,
            "review_status": "AUTO_CHECKED_REFERENCE_ONLY" if status == "PASS" else "PENDING_HUMAN_REVIEW",
        },
        "source": "ai_generated_original",
        "identity_label": "原创题",
        "reference_program": item.get("reference_program", ""),
        "reference_output": item.get("reference_output", ""),
    }
    if reason:
        result["review_reason"] = reason
    return result


def run(cmd: list[str]) -> int:
    print("$", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=ROOT).returncode


def merge_candidate(items: list[dict]) -> bool:
    """候选包先校验；通过后合并到 API 正式包。"""
    pack = {"pack_version": "long-question-pack-v1", "batch_key": BATCH_KEY + "-candidate",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "authoring": {"mode": "deepseek_api", "model_calls": 0, "real_model_called": True,
                          "note": "candidate"}, "items": items}
    CANDIDATE.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    if run([sys.executable, "scripts/validate_long_question_pack.py", "--pack", str(CANDIDATE),
            "--out", "docs/long-question-validation-api-candidate.json",
            "--report", "docs/long-question-validation-api-candidate.md"]) != 0:
        return False
    api = load_api_pack()
    by_slug = {item["slug"]: item for item in api["items"]}
    for item in items:
        by_slug.setdefault(item["slug"], item)
    api["items"] = list(by_slug.values())
    api["authoring"]["model_calls"] = int(api["authoring"].get("model_calls", 0)) + len(items)
    api["authoring"]["note"] = "DeepSeek API generated; validate/triage per batch"
    API_PACK.write_text(json.dumps(api, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def rebuild_handoff() -> bool:
    if run([sys.executable, "scripts/validate_long_question_pack.py", "--pack", str(API_PACK),
            "--out", str(API_VALIDATION), "--report", "docs/long-question-validation-api-20261018.md"]) != 0:
        return False
    if run([sys.executable, "scripts/triage_long_question_pack.py", "--pack", str(API_PACK),
            "--validation", str(API_VALIDATION), "--out", str(API_TRIAGE),
            "--report", "docs/long-question-triage-api-20261018.md"]) != 0:
        return False
    if run([sys.executable, "scripts/build_long_question_handoff.py"]) != 0:
        return False
    if run([sys.executable, "scripts/augment_handoff_dev_assets.py"]) != 0:
        return False
    return True


def dry_run(start_code: str | None = None):
    rows = coverage_rows(start_code)
    print(json.dumps({"remaining_nodes": len(rows),
                      "remaining_gap": sum(int(r["qualified_gap"]) for r in rows),
                      "first": [{"code": r["kp_code"], "name": r["kp_name"],
                                 "gap": int(r["qualified_gap"])} for r in rows[:5]]},
                     ensure_ascii=False, indent=2))


def check_api():
    import urllib.error
    import urllib.request
    env = env_file()
    base = (env.get("LLM_BASE_URL") or "").rstrip("/")
    key = env.get("LLM_API_KEY") or ""
    model = env.get("LLM_MODEL") or ""
    if not (base and key and model):
        print("配置不完整：需要 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL")
        return 1
    req = urllib.request.Request(base + "/models", headers={"Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            body = response.read(500).decode("utf-8", "replace")
            print(json.dumps({"status": response.status, "base": base, "model": model,
                              "body_prefix": body[:200]}, ensure_ascii=False, indent=2))
            return 0
    except urllib.error.HTTPError as exc:
        print(json.dumps({"status": exc.code, "base": base, "model": model,
                          "error": exc.read(300).decode("utf-8", "replace")}, ensure_ascii=False))
        return 1
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "base": base, "model": model,
                          "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1


def self_test():
    global API_PACK, CANDIDATE
    node = {"kp_code": "math.exam.547ca6df680c", "kp_name": "极限计算", "subject": "考研数学",
            "chapter": "极限与连续"}
    item = normalize({
        "title": "测试极限", "question_type": "calculation", "difficulty": "medium",
        "estimated_minutes": 10, "role": "basic", "skill_tags": ["极限"],
        "objective": "检验极限计算与泰勒展开的掌握", "stem": "计算 lim_(x→0) (e^x-1-x)/x^2，并写出展开过程。",
        "answer": "1/2", "final_value": "1/2",
        "solution_steps": ["e^x=1+x+x²/2+o(x²)", "分子=x²/2+o(x²)", "相除得 1/2"],
        "key_points": ["泰勒展开"], "common_errors": ["漏项"],
        "scope": "x→0", "verification_steps": [{"expression": "1/2", "value": "1/2"}],
        "verification": {"method": "sympy", "result": "PASS", "detail": "limit=1/2"},
    }, node, 1)
    import tempfile
    original = API_PACK
    with tempfile.TemporaryDirectory() as tmp:
        API_PACK = Path(tmp) / "api.json"
        CANDIDATE = Path(tmp) / "candidate.json"
        try:
            ok = merge_candidate([item])
        finally:
            API_PACK = original
    if not ok:
        print("SELF-TEST FAIL: candidate validation failed")
        return 1
    print("SELF-TEST PASS")
    return 0


def execute(args) -> int:
    if args.max_calls <= 0 and args.max_cost_cny <= 0:
        print("拒绝执行：未提供 --max-calls 或 --max-cost-cny 预算。")
        return 2
    progress = load_progress()
    rows = coverage_rows(args.start_code)
    if not rows:
        print("没有剩余缺口。")
        return 0
    from scripts.validate_long_question_pack import load_snapshot_stems
    sealed = load_snapshot_stems(ROOT / "storage/quality-audits/long-question-supply-20261017/sealed-questions.copy.sql")
    seen = existing_stems() + sealed
    # 跨进程累计：重复启动不会重置已消耗的调用/费用。
    calls = int(progress.get("calls", 0) or 0)
    prompt_tokens = int(progress.get("prompt_tokens", 0) or 0)
    completion_tokens = int(progress.get("completion_tokens", 0) or 0)
    cost = float(progress.get("cost_cny", 0.0) or 0.0)
    usage_missing = int(progress.get("usage_missing_calls", 0) or 0)
    # deepseek-flash 官方高峰未缓存保守价；可通过 .env 覆盖。
    inp_price = float(os.getenv("DEEPSEEK_INPUT_PRICE_CNY_PER_M", "2") or 2)
    out_price = float(os.getenv("DEEPSEEK_OUTPUT_PRICE_CNY_PER_M", "8") or 8)
    if args.max_cost_cny > 0 and cost >= args.max_cost_cny:
        print(f"累计费用 {cost:.4f} 已达上限 {args.max_cost_cny}，不再调用。")
        save_progress(progress)
        return 3
    for row in rows:
        code = row["kp_code"]
        if progress["nodes"].get(code, {}).get("status") == "done":
            continue
        gap = int(row["qualified_gap"])
        count = min(2, gap)
        messages = build_prompt(row, count)
        items, errors = [], []
        for attempt in range(1, args.max_retries + 1):
            if calls >= args.max_calls and args.max_calls > 0:
                save_progress(progress); print("达到 max-calls，安全退出。"); return 3
            try:
                text, usage = call_provider(messages)
            except Exception as exc:
                errors.append(f"provider:{type(exc).__name__}:{exc}")
                time.sleep(min(2 ** attempt, 15))
                continue
            calls += 1
            call_prompt = int(usage.get("prompt_tokens") or 0)
            call_completion = int(usage.get("completion_tokens") or 0)
            if call_prompt == 0 and call_completion == 0:
                # 上游未返回 usage 时按最大输出保守计入，避免预算失控。
                usage_missing += 1
                call_prompt = max(1, len(json.dumps(messages, ensure_ascii=False)) // 4)
                call_completion = 8000
            prompt_tokens += call_prompt
            completion_tokens += call_completion
            cost += call_prompt / 1e6 * inp_price + call_completion / 1e6 * out_price
            try:
                payload = parse_json(text)
                raw_items = payload.get("questions") or []
            except Exception as exc:
                errors.append(f"parse:{exc}")
                messages = messages + [{"role": "user", "content": "上一条不是合法 JSON，请只输出 JSON 对象。"}]
                continue
            if len(raw_items) < count:
                errors.append("too_few_questions")
                continue
            candidate_items = []
            for index, raw in enumerate(raw_items[:count], 1):
                item = normalize(raw, row, index)
                item_errors = validate_item(item, row, seen)
                if item_errors:
                    errors.extend(f"{index}:{e}" for e in item_errors)
                    continue
                candidate_items.append(item)
            if len(candidate_items) == count:
                items = candidate_items
                seen.extend(item["stem"] for item in items)
                break
        if len(items) != count:
            progress["nodes"][code] = {"status": "failed", "errors": errors[-10:], "attempts": args.max_retries}
            save_progress(progress)
            continue
        if not merge_candidate(items):
            progress["nodes"][code] = {"status": "failed", "errors": ["candidate_validation_failed"]}
            save_progress(progress)
            continue
        progress["nodes"][code] = {"status": "done", "slugs": [i["slug"] for i in items]}
        progress["calls"] = calls
        progress["prompt_tokens"] = prompt_tokens
        progress["completion_tokens"] = completion_tokens
        progress["cost_cny"] = round(cost, 4)
        progress["usage_missing_calls"] = usage_missing
        save_progress(progress)
        if len([n for n in progress["nodes"].values() if n["status"] == "done"]) % args.batch_nodes == 0:
            if not rebuild_handoff():
                print("交接包重建失败；进度已保存。")
                return 4
        if args.max_cost_cny > 0 and cost >= args.max_cost_cny:
            save_progress(progress); print("达到 max-cost-cny，安全退出。"); return 3
    if not rebuild_handoff():
        return 4
    print(json.dumps({"done_nodes": sum(1 for n in progress["nodes"].values() if n["status"] == "done"),
                      "failed_nodes": sum(1 for n in progress["nodes"].values() if n["status"] == "failed"),
                      "calls": calls, "prompt_tokens": prompt_tokens,
                      "completion_tokens": completion_tokens, "cost_cny": round(cost, 4),
                      "usage_missing_calls": usage_missing},
                     ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check-api", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--max-calls", type=int, default=0)
    parser.add_argument("--max-cost-cny", type=float, default=0.0)
    parser.add_argument("--batch-nodes", type=int, default=10)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--start-code", default="cs408.cn.topic.1351211c91cf")
    args = parser.parse_args()
    if args.check_api:
        return check_api()
    if args.dry_run:
        dry_run(args.start_code); return 0
    if args.self_test:
        return self_test()
    if args.execute:
        return execute(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
