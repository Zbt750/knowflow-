"""Read-only scan of the completed H-X bank in its owned isolated instance."""
from collections import Counter
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_phase45hx_batch01 import all_table_fingerprints, save
from scripts.run_phase45hx_batch02 import PORT, SYSTEM_ID, REVISION

RUN = ROOT / "storage/quality-audits/phase45hx-20261010/batch-13"
OUT = RUN / "remaining-bank-audit"


def main():
    prior = json.loads((RUN / "checkpoint.json").read_text(encoding="utf-8"))
    name = prior.get("clone", {}).get("database")
    if (prior.get("status") != "BATCH_03_COMPLETE" or prior.get("port") != PORT or PORT == 5433
            or not isinstance(name, str) or not name.startswith("phase45hx_") or not name.endswith("_test")):
        raise RuntimeError("owned_completed_test_checkpoint_required")
    if OUT.exists() and any(OUT.iterdir()):
        raise RuntimeError("refuse_overwrite_audit")
    OUT.mkdir(parents=True, exist_ok=True)
    from scripts import run_phase45i_agent_real as owner
    _, cluster, port = owner.load_existing_owner()
    if port != PORT:
        raise RuntimeError("owned_port_changed")
    for key in list(os.environ):
        if key.upper().startswith("PG"):
            os.environ.pop(key)
    owner.OUT_DIR = OUT / "postgres-runtime"
    owner.OUT_DIR.mkdir()
    started = owner.start_owned_database(cluster, PORT)
    from sqlalchemy import create_engine, select, text
    from backend.db import create_session_factory
    from backend.models.learning import Question, KnowledgePoint
    from backend.services.question_eligibility import question_eligibility
    from backend.services.quality_verifiers import verify_problem, VERSION
    from backend.services.question_identity import historical_identity
    engine = create_engine(f"postgresql+psycopg://postgres@127.0.0.1:{PORT}/{name}")
    try:
        with create_session_factory(engine)() as db:
            db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            if str(db.scalar(text("SELECT system_identifier FROM pg_control_system()"))) != SYSTEM_ID:
                raise RuntimeError("system_identifier_changed")
            if db.scalar(text("SELECT version_num FROM alembic_version")) != REVISION:
                raise RuntimeError("revision_changed")
            before = all_table_fingerprints(db.connection())
            nodes = {node.id: node for node in db.scalars(select(KnowledgePoint))}
            rows = []
            for q in db.scalars(select(Question).where(Question.bank_scope == "public", Question.generation_batch_id.is_(None))):
                node = nodes.get(q.kp_id)
                eligibility = question_eligibility(q, node, teaching_enabled=False)
                try:
                    independent = verify_problem(q)
                except Exception as exc:
                    independent = {"status": "ERROR", "reason": type(exc).__name__}
                rows.append({"question_id": str(q.id), "node_code": node.code if node else None,
                    "node_name": node.name if node else None, "historical_identity": historical_identity(q),
                    "active": q.is_active, "hidden": q.is_hidden, "question_type": q.question_type,
                    "stem": q.stem, "options": q.options, "answer": q.correct_answer, "explanation": q.explanation,
                    "eligibility": eligibility.public_dict(), "independent_verification": independent,
                    "formal": eligibility.practice_eligible and eligibility.evidence_capability == "verified_objective"})
            if all_table_fingerprints(db.connection()) != before:
                raise RuntimeError("read_only_fingerprints_changed")
        candidates = [row for row in rows if row["active"] and not row["hidden"] and not row["formal"]
            and row["independent_verification"].get("status") == "PASS"]
        report = {"status": "WHOLE_BANK_READ_ONLY_AUDIT_COMPLETE", "verifier_version": VERSION,
            "source_database": name, "port": PORT, "rows_checked": len(rows),
            "historical_rows_checked": sum(row["historical_identity"] is not None for row in rows),
            "formal": sum(row["formal"] for row in rows),
            "independent_statuses": dict(Counter(row["independent_verification"].get("status") for row in rows)),
            "active_nonformal_solver_pass_candidates": len(candidates),
            "candidates": candidates, "all_table_fingerprints_unchanged": True,
            "paid_calls": 0, "development_5433_touched": False, "questions": rows}
        save(OUT / "report.json", report)
        print(json.dumps({key: value for key, value in report.items() if key not in {"questions", "candidates"}}, ensure_ascii=False), flush=True)
        print(json.dumps([{key: row[key] for key in ("question_id", "node_code", "node_name", "historical_identity")}
            for row in candidates], ensure_ascii=False), flush=True)
        return 0
    finally:
        engine.dispose()
        if started:
            owner.command([str(owner.PG_BIN / "pg_ctl.exe"), "-D", str(cluster), "-m", "fast", "-w", "-t", "60", "stop"], timeout=75, check=False)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
