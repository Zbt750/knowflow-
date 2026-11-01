"""Read-only source-pack diff queue for one owned Phase 4.5H-U clone.

Only identifiers, field names and hashes are written to the private audit
report; question text and answers are never copied into the report.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PORT = 59227
SYSTEM_ID = "7694698872540080852"
REVISION = "f49d10c2a703"
FIELDS = ("question_type", "stem", "options", "correct_answer", "explanation")


def digest(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(raw.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    owner_dir = args.owner_dir.resolve()
    output = args.output_dir.resolve()
    audit_root = (ROOT / "storage/quality-audits").resolve()
    if not owner_dir.is_relative_to(audit_root) or not output.is_relative_to(audit_root):
        raise ValueError("private_audit_paths_required")
    if output.exists():
        raise ValueError("output_exists_refuse_overwrite")
    owner_state = json.loads((owner_dir / "owner.json").read_text(encoding="utf-8"))
    database = owner_state.get("database")
    if (owner_state.get("port") != PORT or owner_state.get("system_identifier") != SYSTEM_ID
            or owner_state.get("source_revision") != REVISION
            or not isinstance(database, str) or not database.startswith("phase45hu_")
            or not database.endswith("_test") or owner_state.get("development_5433_touched") is not False):
        raise ValueError("owned_hu_test_clone_required")

    from scripts import run_phase45i_agent_real as owner
    _, cluster, actual_port = owner.load_existing_owner()
    if actual_port != PORT or actual_port == 5433:
        raise ValueError("owned_isolated_cluster_required")
    started = owner.start_owned_database(cluster, actual_port)
    try:
        from psycopg import connect
        with connect(host="127.0.0.1", port=PORT, user="postgres", dbname="postgres",
                     connect_timeout=5) as connection:
            system_id = str(connection.execute("SELECT system_identifier FROM pg_control_system()").fetchone()[0])
        if system_id != SYSTEM_ID:
            raise ValueError("isolated_cluster_system_identifier_mismatch")

        url = f"postgresql+psycopg://postgres@127.0.0.1:{PORT}/{database}"
        import os
        os.environ.update(APP_ENV="test", DATABASE_URL=url, TEST_DATABASE_URL=url,
                          KAOYAN_OWNED_TEST_PORT=str(PORT), LLM_API_KEY="",
                          LLM_BASE_URL="http://127.0.0.1:9", LLM_MODEL="offline-audit",
                          PHASE45I_CLOSE_OFFLINE="1", PYTHONIOENCODING="utf-8")
        from scripts.phase45i_offline_guard import install
        install()
        from backend.models import import_models
        import_models()
        from backend.db import create_db_engine, create_session_factory
        from backend.models.learning import Question
        from backend.services.question_attestation import _subject, question_content_sha256
        from backend.services.quality_verifiers import verify_problem
        from scripts.run_question_repair_pilot import local_pack_registry
        from types import SimpleNamespace
        from sqlalchemy import text, select

        engine = create_db_engine(url)
        factory = create_session_factory(engine)
        try:
            with engine.connect() as connection:
                connection.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                live_database = connection.execute(text("SELECT current_database()")).scalar_one()
                connection.rollback()
            if revision != REVISION or live_database != database:
                raise ValueError("live_clone_revision_or_database_mismatch")

            registry, rejected_files = local_pack_registry(ROOT)
            rows = []
            differences = Counter()
            missing_reference = 0
            exact_exam_rows = 0
            with factory() as db:
                db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
                questions = list(db.scalars(select(Question).where(Question.bank_scope == "public").order_by(Question.id)))
                for question in questions:
                    provenance = (question.grading_config or {}).get("provenance") or {}
                    source = provenance.get("source") or {}
                    if source.get("source_type") != "exam":
                        continue
                    key = (_subject(source.get("subject")), str(source.get("year")), str(source.get("question_number")))
                    matches = {entry["fingerprint"]: entry
                               for entry in registry.get(provenance.get("key"), [])
                               if entry.get("fingerprint") == provenance.get("sha256")}
                    if len(matches) != 1:
                        missing_reference += 1
                        rows.append({"question_id": str(question.id), "source_identity": list(key),
                                     "source_key": provenance.get("key"),
                                     "source_fingerprint": provenance.get("sha256"),
                                     "status": "NO_UNIQUE_EXACT_PACK_REFERENCE"})
                        continue
                    exact_exam_rows += 1
                    # Identical copies of a pack record are one content identity;
                    # collapse them by fingerprint, as the source reconciliation does.
                    entry = next(iter(matches.values()))
                    packed = entry["question"]
                    fields = [field for field in FIELDS
                              if getattr(question, field, None) != getattr(packed, field, None)]
                    if fields:
                        differences.update(fields)
                        answer_review = None
                        if "correct_answer" in fields:
                            def verify_summary(candidate):
                                try:
                                    result = verify_problem(candidate)
                                    return {"status": result.get("status"), "adapter": result.get("adapter"),
                                            "reason": result.get("reason"),
                                            "derived_answer_sha256": digest(result.get("derived_answer"))
                                                if result.get("derived_answer") is not None else None}
                                except Exception as exc:
                                    return {"status": "ERROR", "error_type": type(exc).__name__}
                            pack_candidate = SimpleNamespace(question_type=packed.question_type,
                                stem=packed.stem, options=packed.options, correct_answer=packed.correct_answer)
                            current_check = verify_summary(question)
                            pack_check = verify_summary(pack_candidate)
                            same_problem_statement = all(
                                getattr(question, field, None) == getattr(packed, field, None)
                                for field in ("question_type", "stem", "options"))
                            if same_problem_statement and current_check["status"] == "PASS" and pack_check["status"] == "FAIL":
                                resolution = "CURRENT_ANSWER_SUPPORTED_PACK_ANSWER_CONFLICTS_WITH_SOLVER"
                            elif same_problem_statement and current_check["status"] == "FAIL" and pack_check["status"] == "PASS":
                                resolution = "PACK_ANSWER_SUPPORTED_CURRENT_ANSWER_CONFLICTS_WITH_SOLVER"
                            else:
                                resolution = "NO_AUTOMATIC_RESOLUTION"
                            answer_review = {"same_problem_statement_and_options": same_problem_statement,
                                "current_answer_verification": current_check,
                                "pack_answer_verification": pack_check,
                                "automatic_resolution": resolution}
                        rows.append({"question_id": str(question.id), "source_identity": list(key),
                                     "node_id": str(question.kp_id), "source_key": provenance.get("key"),
                                     "source_fingerprint": provenance.get("sha256"),
                                     "pack_id": entry.get("pack_id"), "pack_version": entry.get("pack_version"),
                                     "pack_file": Path(entry["path"]).resolve().relative_to(ROOT / "storage/question-intake").as_posix(),
                                     "fields_differing": fields,
                                     "question_content_sha256": question_content_sha256(question),
                                     "answer_explanation_sha256": digest({"answer": question.correct_answer,
                                                                           "explanation": question.explanation}),
                                     "pack_fingerprint": entry.get("fingerprint"),
                                     "answer_review": answer_review,
                                     "status": "DIFF_REVIEW_REQUIRED_NO_AUTO_OVERWRITE"})
                db.rollback()
        finally:
            engine.dispose()

        output.mkdir(parents=True)
        report = {"version": "phase45hu-live-source-diff-queue-v3", "database": database,
                  "port": PORT, "system_identifier": SYSTEM_ID, "revision": revision,
                  "read_only_transaction": True, "development_5433_touched": False, "paid_calls": 0,
                  "private_source_pack_rejected_files": len(rejected_files),
                  "public_question_rows": len(questions), "exactly_referenced_exam_rows": exact_exam_rows,
                  "exam_rows_without_unique_exact_pack_reference": missing_reference,
                  "rows_requiring_field_review": len(rows) - missing_reference,
                  "difference_field_occurrences": dict(differences), "items": rows,
                  "limits": ["Identical pack copies are deduplicated by content fingerprint.",
                             "Field differences are not proof of transcription error.",
                             "No question text or answer content is included.",
                             "No database write or qualification update was performed."]}
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        summary = {key: report[key] for key in ("version", "database", "port", "revision",
                   "read_only_transaction", "development_5433_touched", "paid_calls",
                   "public_question_rows", "exactly_referenced_exam_rows",
                   "exam_rows_without_unique_exact_pack_reference", "rows_requiring_field_review",
                   "difference_field_occurrences")}
        print(json.dumps(summary, ensure_ascii=False))
    finally:
        if started:
            owner.command([str(owner.PG_BIN / "pg_ctl.exe"), "-D", str(cluster), "-m", "fast",
                           "-w", "-t", "30", "stop"], timeout=40, check=False)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
