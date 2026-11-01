"""Run a rollback-only real-database API smoke test for Phase 4.5Y-FINAL.

The application lifespan is intentionally bypassed so it cannot start background
jobs or perform unrelated startup maintenance. All request sessions join one
outer PostgreSQL transaction; the outer transaction is always rolled back.
"""
from __future__ import annotations

import hashlib
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(ROOT))

TARGET_URL = "postgresql+psycopg://postgres@127.0.0.1:5433/kaoyan"
EXPECTED_SYSTEM_ID = "7686825087296682120"
EXPECTED_REVISION = "f54c8a1d7e20"
OUT_PATH = ROOT / "storage/quality-audits/final-real-sync/real-api-rollback-smoke.json"


def _quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _snapshot(engine: Engine) -> dict[str, dict[str, Any]]:
    """Hash every public base-table row in deterministic PK order."""
    result: dict[str, dict[str, Any]] = {}
    with engine.connect() as conn:
        tx = conn.begin()
        conn.exec_driver_sql("SET TRANSACTION READ ONLY")
        inspector = inspect(conn)
        for table in sorted(inspector.get_table_names(schema="public")):
            pks = inspector.get_pk_constraint(table, schema="public").get("constrained_columns") or []
            order = ", ".join(f"t.{_quote(col)}" for col in pks) if pks else "payload"
            rows = conn.execute(text(
                f"SELECT to_jsonb(t)::text AS payload FROM public.{_quote(table)} t ORDER BY {order}"
            )).scalars()
            digest = hashlib.sha256()
            count = 0
            for payload in rows:
                digest.update(payload.encode("utf-8"))
                digest.update(b"\n")
                count += 1
            result[table] = {"rows": count, "sha256": digest.hexdigest()}
        tx.rollback()
    return result


def _identity(conn) -> dict[str, Any]:
    row = conn.execute(text("""
        SELECT current_database() AS database, inet_server_addr()::text AS host,
               inet_server_port() AS port, current_setting('server_version') AS server_version,
               (SELECT version_num FROM alembic_version) AS revision,
               (SELECT system_identifier::text FROM pg_control_system()) AS system_identifier
    """)).mappings().one()
    return dict(row)


def _count(conn, table: str) -> int:
    if table not in {
        "daily_plans", "practice_items", "question_attempts", "learning_events", "kp_states"
    }:
        raise ValueError(f"unexpected_count_table:{table}")
    return int(conn.execute(text(f"SELECT count(*) FROM public.{_quote(table)}")).scalar_one())


def _choose_node(session: Session) -> tuple[Any, list[str], str]:
    from backend.models.learning import KpMasteryPolicy, KpState, KnowledgePoint, QuestionVersion

    candidates = list(session.execute(
        select(KpState, KnowledgePoint, KpMasteryPolicy)
        .join(KnowledgePoint, KnowledgePoint.id == KpState.kp_id)
        .join(KpMasteryPolicy, KpMasteryPolicy.kp_id == KpState.kp_id)
        .where(
            KpState.graduation_set_binding_status == "unstarted",
            KpState.graduation_set_version.is_(None),
            KpMasteryPolicy.policy_version == 3,
            KpMasteryPolicy.graduation_set_version > 0,
            KnowledgePoint.is_active.is_(True),
            KnowledgePoint.is_assessable.is_(True),
        )
    ))
    viable: list[tuple[int, int, Any, list[str], str]] = []
    for state, node, policy in candidates:
        qids = [str(qid) for qid in (policy.graduation_question_ids or [])]
        if len(qids) < 6:
            continue
        versions = list(session.scalars(select(QuestionVersion).where(
            QuestionVersion.question_id.in_([UUID(qid) for qid in qids])
        )))
        objective = [version for version in versions
                     if version.question_type in {"single_choice", "fill_blank"}
                     and version.correct_answer and version.grading_mode]
        if not objective:
            continue
        viable.append((len(objective), len(qids), state, qids, str(node.code)))
    if not viable:
        raise RuntimeError("no_unstarted_node_with_reliable_objective_set")
    viable.sort(key=lambda item: (-item[0], -item[1], item[4]))
    _, _, state, qids, code = viable[0]
    return state, qids, code


