"""Add an independently checked public-original batch to an audited clone.

The script clones the already audited Phase 4.5H-S isolated database on the
owned PostgreSQL test cluster. It never reads or connects to the Windows dev
database. Each question and qualification event commits in its own transaction;
progress and the resulting node-coverage report are private under storage/.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE_RUN = ROOT / "storage/quality-audits/phase45hs-20261010"
SYSTEM_ID = "7694698872540080852"
PORT = 59227


def save(path: Path, payload: object) -> None:
    temp = path.with_suffix(path.suffix + ".new")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temp.replace(path)


def row_fingerprint(db, table) -> dict:
    from sqlalchemy import text
    name = table.__tablename__
    quoted = db.bind.dialect.identifier_preparer.quote(name)
    rows = [dict(row) for row in db.execute(text(f"SELECT * FROM public.{quoted} ORDER BY 1")).mappings()]
    raw = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return {"count": len(rows), "sha256": sha256(raw).hexdigest()}


def candidate_targets(db):
    from sqlalchemy import select
    from backend.models.learning import KnowledgePoint
    from scripts.public_bank_originals import originals

    nodes = list(db.scalars(select(KnowledgePoint).where(
        KnowledgePoint.is_active.is_(True), KnowledgePoint.is_assessable.is_(True))))
    targets = []
    for family, keyword, output in originals():
        matches = [node for node in nodes if keyword in node.name and ".family." not in node.code]
        matches.sort(key=lambda node: (node.name != keyword, len(node.name), node.code))
        if not matches:
            targets.append({"family": family, "keyword": keyword, "status": "NO_NODE_MATCH"})
            continue
        node = matches[0]
        targets.append({"family": family, "keyword": keyword, "node_id": str(node.id),
            "node_code": node.code, "node_name": node.name, "subject": node.subject,
            "node_active": node.is_active, "node_assessable": node.is_assessable,
            "node_reference_only": node.is_reference_only, "output": output})
    return targets


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, default=SOURCE_RUN,
        help="audited isolated H-S/H-U checkpoint under storage/quality-audits")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    out = args.output_dir.resolve()
    source_run = args.source_dir.resolve()
    if not out.is_relative_to(ROOT / "storage/quality-audits"):
        raise ValueError("private_audit_output_required")
    if not source_run.is_relative_to(ROOT / "storage/quality-audits"):
        raise ValueError("private_audit_source_required")
    owner_path = out / "owner.json"
    if not args.resume:
        if out.exists():
            raise ValueError("output_directory_exists_refuse_overwrite")
        out.mkdir(parents=True)

    from scripts import run_phase45i_agent_real as owner
    _, cluster, port = owner.load_existing_owner()
    if port != PORT or port == 5433:
        raise ValueError("owned_isolated_cluster_required")
    started = owner.start_owned_database(cluster, port)
    try:
        from psycopg import connect, sql
        if args.resume:
            state = json.loads(owner_path.read_text(encoding="utf-8"))
            database = state["database"]
            if (state.get("port") != PORT or not database.startswith("phase45hu_")
                    or not database.endswith("_test") or state.get("source_run") != str(source_run)):
                raise ValueError("resume_owner_mismatch")
        else:
            source_state = json.loads((source_run / "owner.json").read_text(encoding="utf-8"))
            source_database = source_state.get("database")
            if (source_state.get("port") != PORT or source_state.get("system_identifier") != SYSTEM_ID
                    or not isinstance(source_database, str) or not source_database.endswith("_test")
                    or not source_database.startswith(("phase45hs_", "phase45hu_"))):
                raise ValueError("audited_isolated_source_owner_mismatch")
            database = "phase45hu_" + uuid4().hex[:12] + "_test"
            with connect(host="127.0.0.1", port=PORT, user="postgres", dbname="postgres",
                         autocommit=True, connect_timeout=5) as connection:
                actual = str(connection.execute("SELECT system_identifier FROM pg_control_system()").fetchone()[0])
                if actual != SYSTEM_ID:
                    raise ValueError("isolated_cluster_system_identifier_mismatch")
                active = connection.execute(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname = %s", (source_database,)
                ).fetchone()[0]
                if active:
                    raise ValueError("source_isolated_db_has_active_connections_refuse_clone")
                # Connect to source explicitly to validate the schema revision.
                with connect(host="127.0.0.1", port=PORT, user="postgres", dbname=source_database,
                             connect_timeout=5) as source_connection:
                    revision = source_connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
                if revision != "f49d10c2a703":
                    raise ValueError("source_hs_revision_mismatch")
                connection.execute(sql.SQL("CREATE DATABASE {} TEMPLATE {}")
                    .format(sql.Identifier(database), sql.Identifier(source_database)))
            state = {"database": database, "source_database": source_database,
                     "source_run": str(source_run), "port": PORT,
                     "system_identifier": SYSTEM_ID, "source_revision": revision,
                     "development_5433_touched": False, "paid_calls": 0,
                     "created_at": datetime.now(timezone.utc).isoformat()}
            save(owner_path, state)

        url = f"postgresql+psycopg://postgres@127.0.0.1:{PORT}/{database}"
        os.environ.update(APP_ENV="test", DATABASE_URL=url, TEST_DATABASE_URL=url,
            KAOYAN_OWNED_TEST_PORT=str(PORT), PHASE45I_CLOSE_OFFLINE="1",
            LLM_API_KEY="", LLM_BASE_URL="http://127.0.0.1:9", LLM_MODEL="offline",
            MODEL_SETTINGS_PATH=str(out / "model-settings.bin"), UPLOAD_DIR=str(out / "uploads"),
            CHROMA_DIR=str(out / "chroma"), PYTHONIOENCODING="utf-8")
        from scripts.phase45i_offline_guard import install
        install()
        from backend.models import import_models
        import_models()
        from backend.db import create_db_engine, create_session_factory
        from backend.models.learning import (Question, KnowledgePoint, KpMasteryPolicy,
            QuestionAutoReviewEvent, QuestionAttempt, LearningEvent, KpState)
        from backend.mastery.storage import policy_from_storage
        from backend.services.auto_question_review import qualify_public_question, question_snapshot_sha256
        from backend.services.question_generation import assess_output
        from sqlalchemy import select

        engine = create_db_engine(url)
        factory = create_session_factory(engine)
        try:
            with factory() as db:
                revision = db.execute(__import__("sqlalchemy").text("SELECT version_num FROM alembic_version")).scalar_one()
                if revision != "f49d10c2a703":
                    raise ValueError("clone_revision_mismatch")
                protected_before = {model.__tablename__: row_fingerprint(db, model)
                    for model in (QuestionAttempt, LearningEvent, KpState, KpMasteryPolicy)}
                target_rows = candidate_targets(db)
                policies = {str(p.kp_id): p for p in db.scalars(select(KpMasteryPolicy))}
                node_rows = {str(n.id): n for n in db.scalars(select(KnowledgePoint))}
                before_question_count = db.scalar(select(__import__("sqlalchemy").func.count()).select_from(Question))
                public_rows = list(db.scalars(select(Question).where(Question.bank_scope == "public")))
                before_audit = {"revision": revision, "question_count": before_question_count,
                    "public_question_count": len(public_rows), "protected_history": protected_before,
                    "policies": len(policies), "knowledge_points": len(node_rows)}
            save(out / "baseline.json", before_audit)

            progress_path = out / "progress.json"
            progress = json.loads(progress_path.read_text(encoding="utf-8")) if args.resume and progress_path.exists() else {"rows": []}
            done = {row["family"] for row in progress["rows"]}
            for target in target_rows:
                if target.get("family") in done or target.get("status") == "NO_NODE_MATCH":
                    continue
                from sqlalchemy import func, text
                node = node_rows[target["node_id"]]
                request_id = f"phase45hu-offline-original:{target['family']}:{target['node_code']}"
                candidate = assess_output(target["output"], node, request_id=request_id, mode="original",
                    family=target["family"], trace={"model": "codex_offline_authoring",
                    "prompt_version": "phase45hu-codex-offline-v1", "mode": "codex_offline", "model_calls": 0},
                    difficulty="basic", skill_tags=[node.name])
                row = {key: value for key, value in target.items() if key != "output"}
                row.update({"request_id": request_id, "authoring_mode": "codex_offline",
                    "generation_status": candidate["status"], "generation_errors": candidate["errors"],
                    "independent_verification": candidate.get("question").grading_config.get("generation", {}).get("independent_verification")
                        if candidate.get("question") else None})
                if candidate["status"] != "AUTO_PASS":
                    row["result"] = "NOT_SAVED_GENERATION_QUALITY_GATE"
                    progress["rows"].append(row); save(progress_path, progress); continue
                q = candidate["question"]
                # Some exact solver families produce a proof trace that is
                # richer than the arithmetic-step checker can express. Bind a
                # deterministic, versioned explanation rendered from that
                # allowlisted proof instead of lowering the explanation gate.
                generation = (q.grading_config or {}).get("generation")
                independent = (generation or {}).get("independent_verification")
                from backend.services.auto_question_review import bind_solver_rendered_generation_explanation
                if not isinstance(generation, dict):
                    raise ValueError("generation_record_missing_after_auto_pass")
                explanation_evidence = bind_solver_rendered_generation_explanation(q, independent or {})
                if explanation_evidence is not None:
                    row["explanation_evidence"] = explanation_evidence
                try:
                    with factory() as db:
                        existing = db.get(Question, q.id)
                        if existing is not None:
                            row.update(result="ALREADY_PRESENT", question_id=str(q.id))
                        else:
                            db.add(q); db.flush()
                            snapshot_sha = question_snapshot_sha256(q)
                            event, review = qualify_public_question(db, question_id=q.id, node_id=node.id,
                                expected_snapshot_sha256=snapshot_sha,
                                idempotency_key=f"phase45hu-auto:{q.id}:{snapshot_sha}")
                            row.update(question_id=str(q.id), qualification_status=review.get("status"),
                                qualification_stages=review.get("stages"),
                                qualification_class=review.get("qualification_class"))
                            if event is None:
                                db.rollback()
                                row.update(result="NOT_SAVED_QUALIFICATION_GATE", review_reason=review.get("reason"))
                            else:
                                db.commit()
                                row.update(result="INSERTED_AUTO_VERIFIED", event_id=str(event.id),
                                    question_snapshot_sha256=event.question_snapshot_sha256,
                                    answer_sha256=event.answer_sha256)
                except Exception as exc:
                    row.update(result="TRANSACTION_ERROR_NOT_SAVED", error_type=type(exc).__name__, error=str(exc)[:240])
                progress["rows"].append(row)
                save(progress_path, progress)

            with factory() as db:
                questions = list(db.scalars(select(Question)))
                policies_by_node = {p.kp_id: p for p in db.scalars(select(KpMasteryPolicy))}
                from backend.services.public_bank_supply import supply_for_node
                coverage = [supply_for_node([q for q in questions if q.kp_id == node.id], node,
                    policy_from_storage(policies_by_node[node.id]))
                    for node in db.scalars(select(KnowledgePoint)) if node.id in policies_by_node]
                protected_after = {model.__tablename__: row_fingerprint(db, model)
                    for model in (QuestionAttempt, LearningEvent, KpState, KpMasteryPolicy)}
                totals = {"questions_total": len(questions),
                    "public_questions": sum(q.bank_scope == "public" and not q.generation_batch_id for q in questions),
                    "public_formally_qualified": sum(q.bank_scope == "public" and not q.generation_batch_id
                        and q.content_trust == "auto_verified" and q.auto_review_event_id is not None for q in questions),
                    "policies": len(policies_by_node),
                    "nodes_with_qualified_practice": sum(item["strict_eligible_raw"] > 0 for item in coverage),
                    "nodes_meeting_static_supply": sum(item["status"] == "CONDITIONAL_FUTURE_SUBMISSIONS" for item in coverage),
                    "required_real_exam_policy_count": sum(bool(item["policy"]["required_question_origins"].get("real_exam")) for item in coverage),
                    "origin_quota_shortage_count": sum("ORIGIN_SHORTAGE:real_exam" in item["blocking_reasons"] for item in coverage)}
            history_ok = protected_before == protected_after
            report = {"phase": "4.5H-U-isolated-expansion", "status": "ISOLATED_BATCH_COMPLETE_WITH_REMAINING_COVERAGE_GAPS",
                "source_run": str(source_run.relative_to(ROOT)), "database": database, "port": PORT,
                "system_identifier": SYSTEM_ID, "source_revision": revision, "paid_calls": 0,
                "development_5433_touched": False, "baseline": before_audit, "candidates": progress["rows"],
                "new_inserted_count": sum(r.get("result") == "INSERTED_AUTO_VERIFIED" for r in progress["rows"]),
                "duplicate_or_gate_blocked_count": sum(r.get("result") == "NOT_SAVED_QUALIFICATION_GATE" for r in progress["rows"]),
                "generation_rejected_count": sum(r.get("result") == "NOT_SAVED_GENERATION_QUALITY_GATE" for r in progress["rows"]),
                "totals": totals, "protected_history_before": protected_before,
                "protected_history_after": protected_after, "protected_history_unchanged": history_ok,
                "coverage": coverage}
            if not history_ok:
                raise ValueError("protected_attempt_learning_state_or_policy_fingerprint_changed")
            save(out / "coverage.json", coverage)
            save(out / "report.json", report)
            print(json.dumps({key: value for key, value in report.items() if key != "coverage"},
                ensure_ascii=False, default=str), flush=True)
        finally:
            engine.dispose()
    finally:
        if started:
            owner.command([str(owner.PG_BIN / "pg_ctl.exe"), "-D", str(cluster), "-m", "fast",
                "-w", "-t", "30", "stop"], timeout=40, check=False)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
