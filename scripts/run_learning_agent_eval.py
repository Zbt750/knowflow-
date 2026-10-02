"""隔离合成数据评测学习 Agent；默认协议测试，--live 显式启用付费模型。"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import re
import sys
import time
from uuid import uuid4
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CASES = [
    {"id": "basic", "goal": "洛必达比较弱，只练基础题，安排今天的学习", "budget": 30, "query": "洛必达", "expected": "ready", "basic": True},
    {"id": "short_fill", "goal": "洛必达只做填空题，时间有限，不要超过5分钟", "budget": 5, "query": "洛必达", "expected": "ready", "type": "fill_blank"},
    {"id": "insufficient", "goal": "洛必达只做计算题，只有5分钟，不要安排知识复习，题目不足请说明", "budget": 5, "query": "洛必达", "expected": "needs_info", "type": "calculation"},
    {"id": "reference_only", "goal": "合成原卷节点只有来源引用，帮我找在线题，没有题干就告诉我不要编题", "budget": 30, "query": "合成原卷", "expected": "needs_info"},
    {"id": "unknown_scope", "goal": "帮我复习量子计算考试的超导量子纠错，库里没有就先问我", "budget": 30, "query": "量子纠错", "expected": "needs_info"},
    {"id": "manual_program", "goal": "合成程序节点只做程序题，纸上写，不运行代码，说明需要人工对照", "budget": 20, "query": "合成程序", "expected": "ready", "type": "program"},
    {"id": "existing_today", "goal": "洛必达只做选择题，今日已有的题不要重复加，没有新题就说明", "budget": 15, "query": "洛必达", "expected": "needs_info", "type": "single_choice", "existing": True},
    {"id": "modify", "goal": "洛必达比较弱，安排适合的题", "budget": 30, "query": "洛必达", "expected": "ready", "modify": "少一点，只做填空题，不超过5分钟", "modified_budget": 5, "type": "fill_blank"},
]

# 独立扩展集；默认八场景保持不变，真实调用需另行授权。
EXTENDED_CASES = [
    {"id": "multi_modify", "goal": "洛必达法则比较弱，安排适合的题，不要知识复习", "budget": 30,
     "query": "洛必达", "expected": "ready", "scope_code": "math.calculus.limit.lhopital",
     "modifications": [
         {"goal": "少一点，只做填空题，不超过5分钟", "budget": 5, "type": "fill_blank"},
         {"goal": "还是这个知识点，改为只做选择题，5分钟，不要知识复习", "budget": 5, "type": "single_choice"}]},
    {"id": "unresolved_reference", "goal": "还是那个知识点，帮我安排练习；如果不知道我指哪个就先问我，不要猜", "budget": 15,
     "query": "不存在的指代", "expected": "needs_info"},
    {"id": "excluded_scope", "goal": "在合成评测范围里挑题，但不要合成程序节点的题，不要知识复习，题型不限", "budget": 30,
     "query": "洛必达", "expected": "ready", "excluded_codes": ["eval.program"]},
    {"id": "insufficient_count", "goal": "洛必达法则只做填空题，必须有3道不同的题；不足3道就先告诉我，不要生成不足数量的草案，不要知识复习", "budget": 30,
     "query": "洛必达", "expected": "needs_info", "type": "fill_blank", "required_count": 3},
]


@contextmanager
def isolated_factory(url):
    """全新 schema，无 public 回退；只清理有本脚本标记且未被活跃连接占用的 schema。"""
    from sqlalchemy import create_engine, text
    from backend.db import create_session_factory
    from backend.models.base import Base
    from backend.models import import_models
    from sqlalchemy.engine import make_url
    if not (make_url(url).database or "").endswith("_test"):
        raise ValueError("评测只能连接 _test 数据库")
    admin = create_engine(url, connect_args={"connect_timeout": 5}, pool_pre_ping=True)
    schema = "agent_eval_" + uuid4().hex[:16]
    owner = admin.connect()
    engine = None
    created = False
    try:
        if not owner.scalar(text("SELECT current_database()" )).endswith("_test"):
            raise ValueError("实际数据库不是测试库")
        rows = owner.execute(text("SELECT nspname, obj_description(oid, 'pg_namespace') FROM pg_namespace WHERE nspname LIKE 'agent_eval_%'" )).all()
        for name, marker in rows:
            if not re.fullmatch(r"agent_eval_[0-9a-f]{16}", name) or marker != "kaoyan-agent-eval:v1":
                continue
            if owner.scalar(text("SELECT pg_try_advisory_xact_lock(hashtext(:name))"), {"name": name}):
                owner.exec_driver_sql(f'DROP SCHEMA "{name}" CASCADE')
        owner.execute(text("SELECT pg_advisory_lock(hashtext(:name))"), {"name": schema})
        owner.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        owner.exec_driver_sql(f'COMMENT ON SCHEMA "{schema}" IS \'kaoyan-agent-eval:v1\'')
        owner.commit()
        created = True
        engine = create_engine(url, connect_args={"connect_timeout": 5, "options": f"-csearch_path={schema}"}, pool_pre_ping=True)
        with engine.connect() as check:
            assert check.scalar(text("SELECT current_schema()")) == schema
        import_models()
        Base.metadata.create_all(engine)
        yield create_session_factory(engine)
    finally:
        if engine is not None:
            engine.dispose()
        owner.rollback()
        if created:
            owner.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
            owner.commit()
        owner.close()
        admin.dispose()


def seed_fixture(factory, *, existing=False):
    from backend.models.learning import KnowledgePoint, Question, ExamQuestionReference, DailyPlan, PracticeItem, KpState, QuestionAttempt
    from backend.models.base import Base
    from sqlalchemy import delete
    now = datetime.now(timezone.utc)
    with factory.begin() as db:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(delete(table))
        root = KnowledgePoint(code="eval.root", name="合成评测范围", subject="数学二", is_assessable=False)
        db.add(root); db.flush()
        math = KnowledgePoint(code="math.calculus.limit.lhopital", name="洛必达法则", subject="数学二", parent_id=root.id)
        ref = KnowledgePoint(code="eval.reference", name="合成原卷节点", subject="数学二", is_reference_only=True, parent_id=root.id)
        program = KnowledgePoint(code="eval.program", name="合成程序节点", subject="408", parent_id=root.id)
        db.add_all([math, ref, program]); db.flush()
        # 只有公开仓库里的洛必达演示题，不导入用户数据或大型原卷索引。
        source = json.loads((ROOT / "seed/questions.json").read_text(encoding="utf-8"))["questions"]
        questions = []
        for entry in source:
            if entry["kp_code"] != math.code:
                continue
            q = Question(kp_id=math.id, **{k: v for k, v in entry.items() if k != "kp_code"})
            db.add(q); questions.append(q)
        program_q = Question(kp_id=program.id, question_type="program", stem="合成例题：用伪代码查找数组最大值，并说明时间复杂度。", explanation="人工检查边界与循环。", estimated_minutes=12)
        db.add(program_q)
        db.add(ExamQuestionReference(subject="数学二", year=2020, question_number=1, knowledge_point_id=ref.id, topic_label="合成来源", source_topic_label="合成来源", local_folder="synthetic", source_note="合成索引，无原卷题干"))
        db.add(KpState(kp_id=math.id, state="stuck", assessment_basis="objective_v1", node_self_grade="mastered"))
        db.flush()
        # 合成历史：用户自评已掌握，但客观答错。原始答案哨兵不能进入模型上下文。
        history = DailyPlan(study_date=(now.astimezone(ZoneInfo("Asia/Shanghai")).date() - timedelta(days=1)).isoformat(), status="completed")
        db.add(history); db.flush()
        item = PracticeItem(plan_id=history.id, question_id=questions[0].id, kp_id=math.id, ordinal=1)
        db.add(item); db.flush()
        db.add(QuestionAttempt(practice_item_id=item.id, question_id=questions[0].id, kp_id=math.id, raw_answer="SYNTHETIC_RAW_ANSWER_DO_NOT_SEND", objective_result="wrong", self_grade="mastered", submitted_at=now - timedelta(days=1), idempotency_key=str(uuid4()), result_state="stuck", reason_code="synthetic", grading_evidence={"assessment_basis": "objective_v1", "assisted": False}))
        if existing:
            plan = DailyPlan(study_date=now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat(), status="active")
            db.add(plan); db.flush()
            for i, q in enumerate((q for q in questions if q.question_type == "single_choice"), 1):
                db.add(PracticeItem(plan_id=plan.id, question_id=q.id, kp_id=math.id, ordinal=i))


class ProtocolProvider:
    """只验证协议与报告，不代表真实模型的意图理解/规划质量。"""
    def __init__(self, case): self.case, self.turn, self.nodes = case, 0, []

    def tool_turn(self, messages, tools, *, timeout):
        self.turn += 1
        if self.turn == 1:
            actions = [("search_knowledge", {"query": self.case["query"]})]
        elif self.turn == 2:
            self.nodes = [n["kp_id"] for n in json.loads(messages[-1]["content"])["nodes"]]
            if not self.nodes: return self.final(True)
            actions = [("get_learning_state", {"kp_ids": self.nodes}), ("find_questions", {"kp_ids": self.nodes})]
        elif self.turn == 3:
            qs = json.loads(messages[-1]["content"])["questions"]
            qs = [q for q in qs if not q["in_today_plan"] and q["minutes"] <= self.case.get("modified_budget", self.case["budget"])
                  and (not self.case.get("type") or q["question_type"] == self.case["type"])
                  and (not self.case.get("basic") or q["difficulty"] == "basic")]
            if not qs or len(qs) < self.case.get("required_count", 1): return self.final(True)
            actions = [("validate_plan", {"question_ids": [qs[0]["question_id"]], "rationale": "合成协议测试方案"})]
        else:
            return self.final(not json.loads(messages[-1]["content"]).get("valid"))
        return {"model": "protocol-test-double", "message": {"tool_calls": [{"id": f"{self.turn}-{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}} for i, (name, args) in enumerate(actions)]}}

    def final(self, clarify):
        return {"model": "protocol-test-double", "message": {"content": json.dumps({"message": "合成测试：题量不足或需要明确范围。" if clarify else "合成测试：已校验草案，尚未加入今日学习。", "needs_clarification": clarify})}}


class CheckedProvider:
    def __init__(self, provider): self.provider = provider
    def __getattr__(self, name): return getattr(self.provider, name)
    def tool_turn(self, messages, tools, *, timeout):
        if "SYNTHETIC_RAW_ANSWER_DO_NOT_SEND" in json.dumps(messages, ensure_ascii=False):
            raise ValueError("raw_answer_privacy_violation")
        return self.provider.tool_turn(messages, tools, timeout=timeout)


def snapshot(factory):
    from sqlalchemy import select, func
    from backend.models.learning import DailyPlan, PracticeItem, QuestionAttempt, LearningEvent, KpState
    with factory() as db:
        return {"counts": [db.scalar(select(func.count()).select_from(m)) for m in (DailyPlan, PracticeItem, QuestionAttempt, LearningEvent)],
            "plans": [(str(p.id), p.study_date, p.status) for p in db.scalars(select(DailyPlan).order_by(DailyPlan.id))],
            "items": [(str(i.id), str(i.question_id), i.ordinal, str(i.completed_at), i.latest_self_grade, str(i.answer_revealed_at)) for i in db.scalars(select(PracticeItem).order_by(PracticeItem.id))],
            "states": [(str(s.kp_id), s.state, s.assessment_basis, s.evidence_window, s.node_self_grade,
                s.manual_credit_count, s.pending_review_question_ids, str(s.mastered_at), str(s.next_review_at)) for s in db.scalars(select(KpState).order_by(KpState.kp_id))]}


def assess(factory, case, result, before):
    from sqlalchemy import select
    from backend.models.learning import Question, KnowledgePoint
    draft = result.draft or {}
    ids = [q["question_id"] for q in draft.get("questions", [])]
    with factory() as db:
        by_id = {str(q.id): q for q in db.scalars(select(Question))}
        codes = {str(n.id): n.code for n in db.scalars(select(KnowledgePoint))}
    checks = {"expected_status": result.status == case["expected"], "no_automatic_business_write": snapshot(factory) == before,
        "practice_goal_has_questions": bool(ids) if case["expected"] == "ready" else True,
        "real_questions_only": all(qid in by_id for qid in ids), "no_duplicates": len(ids) == len(set(ids)),
        "time_budget": not draft or 0 < draft["total_minutes"] <= result.budget_minutes,
        "server_validated": result.status != "ready" or any(t["tool"] == "validate_plan" and t["result"].get("valid") for t in result.trace),
        "type_constraint": all(by_id[qid].question_type == case["type"] for qid in ids if qid in by_id) if case.get("type") else True,
        "basic_constraint": all(by_id[qid].difficulty == "basic" for qid in ids if qid in by_id) if case.get("basic") else True,
        "scope_constraint": all(codes.get(str(by_id[qid].kp_id)) == case["scope_code"] for qid in ids if qid in by_id) if case.get("scope_code") else True,
        "excluded_scope": all(codes.get(str(by_id[qid].kp_id)) not in case.get("excluded_codes", []) for qid in ids if qid in by_id),
        "required_count": not ids or len(ids) == case["required_count"] if case.get("required_count") else True}
    # 这是程序约束检查，不以自然语言关键词冒充事实正确性评分。
    return {"case": case["id"], "goal": result.goal, "status": result.status, "error_code": result.error_code, "message": result.message, "draft": result.draft,
        "checks": checks, "passed": all(checks.values()), "metrics": result.metrics, "trace": result.trace,
        "manual_review_required": ["理由是否区分客观作答与自评", "是否如实说明题量与能力限制", "学习内容和题目是否适合目标"]}


def run_suite(factory, provider_factory, cases=CASES, on_record=None):
    from backend.schemas.learning_task import CreateTask, TaskInput
    from backend.services.learning_task_service import create_task, run_task, modify_task
    records = []
    for case in cases:
        seed_fixture(factory, existing=case.get("existing", False))
        before = snapshot(factory)
        created = create_task(factory, CreateTask(goal=case["goal"], budget_minutes=case["budget"]))
        result = run_task(factory, created.task_id, CheckedProvider(provider_factory(case)))
        initial = None
        prior_runs = []
        stage_checks = [assess(factory, {**case, "expected": "ready"} if case.get("modifications") else case, result, before)]
        modifications = case.get("modifications", [])
        if case.get("modify"):
            modifications = [{"goal": case["modify"], "budget": case["modified_budget"], "type": case.get("type")}]
        final_case = case
        for change in modifications:
            if result.status != "ready": break
            saved = result.model_dump(mode="json")
            if initial is None: initial = saved
            else: prior_runs.append(saved)
            modify_task(factory, created.task_id, TaskInput(goal=change["goal"], budget_minutes=change["budget"]))
            final_case = {**case, **change, "modified_budget": change["budget"]}
            result = run_task(factory, created.task_id, CheckedProvider(provider_factory(final_case)))
            stage_checks.append(assess(factory, final_case, result, before))
        record = assess(factory, final_case, result, before)
        record["initial_run"] = initial
        record["prior_runs"] = prior_runs
        record["stages"] = stage_checks
        if case.get("modifications"):
            record["checks"]["all_modifications_executed"] = len(stage_checks) == len(modifications) + 1
            record["checks"]["every_stage_passed"] = all(s["passed"] for s in stage_checks)
            record["passed"] = all(record["checks"].values())
        records.append(record)
        if on_record:
            on_record(records)
        print(f"{case['id']}: {result.status}; constraints={'PASS' if record['passed'] else 'FAIL'}", flush=True)
    return records


def summarize(records):
    runs = [r["metrics"] for r in records]
    runs.extend(r["initial_run"]["metrics"] for r in records if r.get("initial_run"))
    runs.extend(p["metrics"] for r in records for p in r.get("prior_runs", []))
    calls = [call for run in runs for call in run.get("calls", [])]
    known = [call["usage"]["total_tokens"] for call in calls if isinstance(call.get("usage"), dict) and type(call["usage"].get("total_tokens")) is int]
    return {"task_runs": len(runs), "model_calls": len(calls),
        "failed_calls": sum(call.get("status") == "error" for call in calls),
        "retry_calls": sum(call.get("attempt", 1) > 1 for call in calls),
        "observed_total_tokens": sum(known) if known else None,
        "calls_without_total_usage": len(calls) - len(known),
        "total_usage_complete": bool(calls) and len(known) == len(calls),
        "models": sorted({call.get("model", "unknown") for call in calls}),
        "task_total_duration_ms": sum(run.get("duration_ms", 0) for run in runs)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="调用当前模型，会产生费用；需事先获准")
    parser.add_argument("--allow-synthetic-data", action="store_true", help="确认已获准发送合成数据、演示题和内置讲解")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--suite", choices=["baseline", "extended"], default="baseline")
    parser.add_argument("--case", action="append", choices=[c["id"] for c in CASES + EXTENDED_CASES], help="只复测当前套件中的指定场景")
    args = parser.parse_args()
    if args.live and not args.allow_synthetic_data: parser.error("真实模型调用必须先获准并显式指定 --allow-synthetic-data")
    if not 1 <= args.limit <= 8: parser.error("limit 必须为1至8")
    suite = EXTENDED_CASES if args.suite == "extended" else CASES
    selected = [c for c in suite if not args.case or c["id"] in args.case][:args.limit]
    if not selected: parser.error("当前套件没有匹配场景")
    os.environ["APP_ENV"] = "test"
    os.environ.setdefault("TEST_DATABASE_URL", "postgresql+psycopg://kaoyan:kaoyan_dev_pw@127.0.0.1:5433/kaoyan_test")
    from backend.config import get_settings
    get_settings.cache_clear()
    settings = get_settings()
    if args.live:
        from backend.services.model_settings_service import load_local_settings
        from backend.chat.service import provider_from_settings
        effective = load_local_settings(settings.model_copy(update={"app_env": "dev"}))
        provider = provider_from_settings(effective)
        make_provider = lambda case: provider
    else:
        make_provider = ProtocolProvider
    started = time.monotonic()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:6]
    output = ROOT / "eval/reports" / f"learning-agent-{'live' if args.live else 'protocol'}-{run_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    def save_progress(records, complete=False):
        report = {"mode": "real_model" if args.live else "protocol_only", "suite": args.suite, "complete": complete,
            "created_at": datetime.now(timezone.utc).isoformat(), "duration_seconds": round(time.monotonic() - started, 2),
            "passed": sum(r["passed"] for r in records), "total": len(records), "requested_cases": len(selected),
            "summary": summarize(records),
            "quality_claim": "程序约束结果，不等同于真实教学质量评分；协议替身不证明模型能力。", "cases": records}
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report
    save_progress([])
    with isolated_factory(str(settings.active_database_url)) as factory:
        records = run_suite(factory, make_provider, selected, on_record=save_progress)
    report = save_progress(records, complete=True)
    print(f"Report: {output}; {report['passed']}/{report['total']}; mode={report['mode']}")
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
