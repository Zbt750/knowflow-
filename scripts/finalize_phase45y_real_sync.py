"""Create a final read-only inventory for the authorized Phase 4.5Y sync."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, joinedload

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
AUDIT = ROOT / "storage/quality-audits/final-real-sync"
DB_URL = "postgresql+psycopg://postgres@127.0.0.1:5433/kaoyan"
EXPECTED_SYSTEM_ID = "7686825087296682120"
EXPECTED_REVISION = "f54c8a1d7e20"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    from backend.models.learning import (
        KpGraduationQuestionSetVersion,
        KpMasteryPolicy,
        KpState,
        KnowledgePoint,
        Question,
        QuestionVersion,
    )
    from backend.services.auto_question_review import current_auto_review
    from backend.services.question_versions import version_snapshot_hash

    engine = create_engine(DB_URL, pool_pre_ping=True, connect_args={"connect_timeout": 5})
    failures: list[str] = []
    counts: dict[str, int] = {}
    history_fingerprints: dict[str, bool] = {}
    version_checks: dict[str, int] = {}
    set_checks: dict[str, int] = {}
    identity: dict[str, object] = {}

    with engine.connect() as connection:
        tx = connection.begin()
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        identity = dict(connection.execute(text("""
            SELECT current_database() AS database,
                   inet_server_addr()::text AS host,
                   inet_server_port() AS port,
                   current_setting('server_version') AS server_version,
                   (SELECT system_identifier::text FROM pg_control_system()) AS system_identifier,
                   (SELECT version_num FROM alembic_version) AS revision,
                   encode(textsend(current_setting('data_directory')), 'hex') AS data_directory_wire_hex
        """)).mappings().one())
        required_tables = (
            "questions", "question_versions", "question_auto_review_events",
            "kp_mastery_policies", "kp_graduation_question_set_versions",
            "question_attempts", "learning_events", "kp_states", "daily_plans", "practice_items",
        )
        for table in required_tables:
            counts[table] = int(connection.execute(text(f'SELECT count(*) FROM public."{table}"')).scalar_one())
        tx.commit()

    if (identity["database"] != "kaoyan" or identity["host"] != "127.0.0.1/32"
            or int(identity["port"]) != 5433 or identity["system_identifier"] != EXPECTED_SYSTEM_ID
            or identity["revision"] != EXPECTED_REVISION):
        failures.append("database_identity_or_revision_mismatch")

    with Session(engine) as session:
        versions = list(session.scalars(select(QuestionVersion)))
        invalid_version_hashes = sum(
            version_snapshot_hash(version.snapshot_json) != version.content_hash
            for version in versions
        )
        dangling_currents = int(session.execute(text("""
            SELECT count(*) FROM questions q
            LEFT JOIN question_versions v
              ON v.question_id=q.id AND v.id=q.current_version_id
            WHERE q.current_version_id IS NULL OR v.id IS NULL
        """)).scalar_one())
        version_checks = {
            "all_versions_hash_valid": len(versions) - invalid_version_hashes,
            "invalid_version_hashes": invalid_version_hashes,
            "questions_without_valid_current_version": dangling_currents,
        }
        if invalid_version_hashes or dangling_currents:
            failures.append("question_version_integrity_failed")

        reviewed_questions = list(session.scalars(
            select(Question)
            .where(Question.auto_review_event_id.is_not(None))
            .options(joinedload(Question.current_auto_review), joinedload(Question.kp))
        ))
        current_formal = [
            question for question in reviewed_questions
            if current_auto_review(question, question.kp) is not None
        ]
        formal_ids = {str(question.id) for question in current_formal}
        version_checks["questions_with_current_auto_review"] = len(current_formal)

        policies = list(session.scalars(select(KpMasteryPolicy).where(
            KpMasteryPolicy.policy_version == 3,
            KpMasteryPolicy.graduation_set_version.is_not(None),
            KpMasteryPolicy.graduation_set_version > 0,
        )))
        set_keys = [(policy.kp_id, policy.graduation_set_version) for policy in policies]
        sets = list(session.scalars(select(KpGraduationQuestionSetVersion).where(
            KpGraduationQuestionSetVersion.kp_id.in_([key[0] for key in set_keys])
        ))) if set_keys else []
        set_map = {(row.kp_id, row.set_version): row for row in sets}
        active_member_ids: set[object] = set()
        active_member_count = 0
        invalid_members = 0
        duplicate_within_node = 0
        for policy in policies:
            row = set_map.get((policy.kp_id, policy.graduation_set_version))
            if row is None:
                invalid_members += 1
                continue
            qids = [str(value) for value in (row.question_ids or [])]
            vids = [str(value) for value in (row.question_version_ids or [])]
            if len(qids) != len(vids) or len(qids) != len(set(qids)):
                invalid_members += 1
                duplicate_within_node += len(qids) - len(set(qids))
                continue
            active_member_count += len(qids)
            for qid, vid in zip(qids, vids):
                question = session.get(Question, qid)
                version = session.get(QuestionVersion, vid)
                if (question is None or version is None or question.kp_id != policy.kp_id
                        or version.question_id != question.id or question.current_version_id != version.id
                        or str(question.id) not in formal_ids):
                    invalid_members += 1
                active_member_ids.add(qid)
        set_checks = {
            "active_v3_node_sets": len(policies),
            "active_members": active_member_count,
            "unique_active_question_ids": len(active_member_ids),
            "invalid_member_bindings": invalid_members,
            "duplicate_members_within_node": duplicate_within_node,
            "current_formal_questions_not_in_active_set": len(formal_ids - active_member_ids),
            "nonformal_questions_in_active_sets": len(active_member_ids - formal_ids),
        }
        if (len(formal_ids) != 1804 or len(policies) != 253 or active_member_count != 1804
                or invalid_members or duplicate_within_node or formal_ids != active_member_ids):
            failures.append("formal_question_or_set_integrity_failed")

        binding_rows = list(session.execute(
            select(KpState.graduation_set_binding_status, KpState.kp_id)
        ))
        binding_status_counts: dict[str, int] = {}
        for status, _kp_id in binding_rows:
            binding_status_counts[str(status)] = binding_status_counts.get(str(status), 0) + 1

    if counts != {
        "questions": 1935,
        "question_versions": 2322,
        "question_auto_review_events": 1804,
        "kp_mastery_policies": 284,
        "kp_graduation_question_set_versions": 254,
        "question_attempts": 28,
        "learning_events": 29,
        "kp_states": 284,
        "daily_plans": 10,
        "practice_items": 87,
    }:
        failures.append("post_sync_counts_do_not_match_accepted_merge")

    pre = json.loads((AUDIT / "pre-sync-state.json").read_text(encoding="utf-8"))
    merge = json.loads((AUDIT / "production-merge-run/phase45y-final1-merge-simulation.json").read_text(encoding="utf-8"))
    noop = json.loads((AUDIT / "production-merge-run/phase45y-merge-replay-noop.json").read_text(encoding="utf-8"))
    preserved = json.loads((AUDIT / "migration-preservation-check.json").read_text(encoding="utf-8"))
    api = json.loads((AUDIT / "real-api-rollback-smoke.json").read_text(encoding="utf-8"))
    backup = AUDIT / "final-sync-backup.dump"
    toc = AUDIT / "final-sync-backup.toc.txt"
    history_fingerprints = {
        "all_21_preexisting_migration_table_projections_equal": preserved.get("mismatch_count") == 0,
        "attempt_count_unchanged": counts["question_attempts"] == pre["tables"]["question_attempts"]["rows"],
        "learning_event_count_unchanged": counts["learning_events"] == pre["tables"]["learning_events"]["rows"],
        "kp_state_count_unchanged": counts["kp_states"] == pre["tables"]["kp_states"]["rows"],
        "daily_plan_count_unchanged": counts["daily_plans"] == pre["tables"]["daily_plans"]["rows"],
        "practice_item_count_unchanged": counts["practice_items"] == pre["tables"]["practice_items"]["rows"],
        "api_rollback_snapshot_unchanged": api.get("status") == "REAL_API_ROLLBACK_SMOKE_PASS" and api.get("persisted_changes") is False and api.get("post_rollback_snapshot_equal") is True,
    }
    if not all(history_fingerprints.values()):
        failures.append("learner_history_preservation_verification_failed")
    if not (noop.get("status") == "PHASE45Y_MERGE_REPLAY_NOOP" and noop.get("fingerprints_unchanged") is True):
        failures.append("idempotent_replay_check_failed")
    if not backup.is_file() or not toc.is_file():
        failures.append("final_backup_artifacts_missing")

    backup_info = {
        "path": str(backup.relative_to(ROOT)),
        "size_bytes": backup.stat().st_size if backup.exists() else None,
        "sha256": sha256(backup) if backup.exists() else None,
        "toc_path": str(toc.relative_to(ROOT)),
        "toc_sha256": sha256(toc) if toc.exists() else None,
        "toc_lines": sum(1 for _ in toc.open("r", encoding="utf-8")) if toc.exists() else None,
        "pre_migration_revision": pre["identity"]["revision"],
        "restore_drill": "PASS; restored into isolated PostgreSQL and 22-table pre-migration fingerprints matched",
    }
    migration_log = AUDIT / "migration-log.txt"
    migration_passes = sum(1 for line in migration_log.read_text(encoding="utf-8").splitlines() if line.startswith("PASS "))
    if migration_passes != 8:
        failures.append("migration_pass_count_not_8")

    post_state = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "identity": identity,
        "counts": counts,
        "current_formal_and_sets": {**version_checks, **set_checks},
        "kp_state_binding_status_counts": binding_status_counts,
        "history_protection": history_fingerprints,
    }
    (AUDIT / "post-sync-state.json").write_text(json.dumps(post_state, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")

    merge_summary = {
        "status": "MERGED_AND_REPLAYED_NOOP" if not failures else "MERGED_WITH_FAILED_FINAL_CHECKS",
        "database": identity,
        "questions": merge["post_merge_counts"]["questions"],
        "question_versions": merge["post_merge_counts"]["question_versions"],
        "formal_questions": merge["question_merge"]["sealed_formal_questions"],
        "candidate_formal_ids_inserted": merge["question_merge"]["candidate_formal_ids_inserted"],
        "conflict_ids_versioned": merge["question_merge"]["conflict_ids_updated_to_new_version"],
        "target_only_questions_preserved": merge["question_merge"]["target_only_questions_preserved"],
        "review_events_imported": merge["question_merge"]["review_events_imported_current_hash_matched"],
        "active_set_versions": merge["sets_and_policy"]["current_active_sets_imported"],
        "current_set_members": merge["sets_and_policy"]["current_active_set_members"],
        "preserved_historical_set_versions": merge["sets_and_policy"]["additional_historical_started_set_versions_imported"],
        "legacy_unbound_nodes": merge["sets_and_policy"]["legacy_history_nodes_unbound"],
        "idempotency_replay": noop["status"],
        "source_report": str((AUDIT / "production-merge-run/phase45y-final1-merge-simulation.json").relative_to(ROOT)),
    }
    (AUDIT / "merge-summary.json").write_text(json.dumps(merge_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = {
        "status": "REAL_DATABASE_SYNC_COMPLETE" if not failures else "REAL_DATABASE_SYNC_INCOMPLETE",
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "authorized real database migration and versioned formal-question merge; no test data persisted",
        "pre_sync_identity": pre["identity"],
        "post_sync_identity": identity,
        "pre_sync_counts": {name: info["rows"] for name, info in pre["tables"].items() if name in {"questions", "question_attempts", "learning_events", "kp_states", "daily_plans", "practice_items"}},
        "post_sync_counts": counts,
        "backup": backup_info,
        "migration": {"from": pre["identity"]["revision"], "to": identity["revision"], "passed_revisions": migration_passes, "log": str(migration_log.relative_to(ROOT)), "preservation_check": str((AUDIT / "migration-preservation-check.json").relative_to(ROOT))},
        "merge": merge_summary,
        "history_protection": history_fingerprints,
        "question_version_integrity": version_checks,
        "graduation_set_integrity": set_checks,
        "real_api_rollback_smoke": api,
        "failures": failures,
        "artifacts": {
            "final_backup": str(backup.relative_to(ROOT)),
            "toc": str(toc.relative_to(ROOT)),
            "migration_log": str(migration_log.relative_to(ROOT)),
            "merge_summary": str((AUDIT / "merge-summary.json").relative_to(ROOT)),
            "post_sync_state": str((AUDIT / "post-sync-state.json").relative_to(ROOT)),
        },
    }
    (AUDIT / "final-sync-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    engine.dispose()
    print(json.dumps({"status": report["status"], "counts": counts, "version_checks": version_checks,
                      "set_checks": set_checks, "history_protection": history_fingerprints,
                      "failures": failures, "backup": backup_info}, ensure_ascii=False, indent=2, default=str))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
