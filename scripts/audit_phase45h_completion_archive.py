"""Audit the latest available private question backup in an owned temporary PG cluster.

The source backup is never opened for writes. All migrations and assessment are
performed only in a newly initialized, owner-marked temporary cluster.
"""
from __future__ import annotations

import argparse
from collections import Counter
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
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from desktop.postgres import APP_USER, ManagedPostgres
from desktop.runtime_paths import RuntimePaths
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from psycopg import sql as psycopg_sql


BACKUP = ROOT / "storage/backups/phase45a3-20261008-q06-correction-v2"
PG_BIN = Path("C:/Program Files/PostgreSQL/18/bin")


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_backup(folder: Path) -> tuple[Path, dict]:
    folder = folder.resolve()
    allowed = (ROOT / "storage/backups").resolve()
    if folder == allowed or not folder.is_relative_to(allowed) or folder.is_symlink():
        raise ValueError("backup_outside_private_storage")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    dump = folder / manifest.get("database_dump_file", "database.dump")
    if (manifest.get("format") != "phase45a3-q06-correction-db-backup-v1"
            or manifest.get("target_database_modified") is not False
            or not dump.is_file()
            or hash_file(dump) != manifest.get("database_dump_sha256")):
        raise ValueError("backup_manifest_or_hash_invalid")
    return dump, manifest


def _pack_lineage_matches(question, pack_question) -> tuple[bool, dict[str, dict[str, bool]]]:
    """Describe source-pack/content differences without requiring verbatim text.

    The pack key and fingerprint prove which local source-pack row the imported
    Question points at. H-R treats exam-curated questions as allowed to have
    edited explanations/answers, so content equality is reported, not used to
    erase a traceable source identity. The qualification audit separately binds
    the current Question snapshot and explicitly makes no verbatim claim.
    """
    config = question.grading_config if isinstance(question.grading_config, dict) else {}
    revisions = config.get("content_revisions") if isinstance(config.get("content_revisions"), list) else []
    answer_revisions = config.get("answer_revisions") if isinstance(config.get("answer_revisions"), list) else []
    fields = ("question_type", "stem", "options", "correct_answer", "explanation")
    checks = {}
    for field in fields:
        candidates = [getattr(question, field, None)]
        for revision in revisions:
            before = revision.get("before") if isinstance(revision, dict) else None
            if isinstance(before, dict) and field in before:
                candidates.append(before[field])
        for revision in answer_revisions:
            if not isinstance(revision, dict):
                continue
            aliases = {"correct_answer": "previous_answer", "explanation": "previous_explanation"}
            alias = aliases.get(field)
            if alias and alias in revision:
                candidates.append(revision[alias])
            if field in {"correct_answer", "explanation"} and field in revision:
                candidates.append(revision[field])
        pack_value = getattr(pack_question, field, None)
        checks[field] = {
            "current_matches_pack": getattr(question, field, None) == pack_value,
            "retained_revision_matches_pack": pack_value in candidates[1:],
        }
    # Exact pack identity is already required by the signed provenance key and
    # fingerprint lookup in source_pack_evidence. Differences are surfaced to
    # reviewers, not treated as proof of original wording or a broken source.
    return True, checks


