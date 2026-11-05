"""Apply the authorized frozen SELECT-only script, then inspect real app READ ONLY."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from uuid import UUID
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TABLES = ("question_versions", "question_auto_review_events", "kp_graduation_question_set_versions", "personal_generation_batches")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply-select-grants", action="store_true", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    assert out.is_relative_to(ROOT / "storage/quality-audits") and not out.exists()
    out.mkdir(parents=True)
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "status": "STARTED", "authorized_change": "SELECT only on four public tables", "model_calls": 0}
    def save():
        (out / "permission-and-readonly-result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    from sqlalchemy import create_engine, select, text
    from sqlalchemy.orm import Session, joinedload
    from sqlalchemy.engine import make_url
    from backend.config import get_settings
    from backend.models import import_models
    from backend.models.learning import Question, QuestionVersion, KpMasteryPolicy, KpGraduationQuestionSetVersion, PracticeItem, QuestionAttempt
    from backend.services.auto_question_review import current_auto_review
    from backend.services.question_versions import version_snapshot_hash, question_for_practice_item, question_for_attempt
    from backend.services.graduation_question_set import assert_frozen_set_integrity
    from backend.mastery.storage import policy_from_storage
    from scripts.validate_phase45y_real_sync_api import _snapshot, _identity
    import_models()
    app_url = make_url(str(get_settings().active_database_url))
    assert (app_url.host, app_url.port, app_url.database, app_url.username) == ("127.0.0.1", 5433, "kaoyan", "kaoyan")
    owner_url = app_url.set(username="postgres", password="")
    ro = {"connect_timeout": 5, "options": "-c default_transaction_read_only=on"}
    admin_ro = create_engine(owner_url, connect_args=ro)
    engine = create_engine(app_url, connect_args=ro)
    try:
        with engine.connect() as c:
            report["identity"] = _identity(c)
        assert report["identity"]["system_identifier"] == "7686825087296682120"
        assert report["identity"]["revision"] == "f54c8a1d7e20"
        draft = ROOT / "eval/phase5-closeout-v1/database-select-grants.sql"
        manifest = json.loads((ROOT / "storage/quality-audits/phase5-closeout-preparation-20261015-v2/preparation.json").read_text(encoding="utf-8"))
        assert hashlib.sha256(draft.read_bytes()).hexdigest() == manifest["frozen_file_sha256"][draft.relative_to(ROOT).as_posix()]
        before = _snapshot(admin_ro)
        report["pre_business_fingerprints"] = before
        with admin_ro.connect() as c:
            report["acl_before"] = [dict(r) for r in c.execute(text("SELECT relname,relacl::text AS acl FROM pg_class WHERE relnamespace='public'::regnamespace AND relname=ANY(:names) ORDER BY relname"), {"names": list(TABLES)}).mappings()]
        save()
        import psycopg
        with psycopg.connect(owner_url.set(drivername="postgresql").render_as_string(hide_password=False), autocommit=True, connect_timeout=5) as connection:
            connection.execute(draft.read_text(encoding="utf-8"), prepare=False)
        report["grant_committed"] = True
        save()
        with engine.connect() as c:
            report["permissions_after"] = [dict(r) for r in c.execute(text("SELECT relname,has_table_privilege(current_user,oid,'SELECT') AS select_ok,has_table_privilege(current_user,oid,'INSERT,UPDATE,DELETE,TRUNCATE') AS any_write_privilege FROM pg_class WHERE relnamespace='public'::regnamespace AND relname=ANY(:names) ORDER BY relname"), {"names": list(TABLES)}).mappings()]
        assert len(report["permissions_after"]) == 4
        assert all(r["select_ok"] and not r["any_write_privilege"] for r in report["permissions_after"])
        with Session(engine, autoflush=False) as db:
            report["counts"] = {t: db.scalar(text(f'SELECT count(*) FROM public."{t}"')) for t in ("questions", "question_versions", "question_auto_review_events", "kp_graduation_question_set_versions", "question_attempts", "learning_events", "kp_states", "daily_plans", "practice_items")}
            assert report["counts"] == dict(questions=1935, question_versions=2322, question_auto_review_events=1804, kp_graduation_question_set_versions=254, question_attempts=28, learning_events=29, kp_states=284, daily_plans=10, practice_items=87)
            versions = list(db.scalars(select(QuestionVersion)))
            assert all(version_snapshot_hash(v.snapshot_json) == v.content_hash for v in versions)
            questions = list(db.scalars(select(Question).options(joinedload(Question.kp), joinedload(Question.current_auto_review))))
            assert all(q.current_version_id and db.get(QuestionVersion, q.current_version_id).question_id == q.id for q in questions)
            formal = {str(q.id) for q in questions if current_auto_review(q, q.kp) is not None}
            report["formal_count"] = len(formal)
            report["formal_by_subject"] = dict(Counter(q.kp.subject for q in questions if str(q.id) in formal))
            assert len(formal) == 1804
            policies = list(db.scalars(select(KpMasteryPolicy).where(KpMasteryPolicy.policy_version == 3, KpMasteryPolicy.graduation_set_version > 0)))
            members = []
            for p in policies:
                assert_frozen_set_integrity(db, policy_from_storage(p), kp_id=p.kp_id)
                archive = db.scalar(select(KpGraduationQuestionSetVersion).where(KpGraduationQuestionSetVersion.kp_id == p.kp_id, KpGraduationQuestionSetVersion.set_version == p.graduation_set_version))
                assert len(archive.question_ids) == len(archive.question_version_ids) > 0
                for qid, vid in zip(archive.question_ids, archive.question_version_ids):
                    q = db.get(Question, UUID(str(qid)))
                    assert str(q.current_version_id) == str(vid) and q.kp_id == p.kp_id
                    members.append(str(qid))
            assert len(policies) == 253 and len(members) == len(set(members)) == 1804 and set(members) == formal
            report.update(active_sets=len(policies), active_members=len(members))
            historical = []
            for item in db.scalars(select(PracticeItem).where(PracticeItem.question_id.is_not(None))):
                q = question_for_practice_item(db, item)
                v = db.get(QuestionVersion, item.question_version_id)
                assert q.stem == v.stem and q.correct_answer == v.correct_answer and q.explanation == v.explanation
                historical.append(str(item.id))
            attempts = list(db.scalars(select(QuestionAttempt)))
            for a in attempts:
                assert str(question_for_attempt(db, a).version_id) == str(a.question_version_id)
            report.update(historical_bound_items_checked=len(historical), historical_attempts_checked=len(attempts))
            old_plans = list(db.execute(text("SELECT DISTINCT plan_id::text FROM practice_items WHERE question_id IS NOT NULL ORDER BY plan_id::text")).scalars())
            node_id = str(policies[0].kp_id)
        from fastapi.testclient import TestClient
        from backend.app import create_app
        from backend.db import create_session_factory
        app = create_app()
        app.state.settings = get_settings()
        app.state.session_factory = create_session_factory(engine)
        # Deliberately no TestClient context: no lifespan/startup UPDATE/workers.
        client = TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False)
        routes = ["/api/health", "/api/plans/today", "/api/knowledge/tree", f"/api/knowledge/{node_id}", "/api/question-bank?scope=public&limit=2", "/api/question-bank?scope=personal&limit=2"]
        routes += [f"/api/plans/{plan_id}/items" for plan_id in old_plans]
        report["readonly_api"] = []
        for route in routes:
            response = client.get(route)
            record = {"route": route, "status": response.status_code}
            if response.status_code != 200:
                record["error"] = response.text[:1500]
            report["readonly_api"].append(record)
        client.close()
        after = _snapshot(engine)
        report["all_business_tables_unchanged"] = before == after
        report["post_business_fingerprints"] = after
        assert before == after
        assert all(r["status"] == 200 for r in report["readonly_api"])
        report["status"] = "SELECT_GRANTS_APPLIED_REAL_ROLE_READONLY_ACCEPTANCE_PASS"
    except Exception as exc:
        report["status"] = "STOPPED_AFTER_PERMISSION_CHECK_FAILURE"
        report["error_type"] = type(exc).__name__
        save()
        raise
    finally:
        save()
        engine.dispose()
        admin_ro.dispose()
    print(json.dumps({k: report[k] for k in ("status", "counts", "formal_count", "active_sets", "active_members", "all_business_tables_unchanged")}, ensure_ascii=True))


if __name__ == "__main__":
    main()
