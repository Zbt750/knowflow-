"""Persist and restore-check the completed H-X isolated bank; never use app DB settings."""
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_phase45hx_batch01 import all_table_fingerprints, run_logged, save
from scripts.run_phase45hx_batch02 import inventory, PORT, SYSTEM_ID, REVISION, PROTECTED

RUN = ROOT / "storage/quality-audits/phase45hx-20261010/batch-13"
OUT = RUN / "final-checkpoint"
EXPECTED_STATUS = "BATCH_03_COMPLETE"


def main():
    prior = json.loads((RUN / "checkpoint.json").read_text(encoding="utf-8"))
    name = prior.get("clone", {}).get("database")
    if (EXPECTED_STATUS not in {"BATCH_03_COMPLETE", "BATCH_04_COMPLETE", "BATCH_05_COMPLETE"}
            or prior.get("status") != EXPECTED_STATUS or prior.get("port") != PORT or PORT == 5433
            or prior.get("system_identifier_expected") != SYSTEM_ID
            or prior.get("clone", {}).get("revision_after") != REVISION
            or not isinstance(name, str) or not name.startswith("phase45hx_") or not name.endswith("_test")):
        raise RuntimeError("completed_checkpoint_ownership_not_confirmed")
    if OUT.exists() and any(OUT.iterdir()):
        raise RuntimeError("refuse_overwrite_final_checkpoint")
    OUT.mkdir(parents=True, exist_ok=True)
    from scripts import run_phase45i_agent_real as owner
    _, cluster, owned_port = owner.load_existing_owner()
    if owned_port != PORT:
        raise RuntimeError("isolated_cluster_port_mismatch")
    for key in list(os.environ):
        if key.upper().startswith("PG"):
            os.environ.pop(key)
    owner.OUT_DIR = OUT / "postgres-runtime"
    owner.OUT_DIR.mkdir()
    started = owner.start_owned_database(cluster, PORT)
    from psycopg import connect, sql
    from sqlalchemy import create_engine, select, text
    from backend.db import create_session_factory
    from backend.models.learning import Question, KnowledgePoint
    from backend.services.question_eligibility import question_eligibility
    from backend.services.question_identity import historical_identity
    from backend.services.auto_question_review import _grading_tests
    result = {"status": "STARTED", "source_database": name, "port": PORT,
        "system_identifier": SYSTEM_ID, "development_5433_touched": False, "paid_model_calls": 0}
    restored_name = "phase45hxrestore_" + uuid4().hex[:10] + "_test"
    created = False
    engine = None
    restore_engine = None
    try:
        with connect(host="127.0.0.1", port=PORT, user="postgres", dbname="postgres", autocommit=True, connect_timeout=5) as server:
            if str(server.execute("SELECT system_identifier FROM pg_control_system()").fetchone()[0]) != SYSTEM_ID:
                raise RuntimeError("system_identifier_changed")
            if server.execute("SELECT count(*) FROM pg_stat_activity WHERE datname=%s", (name,)).fetchone()[0]:
                raise RuntimeError("source_has_active_sessions")
        engine = create_engine(f"postgresql+psycopg://postgres@127.0.0.1:{PORT}/{name}")
        with create_session_factory(engine)() as db:
            db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            revision = db.scalar(text("SELECT version_num FROM alembic_version"))
            if revision != REVISION:
                raise RuntimeError("source_revision_changed")
            before = all_table_fingerprints(db.connection())
            if {key: before[key] for key in PROTECTED} != prior["protected_history"]["after"]:
                raise RuntimeError("protected_history_no_longer_matches_completed_batch")
            result["inventory"] = inventory(db)
            qrows = list(db.scalars(select(Question).where(Question.bank_scope == "public", Question.generation_batch_id.is_(None))))
            nodes = {node.id: node for node in db.scalars(select(KnowledgePoint))}
            identities = [key for q in qrows if (key := historical_identity(q)) is not None]
            result["historical_identity_audit"] = {"identity_rows": len(identities), "unique_identities": len(set(identities)),
                "duplicate_identity_rows": len(identities) - len(set(identities))}
            eligible = [q for q in qrows if q.kp_id in nodes and question_eligibility(q, nodes[q.kp_id], teaching_enabled=False).evidence_capability == "verified_objective"
                and question_eligibility(q, nodes[q.kp_id], teaching_enabled=False).practice_eligible]
            result["formal_by_qualification_class"] = dict(Counter(q.current_auto_review.qualification_class if q.current_auto_review else "human_verified" for q in eligible))
            target_ids = {prior.get("huffman", {}).get("question_id"), prior.get("crc_variant", {}).get("question_id")}
            target_ids.update(prior.get("restored_question_ids", []))
            result["new_content_real_comparator_checks"] = [
                {"question_id": str(q.id), "grading": _grading_tests(q)} for q in qrows if str(q.id) in target_ids]
            if any(row["grading"]["status"] != "PASS" for row in result["new_content_real_comparator_checks"]):
                raise RuntimeError("new_content_comparator_check_failed")
        engine.dispose()
        engine = None
        dump = OUT / "completed-bank.dump"
        rc = run_logged([str(owner.PG_BIN / "pg_dump.exe"), "--format=custom", "--no-owner", "--no-acl",
            "--host=127.0.0.1", f"--port={PORT}", "--username=postgres", f"--dbname={name}", f"--file={dump}"],
            OUT / "pg-dump.log", env=os.environ.copy(), timeout=300)
        if rc or not dump.is_file() or not dump.stat().st_size:
            raise RuntimeError("completed_bank_dump_failed")
        toc = owner.command([str(owner.PG_BIN / "pg_restore.exe"), "--list", str(dump)])
        if "TABLE DATA" not in toc.stdout:
            raise RuntimeError("backup_toc_not_readable")
        result["backup"] = {"path": str(dump.relative_to(ROOT)), "sha256": sha256(dump.read_bytes()).hexdigest(),
            "size_bytes": dump.stat().st_size, "toc_readable": True}
        with connect(host="127.0.0.1", port=PORT, user="postgres", dbname="postgres", autocommit=True, connect_timeout=5) as server:
            server.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(sql.Identifier(restored_name)))
        created = True
        rc = run_logged([str(owner.PG_BIN / "pg_restore.exe"), "--exit-on-error", "--no-owner", "--no-acl",
            "--host=127.0.0.1", f"--port={PORT}", "--username=postgres", f"--dbname={restored_name}", str(dump)],
            OUT / "restore.log", env=os.environ.copy(), timeout=300)
        if rc:
            raise RuntimeError("independent_restore_failed")
        restore_engine = create_engine(f"postgresql+psycopg://postgres@127.0.0.1:{PORT}/{restored_name}")
        with restore_engine.connect() as connection:
            connection.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            after = all_table_fingerprints(connection)
        if before != after:
            raise RuntimeError("restored_all_table_fingerprints_differ")
        result.update({"status": "ISOLATED_BANK_CHECKPOINT_RESTORE_PASS", "revision": revision,
            "source_fingerprints": before, "restored_fingerprints": after,
            "all_table_fingerprints_equal": True, "table_count": len(before),
            "source_history_unchanged": True, "restore_target": restored_name})
        save(OUT / "report.json", result)
        print(json.dumps({key: value for key, value in result.items() if key not in {"source_fingerprints", "restored_fingerprints", "inventory"}}, ensure_ascii=False), flush=True)
        return 0
    except Exception as exc:
        result.update({"status": "CHECKPOINT_BLOCKED", "error_type": type(exc).__name__, "error": str(exc)[:500]})
        save(OUT / "report.json", result)
        print(json.dumps({key: result.get(key) for key in ("status", "error_type", "error")}, ensure_ascii=False), flush=True)
        return 1
    finally:
        if engine is not None:
            engine.dispose()
        if restore_engine is not None:
            restore_engine.dispose()
        if created:
            with connect(host="127.0.0.1", port=PORT, user="postgres", dbname="postgres", autocommit=True, connect_timeout=5) as server:
                if not server.execute("SELECT count(*) FROM pg_stat_activity WHERE datname=%s", (restored_name,)).fetchone()[0]:
                    server.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(restored_name)))
        if started:
            owner.command([str(owner.PG_BIN / "pg_ctl.exe"), "-D", str(cluster), "-m", "fast", "-w", "-t", "60", "stop"], timeout=75, check=False)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
