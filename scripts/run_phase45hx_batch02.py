"""Recover a complete archived question in a new owned isolated DB clone.

No application settings or production DB URLs are used. Detailed source text,
reports and backups remain in ignored local storage. Existing H-X checkpoints
and old learning records are preserved.
"""
from __future__ import annotations

from collections import Counter
import csv
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_phase45hx_batch01 import all_table_fingerprints, run_logged, save

SOURCE_RUN = ROOT / "storage/quality-audits/phase45hx-20261010/batch-10"
OUT = ROOT / "storage/quality-audits/phase45hx-20261010/batch-12"
PACK = ROOT / "storage/question-intake/phase45hx-20261010/phase45hx-408-2016-v1.json"
PDF = Path("C:/Users/ZBT/Desktop/考研知识点/408/2016/2016年计算机408统考真题.pdf")
PDF_SHA = "67d722ec87e449c4c3949f7965bb325a63c085d1d186561f6b71058a8d9a559b"
PORT = 59227
SYSTEM_ID = "7694698872540080852"
REVISION = "f50c7e2a1b64"
PROTECTED = ("question_attempts", "learning_events", "kp_states", "kp_mastery_policies")
EXPECTED_QUESTIONS = 1
SOURCE_SUCCESS_STATUS = "BATCH_01_COMPLETE"
PHASE_LABEL = "4.5H-X-batch-02"
SUCCESS_STATUS = "BATCH_02_COMPLETE"
TEST_FILES = ["tests/integration/test_phase45hx_recovery.py", "tests/unit/test_phase45hx_math_verifiers.py",
    "tests/unit/test_phase45hx_recovery.py", "tests/unit/test_phase45hs_verifiers.py",
    "tests/unit/test_phase45hs_identity.py", "tests/unit/test_phase45i_quality_verifiers.py",
    "tests/integration/test_auto_question_review.py", "tests/integration/test_phase45hw_graduation.py",
    "tests/integration/test_question_pack_import.py", "tests/integration/test_phase45hs_duplicates.py",
    "tests/unit/test_question_generation.py", "tests/unit/test_phase45i_agent_close.py",
    "tests/integration/test_personal_question_bank.py",
    "tests/integration/test_agent_learning_journey.py", "tests/integration/test_learning_loop.py"]
# An optional, per-source-item Codex review receipt lets a batch use the
# existing hash-bound independent-review path instead of requiring a bespoke
# deterministic solver adapter. Empty by default; existing batches are unchanged.
CODEX_REVIEW_EVIDENCE: dict[str, dict] = {}
TEST_ARGS: list[str] = []
PROCESS_PACK = True
CODEX_PUBLIC_ORIGINALS: list[dict] = []


def inventory(db):
    from sqlalchemy import select
    from backend.models.learning import Question, KnowledgePoint, KpMasteryPolicy
    from backend.services.question_eligibility import question_eligibility
    from backend.services.question_identity import duplicate_findings
    nodes = list(db.scalars(select(KnowledgePoint).where(
        KnowledgePoint.is_active.is_(True), KnowledgePoint.is_assessable.is_(True))))
    node_by_id = {node.id: node for node in nodes}
    policies = {row.kp_id: row for row in db.scalars(select(KpMasteryPolicy))}
    rows = list(db.scalars(select(Question).where(Question.bank_scope == "public",
        Question.generation_batch_id.is_(None))))
    qualified = []
    for question in rows:
        node = node_by_id.get(question.kp_id)
        if node is None:
            continue
        eligibility = question_eligibility(question, node, teaching_enabled=False)
        if (eligibility.practice_eligible and eligibility.evidence_capability == "verified_objective"
                and eligibility.grading_capability == "deterministic"):
            qualified.append(question)
    sets = []
    for node in nodes:
        candidates = sorted((q for q in qualified if q.kp_id == node.id),
            key=lambda q: (q.question_role != "typical", q.difficulty != "medium", str(q.id)))
        unique = []
        for question in candidates:
            findings = duplicate_findings(question, unique)
            if not findings["matches"] and not findings["uncertain_similar"]:
                unique.append(question)
        sets.append({"node_code": node.code, "node_name": node.name, "subject": node.subject,
            "is_reference_only": node.is_reference_only, "has_policy": node.id in policies,
            "eligible_question_count": len(candidates), "unique_question_count": len(unique),
            "candidate_question_ids": [str(q.id) for q in unique[:20]],
            "status": "CANDIDATE_NEEDS_CONTENT_COVERAGE_REVIEW" if unique else "WAITING_FOR_QUALIFIED_QUESTIONS",
            "selection_reason": "current trusted public objective questions, deduplicated; node-wide teaching coverage must still be reviewed; no set frozen"})
    return {"public_total": len(rows), "active_public": sum(q.is_active for q in rows),
        "formal_eligible": len(qualified), "formal_by_subject": dict(Counter(node_by_id[q.kp_id].subject for q in qualified)),
        "formal_by_review_version": dict(Counter(q.current_auto_review.review_version
            if q.current_auto_review else "human_verified" for q in qualified)),
        "assessable_nodes": len(nodes), "policies": len(policies),
        "nodes_with_formal_questions": sum(row["eligible_question_count"] > 0 for row in sets),
        "nodes_with_nonempty_candidates": sum(bool(row["candidate_question_ids"]) for row in sets),
        "nodes_waiting": sum(not row["candidate_question_ids"] for row in sets),
        "frozen_sets": sum(bool(row.graduation_question_ids) for row in policies.values()),
        "candidates": sets}


