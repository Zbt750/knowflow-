"""Restore the archived question bank into an owned loopback-only PG cluster,
repair/qualify only deterministically verifiable historical questions, and run
focused tests against a separate empty test database. The original dev DB is
never contacted.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from scripts.audit_phase45h_completion_archive import (
    BACKUP, PG_BIN, fingerprints, source_pack_evidence, validate_backup,
)
from scripts.run_question_repair_pilot import local_pack_registry
from backend.models.learning import KnowledgePoint, KpMasteryPolicy, Question
from backend.services.auto_question_review import (
    AUTO_REVIEW_VERSION, assess_auto_qualification, prepare_exam_curated_repair,
    qualify_public_question, question_snapshot_sha256,
)
from backend.services.golden_learning_slice import digest
from backend.services.question_attestation import _subject, question_content_sha256
from backend.services.question_production_pipeline import validate_question_content
from backend.services.quality_verifiers import verify_problem, VERSION as VERIFIER_VERSION
from backend.services.question_quality import duplicates


FROZEN = ROOT / "storage/quality-audits/phase45d-20261009/diagnosis"
USER_TEMP_ROOT = Path.home() / "AppData/Local/Temp"
SAFE_TEMP_ROOT = USER_TEMP_ROOT / "phase45hr-hrrun"
OUTPUT_ROOT = ROOT / "storage/quality-audits"
PG_CTL = PG_BIN / "pg_ctl.exe"
POSTGRES = PG_BIN / "postgres.exe"
INITDB = PG_BIN / "initdb.exe"
PG_RESTORE = PG_BIN / "pg_restore.exe"
PG_ISREADY = PG_BIN / "pg_isready.exe"


def _hash_file(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _run(command: list[str], *, env: dict[str, str], timeout: int, log: Path | None = None) -> subprocess.CompletedProcess:
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, timeout=timeout,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if log is not None:
        log.write_bytes((result.stdout or b"") + b"\n--- STDERR ---\n" + (result.stderr or b""))
    if result.returncode:
        tail = ((result.stdout or b"") + (result.stderr or b""))[-3000:].decode("utf-8", "replace")
        raise RuntimeError(f"command_failed:{Path(command[0]).name}:{result.returncode}:{tail}")
    return result


def _fresh_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    if port < 18000:
        raise RuntimeError("temporary_port_outside_safe_range")
    return port


def _clean_environment() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith("PG")}
    env.update({"PYTHONIOENCODING": "utf-8", "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1", "APP_ENV": "test",
                "LLM_API_KEY": "", "LLM_BASE_URL": "http://127.0.0.1:1",
                "LLM_MODEL": "phase45hr-offline-test"})
    return env


def _database_url(port: int, database: str) -> str:
    return URL.create("postgresql+psycopg", username="postgres", host="127.0.0.1",
                      port=port, database=database).render_as_string(hide_password=False)


def _source_snapshot_comparison(questions: list[Question]) -> dict:
    frozen_report = json.loads((FROZEN / "report.json").read_text(encoding="utf-8"))
    raw = json.loads((FROZEN / "inventory-snapshot.json").read_text(encoding="utf-8"))
    matches, changed = Counter(), Counter()
    live_by_id = {str(q.id): q for q in questions}
    from backend.services.auto_question_review import question_snapshot_payload
    for row in raw.get("questions", []):
        qid = str(row["id"])
        current = live_by_id.get(qid)
        frozen_q = Question(**{"bank_scope": "public", "is_hidden": False, **row})
        if current is None:
            matches["frozen_active_not_in_backup"] += 1
            continue
        left, right = question_snapshot_payload(current), question_snapshot_payload(frozen_q)
        if digest(left) == digest(right):
            matches["exact_payload_match"] += 1
        else:
            matches["payload_changed"] += 1
            for field in set(left) | set(right):
                if left.get(field) != right.get(field):
                    changed[field] += 1
    return {"snapshot_integrity": digest(raw) == frozen_report.get("inventory_snapshot_sha256"),
        "snapshot_captured_at": frozen_report.get("checked_at"), "frozen_active_count": len(raw.get("questions", [])),
        "backup_question_count": len(questions), "comparison": dict(matches), "changed_fields": dict(changed),
        "difference_policy": "retain both; do not reconcile or overwrite silently"}


def _select_pilot(rows: list[dict], limit: int = 30) -> list[dict]:
    eligible = [row for row in rows if row["source_pack_traceable"]
                and row.get("node_eligible_leaf", row.get("node_eligible", False))]
    buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in sorted(eligible, key=lambda item: (item.get("solver_status") != "PASS",
                                                   item.get("node_code") or "", item["question_id"])):
        buckets[(row["subject"] or "unknown", row["question_type"] or "unknown")].append(row)
    selected: list[dict] = []
    keys = sorted(buckets)
    while len(selected) < min(limit, len(eligible)):
        progressed = False
        for key in keys:
            items = buckets[key]
            if items:
                selected.append(items.pop(0))
                progressed = True
                if len(selected) >= limit:
                    break
        if not progressed:
            break
    if len(selected) < min(limit, len(eligible)):
        selected_ids = {row["question_id"] for row in selected}
        selected.extend(row for row in eligible if row["question_id"] not in selected_ids)
        selected = selected[:limit]
    return selected


def _safe_stages(assessment: dict) -> dict:
    fields = {"adapter", "method", "node_id", "node_code", "node_subject",
        "node_assessable", "node_is_leaf", "source_pack_node_code",
        "reference_topic_mapping", "semantic_dedup_executed"}
    result = {}
    for name, stage in assessment.get("stages", {}).items():
        if not isinstance(stage, dict):
            continue
        safe = {"status": stage.get("status"), "reason": stage.get("reason")}
        safe.update({key: stage[key] for key in fields if key in stage})
        result[name] = safe
    return result


def run(args) -> dict:
    dump, manifest = validate_backup(args.backup)
    toc = _run([str(PG_RESTORE), "--list", str(dump)], env=_clean_environment(), timeout=45)
    if not toc.stdout:
        raise RuntimeError("backup_toc_empty")
    output = args.output.resolve()
    allowed_output = OUTPUT_ROOT.resolve()
    if output.exists() or not output.is_relative_to(allowed_output):
        raise ValueError("output_must_be_new_private_audit_directory")
    output.mkdir(parents=True)
    SAFE_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    if not SAFE_TEMP_ROOT.resolve().is_relative_to(USER_TEMP_ROOT.resolve()):
        raise ValueError("temporary_root_is_not_under_the_current_user_temp_directory")
    temp = Path(tempfile.mkdtemp(prefix="kaoyan-phase45hr-", dir=SAFE_TEMP_ROOT))
    owner_token = uuid.uuid4().hex
    marker = temp / "phase45hr-owner.json"
    cluster = temp / "cluster"
    port = _fresh_port()
    restore_db, test_db = "kaoyan_phase45hr_restore_test", "kaoyan_phase45hr_sandbox_test"
    report = {"phase": "4.5H-R", "started_at": datetime.now(timezone.utc).isoformat(),
        "original_development_database_contacted": False, "original_development_database_modified": False,
        "paid_model_calls": 0, "backup": {"manifest_revision": manifest.get("alembic_revision_after"),
            "dump_sha256": manifest.get("database_dump_sha256"), "dump_bytes": manifest.get("database_dump_bytes"),
            "is_live_database": False}, "isolated_cluster_port": port,
        "temporary_cluster_started": False, "temporary_cluster_stopped": False,
        "temporary_data_removed": False, "isolated_migration_target": "head"}
    started = False
    postmaster = None
    postgres_log_handle = None
    env = _clean_environment()
    try:
        marker.write_text(json.dumps({"format": 1, "token": owner_token, "pid": os.getpid()}, sort_keys=True), encoding="utf-8")
        _run([str(INITDB), "-D", str(cluster), "-U", "postgres", "--auth-local=trust",
              "--auth-host=trust", "--encoding=UTF8", "--no-locale"], env=env, timeout=300,
             log=output / "initdb.log")
        start_env = _clean_environment()
        postgres_log_handle = (output / "postgres.log").open("ab")
        # Keep the postmaster as a direct child of this still-running Python
        # process. In this Windows sandbox, a server spawned by a short-lived
        # pg_ctl subprocess can be reaped with that subprocess's job object.
        postmaster = subprocess.Popen([str(POSTGRES), "-D", str(cluster), "-p", str(port),
            "-h", "127.0.0.1", "-c", "listen_addresses=127.0.0.1", "-c", "log_statement=none"],
            cwd=ROOT, env=start_env, stdin=subprocess.DEVNULL, stdout=postgres_log_handle,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        started = True
        deadline = __import__("time").monotonic() + 120
        while __import__("time").monotonic() < deadline:
            if postmaster.poll() is not None:
                raise RuntimeError(f"temporary_postgres_exited:{postmaster.returncode}")
            ready = subprocess.run([str(PG_ISREADY), "-h", "127.0.0.1", "-p", str(port), "-t", "2"],
                env=start_env, capture_output=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            if ready.returncode == 0:
                break
            __import__("time").sleep(0.5)
        else:
            raise RuntimeError("temporary_postgres_start_timeout")
        report["temporary_cluster_started"] = True
        report["pg_isready"] = ready.stdout.decode("utf-8", "replace").strip()
        import psycopg
        from psycopg import sql as psycopg_sql
        with psycopg.connect(host="127.0.0.1", port=port, user="postgres", dbname="postgres",
                             passfile="", sslmode="disable", connect_timeout=5, autocommit=True) as conn:
            current_directory = Path(conn.execute("SHOW data_directory").fetchone()[0]).resolve()
            if current_directory != cluster.resolve():
                raise RuntimeError("temporary_cluster_identity_mismatch")
            for database in (restore_db, test_db):
                conn.execute(psycopg_sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'")
                             .format(psycopg_sql.Identifier(database)))
        restore_env = _clean_environment()
        restore_env.update({"PGHOST": "127.0.0.1", "PGPORT": str(port), "PGUSER": "postgres",
                            "PGDATABASE": restore_db})
        restore_result = _run([str(PG_RESTORE), "--no-password", "--exit-on-error", "--no-owner",
            "--no-privileges", "--dbname", restore_db, str(dump)], env=restore_env,
            timeout=300, log=output / "restore.log")
        report["restore_exit_code"] = restore_result.returncode
        restore_url = _database_url(port, restore_db)
        test_url = _database_url(port, test_db)
        migration_env = {**env, "APP_ENV": "test", "TEST_DATABASE_URL": restore_url,
            "DATABASE_URL": restore_url, "UPLOAD_DIR": str(output / "test-resources/uploads"),
            "CHROMA_DIR": str(output / "test-resources/chroma"),
            "MODEL_SETTINGS_PATH": str(output / "test-resources/config/model-settings.bin")}
        migrated = _run([sys.executable, "-m", "alembic", "upgrade", "head"], env=migration_env,
                        timeout=300, log=output / "restore-migration.log")
        report["isolated_migration_exit_code"] = migrated.returncode

        engine = create_engine(restore_url, connect_args={"connect_timeout": 5})
        registry, rejected_files = local_pack_registry(ROOT)
        try:
            with Session(engine, autoflush=False) as db:
                db.connection().exec_driver_sql("SET TRANSACTION READ ONLY")
                questions = list(db.scalars(select(Question).order_by(Question.id)))
                nodes = {row.id: row for row in db.scalars(select(KnowledgePoint))}
                policies = list(db.scalars(select(KpMasteryPolicy).order_by(KpMasteryPolicy.kp_id)))
                revision = db.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one()
                before_history = fingerprints(restore_url)
                question_to_node_before = {str(q.id): str(q.kp_id) for q in questions}
                before_node_flags = Counter((n.subject, bool(n.is_assessable), bool(n.is_reference_only))
                                            for n in nodes.values() if n.is_active)
                frozen_comparison = _source_snapshot_comparison(questions)
                duplicate_map = duplicates(questions)
                status_counts, subject_counts = Counter(), Counter()
                issue_counts, node_counts, type_counts = Counter(), Counter(), Counter()
                per_question = []
                for q in questions:
                    node = nodes.get(q.kp_id)
                    source = ((q.grading_config or {}).get("provenance") or {}).get("source", {})
                    source_evidence = source_pack_evidence(q, registry, node)
                    solver = verify_problem(q)
                    structure = validate_question_content(q)
                    duplicate = duplicate_map.get(str(q.id), {"exact": [], "near": []})
                    node_eligible = bool(node and node.is_active and node.is_assessable and not node.children)
                    subject = "math2" if _subject(str(source.get("subject") or node.subject if node else "")) == "math2" else (
                        "408" if node and str(node.subject).lower() in {"408", "cs408", "computer_science"} else
                        "408" if _subject(str(source.get("subject") or "")) == "408" else "unknown")
                    status_counts["solver:" + str(solver.get("status") or "UNKNOWN")] += 1
                    status_counts["source_pack:" + ("traceable" if source_evidence else "unresolved")] += 1
                    status_counts["structure:" + structure.completeness] += 1
                    status_counts["active:" + str(bool(q.is_active)).lower()] += 1
                    subject_counts[subject] += 1
                    type_counts[f"{subject}:{q.question_type or 'unknown'}"] += 1
                    node_counts["reference_only" if node and node.is_reference_only else
                                "assessable_leaf" if node_eligible else "not_assessable_or_parent"] += 1
                    issue_counts.update(structure.detected_issues)
                    row = {"question_id": str(q.id), "active": bool(q.is_active), "subject": subject,
                        "source_year": source.get("year"), "source_question_number": source.get("question_number"),
                        "question_type": q.question_type, "node_code": node.code if node else None,
                        "node_eligible_leaf": node_eligible, "node_reference_only": bool(node and node.is_reference_only),
                        "question_provenance": q.question_provenance, "source_status": q.source_status,
                        "source_pack_traceable": bool(source_evidence), "source_pack_diff_fields":
                            source_evidence.get("source_pack_content_diff_fields", []) if source_evidence else [],
                        "solver_status": solver.get("status"), "solver_adapter": solver.get("adapter"),
                        "derived_answer_sha256": hashlib.sha256(str(solver.get("derived_answer", "")).encode()).hexdigest()
                            if solver.get("derived_answer") is not None else None,
                        "structure": structure.completeness, "structure_issues": list(structure.detected_issues),
                        "exact_duplicate_count": len(duplicate.get("exact", [])),
                        "near_duplicate_count": len(duplicate.get("near", [])),
                        "strict_grader_status": "not_run"}
                    per_question.append(row)
                report["isolated_backup_actual"] = {"revision_after_migration": revision,
                    "questions": len(questions), "active_questions": sum(q.is_active for q in questions),
                    "inactive_questions": sum(not q.is_active for q in questions), "knowledge_points": len(nodes),
                    "active_assessable_nodes": sum(n.is_active and n.is_assessable for n in nodes.values()),
                    "reference_only_active_assessable_nodes": sum(n.is_active and n.is_assessable and n.is_reference_only for n in nodes.values()),
                    "policy_rows": len(policies), "subjects": dict(subject_counts),
                    "question_type_distribution": dict(type_counts), "node_mapping_class_counts": dict(node_counts),
                    "quality_scan_counts": dict(status_counts), "structure_issue_counts": dict(issue_counts),
                    "solver_version": VERIFIER_VERSION, "local_source_pack_rows": sum(len(v) for v in registry.values()),
                    "rejected_source_pack_files": len(rejected_files), "model_calls": 0}
                report["backup_vs_frozen_snapshot"] = frozen_comparison
                report["history_fingerprints_before"] = before_history
                report["pilot_limit"] = 30

                pilot = _select_pilot(per_question, 30)
                report["pilot_question_ids"] = [row["question_id"] for row in pilot]
                report["pilot_review_results"] = []
                by_id = {str(q.id): q for q in questions}
                for selected in pilot:
                    q = by_id[selected["question_id"]]
                    node = nodes.get(q.kp_id)
                    evidence = source_pack_evidence(q, registry, node) if node else None
                    if not evidence or not node:
                        assessment = {"status": "QUARANTINED", "reason": "source_pack_or_mapping_unresolved", "stages": {}}
                    else:
                        old_provenance, old_status = q.question_provenance, q.source_status
                        source_meta = ((q.grading_config or {}).get("provenance") or {}).get("source", {})
                        if source_meta.get("source_type") == "exam" and old_provenance in {"legacy_unknown", "real_exam"}:
                            q.question_provenance, q.source_status = "real_exam", "traceable"
                        try:
                            with db.no_autoflush:
                                assessment = assess_auto_qualification(db, q, node,
                                    source_evidence=evidence, all_questions=questions)
                        finally:
                            q.question_provenance, q.source_status = old_provenance, old_status
                    report["pilot_review_results"].append({"question_id": selected["question_id"],
                        "subject": selected["subject"], "question_type": selected["question_type"],
                        "node_code": selected["node_code"], "source_pack_traceable": selected["source_pack_traceable"],
                        "solver_status": selected["solver_status"], "solver_adapter": selected["solver_adapter"],
                        "review_status": assessment.get("status"), "reason": assessment.get("reason"),
                        "stages": _safe_stages(assessment)})
                db.rollback()
        finally:
            engine.dispose()

        # Apply content repair and qualification only to active, exact source-pack
        # mapped questions with an allowlisted independent solution. Unsupported
        # graders may receive a bound explanation repair in this isolated copy,
        # but do not get a strict qualification event.
        repair_results = []
        engine = create_engine(restore_url, connect_args={"connect_timeout": 5})
        try:
            with Session(engine, autoflush=False) as scan:
                active_questions = list(scan.scalars(select(Question).where(Question.is_active.is_(True)).order_by(Question.id)))
                nodes_live = {row.id: row for row in scan.scalars(select(KnowledgePoint))}
                candidate_ids = []
                for q in active_questions:
                    node = nodes_live.get(q.kp_id)
                    source = ((q.grading_config or {}).get("provenance") or {}).get("source", {})
                    if (node and node.is_active and node.is_assessable and not node.children
                        and q.bank_scope == "public" and not q.generation_batch_id
                        and q.question_provenance in {"legacy_unknown", "real_exam"}
                        and source.get("source_type") == "exam"
                        and source_pack_evidence(q, registry, node)
                        and verify_problem(q).get("status") == "PASS"):
                        candidate_ids.append(str(q.id))
            for qid in candidate_ids:
                item_result = {"question_id": qid, "repair_status": "not_attempted", "qualification_status": "not_attempted"}
                with Session(engine, autoflush=False) as db:
                    try:
                        q = db.get(Question, uuid.UUID(qid))
                        node = db.get(KnowledgePoint, q.kp_id) if q else None
                        if q is None or node is None:
                            raise ValueError("question_or_node_missing")
                        evidence = source_pack_evidence(q, registry, node)
                        if not evidence:
                            raise ValueError("source_pack_trace_lost_before_repair")
                        solver = verify_problem(q)
                        repair = prepare_exam_curated_repair(q, node, evidence)
                        item_result["repair_status"] = "APPLIED_IN_ISOLATED_BACKUP" if repair.get("changed_fields") else "NO_CONTENT_CHANGE"
                        item_result["repair_version"] = repair.get("repair_version")
                        item_result["changed_fields"] = repair.get("changed_fields", [])
                        item_result["before_content_sha256"] = repair.get("before", {}).get("question_content_sha256")
                        item_result["after_content_sha256"] = repair.get("after_question_content_sha256")
                        item_result["answer_sha256_unchanged"] = repair.get("before", {}).get("answer_sha256") == __import__(
                            "backend.services.answer_verification", fromlist=["answer_version_sha256"]).answer_version_sha256(q)
                        item_result["solver_adapter"] = solver.get("adapter")
                        item_result["human_verified"] = False
                        db.flush()
                        evidence = source_pack_evidence(q, registry, node)
                        if evidence is None:
                            raise ValueError("source_pack_binding_invalid_after_repair")
                        expected = question_snapshot_sha256(q)
                        event, qualification = qualify_public_question(db, question_id=q.id, node_id=node.id,
                            expected_snapshot_sha256=expected,
                            idempotency_key="phase45hr-v1:" + hashlib.sha256((qid + expected).encode()).hexdigest(),
                            source_evidence=evidence)
                        item_result["qualification_status"] = qualification.get("status")
                        item_result["qualification_reason"] = qualification.get("reason")
                        item_result["event_id"] = str(event.id) if event else None
                        item_result["qualification_stages"] = _safe_stages(qualification)
                        item_result["learner_graduated"] = False
                        item_result["formal_graduation_candidate"] = bool(event)
                        db.commit()
                    except Exception as exc:
                        db.rollback()
                        item_result["repair_status"] = "ROLLED_BACK"
                        item_result["qualification_status"] = "BLOCKED"
                        item_result["error_code"] = str(exc)[:240]
                repair_results.append(item_result)
        finally:
            engine.dispose()

        engine = create_engine(restore_url, connect_args={"connect_timeout": 5})
        try:
            with Session(engine, autoflush=False) as db:
                final_questions = list(db.scalars(select(Question).order_by(Question.id)))
                final_nodes = {row.id: row for row in db.scalars(select(KnowledgePoint))}
                final_policies = list(db.scalars(select(KpMasteryPolicy).order_by(KpMasteryPolicy.kp_id)))
                from backend.services.auto_question_review import current_auto_review
                from backend.services.question_eligibility import question_eligibility
                qualified = []
                for q in final_questions:
                    node = final_nodes.get(q.kp_id)
                    event = current_auto_review(q, node) if node else None
                    if event:
                        eligibility = question_eligibility(q, node)
                        source = ((q.grading_config or {}).get("provenance") or {}).get("source", {})
                        qualified.append({"question_id": str(q.id), "subject": "math2" if _subject(source.get("subject")) == "math2" else "408",
                            "node_code": node.code, "question_type": q.question_type,
                            "qualification_class": event.qualification_class, "review_version": event.review_version,
                            "evidence_capability": eligibility.evidence_capability,
                            "mapping_status": eligibility.mapping_status, "human_verified": False})
                after_history = fingerprints(restore_url)
                after_node_flags = Counter((n.subject, bool(n.is_assessable), bool(n.is_reference_only))
                    for n in final_nodes.values() if n.is_active)
                report["isolated_repair_results"] = repair_results
                report["final_qualification"] = {"qualified_count": len(qualified),
                    "by_subject": dict(Counter(item["subject"] for item in qualified)),
                    "by_node": dict(Counter(item["node_code"] for item in qualified)),
                    "by_question_type": dict(Counter(item["question_type"] for item in qualified)),
                    "items": qualified, "auto_review_version": AUTO_REVIEW_VERSION,
                    "human_verified_count": sum(item["human_verified"] for item in qualified)}
                report["protection_checks"] = {
                    "attempts_learning_events_kp_states_policies_unchanged": {
                        name: {"before": before_history[name], "after": after_history[name],
                               "unchanged": before_history[name] == after_history[name]}
                        for name in before_history},
                    "node_assessable_reference_flags_unchanged": before_node_flags == after_node_flags,
                    "policy_row_count_unchanged": len(policies) == len(final_policies),
                    "question_to_node_mappings_unchanged": all(
                        question_to_node_before.get(str(new.id)) == str(new.kp_id)
                        for new in final_questions),
                    "personal_question_auto_qualification_count": sum(
                        1 for item in qualified if item["qualification_class"] not in {"exam_curated", "exam_variant", "development_original"}),
                    "original_development_database_contacted": False,
                }
                report["isolate_per_question_summary"] = per_question
        finally:
            engine.dispose()

        # Tests use a different empty database in the same owned cluster, never
        # the restored source copy and never the original development DB.
        test_url = _database_url(port, test_db)
        test_env = {**env, "APP_ENV": "test", "TEST_DATABASE_URL": test_url, "DATABASE_URL": test_url,
            "UPLOAD_DIR": str(output / "pytest-resources/uploads"),
            "CHROMA_DIR": str(output / "pytest-resources/chroma"),
            "MODEL_SETTINGS_PATH": str(output / "pytest-resources/config/model-settings.bin"),
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
        test_paths = ["tests/integration/test_auto_question_review.py",
            "tests/integration/test_policy_origin_semantics.py",
            "tests/integration/test_phase45e_current_graduation.py",
            "tests/unit/test_question_eligibility.py", "tests/unit/test_policy_origin_semantics.py",
            "tests/unit/grading/test_answer_grading.py",
            "tests/unit/test_phase45hr_curated_repair.py"]
        completed = subprocess.run([sys.executable, "-m", "pytest", *test_paths, "-q", "-o", "addopts=",
                                    "--basetemp", str(output / "pytest-tmp")], cwd=ROOT, env=test_env,
                                   capture_output=True, timeout=900,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        (output / "focused-tests.log").write_bytes((completed.stdout or b"") + b"\n--- STDERR ---\n" + (completed.stderr or b""))
        report["focused_tests"] = {"files": test_paths, "exit_code": completed.returncode,
            "result_tail": ((completed.stdout or b"") + (completed.stderr or b""))[-5000:].decode("utf-8", "replace"),
            "database": test_db, "isolated_from_restored_source_copy": True,
            "real_model_calls_allowed": False}
        report["completion_status"] = "PHASE45HR_PARTIAL_WITH_ISOLATED_FORMAL_CANDIDATES" if report["final_qualification"]["qualified_count"] else "PHASE45HR_BLOCKED_ON_RELIABLE_CONTENT_OR_GRADER"
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        return report
    finally:
        if started:
            try:
                pid_path = cluster / "postmaster.pid"
                if pid_path.exists():
                    fields = pid_path.read_text(encoding="utf-8").splitlines()
                    if (len(fields) < 4 or Path(fields[1]).resolve() != cluster.resolve()
                            or int(fields[3]) != port or postmaster is None or int(fields[0]) != postmaster.pid):
                        raise RuntimeError("refuse_to_stop_cluster_identity_mismatch")
                    if postmaster.poll() is None:
                        _run([str(PG_CTL), "-D", str(cluster), "-m", "fast", "-w", "-t", "60", "stop"],
                             env=_clean_environment(), timeout=75, log=output / "pg-stop.log")
                        postmaster.wait(timeout=20)
                    report["temporary_cluster_stopped"] = postmaster.poll() is not None
                else:
                    report["temporary_cluster_stopped"] = postmaster is not None and postmaster.poll() is not None
            except Exception as exc:
                report["temporary_cluster_stop_error"] = str(exc)[:300]
                report["temporary_cluster_stopped"] = False
        else:
            report["temporary_cluster_stopped"] = not (cluster / "postmaster.pid").exists()
        if postgres_log_handle is not None:
            try:
                postgres_log_handle.close()
            except OSError:
                pass
        marker_is_owned = False
        if marker.is_file():
            try:
                marker_is_owned = json.loads(marker.read_text(encoding="utf-8")).get("token") == owner_token
            except (OSError, json.JSONDecodeError):
                marker_is_owned = False
        prestart_directory_is_owned = not started and not marker.exists() and not (cluster / "postmaster.pid").exists()
        if (report.get("temporary_cluster_stopped") and temp.resolve().parent == SAFE_TEMP_ROOT.resolve()
                and temp.name.startswith("kaoyan-phase45hr-")
                and (marker_is_owned or prestart_directory_is_owned)
                and (postmaster is None or postmaster.poll() is not None)):
            shutil.rmtree(temp)
            report["temporary_data_removed"] = True
        report["finished_at"] = report.get("finished_at") or datetime.now(timezone.utc).isoformat()
        (output / "phase45hr-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", type=Path, default=BACKUP)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT / "phase45hr-20261009" / "isolated-repair-v1")
    args = parser.parse_args()
    report = run(args)
    safe = {key: value for key, value in report.items() if key != "isolate_per_question_summary"}
    print(json.dumps(safe, ensure_ascii=False, indent=2, default=str))
    return 0 if report.get("temporary_cluster_stopped") and report.get("temporary_data_removed") else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
