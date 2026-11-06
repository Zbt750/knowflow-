"""Plan, back up, apply or guarded-recover the approved origin-quota conversion.

Only the local dev database is allowed. Reports/dumps remain under ignored
storage. No model calls, answer verification or historical state writes.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import getpass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from backend.config import get_settings
from backend.models import import_models
from backend.models.base import Base
from backend.db import create_db_engine
from backend.mastery.policy import VERSIONED_POLICY_FIELDS
from backend.services.graduation_policy_migration import policy_snapshot, policy_hash, review_policy_guard
from scripts.answer_trust_migration_preflight import fingerprint_database, delta_signatures, local_database_url, private_output
from scripts.create_development_checkpoint_backup import safe_output

PREVIOUS = "f45a9b7e2c10"
TARGET = "f46b2c8d901a"
# Explicit compatible descendant only. Unknown/new revisions still fail closed.
PERSONAL_BANK_REVISION = "f47c10a2b903"
# The H audit-event migration is a schema-only descendant; accepting it here
# keeps this policy guard usable without changing any policy values or rules.
AUTO_QUESTION_REVIEW_REVISION = "f48c2e7d901a"
BATCH_TIMESTAMP_REVISION = "f49d10c2a703"
FROZEN_GRADUATION_SET_REVISION = "f50c7e2a1b64"
PUBLIC_SET_CAPACITY_REVISION = "f51a2c7d901b"
LEARNER_GRADUATION_SET_BINDING_REVISION = "f52a6c8d301e"
QUESTION_IMMUTABLE_VERSIONS_REVISION = "f53b7e2a901c"
LEGACY_GRADUATION_SET_TRANSITION_REVISION = "f54c8a1d7e20"
# Schema-only descendant adding the supported server_generated provenance value.
# It does not change kp_mastery_policies, so this guarded policy converter can
# safely run after this known migration too.
QUESTION_PROVENANCE_COMPATIBILITY_REVISION = "f55a7b9012c3"
# Reviewed descendants leave the policy table and origin semantics unchanged.
# The final revision strengthens permanent item history, including RESTRICT.
STANDALONE_RETRY_REVISION = "f56b8c9012d4"
PERSONAL_TRAINING_REVISION = "f57c9a21d340"
PERSONAL_TRAINING_DRAFT_REVISION = "f58d22ab41c7"
SOFT_REMOVE_HISTORY_REVISION = "f59e33bc52d8"
COMPATIBLE_POLICY_REVISIONS = (
    TARGET,
    PERSONAL_BANK_REVISION,
    AUTO_QUESTION_REVIEW_REVISION,
    BATCH_TIMESTAMP_REVISION,
    FROZEN_GRADUATION_SET_REVISION,
    PUBLIC_SET_CAPACITY_REVISION,
    LEARNER_GRADUATION_SET_BINDING_REVISION,
    QUESTION_IMMUTABLE_VERSIONS_REVISION,
    LEGACY_GRADUATION_SET_TRANSITION_REVISION,
    QUESTION_PROVENANCE_COMPATIBILITY_REVISION,
    STANDALONE_RETRY_REVISION,
    PERSONAL_TRAINING_REVISION,
    PERSONAL_TRAINING_DRAFT_REVISION,
    SOFT_REMOVE_HISTORY_REVISION,
)
FORMAT = "policy-origin-migration-v1"


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, default=str)


def load_proposal(path: Path) -> dict:
    proposal = json.loads(path.read_text(encoding="utf-8"))
    if (proposal.get("format") != "graduation-policy-compatibility-proposal-v1"
        or proposal.get("proposal_status") != "NOT_APPROVED_NOT_APPLIED"
        or not proposal.get("affected_policies")):
        raise ValueError("The original audited proposal is required")
    ids = [row["node_id"] for row in proposal["affected_policies"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate proposal identities")
    return proposal


def raw_policies(connection, *, lock=False) -> list[dict]:
    rows = connection.execute(text("SELECT * FROM public.kp_mastery_policies ORDER BY kp_id"
        + (" FOR UPDATE" if lock else ""))).mappings().all()
    return [dict(row) for row in rows]


def event_fingerprint(connection) -> dict:
    digest = hashlib.sha256()
    rows = list(connection.execute(text("SELECT to_jsonb(e)::text FROM public.question_answer_verification_events e ORDER BY to_jsonb(e)::text")))
    for row in rows:
        digest.update(row[0].encode("utf-8") + b"\n")
    return {"count": len(rows), "sha256": digest.hexdigest(),
        "current_pointers": connection.scalar(text("SELECT count(*) FROM public.questions WHERE answer_verification_event_id IS NOT NULL"))}


def schema_preflight(connection) -> dict:
    revision = connection.scalar(text("SELECT version_num FROM public.alembic_version"))
    import_models()
    changes = delta_signatures(compare_metadata(MigrationContext.configure(connection,
        opts={"compare_type": True}), Base.metadata))
    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    expected = {("add_column", "kp_mastery_policies", "policy_version"),
                ("add_column", "kp_mastery_policies", "required_question_origins")}
    head = script.get_heads()
    migration_edges = (
        (TARGET, PREVIOUS),
        (PERSONAL_BANK_REVISION, TARGET),
        (AUTO_QUESTION_REVIEW_REVISION, PERSONAL_BANK_REVISION),
        (BATCH_TIMESTAMP_REVISION, AUTO_QUESTION_REVIEW_REVISION),
        (FROZEN_GRADUATION_SET_REVISION, BATCH_TIMESTAMP_REVISION),
        (PUBLIC_SET_CAPACITY_REVISION, FROZEN_GRADUATION_SET_REVISION),
        (LEARNER_GRADUATION_SET_BINDING_REVISION, PUBLIC_SET_CAPACITY_REVISION),
        (QUESTION_IMMUTABLE_VERSIONS_REVISION, LEARNER_GRADUATION_SET_BINDING_REVISION),
        (LEGACY_GRADUATION_SET_TRANSITION_REVISION, QUESTION_IMMUTABLE_VERSIONS_REVISION),
        (QUESTION_PROVENANCE_COMPATIBILITY_REVISION, LEGACY_GRADUATION_SET_TRANSITION_REVISION),
        (STANDALONE_RETRY_REVISION, QUESTION_PROVENANCE_COMPATIBILITY_REVISION),
        (PERSONAL_TRAINING_REVISION, STANDALONE_RETRY_REVISION),
        (PERSONAL_TRAINING_DRAFT_REVISION, PERSONAL_TRAINING_REVISION),
        (SOFT_REMOVE_HISTORY_REVISION, PERSONAL_TRAINING_DRAFT_REVISION),
    )
    chain_ok = (len(head) == 1 and head[0] in COMPATIBLE_POLICY_REVISIONS
        and all(script.get_revision(child).down_revision == parent for child, parent in migration_edges))
    passed = chain_ok and (revision == PREVIOUS and set(changes) == expected
        or revision in COMPATIBLE_POLICY_REVISIONS and not changes)
    if revision in COMPATIBLE_POLICY_REVISIONS:
        checks = inspect(connection).get_check_constraints("kp_mastery_policies", schema="public")
        passed = passed and all(any(token in c["sqltext"] for c in checks)
            for token in ("policy_version", "required_question_origins", "external_exam"))
    return {"revision": revision, "schema_deltas": changes, "chain_passed": chain_ok, "passed": bool(passed)}


def plan(connection, proposal: dict, *, lock=False) -> dict:
    policies = raw_policies(connection, lock=lock)
    by_id = {str(row["kp_id"]): row for row in policies}
    nodes = {str(row["id"]): dict(row) for row in connection.execute(text("SELECT id,code,name,subject,is_active,is_assessable,is_reference_only FROM public.knowledge_points")).mappings()}
    refs = dict(connection.execute(text("SELECT knowledge_point_id::text,count(*) FROM public.exam_question_references GROUP BY knowledge_point_id")).all())
    audit_time = datetime.fromisoformat(proposal["created_at"])
    diffs = [review_policy_guard(by_id.get(row["node_id"]), nodes.get(row["node_id"]),
        refs.get(row["node_id"],0), row, audit_time) for row in proposal["affected_policies"]]
    counts = Counter(row["status"] for row in diffs)
    approved_ids = {row["node_id"] for row in proposal["affected_policies"]}
    return {"format": FORMAT, "created_at": datetime.now(timezone.utc).isoformat(),
        "schema": schema_preflight(connection), "total_policies": len(policies),
        "audited_candidate_count": len(diffs), "status_counts": dict(counts),
        "outside_proposal_count": sum(str(row["kp_id"]) not in approved_ids for row in policies),
        "diffs": diffs, "before_policies": policies, "tables": fingerprint_database(connection),
        "verification_fingerprint": event_fingerprint(connection), "model_calls": 0,
        "legacy_version_count": sum(row.get("policy_version",1) == 1 for row in policies),
        "new_version_count": sum(row.get("policy_version",1) == 2 for row in policies),
        "frozen_set_version_count": sum(row.get("policy_version",1) == 3 for row in policies)}


def protected_data_comparison(before: dict, after: dict) -> dict:
    old, new = before["tables"], after["tables"]
    changed = sorted(t for t in old if t != "kp_mastery_policies" and old[t] != new.get(t))
    extra = sorted(set(new) - set(old))
    events_equal = before["verification_fingerprint"] == after["verification_fingerprint"]
    return {"passed": not changed and not extra and events_equal,
        "changed_protected_tables": changed, "unexpected_tables": extra,
        "verification_unchanged": events_equal, "protected_table_count": len(old)-1}


def backup(connection, proposal: dict, output: Path, pg_bin: Path, url) -> dict:
    snapshot = plan(connection, proposal)
    if not snapshot["schema"]["passed"]:
        raise ValueError("Schema preflight failed")
    output = safe_output(output)
    dump = pg_bin.resolve() / "pg_dump.exe"
    restore = pg_bin.resolve() / "pg_restore.exe"
    if not dump.is_file() or not restore.is_file():
        raise ValueError("Explicit PostgreSQL client tools are required")
    output.mkdir(parents=True)
    account = f"{os.environ.get('USERDOMAIN','.')}\\{getpass.getuser()}"
    if os.name == "nt" and subprocess.run(["icacls",str(output),"/inheritance:r","/grant:r",account+":(OI)(CI)F"],capture_output=True).returncode:
        raise RuntimeError("Could not protect backup directory")
    env = os.environ.copy()
    for key in ("PGHOST","PGHOSTADDR","PGPORT","PGUSER","PGPASSWORD","PGDATABASE","PGSERVICE"):
        env.pop(key,None)
    env.update({"PGHOST":url.host,"PGPORT":str(url.port or 5432),"PGUSER":url.username,"PGDATABASE":url.database})
    if url.password:
        env["PGPASSWORD"] = url.password
    archive = output / "database.dump"
    # pg_dump shares this read-only transaction's snapshot, so the archive and
    # recorded policy/history fingerprints refer to the same database instant.
    snapshot_id = connection.scalar(text("SELECT pg_export_snapshot()"))
    if subprocess.run([str(dump),"--format=custom","--no-password","--snapshot",snapshot_id,
            "--file",str(archive)],env=env,capture_output=True,timeout=60).returncode:
        raise RuntimeError("Database backup failed; credentials are not printed")
    readable = all(subprocess.run(args,capture_output=True,timeout=60).returncode == 0 for args in (
        [str(restore),"--list",str(archive)],
        [str(restore),"--file",os.devnull,str(archive)]))
    if not readable:
        raise RuntimeError("Backup archive could not be decoded")
    manifest = {"format":"phase45a2-policy-backup-v1", "database_sha256":hashlib.sha256(archive.read_bytes()).hexdigest(),
        "archive_readable":True,"includes":"database schema/data and full policy/proposal checkpoints; no asset recopy",
        "before":snapshot,"proposal":proposal}
    write_json(output / "manifest.json",manifest)
    return {"backup":str(output),"database_sha256":manifest["database_sha256"],"archive_readable":True,
        "eligible":snapshot["status_counts"].get("ELIGIBLE",0)}


def checked_backup(path: Path) -> dict:
    root = (ROOT / "storage/backups").resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(root) or resolved == root:
        raise ValueError("Backup must be under the private backup directory")
    manifest = json.loads((resolved/"manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format") != "phase45a2-policy-backup-v1" or not manifest.get("archive_readable"):
        raise ValueError("A passed Phase 4.5A.2 backup is required")
    if hashlib.sha256((resolved/"database.dump").read_bytes()).hexdigest() != manifest["database_sha256"]:
        raise ValueError("Backup hash mismatch")
    return manifest


def update_policy(connection, snapshot: dict, *, restored_updated_at=None):
    assignments = ", ".join(f"{key}=:p_{key}" if key not in {
        "required_question_types","required_question_origins","excluded_question_types","required_skill_tags","review_intervals_days"
    } else f"{key}=CAST(:p_{key} AS json)" for key in VERSIONED_POLICY_FIELDS)
    params = {"id":snapshot["kp_id"]}
    for key in VERSIONED_POLICY_FIELDS:
        value = snapshot[key]
        params["p_"+key] = json.dumps(value,ensure_ascii=False) if isinstance(value,(dict,list)) else value
    timestamp = "updated_at=now()" if restored_updated_at is None else "updated_at=:restored_time"
    if restored_updated_at is not None:
        params["restored_time"] = datetime.fromisoformat(restored_updated_at) if isinstance(restored_updated_at,str) else restored_updated_at
    connection.execute(text(f"UPDATE public.kp_mastery_policies SET {assignments},{timestamp} WHERE kp_id=:id"),params)


def apply_conversion(connection, proposal: dict, saved: dict) -> dict:
    connection.execute(text("SET LOCAL lock_timeout='5s'"))
    connection.execute(text("SET LOCAL statement_timeout='60s'"))
    if not connection.scalar(text("SELECT pg_try_advisory_xact_lock(454520081)")):
        raise ValueError("A policy maintenance operation is running")
    current = plan(connection,proposal,lock=True)
    if not current["schema"]["passed"]:
        raise ValueError("Schema preflight failed")
    expected_initial = saved["before"]
    # A repeat run may legitimately differ only in the already converted policy table.
    if not protected_data_comparison(expected_initial,current)["passed"]:
        raise ValueError("Protected data changed since backup; create a fresh checkpoint")
    if current["schema"]["revision"] == PREVIOUS:
        config = Config(str(ROOT/"alembic.ini")); config.attributes["connection"] = connection
        command.upgrade(config,TARGET)
    before_rows = {str(row["kp_id"]): row for row in current["before_policies"]}
    expected = {key:policy_snapshot(row) for key,row in before_rows.items()}
    mutations = 0
    for diff in current["diffs"]:
        if diff["status"] == "ELIGIBLE":
            # Also bind to the fresh checkpoint, not only the older audit.
            saved_rows = {str(row["kp_id"]):row for row in saved["before"]["before_policies"]}
            if policy_hash(before_rows[diff["node_id"]]) != policy_hash(saved_rows[diff["node_id"]]):
                diff.update(status="POLICY_CHANGED_SINCE_AUDIT",reason="changed_since_backup")
                continue
            update_policy(connection,diff["expected_after"])
            expected[diff["node_id"]] = diff["expected_after"]
            mutations += 1
    after = plan(connection,proposal)
    rows = {str(row["kp_id"]):row for row in after["before_policies"]}
    preservation = len(rows)==len(expected) and all(policy_hash(rows[key])==policy_hash(value) for key,value in expected.items())
    integrity = protected_data_comparison(current,after)
    if not after["schema"]["passed"] or not preservation or not integrity["passed"]:
        raise ValueError("Post-apply invariants failed; transaction will roll back")
    return {"format":FORMAT,"operation":"apply","created_at":datetime.now(timezone.utc).isoformat(),
        "policy_mutations":mutations,"status_counts":dict(Counter(d["status"] for d in current["diffs"])),
        "before":current,"after":after,"policy_preservation_passed":preservation,
        "protected_data":integrity,"model_calls":0}


def recover_policies(connection, saved: dict, *, apply=False) -> dict:
    schema = schema_preflight(connection)
    if not schema["passed"] or schema["revision"] not in COMPATIBLE_POLICY_REVISIONS:
        raise ValueError("Guarded policy recovery requires the versioned schema")
    before_tables = fingerprint_database(connection)
    before_verification = event_fingerprint(connection)
    rows = {str(r["kp_id"]):r for r in raw_policies(connection,lock=apply)}
    restored_hashes = {}
    diffs = []
    for diff in saved["before"]["diffs"]:
        if diff["status"] != "ELIGIBLE":
            continue
        row = rows.get(diff["node_id"])
        if row and policy_hash(row)==diff["old_hash"]:
            diffs.append({"node_id":diff["node_id"],"status":"NOOP_ALREADY_RESTORED"})
            continue
        receipts = connection.scalar(text("SELECT count(*) FROM public.question_attempts WHERE kp_id=:id "
            "AND grading_evidence->>'policy_version'='2'"),{"id":diff["node_id"]})
        status = "RESTORABLE" if row and policy_hash(row)==diff["expected_new_hash"] and not receipts else "STOP_CHANGED_OR_FUTURE_EVIDENCE"
        diffs.append({"node_id":diff["node_id"],"status":status})
        if status=="RESTORABLE" and apply:
            original = next(r for r in saved["before"]["before_policies"] if str(r["kp_id"])==diff["node_id"])
            update_policy(connection,diff["expected_before"],restored_updated_at=original["updated_at"])
            restored_hashes[diff["node_id"]] = diff["old_hash"]
    after_rows = {str(r["kp_id"]):r for r in raw_policies(connection)}
    after_tables = fingerprint_database(connection)
    protection = protected_data_comparison(
        {"tables":before_tables,"verification_fingerprint":before_verification},
        {"tables":after_tables,"verification_fingerprint":event_fingerprint(connection)})
    hashes_match = all(policy_hash(after_rows[key])==value for key,value in restored_hashes.items())
    if not protection["passed"] or not hashes_match:
        raise ValueError("Recovery integrity check failed; transaction will roll back")
    return {"operation":"recover_apply" if apply else "recover_dry_run","diffs":diffs,
        "status_counts":dict(Counter(d["status"] for d in diffs)),"model_calls":0,
        "protected_data":protection,"restored_policy_hashes_passed":hashes_match}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation",required=True)
    for name in ("plan","backup","apply","recover"):
        p = sub.add_parser(name)
        if name != "recover": p.add_argument("--proposal",type=Path,required=True)
        p.add_argument("--output",type=Path,required=True)
        if name=="backup": p.add_argument("--pg-bin",type=Path,required=True)
        if name in {"apply","recover"}: p.add_argument("--backup",type=Path,required=True)
        if name=="recover": p.add_argument("--apply",action="store_true")
    args=parser.parse_args()
    url=local_database_url(get_settings()); engine=create_db_engine(str(url))
    output=safe_output(args.output) if args.operation=="backup" else private_output(args.output)
    proposal=load_proposal(args.proposal) if args.operation!="recover" else None
    saved=checked_backup(args.backup) if args.operation in {"apply","recover"} else None
    if saved and proposal and saved["proposal"] != proposal: raise ValueError("Proposal differs from the checkpoint")
    try:
        if args.operation in {"apply","recover"}:
            with engine.begin() as c:
                result=apply_conversion(c,proposal,saved) if args.operation=="apply" else recover_policies(c,saved,apply=args.apply)
        else:
            with engine.connect() as c:
                c.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
                result=backup(c,proposal,output,args.pg_bin,url) if args.operation=="backup" else plan(c,proposal)
                c.rollback()
        if args.operation!="backup": write_json(output,result)
        print(json.dumps({"operation":args.operation,"output":str(output),"mutations":result.get("policy_mutations",0),
            "status_counts":result.get("status_counts"),"archive_readable":result.get("archive_readable")},ensure_ascii=False))
        return 0
    finally: engine.dispose()


if __name__=="__main__": raise SystemExit(main())