def main() -> None:
    from fastapi.testclient import TestClient
    from backend.api.deps import get_db, get_time_provider
    from backend.app import create_app
    from backend.models.learning import PracticeItem, Question, QuestionVersion
    from backend.services.question_versions import question_for_practice_item

    os.environ["APP_ENV"] = "dev"
    os.environ["DATABASE_URL"] = TARGET_URL
    os.environ.pop("TEST_DATABASE_URL", None)
    engine = create_engine(TARGET_URL, pool_pre_ping=True, connect_args={"connect_timeout": 5})
    pre_api_snapshot = _snapshot(engine)
    report: dict[str, Any] = {
        "status": "RUNNING",
        "database_identity": None,
        "pre_api_counts": {},
        "api_checks": {},
        "persisted_changes": False,
    }
    connection = engine.connect()
    root_tx = connection.begin()
    try:
        identity = _identity(connection)
        report["database_identity"] = identity
        if (identity["database"] != "kaoyan" or identity["host"].split("/")[0] != "127.0.0.1"
                or int(identity["port"]) != 5433 or identity["system_identifier"] != EXPECTED_SYSTEM_ID
                or identity["revision"] != EXPECTED_REVISION):
            raise RuntimeError(f"real_api_target_identity_mismatch:{identity}")
        count_tables = ("daily_plans", "practice_items", "question_attempts", "learning_events", "kp_states")
        report["pre_api_counts"] = {table: _count(connection, table) for table in count_tables}

        from backend.models.learning import KpState
        with Session(bind=connection, autoflush=False, expire_on_commit=False,
                     join_transaction_mode="create_savepoint") as selection_session:
            chosen_state, graduation_qids, node_code = _choose_node(selection_session)
            kp_id = str(chosen_state.kp_id)
            objective_versions = list(selection_session.scalars(select(QuestionVersion).where(
                QuestionVersion.question_id.in_([UUID(qid) for qid in graduation_qids]),
                QuestionVersion.question_type.in_(["single_choice", "fill_blank"]),
            )))
            if not objective_versions:
                raise RuntimeError("selected_set_lost_objective_version")
            fallback_question_id = str(objective_versions[0].question_id)
            historical_item = selection_session.scalar(
                select(PracticeItem)
                .join(Question, Question.id == PracticeItem.question_id)
                .join(QuestionVersion, QuestionVersion.id == PracticeItem.question_version_id)
                .where(
                    PracticeItem.question_id.is_not(None),
                    PracticeItem.question_version_id.is_not(None),
                    Question.current_version_id.is_not(None),
                    PracticeItem.question_version_id != Question.current_version_id,
                    QuestionVersion.correct_answer.is_not(None),
                )
                .order_by(PracticeItem.created_at, PracticeItem.id)
                .limit(1)
            )
            if historical_item is None:
                raise RuntimeError("no_real_historical_item_with_pre_merge_question_version")
            historical_plan_id = str(historical_item.plan_id)
            historical_item_id = str(historical_item.id)
            historical_version_id = str(historical_item.question_version_id)
            historical_question = question_for_practice_item(selection_session, historical_item)
            historical_stem = historical_question.stem
            historical_explanation = historical_question.explanation
            historical_answer = historical_question.correct_answer

        # Avoid colliding with today's real plan. This fixed Shanghai-local date
        # is used only inside the rollback-only transaction.
        used_dates = set(connection.execute(text("SELECT study_date FROM daily_plans")).scalars())
        fixed_now = next(
            datetime(2040, 5, 20, 12, tzinfo=timezone.utc) + timedelta(days=offset)
            for offset in range(4000)
            if (datetime(2040, 5, 20, 12, tzinfo=timezone.utc) + timedelta(days=offset))
            .astimezone(timezone(timedelta(hours=8))).date().isoformat() not in used_dates
        )
        clock = {"now": fixed_now}

        @asynccontextmanager
        async def no_database_lifespan(app):
            yield

        app = create_app()
        app.router.lifespan_context = no_database_lifespan

        def rollback_only_db(request: Request):
            with Session(bind=connection, autoflush=False, expire_on_commit=False,
                         join_transaction_mode="create_savepoint") as session:
                try:
                    yield session
                except Exception:
                    session.rollback()
                    raise

        app.dependency_overrides[get_db] = rollback_only_db
        app.dependency_overrides[get_time_provider] = lambda: (lambda: clock["now"])

        # The local-dev middleware deliberately rejects non-loopback client
        # addresses. TestClient's default peer name is "testclient", which
        # does not represent the actual Windows loopback browser/API caller.
        with TestClient(
            app,
            base_url="http://127.0.0.1",
            client=("127.0.0.1", 50123),
        ) as client:
            historical_plan = client.get(f"/api/plans/{historical_plan_id}/items")
            if historical_plan.status_code != 200:
                raise RuntimeError(f"historical_plan_read_failed:{historical_plan.status_code}:{historical_plan.text[:400]}")
            old_item_view = next((item for item in historical_plan.json().get("items", [])
                                  if item.get("id") == historical_item_id), None)
            if (old_item_view is None or old_item_view.get("question_version_id") != historical_version_id
                    or old_item_view.get("stem") != historical_stem):
                raise RuntimeError("historical_plan_item_did_not_read_bound_old_question_version")
            historical_answer_response = client.get(f"/api/practice-items/{historical_item_id}/answer")
            if historical_answer_response.status_code != 200:
                raise RuntimeError(f"historical_answer_read_failed:{historical_answer_response.status_code}")
            historical_answer_body = historical_answer_response.json()
            if (historical_answer_body.get("question_version_id") != historical_version_id
                    or historical_answer_body.get("correct_answer") != historical_answer
                    or historical_answer_body.get("explanation") != historical_explanation):
                raise RuntimeError("historical_answer_or_explanation_did_not_read_bound_old_question_version")
            report["api_checks"]["historical_old_question_version"] = {
                "status": "PASS",
                "practice_item_id": historical_item_id,
                "question_id": str(historical_item.question_id),
                "bound_version_id": historical_version_id,
                "current_version_differs": True,
                "stem_answer_explanation_bound_to_old_version": True,
            }

            setup = client.get("/api/plans/today")
            if setup.status_code != 200 or setup.json().get("status") != "setup":
                raise RuntimeError(f"today_setup_failed:{setup.status_code}:{setup.text[:400]}")
            report["api_checks"]["get_today_setup"] = {"status_code": setup.status_code}

            generated = client.post("/api/plans/today/generate", json={
                "selected_kp_ids": [kp_id], "budget": "light",
            })
            if generated.status_code != 201:
                raise RuntimeError(f"plan_generation_failed:{generated.status_code}:{generated.text[:500]}")
            plan_body = generated.json()
            plan_id = plan_body["plan_id"]
            items = plan_body.get("items", [])
            if not items:
                raise RuntimeError("generated_plan_has_no_items")

            objective_item = next((item for item in items
                                   if item.get("question_type") in {"single_choice", "fill_blank"}), None)
            if objective_item is None:
                append = client.post(f"/api/plans/{plan_id}/questions", json={
                    "question_ids": [fallback_question_id],
                })
                if append.status_code != 200:
                    raise RuntimeError(f"append_objective_question_failed:{append.status_code}:{append.text[:500]}")
                plan_body = append.json()
                items = plan_body.get("items", [])
                objective_item = next((item for item in items if item.get("question_id") == fallback_question_id), None)
            if objective_item is None:
                raise RuntimeError("no_objective_item_in_generated_plan")
            item_id = objective_item["id"]

            item_answer = client.get(f"/api/practice-items/{item_id}/answer")
            if item_answer.status_code != 200:
                raise RuntimeError(f"answer_read_failed:{item_answer.status_code}:{item_answer.text[:400]}")
            answer_body = item_answer.json()
            answer = answer_body.get("correct_answer")
            qtype = answer_body.get("question_type")
            if not answer or qtype not in {"single_choice", "fill_blank"}:
                raise RuntimeError("selected_objective_answer_missing")
            if not isinstance(answer_body.get("explanation"), str) or not answer_body["explanation"].strip():
                raise RuntimeError("new_question_explanation_unavailable")
            version_binding = connection.execute(text("""
                SELECT pi.question_version_id::text AS practice_version_id,
                       q.current_version_id::text AS current_version_id,
                       v.id::text AS referenced_version_id
                  FROM practice_items pi
                  JOIN questions q ON q.id=pi.question_id
                  JOIN question_versions v ON v.id=pi.question_version_id
                 WHERE pi.id=:item_id
            """), {"item_id": item_id}).mappings().one()
            if (version_binding["practice_version_id"] != answer_body.get("question_version_id")
                    or version_binding["practice_version_id"] != version_binding["current_version_id"]
                    or version_binding["referenced_version_id"] != version_binding["current_version_id"]):
                raise RuntimeError("new_plan_did_not_bind_current_question_version")
            if qtype == "single_choice":
                answer_request = {"selected_option": str(answer).strip().upper()}
            else:
                answer_request = {"raw_answer": str(answer)}
            answer_request.update({"idempotency_key": "phase45y-final-live-smoke-20261014", "confidence": "certain"})
            submission = client.post(
                f"/api/practice-items/{item_id}/answer-submissions", json=answer_request
            )
            if submission.status_code != 200:
                raise RuntimeError(f"answer_submission_failed:{submission.status_code}:{submission.text[:500]}")
            submission_body = submission.json()
            if submission_body.get("result") != "right":
                raise RuntimeError(f"known_answer_not_graded_right:{submission_body}")
            if submission_body.get("question_version_id") != answer_body.get("question_version_id"):
                raise RuntimeError("attempt_question_version_binding_mismatch")
            history = client.get(f"/api/practice-items/{item_id}/answer-submissions")
            if history.status_code != 200 or len(history.json().get("items", [])) != 1:
                raise RuntimeError(f"answer_history_failed:{history.status_code}:{history.text[:400]}")
            persisted_item = client.get(f"/api/plans/{plan_id}/items")
            if persisted_item.status_code != 200:
                raise RuntimeError(f"plan_restore_failed:{persisted_item.status_code}")
            if plan_body.get("completed_count", 0) >= plan_body.get("total_count", 999):
                raise RuntimeError("single_submission_unexpectedly_completed_plan")
            report["api_checks"]["generate_submit_answer_parse_history"] = {
                "generate_status_code": generated.status_code,
                "plan_item_count": len(items),
                "question_type": qtype,
                "answer_status_code": item_answer.status_code,
                "explanation_returned": bool(answer_body.get("explanation")),
                "submission_status_code": submission.status_code,
                "submission_result": submission_body.get("result"),
                "question_version_bound": True,
                "history_count": len(history.json().get("items", [])),
                "same_day_plan_restore": persisted_item.status_code == 200,
            }

            clock["now"] = fixed_now + timedelta(days=1)
            next_day = client.get("/api/plans/today")
            if next_day.status_code != 200 or next_day.json().get("status") != "setup":
                raise RuntimeError(f"next_day_recommendation_failed:{next_day.status_code}:{next_day.text[:400]}")
            recommendations = next_day.json().get("recommendations", [])
            recommended = any(item.get("kp_id") == kp_id for item in recommendations)
            if not recommended:
                raise RuntimeError("tested_node_missing_from_next_day_agent_recommendations")
            report["api_checks"]["next_day_agent_recommendations"] = {
                "status_code": next_day.status_code,
                "recommendation_count": len(recommendations),
                "tested_node_recommended": recommended,
            }

        report["test_node_code"] = node_code
        report["transaction_attempt_rows"] = _count(connection, "question_attempts")
        report["transaction_learning_event_rows"] = _count(connection, "learning_events")
        state = connection.execute(text(
            "SELECT state, mastered_at FROM kp_states WHERE kp_id=:kp_id"
        ), {"kp_id": kp_id}).mappings().one()
        report["api_checks"]["no_graduation_from_one_test_item"] = {
            "state": state["state"], "mastered_at": state["mastered_at"],
            "not_graduated": state["mastered_at"] is None,
        }
        root_tx.rollback()
        after_api_snapshot = _snapshot(engine)
        report["persisted_changes"] = pre_api_snapshot != after_api_snapshot
        report["post_rollback_snapshot_equal"] = pre_api_snapshot == after_api_snapshot
        report["status"] = "REAL_API_ROLLBACK_SMOKE_PASS" if report["post_rollback_snapshot_equal"] else "REAL_API_ROLLBACK_SMOKE_FAIL"
        if not report["post_rollback_snapshot_equal"]:
            report["persisted_snapshot_mismatches"] = sorted(
                table for table in set(pre_api_snapshot) | set(after_api_snapshot)
                if pre_api_snapshot.get(table) != after_api_snapshot.get(table)
            )
    except Exception as exc:
        if root_tx.is_active:
            root_tx.rollback()
        report["status"] = "REAL_API_ROLLBACK_SMOKE_FAIL"
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if root_tx.is_active:
            root_tx.rollback()
        connection.close()
        engine.dispose()

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    if report["status"] != "REAL_API_ROLLBACK_SMOKE_PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