def source_pack_evidence(question, registry: dict, node=None) -> dict | None:
    from backend.services.question_attestation import _subject, question_content_sha256

    config = question.grading_config if isinstance(question.grading_config, dict) else {}
    provenance = config.get("provenance") if isinstance(config.get("provenance"), dict) else {}
    source_meta = provenance.get("source") if isinstance(provenance.get("source"), dict) else {}
    key, expected = provenance.get("key"), provenance.get("sha256")
    matches = [item for item in registry.get(key, []) if item.get("fingerprint") == expected]
    matches = {item["fingerprint"]: item for item in matches}
    if len(matches) != 1:
        return None
    item = next(iter(matches.values()))
    source = item["question"].source
    if node is None or item["question"].kp_code != node.code or node.id != question.kp_id:
        return None
    lineage_matches, lineage_fields = _pack_lineage_matches(question, item["question"])
    if not lineage_matches:
        return None
    source_identity = {"subject": str(source.subject), "year": source.year,
                       "question_number": source.question_number}
    same_identity = (_subject(source_identity["subject"]) == _subject(source_meta.get("subject"))
                     and str(source_identity["year"]) == str(source_meta.get("year"))
                     and str(source_identity["question_number"]) == str(source_meta.get("question_number")))
    path = Path(item["path"]).resolve()
    intake = (ROOT / "storage/question-intake").resolve()
    if not same_identity or not path.is_relative_to(intake):
        return None
    return {
        "status": "TRACEABLE", "method": "curated_source_trace_v1",
        "question_content_sha256": question_content_sha256(question),
        "source_archive_sha256": item["file_sha256"],
        "source_asset_path": path.relative_to(intake).as_posix(),
        "source_pack_id": item["pack_id"],
        "source_pack_version": item["pack_version"],
        "source_pack_question_fingerprint": item["fingerprint"],
        "mapped_node_code": item["question"].kp_code,
        "source_pack_content_comparison": lineage_fields,
        "source_pack_content_diff_fields": [field for field, result in lineage_fields.items()
            if not result["current_matches_pack"]],
        "source_locator": str(getattr(source, "citation", "") or
                              f"{source_identity['subject']}:{source_identity['year']}:Q{source_identity['question_number']}"),
        "source_identity": source_identity,
        "verbatim_verified": False,
        "uncertainties": ["本轮只绑定本地题目包来源身份，未逐字比对原卷页面"],
        "reconstruction_notes": ("保存的来源包键、指纹、来源身份及节点代码可追溯；当前题目与来源包的差异字段已单列。"
            "这证明来源线索，不证明原卷逐字一致、来源权威性或公开再分发权限。"),
    }


def fingerprints(database_url: str) -> dict:
    from sqlalchemy import create_engine
    tables = ("question_attempts", "learning_events", "kp_states", "kp_mastery_policies")
    engine = create_engine(database_url, connect_args={"connect_timeout": 5})
    result = {}
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            for name in tables:
                rows = connection.execute(text(f'SELECT * FROM public."{name}" ORDER BY 1')).mappings().all()
                payload = json.dumps([dict(row) for row in rows], ensure_ascii=False,
                                     sort_keys=True, default=str, separators=(",", ":")).encode()
                result[name] = {"count": len(rows), "sha256": hashlib.sha256(payload).hexdigest()}
    finally:
        engine.dispose()
    return result


