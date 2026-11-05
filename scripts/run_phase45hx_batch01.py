"""Run the first recoverable Phase 4.5H-X question batch on an owned DB clone.

This runner is pinned to the previously audited H-U PostgreSQL test cluster.
It never derives a connection from application settings and never touches the
development database. Source snapshots are immutable; all writes target a new
private ``_test`` clone under the explicitly owned test port.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE_RUN = ROOT / "storage/quality-audits/phase45hu-20261010-public-batch-12"
OUT = ROOT / "storage/quality-audits/phase45hx-20261010/batch-10"
PORT = 59227
SYSTEM_ID = "7694698872540080852"
SOURCE_REVISION = "f49d10c2a703"
MIGRATED_REVISION = "f50c7e2a1b64"
PACK_PATH = ROOT / "storage/question-intake/phase45hx-20261010/phase45hx-408-2026-v1.json"


def save(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".new")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temporary.replace(path)


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def all_table_fingerprints(connection) -> dict:
    from sqlalchemy import text
    tables = connection.execute(text("""SELECT tablename FROM pg_tables
        WHERE schemaname='public' ORDER BY tablename""")).fetchall()
    result = {}
    for (name,) in tables:
        quoted = '"' + name.replace('"', '""') + '"'
        rows = [dict(row) for row in connection.execute(text(f"SELECT * FROM public.{quoted}")).mappings()]
        rows.sort(key=canonical)
        raw = canonical(rows)
        result[name] = {"count": len(rows), "sha256": sha256(raw).hexdigest()}
    return result


def run_logged(command: list[str], log_path: Path, *, env: dict[str, str], timeout: int) -> int:
    with log_path.open("w", encoding="utf-8") as log:
        completed = subprocess.run(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    return completed.returncode


def main() -> int:
    if OUT.exists() and any(OUT.iterdir()):
        raise RuntimeError("phase45hx_output_exists_refuse_overwrite")
    if not PACK_PATH.is_file() or not PACK_PATH.resolve().is_relative_to((ROOT / "storage/question-intake").resolve()):
        raise RuntimeError("private_question_pack_missing_or_outside_intake")
    OUT.mkdir(parents=True, exist_ok=True)

    from scripts import run_phase45i_agent_real as owner
    _, cluster, owned_port = owner.load_existing_owner()
    if owned_port != PORT or owned_port == 5433 or cluster.name != "postgres-cluster":
        raise RuntimeError("expected_existing_owned_isolated_cluster")
    owner.OUT_DIR = OUT / "postgres-runtime"
    owner.OUT_DIR.mkdir()
    started = owner.start_owned_database(cluster, PORT)

    from psycopg import connect, sql
    from sqlalchemy import create_engine, func, select, text
    result = {"phase": "4.5H-X-batch-01", "status": "STARTED", "paid_model_calls": 0,
        "development_5433_touched": False, "source_run": str(SOURCE_RUN.relative_to(ROOT)),
        "port": PORT, "system_identifier_expected": SYSTEM_ID, "started_by_this_run": started,
        "migration_from": SOURCE_REVISION, "migration_to": MIGRATED_REVISION}
    clone_name = "phase45hx_" + uuid4().hex[:12] + "_test"
    test_name = "phase45hxtest_" + uuid4().hex[:10] + "_test"
    test_db_created = False
    try:
        source_state = json.loads((SOURCE_RUN / "owner.json").read_text(encoding="utf-8"))
        source_name = source_state.get("database")
        if (source_state.get("port") != PORT or source_state.get("system_identifier") != SYSTEM_ID
                or source_state.get("source_revision") != SOURCE_REVISION
                or not isinstance(source_name, str) or not source_name.startswith("phase45hu_")
                or not source_name.endswith("_test")):
            raise RuntimeError("audited_hu_source_owner_mismatch")

        with connect(host="127.0.0.1", port=PORT, user="postgres", dbname="postgres",
                     autocommit=True, connect_timeout=5) as server:
            system_id = str(server.execute("SELECT system_identifier FROM pg_control_system()").fetchone()[0])
            if system_id != SYSTEM_ID:
                raise RuntimeError("isolated_cluster_system_id_mismatch")
            if server.execute("SELECT count(*) FROM pg_stat_activity WHERE datname=%s", (source_name,)).fetchone()[0]:
                raise RuntimeError("source_database_has_active_connections_refuse_snapshot")
            if server.execute("SELECT count(*) FROM pg_database WHERE datname IN (%s,%s)",
                              (clone_name, test_name)).fetchone()[0]:
                raise RuntimeError("generated_database_name_collision")

        source_url = f"postgresql+psycopg://postgres@127.0.0.1:{PORT}/{source_name}"
        source_engine = create_engine(source_url, connect_args={"connect_timeout": 5})
        try:
            with source_engine.connect() as connection:
                connection.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                if revision != SOURCE_REVISION:
                    raise RuntimeError("source_database_revision_mismatch")
                before = all_table_fingerprints(connection)
            result["source_baseline"] = {"revision": revision, "tables": before,
                "question_count": before.get("questions", {}).get("count"),
                "policy_count": before.get("kp_mastery_policies", {}).get("count"),
                "attempt_count": before.get("question_attempts", {}).get("count"),
                "learning_event_count": before.get("learning_events", {}).get("count"),
                "kp_state_count": before.get("kp_states", {}).get("count")}
        finally:
            source_engine.dispose()

        dump_path = OUT / "source-checkpoint.dump"
        pg_dump = owner.PG_BIN / "pg_dump.exe"
        pg_restore = owner.PG_BIN / "pg_restore.exe"
        pg_env = {key: value for key, value in os.environ.items() if not key.upper().startswith("PG")}
        dump_rc = run_logged([str(pg_dump), "--format=custom", "--no-owner", "--no-acl",
            "--host=127.0.0.1", f"--port={PORT}", "--username=postgres", f"--dbname={source_name}",
            f"--file={dump_path}"], OUT / "pg-dump.log", env=pg_env, timeout=300)
        if dump_rc != 0 or not dump_path.is_file() or dump_path.stat().st_size == 0:
            raise RuntimeError("source_checkpoint_dump_failed")
        toc = subprocess.run([str(pg_restore), "--list", str(dump_path)], cwd=ROOT,
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if toc.returncode != 0 or "TABLE DATA" not in toc.stdout:
            raise RuntimeError("source_checkpoint_restore_toc_invalid")
        result["backup"] = {"path": str(dump_path.relative_to(ROOT)), "size_bytes": dump_path.stat().st_size,
            "sha256": sha256(dump_path.read_bytes()).hexdigest(), "pg_restore_list_exit": toc.returncode,
            "toc_entries": len(toc.stdout.splitlines()), "readable": True}

        with connect(host="127.0.0.1", port=PORT, user="postgres", dbname="postgres",
                     autocommit=True, connect_timeout=5) as server:
            server.execute(sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                sql.Identifier(clone_name), sql.Identifier(source_name)))
        clone_url = f"postgresql+psycopg://postgres@127.0.0.1:{PORT}/{clone_name}"
        clone_engine = create_engine(clone_url, connect_args={"connect_timeout": 5})
        try:
            with clone_engine.connect() as connection:
                clone_before = all_table_fingerprints(connection)
                if clone_before != before:
                    raise RuntimeError("template_clone_fingerprint_mismatch")
                clone_core_before = {name: clone_before.get(name) for name in
                    ("questions", "question_attempts", "learning_events", "kp_states", "kp_mastery_policies")}
            migration_env = {**os.environ, "APP_ENV": "test", "DATABASE_URL": clone_url,
                "TEST_DATABASE_URL": clone_url, "KAOYAN_OWNED_TEST_PORT": str(PORT),
                "LLM_API_KEY": "", "LLM_BASE_URL": "http://127.0.0.1:9", "LLM_MODEL": "offline",
                "PYTHONIOENCODING": "utf-8"}
            migration_rc = run_logged([sys.executable, "-m", "alembic", "upgrade", "head"],
                OUT / "clone-migration.log", env=migration_env, timeout=300)
            if migration_rc != 0:
                raise RuntimeError("isolated_clone_migration_failed")
            with clone_engine.connect() as connection:
                migrated = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                clone_after_migration = all_table_fingerprints(connection)
                if migrated != MIGRATED_REVISION:
                    raise RuntimeError("isolated_clone_unexpected_revision")
                protected = {name: clone_after_migration.get(name) for name in
                    ("questions", "question_attempts", "learning_events", "kp_states")}
                if protected != {name: clone_core_before.get(name) for name in protected}:
                    raise RuntimeError("migration_changed_question_or_learning_history")
                policy_rows = connection.execute(text("""SELECT count(*), count(*) FILTER (WHERE policy_version=3),
                    count(*) FILTER (WHERE graduation_set_version>0 OR graduation_question_ids::jsonb <> '[]'::jsonb)
                    FROM kp_mastery_policies""")).fetchone()
                set_rows = connection.execute(text("SELECT count(*) FROM kp_graduation_question_set_versions")).scalar_one()
            result["clone"] = {"database": clone_name, "revision_after": migrated,
                "source_and_clone_fingerprints_match_before_migration": True,
                "policy_rows_after_migration": policy_rows[0], "v3_policies_after_migration": policy_rows[1],
                "frozen_sets_after_migration": policy_rows[2], "set_history_rows": set_rows,
                "protected_content_and_history_unchanged_by_migration": True}

            with connect(host="127.0.0.1", port=PORT, user="postgres", dbname="postgres",
                         autocommit=True, connect_timeout=5) as server:
                server.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(
                    sql.Identifier(test_name)))
            test_db_created = True
            test_url = f"postgresql+psycopg://postgres@127.0.0.1:{PORT}/{test_name}"
            test_out = OUT / "pytest-offline"
            test_out.mkdir()
            test_env = {**os.environ, "APP_ENV": "test", "DATABASE_URL": test_url,
                "TEST_DATABASE_URL": test_url, "KAOYAN_OWNED_TEST_PORT": str(PORT),
                "PHASE45I_CLOSE_OFFLINE": "1", "PHASE45I_CLOSE_OUTPUT": str(test_out),
                "LLM_API_KEY": "", "LLM_BASE_URL": "http://127.0.0.1:9", "LLM_MODEL": "offline",
                "PYTHONIOENCODING": "utf-8", "UPLOAD_DIR": str(test_out / "uploads"),
                "CHROMA_DIR": str(test_out / "chroma"), "MODEL_SETTINGS_PATH": str(test_out / "settings.bin")}
            test_files = ["tests/unit/test_phase45d_verifiers.py", "tests/unit/test_phase45i_quality_verifiers.py",
                "tests/unit/test_phase45hs_identity.py", "tests/unit/test_question_attestation.py",
                "tests/integration/test_auto_question_review.py",
                "tests/integration/test_question_pack_import.py", "tests/integration/test_phase45hw_graduation.py",
                "tests/integration/test_agent_learning_journey.py", "tests/integration/test_learning_loop.py"]
            pytest_rc = run_logged([sys.executable, "-m", "pytest", *test_files, "-q", "-o", "addopts=",
                "--basetemp", str(test_out / "pytest-tmp")],
                test_out / "pytest.log", env=test_env, timeout=1800)
            summary = {"exit_code": pytest_rc, "files": test_files,
                "log": str((test_out / "pytest.log").relative_to(ROOT)),
                "network_guard": json.loads((test_out / "offline-network-guard.json").read_text(encoding="utf-8"))
                    if (test_out / "offline-network-guard.json").exists() else None}
            if pytest_rc != 0:
                result["focused_tests"] = summary
                result["status"] = "BLOCKED_TESTS"
                save(OUT / "checkpoint.json", result)
                print(json.dumps(result, ensure_ascii=False, default=str), flush=True)
                return 1
            result["focused_tests"] = summary

            # Import and qualify one source-traceable, precisely bounded item.
            from backend.models.learning import (Question, KnowledgePoint, KpMasteryPolicy,
                QuestionAttempt, LearningEvent, KpState, QuestionAutoReviewEvent)
            from backend.models import import_models
            from backend.db import create_session_factory
            from backend.services.question_pack import QuestionPack, import_pack
            from backend.services.auto_question_review import (question_snapshot_sha256,
                qualify_public_question, prepare_exam_curated_repair)
            from scripts.run_question_repair_pilot import local_pack_registry
            from scripts.audit_phase45h_completion_archive import source_pack_evidence
            from backend.services.question_identity import historical_identity, normalized_text
            from backend.services.question_attestation import _subject
            import_models()
            factory = create_session_factory(clone_engine)
            payload = json.loads(PACK_PATH.read_text(encoding="utf-8"))
            pack = QuestionPack.model_validate(payload)
            registry, rejected_files = local_pack_registry(ROOT)
            pack_question = pack.questions[0]
            source_fingerprint = sha256(PACK_PATH.read_bytes()).hexdigest()
            protected_models = (QuestionAttempt, LearningEvent, KpState, KpMasteryPolicy)
            with factory() as db:
                db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
                protected_before = {model.__tablename__: all_table_fingerprints(db.connection())[model.__tablename__]
                    for model in protected_models}
            with factory() as db:
                preview = import_pack(db, pack, apply=False)
                db.rollback()
            result["question_batch"] = {"pack_id": pack.pack_id, "version": pack.version,
                "pack_file_sha256": source_fingerprint, "local_registry_rejected_files": len(rejected_files),
                "dry_run": preview}
            node = None
            question = None
            with factory() as db:
                node = db.scalar(select(KnowledgePoint).where(KnowledgePoint.code == pack_question.kp_code))
                identity = (_subject(pack_question.source.subject), pack_question.source.year,
                    pack_question.source.question_number)
                public_rows = list(db.scalars(select(Question).where(Question.kp_id == node.id,
                    Question.bank_scope == "public", Question.generation_batch_id.is_(None)))) if node else []
                matches = [row for row in public_rows if historical_identity(row) == identity]
                if node is None or len(matches) != 1:
                    raise RuntimeError(f"expected_one_existing_canonical_exam_identity_found_{len(matches)}")
                question = matches[0]
                result["question_batch"].update({"canonical_existing_question_id": str(question.id),
                    "canonical_identity": list(identity), "canonical_stem_matches_candidate_after_whitespace_normalization":
                        normalized_text(question.stem) == normalized_text(pack_question.stem),
                    "new_question_rows_expected": 0,
                    "dedup_resolution": "same_public_exam_subject_year_question; repair canonical record instead of creating a second row"})
                if preview.get("new"):
                    raise RuntimeError("import_pack_did_not_block_same_exam_identity")
                from backend.services.auto_question_review import current_auto_review
                if current_auto_review(question, node):
                    db.rollback()
                    result["question_batch"].update({"result": "EXISTING_CANONICAL_ALREADY_AUTO_VERIFIED",
                        "question_id": str(question.id)})
                else:
                    evidence = source_pack_evidence(question, registry, node)
                    if evidence is None:
                        db.rollback()
                        raise RuntimeError("existing_canonical_source_pack_evidence_unavailable")
                    repair = prepare_exam_curated_repair(question, node, evidence)
                    db.flush()
                    evidence = source_pack_evidence(question, registry, node)
                    snapshot_sha = question_snapshot_sha256(question)
                    event, assessment = qualify_public_question(db, question_id=question.id,
                        node_id=node.id, expected_snapshot_sha256=snapshot_sha,
                        idempotency_key=f"phase45hx-batch01:{question.id}:{snapshot_sha}",
                        source_evidence=evidence)
                    if event is None or assessment.get("status") != "AUTO_VERIFIED":
                        duplicate_stage = assessment.get("stages", {}).get("duplicates", {})
                        near_ids = duplicate_stage.get("near", [])
                        near_rows = (db.scalars(select(Question).where(Question.id.in_(near_ids))).all()
                            if near_ids else [])
                        near_details = [{"question_id": str(row.id), "node_code": node.code,
                            "stem": row.stem, "question_type": row.question_type,
                            "options": row.options, "answer": row.correct_answer,
                            "source": ((row.grading_config or {}).get("provenance", {}).get("source", {}))}
                            for row in near_rows]
                        db.rollback()
                        result["question_batch"].update({"result": "EXISTING_CANONICAL_REPAIR_BLOCKED",
                            "review_status": assessment.get("status"), "stages": assessment.get("stages"),
                            "near_duplicate_details": near_details, "repair_preview": repair})
                    else:
                        db.commit()
                        result["question_batch"].update({"result": "REPAIRED_EXISTING_AUTO_VERIFIED",
                            "question_id": str(question.id), "question_node": node.code,
                            "qualification_class": assessment.get("qualification_class"),
                            "review_version": event.review_version, "event_id": str(event.id),
                            "question_snapshot_sha256": event.question_snapshot_sha256,
                            "answer_sha256": event.answer_sha256, "stages": assessment.get("stages"),
                            "repair": repair,
                            "source_boundary": {"traceability": "TRACEABLE",
                                "authenticity": "NOT_INDEPENDENTLY_AUTHENTICATED",
                                "verbatim_concordance": "NOT_CLAIMED",
                                "public_redistribution_rights": "UNCONFIRMED"}})

            # Verify v3 candidate availability without freezing any real node.
            from backend.services.question_eligibility import question_eligibility
            from backend.mastery.storage import policy_from_storage
            with factory() as db:
                questions = list(db.scalars(select(Question).where(Question.bank_scope == "public",
                    Question.generation_batch_id.is_(None), Question.is_active.is_(True), Question.is_hidden.is_(False))))
                nodes = list(db.scalars(select(KnowledgePoint).where(KnowledgePoint.is_active.is_(True),
                    KnowledgePoint.is_assessable.is_(True))))
                policies = {row.kp_id: row for row in db.scalars(select(KpMasteryPolicy))}
                by_node = {}
                for question in questions:
                    node = next((row for row in nodes if row.id == question.kp_id), None)
                    if node is None:
                        continue
                    eligibility = question_eligibility(question, node, teaching_enabled=False)
                    if eligibility.practice_eligible and eligibility.evidence_capability == "verified_objective" \
                            and eligibility.grading_capability == "deterministic":
                        by_node.setdefault(node.id, []).append(question)
                from backend.services.question_identity import duplicate_findings
                sets = []
                missing = []
                for node in nodes:
                    rows = by_node.get(node.id, [])
                    rows.sort(key=lambda q: (q.question_role != "typical", q.difficulty != "medium", str(q.id)))
                    unique_rows = []
                    duplicate_or_uncertain = []
                    for candidate in rows:
                        findings = duplicate_findings(candidate, unique_rows)
                        if findings["matches"] or findings["uncertain_similar"]:
                            duplicate_or_uncertain.append({"question_id": str(candidate.id),
                                "matches": findings["matches"], "uncertain_similar": findings["uncertain_similar"]})
                        else:
                            unique_rows.append(candidate)
                    ids = [str(q.id) for q in unique_rows[:20]]
                    status = "CANDIDATE_REQUIRES_REVIEW" if ids else "WAITING_FOR_QUALIFIED_PUBLIC_QUESTIONS"
                    entry = {"node_id": str(node.id), "node_code": node.code, "node_name": node.name,
                        "subject": node.subject, "policy_version": policy_from_storage(policies[node.id]).policy_version
                            if node.id in policies else None,
                        "is_reference_only": node.is_reference_only,
                        "has_policy": node.id in policies,
                        "eligible_question_count": len(rows),
                        "qualified_unique_question_count": len(unique_rows), "candidate_question_ids": ids,
                        "candidate_count": len(ids), "status": status,
                        "duplicate_or_uncertain_skipped": duplicate_or_uncertain,
                        "selection_note": "current eligible public deterministic objective questions only; reference-only nodes are included only when exact current eligibility passes; known/uncertain duplicates omitted; capped to schema limit 20; not frozen"}
                    sets.append(entry)
                    if not ids:
                        missing.append(entry)
                result["graduation_set_candidates"] = {"assessable_active_nodes": len(nodes),
                    "nodes_with_policy": sum(node.id in policies for node in nodes),
                    "reference_only_nodes": sum(bool(node.is_reference_only) for node in nodes),
                    "nodes_without_policy": sum(node.id not in policies for node in nodes),
                    "nodes_with_candidate_sets": sum(bool(row["candidate_question_ids"]) for row in sets),
                    "nodes_waiting_for_questions": len(missing), "frozen_nodes": 0,
                    "empty_sets_auto_graduate": False, "candidates": sets, "missing": missing}

                protected_after = {model.__tablename__: all_table_fingerprints(db.connection())[model.__tablename__]
                    for model in protected_models}
                result["protected_history"] = {"before": protected_before, "after": protected_after,
                    "unchanged": protected_before == protected_after}
                if protected_before != protected_after:
                    raise RuntimeError("protected_attempt_event_kpstate_or_policy_changed")

            result["status"] = "BATCH_01_COMPLETE" if result["question_batch"].get("result") in {
                "INSERTED_AUTO_VERIFIED", "REPAIRED_EXISTING_AUTO_VERIFIED", "EXISTING_CANONICAL_ALREADY_AUTO_VERIFIED"} \
                else "BATCH_01_NO_INSERT"
            save(OUT / "checkpoint.json", result)
            print(json.dumps({key: value for key, value in result.items()
                if key not in {"graduation_set_candidates", "protected_history"}},
                ensure_ascii=False, default=str), flush=True)
        finally:
            clone_engine.dispose()
    except Exception as exc:
        result.update({"status": "BLOCKED_EXCEPTION", "error_type": type(exc).__name__,
            "error": str(exc)[:500]})
        save(OUT / "checkpoint.json", result)
        print(json.dumps({key: value for key, value in result.items()
            if key not in {"graduation_set_candidates", "protected_history"}},
            ensure_ascii=False, default=str), flush=True)
        return 1
    finally:
        if test_db_created:
            with connect(host="127.0.0.1", port=PORT, user="postgres", dbname="postgres",
                         autocommit=True, connect_timeout=5) as server:
                active = server.execute("SELECT count(*) FROM pg_stat_activity WHERE datname=%s", (test_name,)).fetchone()[0]
                if active == 0:
                    server.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(test_name)))
        if started:
            owner.command([str(owner.PG_BIN / "pg_ctl.exe"), "-D", str(cluster), "-m", "fast",
                "-w", "-t", "60", "stop"], timeout=75, check=False)

    return 0 if result.get("status") == "BATCH_01_COMPLETE" else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
