"""同一隔离题库上的离线对照；默认协议 Agent，不调用付费模型、不写今日卷。"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_learning_agent_eval import CASES, EXTENDED_CASES, ProtocolProvider, isolated_factory, run_suite, snapshot

COMPARISON_CASES = [c for c in CASES + EXTENDED_CASES if c["id"] in {
    "basic", "short_fill", "reference_only", "multi_modify", "excluded_scope", "insufficient_count"}]


def rule_plan(factory, case, *, goal, budget, original_goal):
    """复用线上缺口选题器；显式范围、题型、任意分钟是离线共享约束适配。

    case.query 是人工给定的定位关键词，不把该适配器包装成会理解自然语言的产品。
    """
    from sqlalchemy import select
    from backend.models.learning import Question, KpState, KpMasteryPolicy
    from backend.services.learning_task_tools import TaskTools
    from backend.services.practice_service import _candidates_for, _empty_snapshot
    from backend.mastery.storage import policy_from_storage, snapshot_from_storage
    from backend.mastery.selection import select_questions
    now = datetime.now(timezone.utc)
    started = time.monotonic()
    before = snapshot(factory)
    tools = TaskTools(factory, budget_minutes=budget, now=now, goal=original_goal + "\n" + goal)
    nodes = tools.execute("search_knowledge", {"query": case["query"]})["nodes"]
    node_ids = [n["kp_id"] for n in nodes if n["assessable"] and not n["reference_only"]][:8]
    chosen = []
    total = 0
    if node_ids:
        tools.execute("get_learning_state", {"kp_ids": node_ids})
        pool = tools.execute("find_questions", {"kp_ids": node_ids, "question_type": tools.required_type})["questions"]
        ids = [UUID(q["question_id"]) for q in pool if not q["in_today_plan"]
               and q["minutes"] <= budget and (not tools.basic_only or q["difficulty"] == "basic")]
        with factory() as db:
            for node in node_ids:
                kp_id = UUID(node)
                rows = db.scalars(select(Question).where(Question.id.in_(ids), Question.kp_id == kp_id).order_by(Question.id)).all()
                state = db.get(KpState, kp_id)
                current = snapshot_from_storage(state) if state else _empty_snapshot()
                selection = select_questions(policy_from_storage(db.get(KpMasteryPolicy, kp_id)), current.evidence_window,
                    _candidates_for(db, kp_id, rows), manual_credit_count=current.manual_credit_count,
                    manual_confirmed_at=current.manual_confirmed_at, budget="light", limit=12, reference_time=now)
                # 现有选择器只有45/90/120分钟三档；在共享适配层执行本次精确分钟上限。
                for item in selection.items:
                    if total + item.estimated_minutes > budget:
                        continue
                    if len(chosen) >= (tools.required_count or 12):
                        break
                    chosen.append(item.question_id)
                    total += item.estimated_minutes
    validation = tools.execute("validate_plan", {"question_ids": chosen, "rationale": "复用缺口选题器的离线约束对照。"})
    return {"status": "ready" if validation["valid"] else "needs_info",
        "draft": tools.draft, "validation": validation,
        "duration_ms": round((time.monotonic() - started) * 1000, 2),
        "model_calls": 0, "no_business_write": snapshot(factory) == before,
        "intent_resolution": "人工给定定位关键词；未测自然语言理解",
        "baseline_kind": "existing_selector_with_shared_constraint_adapter"}


def compare(factory, cases=COMPARISON_CASES):
    rows = []
    for case in cases:
        agent = run_suite(factory, ProtocolProvider, [case])[0]
        stages = []
        for stage in agent["stages"]:
            budget = stage["draft"]["budget_minutes"] if stage["draft"] else case["budget"]
            # 明确的修改预算来自测试场景，不能用旧预算替代失败阶段的预算。
            for change in case.get("modifications", []):
                if change["goal"] == stage["goal"]:
                    budget = change["budget"]
            rules = rule_plan(factory, case, goal=stage["goal"], budget=budget, original_goal=case["goal"])
            expected = "ready" if case.get("modifications") else case["expected"]
            stages.append({"goal": stage["goal"], "budget_minutes": budget,
                "agent": {"status": stage["status"], "constraint_pass": stage["passed"], "draft": stage["draft"],
                    "model_calls": stage["metrics"].get("model_calls", 0), "duration_ms": stage["metrics"].get("duration_ms", 0)},
                "rules": rules, "rule_status_matches_expectation": rules["status"] == expected})
        rows.append({"case": case["id"], "agent_protocol_pass": agent["passed"], "stages": stages,
            "both_constraint_pass": agent["passed"] and all(s["rule_status_matches_expectation"] and s["rules"]["no_business_write"] for s in stages)})
    return rows


def main():
    os.environ["APP_ENV"] = "test"
    os.environ.setdefault("TEST_DATABASE_URL", "postgresql+psycopg://kaoyan:kaoyan_dev_pw@127.0.0.1:5433/kaoyan_test")
    from backend.config import get_settings
    get_settings.cache_clear()
    with isolated_factory(str(get_settings().active_database_url)) as factory:
        rows = compare(factory)
    report = {"mode": "protocol_agent_vs_adapted_existing_rules", "complete": True,
        "claim": "仅对照选题约束和数据复用；无真实模型能力、教学效果或延迟优劣结论。规则定位关键词为人工提供，新增适配器不是原有线上自然语言功能。",
        "cases": rows, "both_constraint_pass": sum(r["both_constraint_pass"] for r in rows), "total": len(rows)}
    path = ROOT / "eval/reports" / ("learning-planner-comparison-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:6] + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report: {path}; both constraints {report['both_constraint_pass']}/{report['total']}")
    return 0 if report["both_constraint_pass"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
