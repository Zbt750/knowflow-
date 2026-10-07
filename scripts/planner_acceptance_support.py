"""Test-only PostgreSQL isolation and hard preflight for Planner acceptance."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from sqlalchemy import event, select, text
from sqlalchemy.engine import make_url
from backend.db import create_db_engine, create_session_factory


def isolated_engine(url: str, schema: str):
    parsed = make_url(url)
    if parsed.database != "kaoyan_test" or not re.fullmatch(r"planner_factual_repair_20261007_[a-z0-9]+_test", schema):
        raise ValueError("Acceptance requires a uniquely named schema in kaoyan_test")
    # Startup options are session defaults, not transactional SET statements.
    # No public fallback: a missing test table must fail rather than touch public.
    engine = create_db_engine(parsed.update_query_dict({"options": f"-csearch_path={schema}"}).render_as_string(hide_password=False))

    @event.listens_for(engine, "checkout")
    def verify_checkout(connection, _record, _proxy):
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_schema()")
            if cursor.fetchone()[0] != schema:
                raise RuntimeError("test_schema_checkout_mismatch")
        connection.rollback()

    return engine


def verify_isolation(engine, schema: str):
    rows = []
    for index in range(3):
        with engine.connect() as connection:
            actual, pid = connection.execute(text("SELECT current_schema(), pg_backend_pid()")).one()
            assert actual == schema, (index, actual, schema)
            rows.append({"checkout": index + 1, "schema": actual, "backend_pid": pid})
    with create_session_factory(engine)() as db:
        actual = db.scalar(text("SELECT current_schema()"))
        assert actual == schema
    return {"checkouts": rows, "application_session_schema": actual, "passed": True}


def preflight(factory, schema: str, manifest: dict):
    from backend.models.learning import QuestionAttempt
    from backend.services.learning_task_service import _daily_plan_snapshot
    from backend.services.learning_task_tools import TaskTools
    from scripts.expand_phase3b_inventory import protected_fingerprints
    now = datetime.now(timezone.utc)
    with factory() as db:
        actual = db.scalar(text("SELECT current_schema()"))
        assert actual == schema
        plan, _ = _daily_plan_snapshot(db, now=now)
        attempts = list(db.scalars(select(QuestionAttempt)))
        protected = protected_fingerprints(db)
    assert plan and plan["plan_id"] == manifest["plan_id"], "current_plan_missing_or_different"
    nodes = manifest["knowledge_node_ids"]
    tools = TaskTools(factory, budget_minutes=90, now=now, goal="根据我今天实际学习情况，接下来应该练什么？", current_plan=plan,
        handoff={"target_knowledge_node_ids": nodes, "request_type": "recommend"})
    state = tools.execute("get_learning_state", {"kp_ids": nodes})
    inventory = tools.execute("find_questions", {"kp_ids": nodes})
    summary = tools.planner_factual_summary()
    p, o, e, i = (summary[key] for key in ("today_plan", "observations", "evidence", "inventory"))
    checks = {
        "plan": (p["total_items"], p["completed_items"], p["pending_items"], p["remaining_minutes"]) == (6, 4, 2, 8),
        "attempts": len(attempts) == 5 and o["attempt_observation_count"] == 5,
        "observations": (o["unassisted_correct_observation_count"], o["hint_assisted_correct_observation_count"], o["solution_assisted_correct_observation_count"], o["incorrect_observation_count"]) == (1, 1, 1, 2),
        "hint_incorrect": any(a.objective_result == "wrong" and (a.grading_evidence or {}).get("assistance_level") == "hint_1" for a in attempts),
        "confirmations": e["effective_confirmation_count"] == e["verified_objective_confirmation_count"] == 0,
        "inventory": i["additional_eligible_count"] == 0,
        "trust": summary["answer_reliability"]["counts"] == {"ai_generated_consistent": 6},
        "consistency": summary["consistency"]["valid"] and p["completed_items"] + p["pending_items"] == p["total_items"] and not set(p["completed_question_ids"]) & set(p["pending_question_ids"]),
    }
    report = {"schema": actual, "plan": plan, "state": state, "inventory": inventory, "factual_summary": summary,
        "checks": checks, "protected_state": protected, "passed": all(checks.values())}
    return report
