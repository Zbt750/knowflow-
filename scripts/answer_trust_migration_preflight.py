"""Read-only local schema/data fingerprints around the Phase 4.5A migration.

Only aggregate counts and hashes are written to ignored storage/answer-trust.
This command never applies a migration or records an answer verification.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url

from backend.config import get_settings
from backend.db import create_db_engine
from backend.models import import_models
from backend.models.base import Base

PREVIOUS = "e42c7a10b9f3"
TARGET = "f45a9b7e2c10"
EVENT_TABLE = "question_answer_verification_events"
POINTER = "answer_verification_event_id"
FORMAT = "answer-trust-migration-fingerprint-v1"
EXPECTED_DELTAS = {
    ("add_table", EVENT_TABLE, ""),
    ("add_index", EVENT_TABLE, "ix_answer_verification_question_created"),
    ("add_index", EVENT_TABLE, "ix_question_answer_verification_events_question_id"),
    ("add_column", "questions", POINTER),
    ("add_fk", "questions", "fk_question_current_answer_verification"),
}


def local_database_url(settings):
    url = make_url(str(settings.active_database_url))
    if settings.app_env != "dev" or url.database != "kaoyan" or url.host not in {
        "localhost", "127.0.0.1", "::1"
    }:
        raise ValueError("This operation requires the local APP_ENV=dev kaoyan database")
    return url


def private_output(path: Path) -> Path:
    resolved = path.resolve()
    root = (ROOT / "storage/answer-trust").resolve()
    if not resolved.is_relative_to(root) or resolved == root or resolved.exists():
        raise ValueError("Use a new output file under ignored storage/answer-trust")
    return resolved


def delta_signatures(differences) -> list[tuple[str, str, str]]:
    signatures = []
    for difference in differences:
        if isinstance(difference, list):
            signatures.extend((str(d[0]), str(d[2]), str(d[3])) for d in difference)
        elif difference[0] == "add_column":
            signatures.append((difference[0], difference[2], difference[3].name))
        else:
            obj = difference[-1]
            table = getattr(obj, "table", None)
            signatures.append((difference[0], table.name if table is not None else obj.name,
                obj.name if table is not None else ""))
    return sorted(signatures)


def migration_chain() -> dict:
    config = Config(str(ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    target = script.get_revision(TARGET)
    return {"heads": script.get_heads(), "target": target.revision,
        "previous": target.down_revision,
        "passed": script.get_heads() == [TARGET] and target.down_revision == PREVIOUS}


def fingerprint_database(connection) -> dict:
    """Hash canonical full rows without persisting any question/user content."""
    tables = sorted(inspect(connection).get_table_names(schema="public"))
    result = {}
    for table in tables:
        if table in {"alembic_version", EVENT_TABLE}:
            continue
        if not re.fullmatch(r"[a-z][a-z0-9_]*", table):
            raise ValueError("Unexpected table identifier")
        projection = "to_jsonb(t) - 'answer_verification_event_id'" if table == "questions" else "to_jsonb(t)"
        digest = hashlib.sha256()
        count = 0
        rows = connection.execute(text(
            f'SELECT ({projection})::text FROM public."{table}" t ORDER BY ({projection})::text'
        ))
        for row in rows:
            raw = row[0].encode("utf-8")
            digest.update(len(raw).to_bytes(8, "big"))
            digest.update(raw)
            count += 1
        result[table] = {"rows": count, "sha256": digest.hexdigest()}
    return result


def compare_fingerprints(before: dict, after: dict) -> dict:
    old, new = before["tables"], after["tables"]
    changed = sorted(name for name in old if old[name] != new.get(name))
    unexpected = sorted(set(new) - set(old))
    return {"passed": not changed and not unexpected,
        "changed_existing_tables": changed, "unexpected_data_tables": unexpected,
        "protected_table_count": len(old)}


def build_report(connection, *, phase: str) -> dict:
    inspector = inspect(connection)
    revision = connection.scalar(text("SELECT version_num FROM public.alembic_version"))
    import_models()
    differences = delta_signatures(compare_metadata(
        MigrationContext.configure(connection, opts={"compare_type": True}), Base.metadata))
    columns = {row["name"] for row in inspector.get_columns("questions", schema="public")}
    table_exists = inspector.has_table(EVENT_TABLE, schema="public")
    function_exists = bool(connection.scalar(text(
        "SELECT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname='public' AND p.proname='reject_answer_verification_mutation')")))
    checks = inspector.get_check_constraints("questions", schema="public")
    provenance_checks = [c["sqltext"] for c in checks if "answer_provenance" in c["sqltext"]]
    all_tables = fingerprint_database(connection)
    answer_states = connection.execute(text(
        "SELECT answer_provenance, answer_reliability, count(*) FROM public.questions GROUP BY 1,2 ORDER BY 1,2"
    )).all()
    policies = connection.execute(text(
        "SELECT required_question_types, note FROM public.kp_mastery_policies"
    )).all()
    policy_types = Counter(json.dumps(row[0], ensure_ascii=False, sort_keys=True) for row in policies)
    policy_origins = Counter("reference_index_seed" if (row[1] or "").startswith("历年真题索引策略：") else "other"
        for row in policies)
    triggers = connection.execute(text(
        "SELECT t.tgname, t.tgenabled, p.proname FROM pg_trigger t "
        "JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
        "JOIN pg_proc p ON p.oid=t.tgfoid WHERE n.nspname='public' "
        "AND c.relname=:table AND NOT t.tgisinternal"), {"table": EVENT_TABLE}).all()
    event_count = connection.scalar(text(f"SELECT count(*) FROM public.{EVENT_TABLE}")) if table_exists else None
    pointer_count = connection.scalar(text(f"SELECT count(*) FROM public.questions WHERE {POINTER} IS NOT NULL")) if POINTER in columns else None
    foreign_keys = inspector.get_foreign_keys("questions", schema="public")
    pointer_fk = any(f["constrained_columns"] == [POINTER] and f["referred_table"] == EVENT_TABLE
        and f["options"].get("ondelete") == "RESTRICT" for f in foreign_keys)
    event_constraints = inspector.get_check_constraints(EVENT_TABLE, schema="public") if table_exists else []
    unique_keys = inspector.get_unique_constraints(EVENT_TABLE, schema="public") if table_exists else []
    event_contract = (table_exists and all(any(token in c["sqltext"] for c in event_constraints)
        for token in ("event_type", "verification_type", "answer_sha256", "idempotency_key"))
        and any(u["column_names"] == ["idempotency_key"] for u in unique_keys))
    schema_passed = (
        revision == PREVIOUS and set(differences) == EXPECTED_DELTAS and not table_exists
        and POINTER not in columns and not function_exists
        and provenance_checks and not any("human_verified" in c for c in provenance_checks)
    ) if phase == "before" else (
        revision == TARGET and not differences and event_contract and pointer_fk and function_exists
        and any(t[0] == "question_answer_verification_events_immutable" and t[1] == "O"
            and t[2] == "reject_answer_verification_mutation" for t in triggers)
        and any("human_verified" in c for c in provenance_checks)
        and event_count == 0 and pointer_count == 0
    )
    return {"format": FORMAT, "created_at": datetime.now(timezone.utc).isoformat(),
        "phase": phase, "read_only": True, "model_calls": 0,
        "database": "local_dev_kaoyan", "revision": revision,
        "schema_passed": bool(schema_passed), "schema_deltas": differences,
        "migration_chain": migration_chain(), "tables": all_tables,
        "evidence_window_entries": connection.scalar(text(
            "SELECT COALESCE(sum(jsonb_array_length(evidence_window::jsonb)),0) FROM public.kp_states")),
        "answer_distribution": [{"provenance": p, "reliability": r, "count": n} for p,r,n in answer_states],
        "policy_type_distribution": dict(sorted(policy_types.items())),
        "policy_creation_distribution": dict(policy_origins),
        "event_table_exists": table_exists, "verification_events": event_count,
        "current_event_pointers": pointer_count, "pointer_fk_valid": pointer_fk,
        "append_only_trigger": [dict(name=t[0], enabled=t[1], function=t[2]) for t in triggers],
        "fingerprint_note": "All existing public table rows are hashed; only the added null Question pointer and Alembic revision are excluded."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("before", "after"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--before", type=Path)
    args = parser.parse_args()
    output = private_output(args.output)
    if args.phase == "after" and args.before is None:
        parser.error("--after requires --before fingerprint")
    settings = get_settings()
    url = local_database_url(settings)
    engine = create_db_engine(str(url))
    try:
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            report = build_report(connection, phase=args.phase)
            connection.rollback()
        if args.before:
            before = json.loads(args.before.read_text(encoding="utf-8"))
            if before.get("format") != FORMAT or before.get("phase") != "before" or not before.get("schema_passed"):
                raise ValueError("Before fingerprint is not a passed preflight")
            report["data_comparison"] = compare_fingerprints(before, report)
        report["passed"] = report["schema_passed"] and report["migration_chain"]["passed"] and report.get(
            "data_comparison", {"passed": True})["passed"]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"passed": report["passed"], "revision": report["revision"],
            "protected_tables": len(report["tables"]), "output": str(output)}, ensure_ascii=False))
        return 0 if report["passed"] else 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
