"""Owned PostgreSQL fixture; model calls fail closed, no synthetic query API."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from uuid import uuid4
from backend.models.learning import (KnowledgePoint, KpState, Question, DailyPlan,
    PracticeItem, QuestionAttempt, LearningEvent)

NOW = datetime(2026, 10, 20, 2, tzinfo=timezone.utc)


def prepare_fixture(factory, *, question_specs=None):
    from tests.integration.test_learning_loop import mark_isolated_question_trusted
    from backend.services.question_eligibility import question_eligibility
    with factory.begin() as db:
        math = KnowledgePoint(code="fixture.math", name="隔离数学二", subject="考研数学", is_assessable=False)
        cs = KnowledgePoint(code="fixture.cs", name="隔离408", subject="408", is_assessable=False)
        db.add_all([math, cs]); db.flush()
        lhopital = KnowledgePoint(code="fixture.math.lhopital", name="洛必达法则", subject="考研数学", parent_id=math.id)
        derivative = KnowledgePoint(code="fixture.math.derivative", name="导数计算", subject="考研数学", parent_id=math.id)
        ds = KnowledgePoint(code="fixture.cs.ds", name="线性表", subject="408", parent_id=cs.id)
        db.add_all([lhopital, derivative, ds]); db.flush()
        for node in (lhopital, derivative, ds):
            db.add(KpState(kp_id=node.id))
        rows = []
        for index, (name, node, source, trusted) in enumerate([
            ("洛必达真题甲", lhopital, "exam", True), ("洛必达真题乙", lhopital, "exam", True),
            ("洛必达原创丙", lhopital, "original", True), ("洛必达未审核丁", lhopital, "original", False),
            ("导数原创戊", derivative, "original", True), ("408原创己", ds, "original", True),
        ]):
            spec = question_specs[index] if question_specs else {}
            q = Question(kp_id=node.id, stem=spec.get("stem", name + "：计算极限并选择正确答案。"), question_type="single_choice",
                options=spec.get("options", {"A": "1", "B": "2"}), correct_answer=spec.get("correct_answer", "A"),
                explanation=spec.get("explanation", "本样本只用于隔离查询计数与版本绑定验证。"),
                grading_config={"verified": True, "method": "single_choice", "generation": {"mode": "original", "authoring_mode": "codex_offline"}})
            db.add(q); db.flush()
            if trusted:
                mark_isolated_question_trusted(q, db=db)
            if source == "exam":
                q.question_provenance = "real_exam"; q.source_status = "verified"
            db.flush()
            eligibility = question_eligibility(q, node)
            assert eligibility.practice_eligible is trusted, (name, eligibility.blocking_reasons)
            rows.append(q)
        plan = DailyPlan(study_date="2026-10-20", status="active")
        db.add(plan); db.flush()
        for index, (q, result) in enumerate([(rows[0], "wrong"), (rows[1], "right"),
                (rows[2], "wrong"), (rows[4], "wrong"), (rows[5], "wrong")], 1):
            item = PracticeItem(plan_id=plan.id, question_id=q.id, kp_id=q.kp_id, ordinal=index)
            db.add(item); db.flush()
            attempt = QuestionAttempt(practice_item_id=item.id, question_id=q.id, kp_id=q.kp_id,
                objective_result=result, grading_evidence={"assisted": False}, submitted_at=NOW,
                idempotency_key="followup-fixture-"+str(uuid4()), result_state="LEARNING", reason_code="isolated_fixture")
            db.add(attempt); db.flush()
            db.add(LearningEvent(kp_id=q.kp_id, source_id=attempt.id, event_type="answer_submitted",
                payload={"synthetic_fixture": True}, occurred_at=NOW))
        return {"lhopital_id": str(lhopital.id), "question_ids": [str(q.id) for q in rows],
            "math_eligible": 4, "math_active": 5, "lhopital_eligible": 3, "lhopital_exam": 2,
            "lhopital_exam_attempted": 2, "lhopital_exam_wrong": 1}


class NoModel:
    def __init__(self, **kwargs):
        self.model = "e2e-offline-fixture"

    def __getattr__(self, name):
        def denied(*args, **kwargs):
            if os.environ.get("QUERY_FOLLOWUP_OUTPUT"):
                path = Path(os.environ["QUERY_FOLLOWUP_OUTPUT"]) / "model-calls.json"
                calls = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
                calls.append({"method": name, "blocked": True})
                path.write_text(json.dumps(calls), encoding="utf-8")
            raise AssertionError("Query regression must not call any model: " + name)
        return denied


def create_e2e_app():
    from scripts.prepare_e2e_learning import validate_test_target
    from backend.db import create_db_engine, create_session_factory
    from scripts.e2e_backend import create_e2e_app as offline_app
    url = validate_test_target(os.environ["TEST_DATABASE_URL"], os.environ["KAOYAN_OWNED_TEST_PORT"])
    engine = create_db_engine(url)
    factory = create_session_factory(engine)
    try:
        from sqlalchemy import text
        with factory.begin() as db:
            db.execute(text("TRUNCATE chat_sessions, knowledge_points, questions, daily_plans CASCADE"))
        facts = prepare_fixture(factory)
    finally:
        engine.dispose()
    output = Path(os.environ["QUERY_FOLLOWUP_OUTPUT"])
    output.mkdir(parents=True, exist_ok=True)
    (output / "fixture.json").write_text(json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "model-calls.json").write_text("[]", encoding="utf-8")
    # Capture executed read SQL, without parameter values or credentials. This
    # audit lives only in this owned test backend, never in production routes.
    from sqlalchemy import event
    from sqlalchemy.engine import Engine
    import re
    @event.listens_for(Engine, "before_cursor_execute")
    def capture_read_sql(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            tables = [name for name in ("questions", "question_attempts", "learning_events", "knowledge_points")
                if re.search(r"\b" + name + r"\b", statement)]
            if tables:
                with (output / "read-sql.jsonl").open("a", encoding="utf-8") as log:
                    log.write(json.dumps({"tables": tables, "sql": " ".join(statement.split())}) + "\n")
    app = offline_app()
    from backend.chat import service
    service.Provider = NoModel
    import backend.app as app_module
    app_module._try_build_retrieval_stack = lambda *args: False
    from backend.api.deps import get_time_provider
    app.dependency_overrides[get_time_provider] = lambda: lambda: NOW
    return app


if __name__ == "__main__":
    import sys
    from sqlalchemy import select, func
    from uuid import UUID
    from scripts.prepare_e2e_learning import validate_test_target
    from backend.db import create_db_engine, create_session_factory
    from backend.models.chat import ChatMessage
    from backend.models.learning import QuestionVersion
    url = validate_test_target(os.environ["TEST_DATABASE_URL"], os.environ["KAOYAN_OWNED_TEST_PORT"])
    engine = create_db_engine(url)
    try:
        with create_session_factory(engine)() as db:
            data = {"counts": {m.__name__: db.scalar(select(func.count()).select_from(m)) for m in
                (Question, QuestionVersion, PracticeItem, QuestionAttempt, LearningEvent)},
                "messages": [{"id": str(r.id), "role": r.role, "content": r.content, "status": r.status,
                    "evidence": (r.metadata_ or {}).get("read_only_data_query")}
                    for r in db.scalars(select(ChatMessage).where(ChatMessage.session_id == UUID(sys.argv[1])).order_by(ChatMessage.seq))]}
            print(json.dumps(data, ensure_ascii=True, default=str))
    finally:
        engine.dispose()
