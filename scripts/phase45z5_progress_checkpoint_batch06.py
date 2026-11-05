"""Read-only progress + independent restore verification after original batch 06."""
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
CHECKPOINT = BASE / "originals/batch06-revised/checkpoint.json"
BACKUP = BASE / "originals/batch06-revised/post-batch06.dump"
OUT = BASE / "progress-after-batch06.json"
DBS = (
    ("phase45z5_work_20261013_test", "phase45z5_work_20261013_test"),
    ("phase45z5_batch06_restore_20261013_test", "phase45z5_batch06_restore_20261013_test"),
)
PORT = 59227
SYSTEM_ID = 7694698872540080852


def read_tables(db_name: str) -> dict:
    url = f"postgresql+psycopg://postgres@127.0.0.1:{PORT}/{db_name}"
    engine = create_engine(url, connect_args={"options": "-c default_transaction_read_only=on"})
    try:
        with Session(engine) as db:
            db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            identity = tuple(db.execute(text(
                "SELECT current_database(), inet_server_port(), system_identifier "
                "FROM (SELECT current_database(), inet_server_port(), system_identifier "
                "FROM pg_control_system()) s"
            )).one())
            if identity != (db_name, PORT, SYSTEM_ID):
                raise RuntimeError(f"isolated_database_identity_mismatch:{identity}")
            return {"identity": list(identity), "tables": all_table_fingerprints(db.connection())}
    finally:
        engine.dispose()


def main() -> None:
    if OUT.exists():
        raise SystemExit(f"refusing_to_overwrite:{OUT}")
    if not CHECKPOINT.is_file() or not BACKUP.is_file():
        raise SystemExit("batch06_checkpoint_or_backup_missing")
    applied = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    if applied.get("status") != "BATCH06_APPLIED" or applied.get("rejected"):
        raise SystemExit("batch06_not_cleanly_applied")

    current = read_tables(DBS[0][0])
    restored = read_tables(DBS[1][0])
    if current["tables"] != restored["tables"]:
        mismatches = {name: {"current": current["tables"].get(name),
                             "restored": restored["tables"].get(name)}
                      for name in sorted(set(current["tables"]) | set(restored["tables"]))
                      if current["tables"].get(name) != restored["tables"].get(name)}
        raise RuntimeError("independent_restore_table_fingerprint_mismatch:" +
                           json.dumps(mismatches, ensure_ascii=False, sort_keys=True))

    url = f"postgresql+psycopg://postgres@127.0.0.1:{PORT}/{DBS[0][0]}"
    engine = create_engine(url, connect_args={"options": "-c default_transaction_read_only=on"})
    try:
        with Session(engine) as db:
            db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            questions = list(db.scalars(select(Question)))
            formal = [q for q in questions if q.bank_scope == "public"
                      and q.generation_batch_id is None
                      and (lambda e: e.practice_eligible
                           and e.evidence_capability == "verified_objective"
                           and e.grading_capability == "deterministic")(
                               question_eligibility(q, q.kp))]
            formal_ids = {str(q.id) for q in formal}
            policies = list(db.scalars(select(KpMasteryPolicy)))
            members = [str(qid) for p in policies for qid in (p.graduation_question_ids or [])]
            if set(members) != formal_ids or len(members) != len(formal_ids):
                raise RuntimeError("current_formal_question_graduation_membership_mismatch")

            baseline = json.loads((BASE / "known-content/checkpoint.json").read_text(encoding="utf-8"))
            protected = {
                "attempts": list(table_fingerprint(db, QuestionAttempt)),
                "learning_events": list(table_fingerprint(db, LearningEvent)),
                "kp_states": list(table_fingerprint(db, KpState)),
            }
            expected_history = baseline["before"]["protected_history"]
            expected_history = {key: list(value) for key, value in expected_history.items()}
            if protected != expected_history:
                raise RuntimeError("protected_learning_history_changed")
            rules = policy_rule_fingerprint(db)
            if rules != baseline["before"]["policy_rule_fingerprint"]:
                raise RuntimeError("graduation_algorithm_fingerprint_changed")

            accepted_ids = {entry["question_id"] for entry in applied["accepted"]}
            by_id = {str(q.id): q for q in formal}
            if not accepted_ids <= set(by_id):
                raise RuntimeError("batch06_questions_not_all_currently_formal")
            source_counts = Counter(
                "exam_curated" if q.question_provenance == "real_exam" else
                "exam_variant" if q.is_variant else "development_original"
                for q in formal
            )
            subject_counts = Counter(q.kp.subject for q in formal)
            nodes = {}
            for q in formal:
                cell = nodes.setdefault(q.kp.code, {"name": q.kp.name,
                    "subject": q.kp.subject, "formal_questions": 0})
                cell["formal_questions"] += 1

            output = {
                "status": "PHASE45Z5_IN_PROGRESS_RESTORE_VERIFIED",
                "batch": "06",
                "schema_revision": db.execute(text("SELECT version_num FROM alembic_version")).scalar(),
                "database": {"name": DBS[0][0], "port": PORT, "system_identifier": SYSTEM_ID},
                "question_records": len(questions),
                "formal_questions": len(formal),
                "formal_by_subject": dict(subject_counts),
                "formal_by_source": dict(source_counts),
                "formal_nodes": len(nodes),
                "graduation_sets": len(policies),
                "formal_questions_in_current_sets_exactly_once": True,
                "batch06_added_questions": len(accepted_ids),
                "batch06_new_set_publications": len(applied["publications"]),
                "shortfall_to_2000": max(0, 2000 - len(formal)),
                "node_distribution": nodes,
                "protected_history": protected,
                "graduation_algorithm_fingerprint": rules,
                "isolated_restore": {
                    "database": DBS[1][0],
                    "table_count": len(current["tables"]),
                    "all_table_fingerprints_match": True,
                },
                "backup": {
                    "path": str(BACKUP),
                    "sha256": hashlib.sha256(BACKUP.read_bytes()).hexdigest().upper(),
                    "rows_archive_verified_by_restore": True,
                },
                "paid_model_calls": 0,
                "development_5433_accessed": False,
                "deployment_ready": False,
            }
    finally:
        engine.dispose()

    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: output[key] for key in (
        "status", "question_records", "formal_questions", "formal_by_subject",
        "formal_by_source", "formal_nodes", "graduation_sets", "batch06_added_questions",
        "batch06_new_set_publications", "shortfall_to_2000", "isolated_restore", "backup",
    )}, ensure_ascii=False))


if __name__ == "__main__":
    main()
