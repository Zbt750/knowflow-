"""Apply only f45a9b7e2c10 after a passed preflight and verified recovery backup."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from backend.config import get_settings
from backend.db import create_db_engine
from scripts.answer_trust_migration_preflight import (
    FORMAT, PREVIOUS, TARGET, build_report, compare_fingerprints,
    local_database_url, private_output,
)
from scripts.verify_checkpoint_restore import check_backup


def verify_inputs(before: dict, recovery: dict, backup_facts: dict) -> None:
    if (before.get("format") != FORMAT or before.get("phase") != "before"
            or before.get("revision") != PREVIOUS or before.get("passed") is not True):
        raise ValueError("A passed expected-version preflight is required")
    if (recovery.get("restore_passed") is not True or recovery.get("cleanup_passed") is not True
            or recovery.get("database_sha256") != backup_facts["database_sha256"]
            or recovery.get("restored_migration_revision") != PREVIOUS
            or recovery.get("development_database_modified") is not False):
        raise ValueError("A matching successful isolated restore check is required")
    for table, count in recovery.get("restored_row_counts", {}).items():
        if table not in before["tables"] or before["tables"][table]["rows"] != count:
            raise ValueError("Backup row counts do not match the preflight")


def probe_append_only_function(connection) -> dict:
    """Exercise the installed function on session-local rows, never audit data."""
    connection.execute(text("CREATE TEMP TABLE phase45_trigger_probe (probe integer) ON COMMIT DROP"))
    connection.execute(text("CREATE TRIGGER phase45_probe BEFORE UPDATE OR DELETE ON phase45_trigger_probe "
        "FOR EACH ROW EXECUTE FUNCTION public.reject_answer_verification_mutation()"))
    connection.execute(text("INSERT INTO phase45_trigger_probe VALUES (1)"))
    refused = []
    for operation, sql in (("update", "UPDATE phase45_trigger_probe SET probe=2"),
                           ("delete", "DELETE FROM phase45_trigger_probe")):
        savepoint = connection.begin_nested()
        try:
            connection.execute(text(sql))
        except DBAPIError as exc:
            savepoint.rollback()
            if getattr(exc.orig, "sqlstate", None) != "P0001" or "append-only" not in str(exc.orig):
                raise
            refused.append(operation)
        else:
            savepoint.rollback()
            raise ValueError("Installed append-only function did not refuse mutation")
    return {"passed": refused == ["update", "delete"], "refused": refused,
        "test_relation": "session_temporary_table", "verification_data_written": False}


def activate(connection, before: dict) -> dict:
    connection.execute(text("SET LOCAL lock_timeout = '5s'"))
    connection.execute(text("SET LOCAL statement_timeout = '60s'"))
    if not connection.scalar(text("SELECT pg_try_advisory_xact_lock(454510071)")):
        raise ValueError("Another answer-trust activation is running")
    revision = connection.scalar(text("SELECT version_num FROM public.alembic_version FOR UPDATE"))
    if revision != PREVIOUS:
        raise ValueError("Database revision changed; activation refused")
    current = build_report(connection, phase="before")
    if not current["schema_passed"] or not current["migration_chain"]["passed"]:
        raise ValueError("Current schema no longer matches the preflight")
    if not compare_fingerprints(before, current)["passed"]:
        raise ValueError("Database rows changed since preflight; create a new backup/preflight")
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection"] = connection
    command.upgrade(config, TARGET)
    trigger_check = probe_append_only_function(connection)
    after = build_report(connection, phase="after")
    after["trigger_execution_check"] = trigger_check
    after["data_comparison"] = compare_fingerprints(before, after)
    if not after["schema_passed"] or not after["data_comparison"]["passed"]:
        raise ValueError("Post-upgrade integrity check failed; enclosing transaction will roll back")
    after["passed"] = True
    return after


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--restore-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", required=True)
    args = parser.parse_args()
    output = private_output(args.output)
    settings = get_settings()
    url = local_database_url(settings)
    _, backup_facts = check_backup(args.backup)
    before = json.loads(args.before.read_text(encoding="utf-8"))
    recovery = json.loads(args.restore_report.read_text(encoding="utf-8"))
    verify_inputs(before, recovery, backup_facts)
    engine = create_db_engine(str(url))
    try:
        with engine.begin() as connection:
            receipt = activate(connection, before)
        receipt["activation"] = {"committed_at": datetime.now(timezone.utc).isoformat(),
            "backup_database_sha256": backup_facts["database_sha256"],
            "backup": str(args.backup.resolve()), "verification_data_written": False}
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"passed": True, "revision": receipt["revision"],
            "existing_tables_unchanged": receipt["data_comparison"]["protected_table_count"],
            "verification_events": receipt["verification_events"], "output": str(output)}, ensure_ascii=False))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