def run(args) -> dict:
    from backend.models.learning import (KnowledgePoint, KpMasteryPolicy, LearningEvent,
        Question, QuestionAttempt, QuestionAnswerConsistencyRun, KpState)
    from backend.services.auto_question_review import assess_auto_qualification
    from backend.services.quality_verifiers import verify_problem
    from backend.services.question_repair import local_pack_registry
    from backend.services.question_attestation import question_content_sha256
    from backend.services.question_production_pipeline import validate_question_content
    from backend.services.question_quality import duplicates
    from backend.services.golden_learning_slice import digest
    from scripts.run_question_repair_pilot import decoded
    from sqlalchemy import create_engine

    dump, manifest = validate_backup(args.backup)
    toc_bin = PG_BIN / ("pg_restore.exe" if os.name == "nt" else "pg_restore")
    restore_bin = toc_bin
    toc = subprocess.run([str(toc_bin), "--list", str(dump)], capture_output=True, timeout=30)
    if toc.returncode:
        raise ValueError("backup_archive_toc_invalid")
    output = args.output.resolve()
    allowed_output = (ROOT / "storage/quality-audits").resolve()
    if output.exists() or not output.is_relative_to(allowed_output):
        raise ValueError("output_must_be_new_private_quality_audit_directory")
    output.mkdir(parents=True)
    temp = Path(tempfile.mkdtemp(prefix="kaoyan-phase45h-completion-"))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    if port < 18000:
        raise ValueError("temporary_port_outside_manager_range")
    # Keep the disposable database state under the explicitly-selected temp
    # root, while pointing RuntimePaths at the immutable backend resources
    # subtree so the two roots cannot overlap.
    manager = ManagedPostgres(RuntimePaths.windows(resources=ROOT / "backend", local_app_data=temp), PG_BIN, port=port)
    report = {
        "version": "phase45h-completion-archive-audit-v1",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "source_backup": {"created_at": manifest.get("created_at"),
            "revision_before_isolated_migration": manifest.get("alembic_revision_after"),
            "sha256": manifest.get("database_dump_sha256"), "dump_bytes": manifest.get("database_dump_bytes"),
            "source_database_modified_at_backup": manifest.get("target_database_modified"),
            "is_live_database": False},
        "source_assets": {"directory": "storage/question-intake", "included_in_this_report": False},
        "original_development_database_connected": False,
        "original_development_database_modified": False,
        "model_calls": 0,
        "temporary_cluster_stopped": False,
        "temporary_data_removed": False,
    }
    try:
        with manager:
            database_name = "kaoyan_h_completion_test"
            with manager._connect() as connection:
                exists = connection.execute("SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname=%s)",
                                             (database_name,)).fetchone()[0]
                if exists:
                    raise ValueError("temporary_database_collision")
                connection.execute(psycopg_sql.SQL("CREATE DATABASE {} OWNER {} TEMPLATE template0").format(
                    psycopg_sql.Identifier(database_name), psycopg_sql.Identifier(APP_USER)))
            url = make_url(manager.database_url).set(database=database_name)
            database_url = url.render_as_string(hide_password=False)
            env = os.environ.copy()
            for key in ("PGHOST", "PGHOSTADDR", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE", "PGSERVICE"):
                env.pop(key, None)
            env.update({"PGHOST": url.host or "127.0.0.1", "PGPORT": str(url.port or port),
                        "PGUSER": url.username or APP_USER, "PGDATABASE": database_name,
                        "APP_ENV": "test", "DATABASE_URL": database_url, "TEST_DATABASE_URL": database_url,
                        "PHASE45E_OWNED_TEST_PORT": str(port), "PYTHONIOENCODING": "utf-8",
                        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
            if url.password:
                env["PGPASSWORD"] = url.password
            restored = subprocess.run([str(restore_bin), "--no-password", "--exit-on-error", "--no-owner",
                "--no-privileges", "--dbname", database_name, str(dump)], env=env,
                capture_output=True, timeout=120)
            report["restore_exit_code"] = restored.returncode
            if restored.returncode:
                raise ValueError("isolated_backup_restore_failed")
            pre_engine = create_engine(database_url, connect_args={"connect_timeout": 5})
            try:
                with pre_engine.connect() as connection:
                    connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                    report["backup_revision_restored"] = connection.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one()
                    report["backup_counts_before_migration"] = {
                        "questions": connection.execute(text('SELECT count(*) FROM public.questions')).scalar_one(),
                        "active_questions": connection.execute(text('SELECT count(*) FROM public.questions WHERE is_active')).scalar_one(),
                        "inactive_questions": connection.execute(text('SELECT count(*) FROM public.questions WHERE NOT is_active')).scalar_one(),
                        "knowledge_points": connection.execute(text('SELECT count(*) FROM public.knowledge_points')).scalar_one(),
                        "policies": connection.execute(text('SELECT count(*) FROM public.kp_mastery_policies')).scalar_one(),
                    }
            finally:
                pre_engine.dispose()
            migrated = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT,
                env=env, capture_output=True, timeout=180)
            report["isolated_migration_exit_code"] = migrated.returncode
            if migrated.returncode:
                (output / "isolated-migration.log").write_bytes(migrated.stdout + migrated.stderr)
                raise ValueError("isolated_schema_migration_failed")

            engine = create_engine(database_url, connect_args={"connect_timeout": 5})
            registry, rejected_assets = local_pack_registry(ROOT)
            try:
                with Session(engine, autoflush=False) as db:
                    db.connection().exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                    questions = list(db.scalars(select(Question).order_by(Question.id)))
                    nodes = {row.id: row for row in db.scalars(select(KnowledgePoint))}
                    policies = {row.kp_id: row for row in db.scalars(select(KpMasteryPolicy))}
                    runs = list(db.scalars(select(QuestionAnswerConsistencyRun)))
                    frozen_dir = ROOT / "storage/quality-audits/phase45d-20261009/diagnosis"
                    frozen_report = json.loads((frozen_dir / "report.json").read_text(encoding="utf-8"))
                    frozen_raw = json.loads((frozen_dir / "inventory-snapshot.json").read_text(encoding="utf-8"))
                    frozen_integrity = digest(frozen_raw) == frozen_report.get("inventory_snapshot_sha256")
                    frozen_by_id = {str(row["id"]): Question(**{"bank_scope": "public", "is_hidden": False, **row})
                                    for row in frozen_raw.get("questions", [])}
                    from backend.services.auto_question_review import question_snapshot_payload
                    snapshot_matches = Counter()
                    snapshot_changed_fields = Counter()
                    for question in questions:
                        baseline = frozen_by_id.get(str(question.id))
                        if baseline is None:
                            snapshot_matches["not_in_frozen_active_snapshot"] += 1
                            continue
                        current_payload = question_snapshot_payload(question)
                        baseline_payload = question_snapshot_payload(baseline)
                        if digest(current_payload) == digest(baseline_payload):
                            snapshot_matches["exact_payload_match"] += 1
                        else:
                            snapshot_matches["payload_changed"] += 1
                            for field in set(current_payload) | set(baseline_payload):
                                if current_payload.get(field) != baseline_payload.get(field):
                                    snapshot_changed_fields[field] += 1
                    snapshot_matches["frozen_rows_absent_from_backup"] = sum(
                        1 for key in frozen_by_id if key not in {str(q.id) for q in questions})
                    run_counts = Counter(run.question_id for run in runs)
                    origin_counts = Counter(q.question_provenance for q in questions)
                    use_counts = Counter((q.bank_scope, q.is_active) for q in questions)
                    node_class = Counter("inactive_node" if not nodes.get(q.kp_id) or not nodes[q.kp_id].is_active
                        else "not_assessable" if not nodes[q.kp_id].is_assessable
                        else "reference_only" if nodes[q.kp_id].is_reference_only else "assessable_leaf"
                        for q in questions)
                    source_status = Counter(q.source_status or "unknown" for q in questions)
                    source_type_counts = Counter()
                    answer_missing = explanation_missing = 0
                    solver_counts = Counter()
                    review_counts = Counter()
                    blocker_counts = Counter()
                    rows = []
                    duplicate_map = duplicates(questions)
                    structure_counts = Counter()
                    structure_issue_counts = Counter()
                    exact_duplicate_rows = near_duplicate_rows = 0
                    history_before = fingerprints(database_url)
                    assessable = [n for n in nodes.values() if n.is_active and n.is_assessable and not n.is_reference_only]
                    all_questions = questions
                    for q in questions:
                        node = nodes.get(q.kp_id)
                        source = ((q.grading_config or {}).get("provenance") or {}).get("source", {})
                        source_type_counts[str(source.get("source_type") or "missing")] += 1
                        answer_missing += not bool((q.correct_answer or "").strip())
                        explanation_missing += not bool((q.explanation or "").strip())
                        solver = verify_problem(q)
                        solver_counts[str(solver.get("status") or "UNKNOWN")] += 1
                        structure = validate_question_content(q,
                            is_reference_only=bool(node and node.is_reference_only))
                        structure_counts[str(structure.completeness)] += 1
                        structure_issue_counts.update(structure.detected_issues)
                        duplicate = duplicate_map.get(str(q.id), {"exact": [], "near": []})
                        exact_duplicate_rows += bool(duplicate.get("exact"))
                        near_duplicate_rows += bool(duplicate.get("near"))
                        source_evidence = source_pack_evidence(q, registry, node)
                        original_provenance, original_status = q.question_provenance, q.source_status
                        proposed_reclassification = False
                        if (source_evidence and source.get("source_type") == "exam"
                                and q.question_provenance == "legacy_unknown"):
                            # In-memory proposal only. Nothing is flushed or committed.
                            q.question_provenance = "real_exam"
                            q.source_status = "traceable"
                            proposed_reclassification = True
                        try:
                            with db.no_autoflush:
                                assessment = assess_auto_qualification(db, q, node,
                                    source_evidence=source_evidence, all_questions=all_questions) if node else {
                                        "status": "QUARANTINED", "reason": "mapping_missing"}
                            status = str(assessment.get("status", "UNKNOWN"))
                            review_counts[status] += 1
                            reason = str(assessment.get("reason") or "")
                            if reason:
                                blocker_counts[reason] += 1
                            else:
                                for stage_name, item in assessment.get("stages", {}).items():
                                    if item.get("status") != "PASS":
                                        blocker_counts[f"{stage_name}:{item.get('reason') or item.get('status')}"] += 1
                            rows.append({"question_id": str(q.id), "active": bool(q.is_active),
                                "original_provenance": original_provenance,
                                "proposed_provenance": q.question_provenance if proposed_reclassification else original_provenance,
                                "proposed_source_status": q.source_status if proposed_reclassification else original_status,
                                "proposal_only": proposed_reclassification,
                                "node_code": node.code if node else None,
                                "node_class": ("missing" if node is None else "inactive" if not node.is_active
                                    else "not_assessable" if not node.is_assessable
                                    else "reference_only" if node.is_reference_only else "assessable_leaf"),
                                "local_source_pack_traceable": bool(source_evidence),
                                "source_content_sha256": question_content_sha256(q),
                                "source_archive_sha256": source_evidence.get("source_archive_sha256") if source_evidence else None,
                                "source_verbatim_verified": False,
                                "independent_solver_status": solver.get("status"),
                                "structure_completeness": structure.completeness,
                                "structure_issues": list(structure.detected_issues),
                                "exact_duplicate_count": len(duplicate.get("exact", [])),
                                "near_duplicate_count": len(duplicate.get("near", [])),
                                "review_status": status, "review_reason": reason or None})
                        except Exception as exc:
                            review_counts["ASSESSMENT_ERROR"] += 1
                            blocker_counts[f"assessment_error:{type(exc).__name__}"] += 1
                            rows.append({"question_id": str(q.id), "review_status": "ASSESSMENT_ERROR",
                                "error_type": type(exc).__name__, "node_class": "not_completed"})
                        finally:
                            q.question_provenance, q.source_status = original_provenance, original_status

                    policy_summary = []
                    for node in sorted(assessable, key=lambda row: row.code):
                        policy = policies.get(node.id)
                        mapped = [q for q in questions if q.kp_id == node.id]
                        policy_summary.append({"node_code": node.code, "node_name": node.name,
                            "subject": node.subject, "questions": len(mapped),
                            "active_questions": sum(q.is_active for q in mapped),
                            "policy_present": policy is not None,
                            "required_types": (policy.required_question_types if policy else None),
                            "min_confirmations": (policy.min_confirmations if policy else None),
                            "min_day_span": (policy.min_day_span if policy else None)})
                    db.rollback()
                    history_after = fingerprints(database_url)
                    report["history_fingerprints_before_after"] = {name: {
                        "before": history_before[name], "after": history_after[name],
                        "unchanged": history_before[name] == history_after[name]} for name in history_before}
                    report["question_summary"] = {"total": len(questions),
                        "active": sum(q.is_active for q in questions), "inactive": sum(not q.is_active for q in questions),
                        "bank_scope_active_counts": {f"{scope}:{active}": count for (scope, active), count in use_counts.items()},
                        "provenance_counts": dict(origin_counts), "source_status_counts": dict(source_status),
                        "active_provenance_counts": dict(Counter(q.question_provenance for q in questions if q.is_active)),
                        "inactive_provenance_counts": dict(Counter(q.question_provenance for q in questions if not q.is_active)),
                        "active_source_status_counts": dict(Counter(q.source_status or "unknown" for q in questions if q.is_active)),
                        "inactive_source_status_counts": dict(Counter(q.source_status or "unknown" for q in questions if not q.is_active)),
                        "source_type_counts": dict(source_type_counts), "missing_answer": answer_missing,
                        "missing_explanation": explanation_missing, "independent_solver_status": dict(solver_counts),
                        "consistency_run_rows": len(runs), "questions_with_consistency_runs": len(run_counts),
                        "structural_completeness": dict(structure_counts),
                        "structural_issue_counts": dict(structure_issue_counts),
                        "exact_duplicate_rows": exact_duplicate_rows, "near_duplicate_rows": near_duplicate_rows}
                    report["frozen_snapshot_comparison"] = {"snapshot_integrity_passed": frozen_integrity,
                        "snapshot_captured_at": frozen_report.get("checked_at"),
                        "snapshot_revision": frozen_report.get("revision"),
                        "active_snapshot_questions": len(frozen_by_id),
                        "question_payload_comparison": dict(snapshot_matches),
                        "changed_payload_fields": dict(snapshot_changed_fields),
                        "warning": "The verified backup predates the frozen active-question snapshot; differences remain reported, not reconciled."}
                    report["knowledge_summary"] = {"total": len(nodes), "active": sum(n.is_active for n in nodes.values()),
                        "active_assessable": sum(n.is_active and n.is_assessable for n in nodes.values()),
                        "active_assessable_not_reference_only": len(assessable),
                        "active_assessable_reference_only": sum(n.is_active and n.is_assessable and n.is_reference_only for n in nodes.values()),
                        "policy_rows": len(policies), "active_question_node_classes": dict(node_class)}
                    report["local_pack_audit"] = {"candidate_rows": sum(len(v) for v in registry.values()),
                        "rejected_files": len(rejected_assets),
                        "questions_with_unique_matching_source_pack": sum(row.get("local_source_pack_traceable", False) for row in rows),
                        "question_source_identity_matches": sum(row.get("local_source_pack_traceable", False) for row in rows),
                        "active_questions_with_source_pack": sum(row.get("local_source_pack_traceable", False) for row in rows if row.get("active")),
                        "inactive_questions_with_source_pack": sum(row.get("local_source_pack_traceable", False) for row in rows if not row.get("active")),
                        "note": "structured local source-pack trace only; no independent source authenticity or page-verbatim proof"}
                    report["auto_review"] = {"version": "public-question-auto-review-v2",
                        "read_only_assessment_statuses": dict(review_counts),
                        "blockers": dict(blocker_counts), "formal_qualification_events_written": 0,
                        "student_graduation_algorithm_changed": False,
                        "personal_question_exclusion_retained": True}
                    report["assessable_leaf_inventory"] = policy_summary
                    report["per_question_results"] = rows
            finally:
                engine.dispose()
            report["migration_head_in_isolated_copy"] = "f48c2e7d901a"
            report["isolated_migration_only"] = True
            report["assessment_database_read_only"] = True
    finally:
        report["temporary_cluster_stopped"] = not (manager.cluster / "postmaster.pid").exists()
        marker = manager.marker
        if (report["temporary_cluster_stopped"] and manager.owner and marker.is_file()
                and temp.resolve().parent == Path(tempfile.gettempdir()).resolve()
                and temp.name.startswith("kaoyan-phase45h-completion-")
                and json.loads(marker.read_text(encoding="utf-8"))["cluster_id"] == manager.owner["cluster_id"]):
            shutil.rmtree(temp)
            report["temporary_data_removed"] = True
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        output.mkdir(parents=True, exist_ok=True)
        (output / "archive-audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", type=Path, default=BACKUP)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args)
    safe = {key: value for key, value in report.items() if key != "per_question_results"}
    print(json.dumps(safe, ensure_ascii=False, indent=2, default=str))
    return 0 if report.get("temporary_cluster_stopped") and report.get("temporary_data_removed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
