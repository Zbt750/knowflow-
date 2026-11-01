"""Owned, isolated real-bank browser fixture; never sends model requests.

Prepare once, then serve with uvicorn scripts.final_user_acceptance:app --factory.
The seed uses the existing answer/reveal services, not fabricated receipts.
"""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "storage/quality-audits/final-real-user-20261015"
DATABASE = "phase5_final_user_realbank_20261015_test"
BASE = "phase5_final_retest_base_20261015_test"
URL = f"postgresql+psycopg://postgres@127.0.0.1:59271/{DATABASE}"


def configure():
    os.environ.update(APP_ENV="test", DATABASE_URL=URL, TEST_DATABASE_URL=URL,
        KAOYAN_OWNED_TEST_PORT="59271", UPLOAD_DIR=str(OUT / "uploads"),
        CHROMA_DIR=str(OUT / "chroma"), HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
        ALLOWED_WEB_ORIGINS='["http://127.0.0.1:5184"]')
    from backend.config import get_settings
    get_settings.cache_clear()


def verify():
    import psycopg
    with psycopg.connect("postgresql://postgres@127.0.0.1:59271/postgres",
            options="-c default_transaction_read_only=on", connect_timeout=3) as conn:
        assert str(conn.execute("select system_identifier from pg_control_system()").fetchone()[0]) == "7696773489828724208"


def app():
    verify()
    configure()
    from scripts.e2e_backend import create_e2e_app
    return create_e2e_app()


def prepare():
    import psycopg
    from psycopg import sql
    verify()
    with psycopg.connect("postgresql://postgres@127.0.0.1:59271/postgres", autocommit=True) as conn:
        assert conn.execute("select 1 from pg_database where datname=%s", (DATABASE,)).fetchone() is None, "Preserve existing evidence; never overwrite"
        conn.execute(sql.SQL("create database {} template {}").format(sql.Identifier(DATABASE), sql.Identifier(BASE)))
    configure()
    from backend.db import create_db_engine, create_session_factory
    from backend.models.learning import KnowledgePoint, KpState
    from sqlalchemy import select, text
    from scripts.phase5_run_frozen_ai_eval import seed_profile
    engine = create_db_engine(URL)
    factory = create_session_factory(engine)
    cases = json.loads((ROOT / "eval/phase5-closeout-v1/cases.json").read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    nodes = {}
    with factory() as db:
        for key, code in cases["node_keys"].items():
            node = db.scalar(select(KnowledgePoint).where(KnowledgePoint.code == code))
            nodes[key] = {"id": str(node.id), "code": code, "name": node.name}
    # All observations are produced through the existing production services.
    from uuid import UUID
    seed_profile(factory, {"profile": "weak_integral"}, UUID(nodes["integral"]["id"]), now)
    seed_profile(factory, {"profile": "solution_integral"}, UUID(nodes["integral"]["id"]), now - timedelta(days=3))
    seed_profile(factory, {"profile": "corrected_encoding"}, UUID(nodes["encoding"]["id"]), now)
    seed_profile(factory, {"profile": "graduated_determinant"}, UUID(nodes["determinant"]["id"]), now)
    with factory() as db:
        assert db.scalar(text("select count(*) from daily_plans where study_date=:day"), {"day": now.astimezone(timezone(timedelta(hours=8))).date().isoformat()}) == 0
        counts = {table: db.scalar(text(f'select count(*) from "{table}"')) for table in
                  ("questions", "question_versions", "question_attempts", "learning_events", "kp_states", "daily_plans", "practice_items")}
        assert db.get(KpState, UUID(nodes["determinant"]["id"])).mastered_at is not None
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "fixture.json").write_text(json.dumps({"database": DATABASE, "port": 59271,
        "system_identifier": "7696773489828724208", "model": "offline UI transport only",
        "created_at": now.isoformat(), "nodes": nodes, "counts": counts,
        "fixture_method": "sealed formal-bank clone; legitimate append/answer/reveal services; no fabricated formal receipt",
        "paid_calls": 0}, ensure_ascii=False, indent=2), encoding="utf-8")
    engine.dispose()
    print(json.dumps({"database": DATABASE, "counts": counts, "paid_calls": 0}))


