"""Read-only progress and independent restore audit after sample upgrade batch 05."""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.models.learning import (  # noqa: E402
    KpMasteryPolicy, KpState, LearningEvent, Question, QuestionAttempt,
)
from backend.services.question_eligibility import question_eligibility  # noqa: E402
from scripts.phase45z5_original_batch01 import (  # noqa: E402
    policy_rule_fingerprint, table_fingerprint,
)
from scripts.run_phase45hx_batch01 import all_table_fingerprints  # noqa: E402

BASE = ROOT / "storage/quality-audits/phase45z5-20261013"
OUT = BASE / "progress-after-sample05.json"
BACKUP = BASE / "sample-upgrades/batch05/post-sample-upgrade.dump"
DATABASES = (
    ("phase45z5_work_20261013_test", "postgresql+psycopg://postgres@127.0.0.1:59227/phase45z5_work_20261013_test"),
    ("phase45z5_batch05_sample_restore_20261013_test", "postgresql+psycopg://postgres@127.0.0.1:59227/phase45z5_batch05_sample_restore_20261013_test"),
)
SYSTEM_ID = 7694698872540080852


def inspect_database(expected_name: str, url: str) -> tuple[dict, dict, dict]:
    engine = create_engine(url, connect_args={"options": "-c default_transaction_read_only=on"})
    try:
        with Session(engine) as db:
            db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            identity = tuple(db.execute(text(
                "SELECT current_database(), inet_server_port(), system_identifier "
                "FROM pg_control_system()"
            )).one())
            if identity != (expected_name, 59227, SYSTEM_ID):
                raise RuntimeError(f"isolated_identity_mismatch:{identity}")
            table_fps = all_table_fingerprints(db.connection())
            data = {"database": expected_name, "identity": list(identity), "tables": table_fps}
            if expected_name != DATABASES[0][0]:
                return data, {}, table_fps

            questions = list(db.scalars(select(Question)))
            formal = []
            for q in questions:
                result = question_eligibility(q, q.kp)
                if (q.bank_scope == "public" and result.practice_eligible
                        and result.evidence_capability == "verified_objective"
                        and result.grading_capability == "deterministic"):
                    formal.append(q)
            formal_ids = {str(q.id) for q in formal}
            policies = list(db.scalars(select(KpMasteryPolicy)))
            members = [str(qid) for policy in policies
                       for qid in (policy.graduation_question_ids or [])]
            if set(members) != formal_ids or len(members) != len(formal_ids):
                raise RuntimeError("formal_question_and_graduation_membership_mismatch")

            baseline = json.loads((BASE / "known-content/checkpoint.json").read_text(encoding="utf-8"))
            protected = {
                "attempts": table_fingerprint(db, QuestionAttempt),
                "learning_events": table_fingerprint(db, LearningEvent),
                "kp_states": table_fingerprint(db, KpState),
            }
            if json.loads(json.dumps(protected)) != baseline["before"]["protected_history"]:
                raise RuntimeError("protected_learning_history_changed")
            policy_fp = policy_rule_fingerprint(db)
            if policy_fp != baseline["before"]["policy_rule_fingerprint"]:
                raise RuntimeError("graduation_algorithm_fingerprint_changed")

            node_counts = {}
            for q in formal:
                node = node_counts.setdefault(q.kp.code, {
                    "name": q.kp.name, "subject": q.kp.subject, "count": 0,
                })
                node["count"] += 1
            source_counts = Counter(
                "exam_curated" if q.question_provenance == "real_exam" else
                "exam_variant" if q.is_variant else "development_original"
                for q in formal
            )

            sample = json.loads((ROOT / "storage/quality-audits/phase45z-20261013/ai-original-random-sample-100.json").read_text(encoding="utf-8"))
            previous_report = json.loads((ROOT / "storage/quality-audits/phase45z4-20261013/phase45z4-final-report.json").read_text(encoding="utf-8"))
            processed = {item["question_id"] for item in previous_report["upgraded_questions"]}
            batch_results = []
            for batch_dir in sorted((BASE / "sample-upgrades").glob("batch*")):
                path = batch_dir / "checkpoint.json"
                if path.exists():
                    report = json.loads(path.read_text(encoding="utf-8"))
                    processed.update(item["id"] for item in report["results"])
                    batch_results.extend(report["results"])
            keep_path = BASE / "sample-upgrades/remaining-kept/decisions.json"
            keep_report = json.loads(keep_path.read_text(encoding="utf-8"))
            processed.update(item["question_id"] for item in keep_report["results"])
            pending = [qid for qid in sample["below_target_candidate_question_ids"] if qid not in processed]

            versions = [{
                "node_id": str(policy.kp_id),
                "latest_version": policy.graduation_set_version,
                "member_count": len(policy.graduation_question_ids or []),
            } for policy in policies if policy.graduation_question_ids]
            data.update({
                "status": "PHASE45Z5_IN_PROGRESS",
                "schema_revision": db.execute(text("SELECT version_num FROM alembic_version")).scalar(),
                "question_records": len(questions),
                "formal_questions": len(formal),
                "formal_subjects": dict(Counter(q.kp.subject for q in formal)),
                "formal_sources": dict(source_counts),
                "formal_nodes": len(node_counts),
                "node_distribution": node_counts,
                "graduation_set_count": len(versions),
                "graduation_set_versions": versions,
                "formal_memberships": len(members),
                "all_formal_questions_in_current_sets_exactly_once": True,
                "shortfall_to_2000": max(0, 2000 - len(formal)),
                "sample_candidates_upgraded_this_phase": len(batch_results),
                "sample_candidate_keep_decisions": len(keep_report["results"]),
                "sample_candidates_processed": len(batch_results) + len(keep_report["results"]),
                "sample_candidates_pending": pending,
                "protected_history": protected,
                "graduation_algorithm_fingerprint": policy_fp,
                "paid_model_calls": 0,
                "development_5433_accessed": False,
                "deployment_ready": False,
            })
            return data, protected, table_fps
    finally:
        engine.dispose()


def main() -> None:
    if OUT.exists():
        raise SystemExit(f"refusing_to_overwrite:{OUT}")
    if not BACKUP.is_file():
        raise SystemExit("latest_backup_missing")
    current, protected, current_tables = inspect_database(*DATABASES[0])
    restored, _, restored_tables = inspect_database(*DATABASES[1])
    if current_tables != restored_tables:
        mismatches = {name: {"current": current_tables.get(name), "restored": restored_tables.get(name)}
                      for name in sorted(set(current_tables) | set(restored_tables))
                      if current_tables.get(name) != restored_tables.get(name)}
        raise RuntimeError("independent_restore_full_table_fingerprint_mismatch:" +
                           json.dumps(mismatches, ensure_ascii=False, sort_keys=True))
    current["independent_restore"] = {
        "database": DATABASES[1][0],
        "full_public_table_count": len(current_tables),
        "all_table_fingerprints_match": True,
        "backup_path": str(BACKUP),
        "backup_sha256": hashlib.sha256(BACKUP.read_bytes()).hexdigest().upper(),
        "restored_formal_questions": current["formal_questions"],
        "restored_question_records": restored_tables.get("questions", {}).get("count"),
    }
    current["status"] = "PHASE45Z5_IN_PROGRESS_RESTORE_VERIFIED"
    OUT.write_text(json.dumps(current, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({key: current[key] for key in (
        "status", "question_records", "formal_questions", "formal_subjects", "formal_sources",
        "formal_nodes", "graduation_set_count", "sample_candidates_upgraded_this_phase",
        "sample_candidate_keep_decisions", "sample_candidates_pending", "independent_restore",
    )}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
