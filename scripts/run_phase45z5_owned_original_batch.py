"""Execute one authored Z5 batch and verify its backup on the owned test cluster.

This is a maintenance runner, independent of application database settings.
It cannot target port 5433 or a database other than the existing Z5 work copy.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def normalized(value):
    return json.loads(json.dumps(value, default=str))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("batch_module")
    args = parser.parse_args()
    if not re.fullmatch(r"phase45z5_original_batch\d{2}", args.batch_module):
        raise SystemExit("authored_z5_batch_module_required")
    batch = importlib.import_module("scripts." + args.batch_module)
    if (batch.DB_NAME != "phase45z5_work_20261013_test" or batch.PORT != 59227
            or batch.SYSTEM_ID != "7694698872540080852"):
        raise SystemExit("pinned_isolated_target_mismatch")
    output = batch.OUT_DIR.resolve()
    if not output.is_relative_to((ROOT / "storage/quality-audits/phase45z5-20261013").resolve()):
        raise SystemExit("batch_output_outside_private_audit_root")
    checkpoint_path = output / "checkpoint.json"
    if checkpoint_path.exists() or (output / "preview.json").exists():
        raise SystemExit("existing_batch_evidence_refuse_repeat_or_overwrite")
    previous_path = batch.BACKUP.parent / "checkpoint.json"
    previous = json.loads(previous_path.read_text(encoding="utf-8"))
    if not batch.BACKUP.is_file() or hashlib.sha256(batch.BACKUP.read_bytes()).hexdigest().upper() != batch.BACKUP_SHA256:
        raise SystemExit("prebatch_backup_hash_mismatch")
    specs = batch.candidates()
    source_sha = hashlib.sha256(Path(batch.__file__).read_bytes()).hexdigest()
    from scripts import run_phase45i_agent_real as infra
    from scripts.phase45z5_original_batch01 import table_fingerprint, policy_rule_fingerprint
    from scripts.run_phase45hx_batch01 import all_table_fingerprints
    from sqlalchemy import create_engine, select, text
    from sqlalchemy.engine import URL
    from sqlalchemy.orm import Session, selectinload
    from backend.models.learning import (Question, QuestionAutoReviewEvent, KpGraduationQuestionSetVersion,
        KpMasteryPolicy, QuestionAttempt, LearningEvent, KpState)
    from backend.services.question_eligibility import question_eligibility
    import psycopg
    from psycopg import sql

    def live_snapshot(engine):
        with Session(engine) as db:
            db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            identity = db.execute(text("SELECT current_database(),inet_server_port(),"
                "(SELECT system_identifier::text FROM pg_control_system()),"
                "(SELECT version_num FROM alembic_version)")).one()
            if tuple(identity) != (batch.DB_NAME, batch.PORT, batch.SYSTEM_ID, "f52a6c8d301e"):
                raise RuntimeError("live_work_database_identity_or_revision_mismatch")
            return normalized({"question_rows": db.query(Question).count(),
                "auto_review_events": db.query(QuestionAutoReviewEvent).count(),
                "set_versions": db.query(KpGraduationQuestionSetVersion).count(),
                "policy_rule_fingerprint": policy_rule_fingerprint(db),
                "protected_history": {"attempts": table_fingerprint(db, QuestionAttempt),
                    "learning_events": table_fingerprint(db, LearningEvent),
                    "kp_states": table_fingerprint(db, KpState)}})

    owner, cluster, port = infra.load_existing_owner()
    if port != batch.PORT:
        raise RuntimeError("owned_cluster_port_mismatch")
    output.mkdir(parents=True, exist_ok=True)
    infra.OUT_DIR = output / "runtime"
    infra.OUT_DIR.mkdir(exist_ok=True)
    started = infra.start_owned_database(cluster, port)
    engine = None
    operation = {"source_sha256": source_sha, "batch_module": args.batch_module,
        "paid_model_calls": 0, "development_5433_accessed": False, "normal_stop": None}
    try:
        infra.verify_database(cluster, port)
        url = URL.create("postgresql+psycopg", username="postgres", host="127.0.0.1", port=port, database=batch.DB_NAME)
        engine = create_engine(url, pool_pre_ping=True)
        before = live_snapshot(engine)
        if before != previous["after"]:
            raise RuntimeError("live_database_differs_from_previous_committed_checkpoint")
        sys.argv = [args.batch_module + ".py", "--mode", "dry-run"]
        batch.main()
        preview = json.loads((output / "preview.json").read_text(encoding="utf-8"))
        if preview["status"] != "DRY_RUN_ROLLED_BACK" or preview["rejected"] or len(preview["accepted"]) != len(specs):
            raise RuntimeError("dryrun_has_rejected_candidates_no_apply")
        if live_snapshot(engine) != before or preview["before"] != before:
            raise RuntimeError("dryrun_not_fully_rolled_back_or_preview_baseline_changed")
        if hashlib.sha256(Path(batch.__file__).read_bytes()).hexdigest() != source_sha:
            raise RuntimeError("candidate_source_changed_after_preview")
        sys.argv = [args.batch_module + ".py", "--mode", "apply"]
        batch.main()
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        operation["database_write_committed"] = True
        if checkpoint["rejected"] or len(checkpoint["accepted"]) != len(specs) or checkpoint["before"] != before:
            raise RuntimeError("apply_result_differs_from_clean_preview")
        actual = live_snapshot(engine)
        if actual != checkpoint["after"] or actual["protected_history"] != before["protected_history"] or actual["policy_rule_fingerprint"] != before["policy_rule_fingerprint"]:
            raise RuntimeError("postapply_history_or_policy_or_checkpoint_mismatch")
        with Session(engine) as db:
            db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            formal = []
            for question in db.scalars(select(Question).options(selectinload(Question.kp))):
                eligibility = question_eligibility(question, question.kp)
                if question.bank_scope == "public" and eligibility.practice_eligible and eligibility.evidence_capability == "verified_objective" and eligibility.grading_capability == "deterministic":
                    formal.append(question)
            policies = list(db.scalars(select(KpMasteryPolicy)))
            members = [str(qid) for p in policies for qid in (p.graduation_question_ids or [])]
            ids = {str(q.id) for q in formal}
            if set(members) != ids or len(members) != len(ids) or len(formal) != len(ids):
                raise RuntimeError("formal_membership_missing_or_duplicate")
            nodes = {q.kp.code: {"name": q.kp.name, "subject": q.kp.subject, "count": 0} for q in formal}
            for question in formal: nodes[question.kp.code]["count"] += 1
            audit = {"status": "PHASE45Z5_IN_PROGRESS_RESTORE_VERIFIED", "candidate_count": len(specs),
                "accepted_count": len(checkpoint["accepted"]), "formal_questions": len(formal),
                "formal_subjects": dict(Counter(q.kp.subject for q in formal)),
                "formal_sources": dict(Counter("exam_curated" if q.question_provenance == "real_exam" else "exam_variant" if q.is_variant else "development_original" for q in formal)),
                "formal_nodes": len(nodes), "node_distribution": nodes,
                "nonempty_current_sets": sum(bool(p.graduation_question_ids) for p in policies),
                "current_formal_memberships": len(members), "all_formal_questions_in_current_sets_exactly_once": True,
                "protected_history": actual["protected_history"], "graduation_algorithm_fingerprint": actual["policy_rule_fingerprint"],
                "shortfall_to_2000": max(0, 2000-len(formal)), "development_5433_accessed": False,
                "paid_model_calls": 0, "deployment_ready": False,
                "difficulty_population_pass_not_claimed": True, "batch_source_sha256": source_sha}
        dump_path = output / "post-batch.dump"
        if dump_path.exists(): raise RuntimeError("backup_exists_refuse_overwrite")
        infra.command([str(infra.PG_BIN/"pg_dump.exe"), "-h", "127.0.0.1", "-p", str(port), "-U", "postgres", "-d", batch.DB_NAME, "-Fc", "-f", str(dump_path)], timeout=180)
        backup_sha = hashlib.sha256(dump_path.read_bytes()).hexdigest().upper()
        toc = infra.command([str(infra.PG_BIN/"pg_restore.exe"), "--list", str(dump_path)], timeout=60)
        if "TABLE DATA public questions" not in toc.stdout: raise RuntimeError("backup_toc_invalid")
        number = args.batch_module.removeprefix("phase45z5_original_batch")
        restore_db = f"phase45z5_batch{number}_restore_20261013_test"
        with psycopg.connect(host="127.0.0.1", port=port, user="postgres", dbname="postgres", sslmode="disable", connect_timeout=8, autocommit=True) as conn:
            if conn.execute("SELECT 1 FROM pg_database WHERE datname=%s", (restore_db,)).fetchone():
                raise RuntimeError("restore_database_exists_refuse_overwrite")
            conn.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(restore_db)))
        infra.command([str(infra.PG_BIN/"pg_restore.exe"), "--exit-on-error", "-h", "127.0.0.1", "-p", str(port), "-U", "postgres", "-d", restore_db, str(dump_path)], timeout=240)
        restore_engine = create_engine(URL.create("postgresql+psycopg", username="postgres", host="127.0.0.1", port=port, database=restore_db))
        try:
            with engine.connect() as conn: current_fps = all_table_fingerprints(conn)
            with restore_engine.connect() as conn: restored_fps = all_table_fingerprints(conn)
            if current_fps != restored_fps: raise RuntimeError("independent_restore_fingerprint_mismatch")
        finally: restore_engine.dispose()
        audit["backup"] = {"path": dump_path.relative_to(ROOT).as_posix(), "sha256": backup_sha,
            "toc_entries": len(toc.stdout.splitlines()), "restored_database": restore_db,
            "all_table_fingerprints_match": True, "table_count": len(current_fps)}
        (output/"post-batch-audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        operation["status"] = "APPLIED_AND_RESTORE_VERIFIED"
        print(json.dumps({key:audit[key] for key in ("formal_questions","formal_subjects","formal_sources","formal_nodes","nonempty_current_sets","current_formal_memberships","shortfall_to_2000","backup")}, ensure_ascii=True), flush=True)
    except BaseException as exc:
        operation["status"] = "STOPPED_ON_CHECK_FAILURE"
        operation["error"] = str(exc)
        raise
    finally:
        if engine is not None: engine.dispose()
        if started:
            stop = infra.command([str(infra.PG_BIN/"pg_ctl.exe"), "-D", str(cluster), "-m", "fast", "-w", "-t", "60", "stop"], timeout=75, check=False, capture=False)
            operation["normal_stop"] = stop.returncode == 0
            print("ISOLATED_CLUSTER_STOPPED_NORMALLY" if stop.returncode == 0 else "ISOLATED_CLUSTER_STOP_FAILED", flush=True)
        (output/"operation.json").write_text(json.dumps(operation, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


if __name__ == "__main__": main()