def export_answers():
    import psycopg
    verify()
    with psycopg.connect(URL.replace("postgresql+psycopg", "postgresql"),
            options="-c default_transaction_read_only=on") as conn:
        rows = conn.execute("select q.id, v.correct_answer from questions q join question_versions v on v.id=q.current_version_id").fetchall()
    (OUT / "answers.json").write_text(json.dumps({str(q): a for q, a in rows}, ensure_ascii=False), encoding="utf-8")


def audit():
    from collections import Counter
    from uuid import UUID
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    from backend.services.learning_task_tools import TaskTools
    from backend.schemas.learning_task import NodeIds, FindQuestions, ValidatePlan
    verify()
    configure()
    engine = create_engine(URL, connect_args={"options": "-c default_transaction_read_only=on"})
    factory = sessionmaker(engine)
    nodes = json.loads((OUT / "fixture.json").read_text(encoding="utf-8"))["nodes"]
    ids = [UUID(nodes[key]["id"]) for key in ("integral", "encoding", "determinant", "derivative")]
    tools = TaskTools(factory, budget_minutes=20, now=datetime.now(timezone.utc),
        goal="我只有20分钟，读取最近错题和学习记录，先查询再安排。")
    # Explicitly discover nodes, exactly as the Agent tool sequence does.
    from backend.schemas.learning_task import SearchKnowledge
    with factory() as db:
        for key in ("integral", "encoding", "determinant", "derivative"):
            tools.search_knowledge(db, SearchKnowledge(query=nodes[key]["code"]))
        states = tools.get_learning_state(db, NodeIds(kp_ids=ids))
        inventory = tools.find_questions(db, FindQuestions(kp_ids=ids))
        candidates = [q for q in inventory["questions"] if not q["in_today_plan"] and q["minutes"] <= 20]
        draft = tools.validate_plan(db, ValidatePlan(question_ids=[UUID(candidates[0]["question_id"])],
            rationale="免费确定性校验：只用已查询真实题，20分钟内，未确认不写卷")) if candidates else None
        attempts = db.execute(text("select objective_result, grading_evidence->>'assisted', count(*) from question_attempts group by 1,2")).all()
        assert any(r == "right" and a == "true" and n for r, a, n in attempts)
        assert any(r == "wrong" and a == "false" and n for r, a, n in attempts)
        assert any(r == "right" and a == "false" and n for r, a, n in attempts)
        unbound = db.scalar(text("select count(*) from question_attempts where question_version_id is null"))
        assert unbound == 0
        preserved = {}
        import psycopg
        for table in ("questions", "question_versions", "question_auto_review_events", "kp_graduation_question_set_versions", "kp_mastery_policies"):
            query = f'select count(*), md5(string_agg(md5(row_to_json(t)::text),\'\' order by row_to_json(t)::text)) from "{table}" t'
            current = tuple(db.execute(text(query)).one())
            with psycopg.connect(f"postgresql://postgres@127.0.0.1:59271/{BASE}", options="-c default_transaction_read_only=on") as conn:
                original = conn.execute(query).fetchone()
            assert current == original, table
            preserved[table] = {"rows": current[0], "md5": current[1], "unchanged_from_base": True}
    report = {"read_only": True, "paid_calls": 0, "states": states, "inventory": inventory,
        "source_counts_in_observed_candidates": dict(Counter(q["source_category"] for q in inventory["questions"])),
        "validated_20_minute_draft": draft, "attempt_kinds": attempts, "unbound_attempts": unbound,
        "bank_and_policy_fingerprints": preserved, "real_ai_quality": "NOT_TESTED_PENDING_AMOUNT_AUTHORIZATION"}
    (OUT / "evidence-audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"unbound_attempts": unbound, "observed_candidate_sources": report["source_counts_in_observed_candidates"],
        "bank_and_policy_unchanged": True, "paid_calls": 0, "draft_valid": draft.get("valid") if draft else None}))
    engine.dispose()


if __name__ == "__main__":
    if "--export-answers" in sys.argv:
        export_answers()
    elif "--audit" in sys.argv:
        audit()
    else:
        prepare()