def main():
    if OUT.exists() and any(OUT.iterdir()):
        raise RuntimeError("refuse_overwrite_existing_batch")
    if PDF is not None and sha256(PDF.read_bytes()).hexdigest() != PDF_SHA:
        raise RuntimeError("source_pdf_fingerprint_changed")
    prior = json.loads((SOURCE_RUN / "checkpoint.json").read_text(encoding="utf-8"))
    source_name = prior.get("clone", {}).get("database")
    if (prior.get("status") != SOURCE_SUCCESS_STATUS or prior.get("port") != PORT
            or prior.get("system_identifier_expected") != SYSTEM_ID
            or prior.get("clone", {}).get("revision_after") != REVISION
            or not isinstance(source_name, str) or not source_name.startswith("phase45hx_")
            or not source_name.endswith("_test") or PORT == 5433):
        raise RuntimeError("source_checkpoint_ownership_mismatch")
    pack = None
    if PROCESS_PACK:
        from backend.services.question_pack import QuestionPack
        pack = QuestionPack.model_validate(json.loads(PACK.read_text(encoding="utf-8")))
        if len(pack.questions) != EXPECTED_QUESTIONS or not 1 <= EXPECTED_QUESTIONS <= 10:
            raise RuntimeError("unexpected_batch_question_count")
    OUT.mkdir(parents=True, exist_ok=True)
    result = {"phase": PHASE_LABEL, "status": "STARTED", "paid_model_calls": 0,
        "development_5433_touched": False, "source_database": source_name,
        "source_checkpoint": str(SOURCE_RUN.relative_to(ROOT)), "port": PORT,
        "system_identifier_expected": SYSTEM_ID, "source_pdf_sha256": PDF_SHA if PDF is not None else None,
        "pack_sha256": sha256(PACK.read_bytes()).hexdigest() if PROCESS_PACK else None}
    if PROCESS_PACK:
        mapping_path = ROOT / "tmp/phase1_20261006/candidate_question_mapping.csv"
        with mapping_path.open(encoding="utf-8-sig", newline="") as stream:
            mapping = list(csv.DictReader(stream))
        from backend.services.question_attestation import _subject
        candidates = []
        for item in pack.questions:
            matching = [row for row in mapping if _subject(row.get("subject")) == _subject(item.source.subject)
                and row.get("year") == str(item.source.year) and row.get("question_number") == str(item.source.question_number)]
            if len(matching) != 1 or matching[0].get("mapping_status") != "UNMATCHED":
                raise RuntimeError("old_candidate_identity_or_mapping_changed")
            candidates.append(matching[0])
        result["old_candidates"] = candidates
        result["old_unmatched_total"] = sum(row.get("mapping_status") == "UNMATCHED" for row in mapping)
    else:
        result["old_candidates"] = []
        result["old_unmatched_total"] = None
    result["code_sha256"] = {path: sha256((ROOT / path).read_bytes()).hexdigest() for path in (
        "backend/services/phase45hs_verifiers.py", "backend/services/quality_verifiers.py",
        "backend/services/auto_question_review.py", "backend/services/graduation_question_set.py",
        "backend/services/phase45hx_math_verifiers.py", "backend/services/phase45hx_exam_verifiers.py",
        "backend/services/question_generation.py",
        "backend/mastery/origin_evidence.py", "scripts/run_phase45hx_batch02.py")}
    from scripts import run_phase45i_agent_real as owner
    _, cluster, owned_port = owner.load_existing_owner()
    if owned_port != PORT:
        raise RuntimeError("isolated_port_ownership_mismatch")
    owner.OUT_DIR = OUT / "postgres-runtime"
    owner.OUT_DIR.mkdir()
    started = owner.start_owned_database(cluster, PORT)
    from psycopg import connect, sql
    from sqlalchemy import create_engine, text, select
    clone_name = "phase45hx_" + uuid4().hex[:12] + "_test"
    test_name = "phase45hxtest_" + uuid4().hex[:10] + "_test"
    test_created = False
    engine = None
    try:
        with connect(host="127.0.0.1", port=PORT, user="postgres", dbname="postgres",
                autocommit=True, connect_timeout=5) as server:
            if str(server.execute("SELECT system_identifier FROM pg_control_system()").fetchone()[0]) != SYSTEM_ID:
                raise RuntimeError("system_identifier_mismatch")
            if server.execute("SELECT count(*) FROM pg_stat_activity WHERE datname=%s", (source_name,)).fetchone()[0]:
                raise RuntimeError("source_has_active_connections")
        source_engine = create_engine(f"postgresql+psycopg://postgres@127.0.0.1:{PORT}/{source_name}")
        try:
            with source_engine.connect() as connection:
                connection.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                if connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() != REVISION:
                    raise RuntimeError("unexpected_source_revision")
                before = all_table_fingerprints(connection)
        finally:
            source_engine.dispose()
        pg_env = {key: value for key, value in os.environ.items() if not key.upper().startswith("PG")}
        dump = OUT / "source-checkpoint.dump"
        rc = run_logged([str(owner.PG_BIN / "pg_dump.exe"), "--format=custom", "--no-owner", "--no-acl",
            "--host=127.0.0.1", f"--port={PORT}", "--username=postgres", f"--dbname={source_name}",
            f"--file={dump}"], OUT / "pg-dump.log", env=pg_env, timeout=300)
        if rc or not dump.is_file() or not dump.stat().st_size:
            raise RuntimeError("source_backup_failed")
        toc = owner.command([str(owner.PG_BIN / "pg_restore.exe"), "--list", str(dump)])
        if "TABLE DATA" not in toc.stdout:
            raise RuntimeError("source_backup_toc_invalid")
        result["backup"] = {"sha256": sha256(dump.read_bytes()).hexdigest(),
            "size_bytes": dump.stat().st_size, "toc_readable": True}
        with connect(host="127.0.0.1", port=PORT, user="postgres", dbname="postgres",
                autocommit=True, connect_timeout=5) as server:
            server.execute(sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(sql.Identifier(clone_name), sql.Identifier(source_name)))
            server.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(sql.Identifier(test_name)))
        test_created = True
        engine = create_engine(f"postgresql+psycopg://postgres@127.0.0.1:{PORT}/{clone_name}")
        with engine.connect() as connection:
            if all_table_fingerprints(connection) != before:
                raise RuntimeError("source_clone_fingerprints_differ")
        result["clone"] = {"database": clone_name, "revision_after": REVISION, "source_clone_fingerprints_match": True}
        test_out = OUT / "pytest-offline"
        test_out.mkdir()
        test_url = f"postgresql+psycopg://postgres@127.0.0.1:{PORT}/{test_name}"
        env = {**os.environ, "APP_ENV": "test", "TEST_DATABASE_URL": test_url, "DATABASE_URL": test_url,
            "KAOYAN_OWNED_TEST_PORT": str(PORT), "PHASE45I_CLOSE_OFFLINE": "1", "PHASE45I_CLOSE_OUTPUT": str(test_out),
            "LLM_API_KEY": "", "LLM_BASE_URL": "http://127.0.0.1:9", "LLM_MODEL": "offline",
            "PYTHONIOENCODING": "utf-8", "UPLOAD_DIR": str(test_out / "uploads"),
            "CHROMA_DIR": str(test_out / "chroma"), "MODEL_SETTINGS_PATH": str(test_out / "settings.bin")}
        files = TEST_FILES
        rc = run_logged([sys.executable, "-m", "pytest", *files, *TEST_ARGS, "-q", "-x", "-o", "addopts=", "-o", "faulthandler_timeout=120",
            "--basetemp", str(test_out / "pytest-tmp")], test_out / "pytest.log", env=env, timeout=1800)
        result["tests"] = {"exit_code": rc, "files": files, "extra_args": TEST_ARGS,
            "log": str((test_out / "pytest.log").relative_to(ROOT))}
        if rc:
            raise RuntimeError("preflight_tests_failed_no_question_writes")
        from backend.db import create_session_factory
        from backend.models.learning import Question, KnowledgePoint
        from backend.services.question_pack import import_pack
        from backend.services.question_repair import local_pack_registry
        from backend.services.auto_question_review import (attach_codex_independent_review,
            prepare_exam_curated_repair, qualify_public_question, question_snapshot_sha256,
            assess_auto_qualification)
        from scripts.audit_phase45h_completion_archive import source_pack_evidence
        from backend.services.question_generation import prepare_codex_public_original
        factory = create_session_factory(engine)
        with factory() as db:
            result["before_inventory"] = inventory(db)
            if PROCESS_PACK:
                preview = import_pack(db, pack, apply=False)
                db.rollback()
            else:
                preview = {"mode":"not_run","new":0,"unchanged":0,"duplicates":0,"identity_conflicts":0}
        result["import_preview"] = preview
        if PROCESS_PACK and (preview["new"] != EXPECTED_QUESTIONS or preview["duplicates"] or preview["identity_conflicts"]):
            raise RuntimeError("unexpected_duplicate_or_import_identity_stop")
        registry, _ = local_pack_registry(ROOT)
        with factory() as db:
            imported = import_pack(db, pack, apply=True) if PROCESS_PACK else {"new":0,"unchanged":0}
            result["qualification"] = []
            result["recovery"] = []
            result["new_question_rows"] = imported["new"]
            for item in pack.questions if PROCESS_PACK else []:
                question = db.scalar(select(Question).where(Question.grading_config["provenance"]["key"].as_string()
                    == f"{pack.pack_id}:{item.source_id}"))
                node = db.get(KnowledgePoint, question.kp_id)
                source = source_pack_evidence(question, registry, node)
                if source is None:
                    raise RuntimeError("source_binding_unavailable")
                review_evidence = CODEX_REVIEW_EVIDENCE.get(item.source_id)
                if review_evidence:
                    receipt = attach_codex_independent_review(question, node, **review_evidence)
                    repair = {"kind": "codex_independent_review", "version": receipt["version"],
                        "question_content_sha256": receipt["question_content_sha256"],
                        "human_verified": False, "used_fixed_solver_family": False}
                else:
                    repair = prepare_exam_curated_repair(question, node, source)
                db.flush()
                source = source_pack_evidence(question, registry, node)
                snapshot = question_snapshot_sha256(question)
                key = f"{PHASE_LABEL}:{question.id}:{snapshot}"
                event, assessment = qualify_public_question(db, question_id=question.id, node_id=node.id,
                    expected_snapshot_sha256=snapshot, idempotency_key=key, source_evidence=source)
                result["qualification"].append(assessment)
                if event is None or assessment["status"] != "AUTO_VERIFIED":
                    raise RuntimeError("restored_question_not_auto_verified_rolled_back")
                repeated, noop = qualify_public_question(db, question_id=question.id, node_id=node.id,
                    expected_snapshot_sha256=snapshot, idempotency_key=key, source_evidence=source)
                if noop["status"] != "NOOP" or repeated.id != event.id:
                    raise RuntimeError("qualification_idempotency_failed")
                result["recovery"].append({"question_id": str(question.id),
                    "node_code": node.code, "source_identity": [_subject(item.source.subject), item.source.year, item.source.question_number],
                    "repair": repair, "qualification_idempotency": noop, "human_verified": False,
                    "public_redistribution_rights": "UNCONFIRMED"})
            result["codex_public_originals"] = []
            for spec in CODEX_PUBLIC_ORIGINALS:
                node = db.scalar(select(KnowledgePoint).where(KnowledgePoint.code == spec["node_code"]))
                if node is None:
                    result["codex_public_originals"].append({"request_id":spec["request_id"],"status":"REJECTED","reason":"node_not_found"})
                    continue
                try:
                    question = prepare_codex_public_original(spec["output"], node,
                        request_id=spec["request_id"], derived_answer=spec["derived_answer"],
                        method_evidence=spec["method_evidence"],
                        explanation_key_steps=spec["explanation_key_steps"],
                        option_truth_table=spec.get("option_truth_table"),
                        difficulty=spec.get("difficulty","medium"),skill_tags=spec.get("skill_tags"),
                        difficulty_reason=spec["difficulty_reason"])
                    existing=list(db.scalars(select(Question).where(
                        Question.bank_scope=="public",Question.generation_batch_id.is_(None))))
                    assessment=assess_auto_qualification(db,question,node,all_questions=existing)
                    if assessment.get("status")!="AUTO_VERIFIED":
                        result["codex_public_originals"].append({"request_id":spec["request_id"],
                            "node_code":node.code,"status":assessment.get("status"),
                            "blockers":assessment.get("blocking_reasons",[]),"assessment":assessment})
                        continue
                    savepoint=db.begin_nested()
                    try:
                        db.add(question);db.flush()
                        snapshot=question_snapshot_sha256(question)
                        key=f"{PHASE_LABEL}:codex-original:{question.id}:{snapshot}"
                        event,qualified=qualify_public_question(db,question_id=question.id,node_id=node.id,
                            expected_snapshot_sha256=snapshot,idempotency_key=key)
                        if event is None or qualified.get("status")!="AUTO_VERIFIED":
                            raise RuntimeError("codex_original_qualification_failed")
                        repeated,noop=qualify_public_question(db,question_id=question.id,node_id=node.id,
                            expected_snapshot_sha256=snapshot,idempotency_key=key)
                        if noop.get("status")!="NOOP" or repeated.id!=event.id:
                            raise RuntimeError("codex_original_qualification_not_idempotent")
                        savepoint.commit()
                    except Exception:
                        savepoint.rollback()
                        raise
                    result["qualification"].append(qualified)
                    result["codex_public_originals"].append({"request_id":spec["request_id"],
                        "question_id":str(question.id),"node_code":node.code,
                        "status":"AUTO_VERIFIED","qualification_class":event.qualification_class,
                        "human_verified":False,"idempotency":noop})
                    result["new_question_rows"] += 1
                except Exception as exc:
                    result["codex_public_originals"].append({"request_id":spec.get("request_id"),
                        "node_code":spec.get("node_code"),"status":"REJECTED",
                        "reason":type(exc).__name__+":"+str(exc)[:250]})
            result["restored_question_ids"] = [row["question_id"] for row in result["recovery"]]
            db.commit()
        with factory() as db:
            result["after_inventory"] = inventory(db)
            after = all_table_fingerprints(db.connection())
            result["protected_history"] = {"before": {key: before[key] for key in PROTECTED},
                "after": {key: after[key] for key in PROTECTED},
                "unchanged": all(before[key] == after[key] for key in PROTECTED)}
            if not result["protected_history"]["unchanged"]:
                raise RuntimeError("existing_history_or_policy_changed")
        result["status"] = SUCCESS_STATUS
        save(OUT / "checkpoint.json", result)
        print(json.dumps({key: result[key] for key in ("status", "clone", "recovery", "tests", "paid_model_calls", "development_5433_touched")}, ensure_ascii=False, default=str), flush=True)
        return 0
    except Exception as exc:
        result.update({"status": "BLOCKED_EXCEPTION", "error_type": type(exc).__name__, "error": str(exc)[:500]})
        save(OUT / "checkpoint.json", result)
        print(json.dumps({key: result[key] for key in ("status", "error_type", "error")}, ensure_ascii=False), flush=True)
        return 1
    finally:
        if engine is not None:
            engine.dispose()
        if test_created:
            with connect(host="127.0.0.1", port=PORT, user="postgres", dbname="postgres", autocommit=True, connect_timeout=5) as server:
                if not server.execute("SELECT count(*) FROM pg_stat_activity WHERE datname=%s", (test_name,)).fetchone()[0]:
                    server.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(test_name)))
        if started:
            owner.command([str(owner.PG_BIN / "pg_ctl.exe"), "-D", str(cluster), "-m", "fast", "-w", "-t", "60", "stop"], timeout=75, check=False)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
