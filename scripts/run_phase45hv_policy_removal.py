"""Clone H-U's owned isolated database and remove graduation source quotas.

This runner is intentionally pinned to the audited PostgreSQL test cluster and
never derives a connection from application/dev settings. The source checkpoint
is template-cloned and left unchanged; all writes occur in a new private _test
database.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE_RUN_DEFAULT = ROOT / "storage/quality-audits/phase45hu-20261010-public-batch-12"
PORT = 59227
SYSTEM_ID = "7694698872540080852"
REVISION = "f49d10c2a703"
PROTECTED_TABLES = ("question_attempts", "learning_events", "kp_states", "questions",
                    "question_auto_review_events")


def save(path: Path, payload: object) -> None:
    temp = path.with_suffix(path.suffix + ".new")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temp.replace(path)


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str,
                      separators=(",", ":")).encode("utf-8")


def row_fingerprint(db, model) -> dict:
    from sqlalchemy import select
    rows = list(db.scalars(select(model)))
    cols = list(model.__table__.columns)
    pk = [column.key for column in model.__table__.primary_key.columns]
    rows.sort(key=lambda row: tuple(str(getattr(row, key)) for key in pk))
    payload = [{column.key: getattr(row, column.key) for column in cols} for row in rows]
    return {"count": len(rows), "sha256": sha256(_canonical(payload)).hexdigest()}


def policy_values(row) -> dict:
    from backend.services.graduation_policy_migration import policy_snapshot
    values = {column.key: getattr(row, column.key) for column in row.__table__.columns}
    return policy_snapshot(values)


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, default=SOURCE_RUN_DEFAULT)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    source_run, out = args.source_dir.resolve(), args.output_dir.resolve()
    private_root = ROOT / "storage/quality-audits"
    if not source_run.is_relative_to(private_root) or not out.is_relative_to(private_root):
        raise ValueError("private_isolated_audit_paths_required")
    if out.exists():
        raise ValueError("refuse_overwrite_existing_output_directory")
    out.mkdir(parents=True)

    from scripts import run_phase45i_agent_real as owner
    _, cluster, owned_port = owner.load_existing_owner()
    if owned_port != PORT or owned_port == 5433:
        raise ValueError("expected_owned_test_cluster_only")
    started = owner.start_owned_database(cluster, owned_port)
    result = {"phase": "4.5H-V-policy-source-quota-removal", "paid_calls": 0,
              "development_5433_touched": False, "source_run": str(source_run.relative_to(ROOT)),
              "port": PORT, "system_identifier_expected": SYSTEM_ID}
    try:
        from psycopg import connect, sql
        source_owner = json.loads((source_run / "owner.json").read_text(encoding="utf-8"))
        source_db = source_owner.get("database")
        if (source_owner.get("port") != PORT or source_owner.get("system_identifier") != SYSTEM_ID
                or source_owner.get("source_revision") != REVISION
                or not isinstance(source_db, str) or not source_db.startswith("phase45hu_")
                or not source_db.endswith("_test")):
            raise ValueError("audited_hu_source_owner_mismatch")
        with connect(host="127.0.0.1", port=PORT, user="postgres", dbname="postgres",
                     autocommit=True, connect_timeout=5) as server:
            actual_system_id = str(server.execute("SELECT system_identifier FROM pg_control_system()").fetchone()[0])
            if actual_system_id != SYSTEM_ID:
                raise ValueError("owned_cluster_system_identifier_mismatch")
            active = server.execute("SELECT count(*) FROM pg_stat_activity WHERE datname=%s", (source_db,)).fetchone()[0]
            if active:
                raise ValueError("source_checkpoint_has_active_connections_refuse_clone")
            with connect(host="127.0.0.1", port=PORT, user="postgres", dbname=source_db,
                         connect_timeout=5) as source:
                revision = source.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            if revision != REVISION:
                raise ValueError("source_schema_revision_mismatch")
            database = "phase45hv_" + uuid4().hex[:12] + "_test"
            server.execute(sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                sql.Identifier(database), sql.Identifier(source_db)))
        result.update(database=database, source_database=source_db, system_identifier=actual_system_id,
                      schema_revision=revision, source_unchanged=True)
        save(out / "owner.json", {"database": database, "source_database": source_db,
            "source_run": str(source_run), "port": PORT, "system_identifier": SYSTEM_ID,
            "source_revision": revision, "development_5433_touched": False, "paid_calls": 0,
            "created_at": datetime.now(timezone.utc).isoformat()})

        url = f"postgresql+psycopg://postgres@127.0.0.1:{PORT}/{database}"
        os.environ.update(APP_ENV="test", DATABASE_URL=url, TEST_DATABASE_URL=url,
            KAOYAN_OWNED_TEST_PORT=str(PORT), PHASE45I_CLOSE_OFFLINE="1",
            LLM_API_KEY="", LLM_BASE_URL="http://127.0.0.1:9", LLM_MODEL="offline",
            MODEL_SETTINGS_PATH=str(out / "model-settings.bin"), UPLOAD_DIR=str(out / "uploads"),
            CHROMA_DIR=str(out / "chroma"), PYTHONIOENCODING="utf-8")
        from scripts.phase45i_offline_guard import install
        install()
        from sqlalchemy import func, select, text
        from backend.models import import_models
        import_models()
        from backend.db import create_db_engine, create_session_factory
        from backend.models.learning import (KpMasteryPolicy, QuestionAttempt, LearningEvent,
            KpState, Question, QuestionAutoReviewEvent, KnowledgePoint)
        from backend.services.graduation_policy_migration import remove_exam_source_quotas
        from backend.mastery.storage import policy_from_storage
        from backend.services.public_bank_supply import supply_for_node
        from backend.services.question_eligibility import question_eligibility
        from backend.services.auto_question_review import current_auto_review

        engine = create_db_engine(url)
        factory = create_session_factory(engine)
        try:
            with factory() as db:
                actual_revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                if actual_revision != REVISION:
                    raise ValueError("clone_schema_revision_mismatch")
                protected = {name: row_fingerprint(db, model) for name, model in zip(PROTECTED_TABLES,
                    (QuestionAttempt, LearningEvent, KpState, Question, QuestionAutoReviewEvent))}
                policy_rows = list(db.scalars(select(KpMasteryPolicy).order_by(KpMasteryPolicy.kp_id)))
                before_by_id = {str(row.kp_id): policy_values(row) for row in policy_rows}
                origins_before = Counter()
                origin_rows_before = 0
                legacy_exam_type_rows = 0
                for row in policy_rows:
                    origins = dict(row.required_question_origins or {})
                    if origins:
                        origin_rows_before += 1
                        origins_before.update(origins)
                    if "external_exam" in (row.required_question_types or {}):
                        legacy_exam_type_rows += 1
                question_rows = list(db.scalars(select(Question).where(
                    Question.bank_scope == "public", Question.generation_batch_id.is_(None))))
                provenance_counts = Counter(q.question_provenance for q in question_rows)
                exam_identity = set()
                exam_year_counts = Counter()
                exam_subject_counts = Counter()
                exam_identity_by_provenance = Counter()
                exam_identity_rows_by_provenance = Counter()
                exam_duplicate_identity_rows = 0
                formal_by_class = Counter()
                for q in question_rows:
                    # Source identity and provenance are independent dimensions.
                    # Legacy rows may have a real exam source in their metadata
                    # while question_provenance remains legacy_unknown; count the
                    # identity on every public row instead of undercounting it.
                    config = q.grading_config if isinstance(q.grading_config, dict) else {}
                    prov = config.get("provenance") if isinstance(config.get("provenance"), dict) else {}
                    source = prov.get("source") if isinstance(prov.get("source"), dict) else {}
                    subject = str(source.get("subject") or "").strip()
                    year_raw = str(source.get("year") or "").strip()
                    number_raw = str(source.get("question_number") or "").strip()
                    year_match = re.search(r"20\d{2}", year_raw)
                    number_match = re.search(r"\d+", number_raw)
                    subject_key = ("math2" if subject in {"数学二", "考研数学", "math2"}
                                   else "408" if subject == "408" else subject)
                    if subject_key and year_match and number_match:
                        year = year_match.group(0)
                        identity = (subject_key, year, str(int(number_match.group(0))))
                        if identity in exam_identity:
                            exam_duplicate_identity_rows += 1
                        exam_identity.add(identity)
                        exam_year_counts[year] += 1
                        exam_subject_counts[subject_key] += 1
                        exam_identity_by_provenance[q.question_provenance or "unknown"] += 1
                        exam_identity_rows_by_provenance[q.question_provenance or "unknown"] += 1
                    node = db.get(KnowledgePoint, q.kp_id) if q.kp_id else None
                    if node is None:
                        continue
                    eligibility = question_eligibility(q, node)
                    if q.is_active and not q.is_hidden and eligibility.evidence_capability == "verified_objective":
                        review = current_auto_review(q, node)
                        formal_by_class[getattr(review, "qualification_class", None) or q.question_provenance] += 1
                before = {"revision": actual_revision, "policies": len(policy_rows),
                    "origin_quota_rows": origin_rows_before, "origin_quota_distribution": dict(origins_before),
                    "legacy_external_exam_type_rows": legacy_exam_type_rows,
                    "public_questions": len(question_rows),
                    "active_public_questions": sum(q.is_active for q in question_rows),
                    "question_provenance_counts": dict(provenance_counts),
                    "public_question_rows_with_exam_source_identity": sum(exam_identity_by_provenance.values()),
                    "public_unique_exam_source_identity_count": len(exam_identity),
                    "public_exam_identity_duplicate_rows": exam_duplicate_identity_rows,
                    "exam_source_identity_rows_by_question_provenance": dict(exam_identity_rows_by_provenance),
                    "exam_source_identity_rows_by_subject_field": dict(exam_subject_counts),
                    "exam_source_identity_rows_by_year": dict(exam_year_counts),
                    "currently_formal_eligible_by_review_class": dict(formal_by_class),
                    "protected_table_fingerprints": protected}
            save(out / "baseline.json", before)

            changed = 0
            migration_counts = Counter()
            now = datetime.now(timezone.utc)
            with factory() as db:
                policies = list(db.scalars(select(KpMasteryPolicy).order_by(KpMasteryPolicy.kp_id)))
                for row in policies:
                    current = policy_values(row)
                    target = remove_exam_source_quotas(current)
                    if target == current:
                        continue
                    if current["required_question_origins"]:
                        migration_counts["rows_cleared_origin_quotas"] += 1
                    if "external_exam" in current["required_question_types"]:
                        migration_counts["rows_removed_external_exam_type"] += 1
                        migration_counts["preserved_distinct_question_floor"] += int(
                            target["min_real_questions"] > current["min_real_questions"])
                    row.required_question_origins = target["required_question_origins"]
                    row.required_question_types = target["required_question_types"]
                    row.min_real_questions = target["min_real_questions"]
                    row.updated_at = now
                    changed += 1
                db.commit()
            migration_counts["policy_rows_mutated"] = changed

            # Idempotency and exact preservation checks.
            with factory() as db:
                after_rows = list(db.scalars(select(KpMasteryPolicy).order_by(KpMasteryPolicy.kp_id)))
                after_by_id = {str(row.kp_id): policy_values(row) for row in after_rows}
                if len(after_rows) != len(policy_rows):
                    raise ValueError("policy_count_changed")
                for kp_id, old in before_by_id.items():
                    new = after_by_id[kp_id]
                    expected = remove_exam_source_quotas(old)
                    if new != expected:
                        raise ValueError("policy_change_outside_guarded_source_quota_removal")
                    if new["min_confirmations"] != old["min_confirmations"]:
                        raise ValueError("min_confirmations_changed")
                    if new["min_day_span"] != old["min_day_span"]:
                        raise ValueError("min_day_span_changed")
                    if new["required_skill_tags"] != old["required_skill_tags"]:
                        raise ValueError("skill_requirements_changed")
                    if new["required_variant_count"] != old["required_variant_count"]:
                        raise ValueError("variant_requirement_changed")
                    if new["required_question_types"] != expected["required_question_types"]:
                        raise ValueError("question_type_requirement_changed_unexpectedly")
                    if new["min_real_questions"] < old["min_real_questions"]:
                        raise ValueError("distinct_question_floor_reduced")
                    if remove_exam_source_quotas(new) != new:
                        raise ValueError("migration_not_idempotent")
                after_protected = {name: row_fingerprint(db, model) for name, model in zip(PROTECTED_TABLES,
                    (QuestionAttempt, LearningEvent, KpState, Question, QuestionAutoReviewEvent))}
                if protected != after_protected:
                    raise ValueError("protected_history_or_question_content_changed")

                questions = list(db.scalars(select(Question)))
                nodes = {node.id: node for node in db.scalars(select(KnowledgePoint))}
                policies_by_node = {row.kp_id: row for row in after_rows}
                coverage = []
                for kp_id, row in policies_by_node.items():
                    node = nodes.get(kp_id)
                    if node is None:
                        continue
                    policy = policy_from_storage(row)
                    coverage.append(supply_for_node([q for q in questions if q.kp_id == kp_id], node, policy))
                coverage.sort(key=lambda item: item["code"])
                by_subject = {}
                for subject in sorted({item["subject"] for item in coverage}):
                    selected = [item for item in coverage if item["subject"] == subject]
                    by_subject[subject] = {
                        "policy_nodes": len(selected),
                        "nodes_with_formally_qualified_questions": sum(item["strict_eligible_raw"] > 0 for item in selected),
                        "nodes_with_complete_static_supply": sum(item["status"] == "CONDITIONAL_FUTURE_SUBMISSIONS" for item in selected),
                        "nodes_missing_distinct_trusted_questions": sum("DISTINCT_TRUSTED_QUESTION_SHORTAGE" in item["blocking_reasons"] for item in selected),
                        "nodes_blocked_by_other_requirements": sum(bool(item["blocking_reasons"]) for item in selected),
                    }
                totals = {"policy_nodes": len(coverage),
                    "nodes_with_formally_qualified_questions": sum(item["strict_eligible_raw"] > 0 for item in coverage),
                    "nodes_with_complete_static_supply": sum(item["status"] == "CONDITIONAL_FUTURE_SUBMISSIONS" for item in coverage),
                    "nodes_blocked_by_real_exam_origin_shortage": sum(any(r.startswith("ORIGIN_SHORTAGE:") for r in item["blocking_reasons"]) for item in coverage),
                    "public_question_count": len(question_rows),
                    "qualified_question_count": sum(item["strict_eligible_raw"] for item in coverage)}
                if any(row.required_question_origins for row in after_rows):
                    raise ValueError("source_origin_quota_remains_after_migration")
                if any("external_exam" in (row.required_question_types or {}) for row in after_rows):
                    raise ValueError("legacy_external_exam_type_quota_remains")
                report = {"phase": "4.5H-V-policy-source-quota-removal", "status": "ISOLATED_POLICY_MIGRATION_PASS",
                    "database": database, "source_database": source_db, "port": PORT,
                    "system_identifier": actual_system_id, "schema_revision": actual_revision,
                    "paid_calls": 0, "development_5433_touched": False,
                    "baseline": before, "migration": dict(migration_counts),
                    "policies_after": len(after_rows), "remaining_origin_quota_rows": 0,
                    "remaining_external_exam_type_quota_rows": 0,
                    "protected_table_fingerprints_after": after_protected,
                    "protected_data_unchanged": protected == after_protected,
                    "coverage_totals": totals, "coverage_by_subject": by_subject,
                    "coverage": coverage}
            save(out / "coverage.json", coverage)
            save(out / "report.json", report)
            result.update({key: value for key, value in report.items() if key != "coverage"})
            save(out / "run-summary.json", result)
            print(json.dumps({key: value for key, value in result.items() if key != "coverage"},
                             ensure_ascii=False, default=str))
        finally:
            engine.dispose()
    finally:
        if started:
            stopped = owner.command([str(owner.PG_BIN / "pg_ctl.exe"), "-D", str(cluster),
                "-m", "fast", "-w", "-t", "30", "stop"], timeout=40, check=False)
            result["owned_test_cluster_stopped"] = stopped.returncode == 0
            if out.exists():
                save(out / "run-summary.json", result)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
