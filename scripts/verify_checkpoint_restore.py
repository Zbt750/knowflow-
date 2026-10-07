"""Restore a private checkpoint into a newly-created disposable local database.

Never targets an existing database, never extracts assets or calls a model.
Cleanup is limited to the random database created by this invocation.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import subprocess
import sys
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from backend.config import get_settings


def validate_database_name(name):
    if not re.fullmatch(r"kaoyan_restore_[a-f0-9]{32}", name):
        raise ValueError("Only a newly generated recovery-drill database is allowed")
    return name


def safe_asset_name(name):
    """Validate portable archive names, even though this drill never extracts."""
    if not isinstance(name, str) or not name or "\\" in name:
        raise ValueError("Unsafe asset path")
    path = PurePosixPath(name)
    if (path.is_absolute() or PureWindowsPath(name).drive or
            any(part in {"", ".", ".."} or ":" in part for part in name.split("/"))):
        raise ValueError("Unsafe asset path")
    return path.as_posix()


def material_asset_coverage(materials, assets, upload_prefix):
    """Compare restored rows to verified archived bytes, not live source files."""
    prefix = safe_asset_name(upload_prefix)
    inventory = {safe_asset_name(row["path"]): row for row in assets}
    counts = {"materials": 0, "matched": 0, "missing": 0, "unsafe_paths": 0,
              "hash_mismatches": 0, "size_mismatches": 0, "unknown_hashes": 0}
    for material in materials:
        counts["materials"] += 1
        try:
            stored = safe_asset_name(material["stored_path"])
        except ValueError:
            counts["unsafe_paths"] += 1
            continue
        asset = inventory.get(f"{prefix}/{stored}")
        if not asset:
            counts["missing"] += 1
            continue
        counts["matched"] += 1
        if material["raw_hash"]:
            counts["hash_mismatches"] += material["raw_hash"] != asset["sha256"]
        else:
            counts["unknown_hashes"] += 1
        if material["file_size"] is not None:
            counts["size_mismatches"] += material["file_size"] != asset["bytes"]
    counts["passed"] = not any(counts[key] for key in (
        "missing", "unsafe_paths", "hash_mismatches", "size_mismatches", "unknown_hashes"))
    return counts


def check_backup(folder):
    folder = folder.resolve()
    allowed = (ROOT / "storage/backups").resolve()
    if folder == allowed or not folder.is_relative_to(allowed) or folder.is_symlink():
        raise ValueError("Use a private checkpoint under storage/backups")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format") != "development-checkpoint-backup-v1":
        raise ValueError("Unknown backup format")
    dump = folder / "database.dump"
    if hashlib.sha256(dump.read_bytes()).hexdigest() != manifest["database_sha256"]:
        raise ValueError("Database archive hash mismatch")
    with zipfile.ZipFile(folder / "private-assets.zip") as archive:
        expected = manifest["assets"]
        names = [r["path"] for r in expected]
        for name in names:
            safe_asset_name(name)
        if len(set(names)) != len(names) or sorted(archive.namelist()) != sorted(names):
            raise ValueError("Asset inventory mismatch or duplicate paths")
        for row in expected:
            data = archive.read(row["path"])
            if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
                raise ValueError("Asset hash mismatch")
    return dump, {"database_sha256": manifest["database_sha256"], "asset_files_verified": len(names)}


def drill(backup, pg_bin, *, admin_user):
    settings = get_settings()
    source = make_url(str(settings.active_database_url))
    if settings.app_env != "dev" or source.host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Recovery drill is restricted to local development PostgreSQL")
    dump, facts = check_backup(backup)
    restore = pg_bin.resolve() / ("pg_restore.exe" if os.name == "nt" else "pg_restore")
    if not restore.is_file():
        raise ValueError("Explicit PostgreSQL client binary required")
    name = validate_database_name("kaoyan_restore_" + uuid.uuid4().hex)
    admin = source.set(database="postgres", username=admin_user,
                       password=os.environ.get("KAOYAN_RESTORE_ADMIN_PASSWORD"))
    engine = create_engine(admin, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 5})
    created = False
    facts.update({"version": "checkpoint-restore-drill-v1", "created_at": datetime.now(timezone.utc).isoformat(),
                  "temporary_database": name, "development_database_modified": False,
                  "assets_extracted": False, "model_calls": 0, "restore_passed": False, "cleanup_passed": False})
    try:
        with engine.connect() as conn:
            if conn.execute(text("SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname=:name)"), {"name": name}).scalar():
                raise ValueError("Temporary database already exists; refusing to reuse")
            conn.execute(text(f'CREATE DATABASE "{name}" TEMPLATE template0'))
            created = True
        env = os.environ.copy()
        # Do not inherit credentials/service overrides that point at another DB.
        for key in ("PGHOST", "PGHOSTADDR", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE", "PGSERVICE"):
            env.pop(key, None)
        env.update({"PGHOST": admin.host, "PGPORT": str(admin.port or 5432),
                    "PGUSER": admin.username, "PGDATABASE": name})
        if admin.password:
            env["PGPASSWORD"] = admin.password
        result = subprocess.run([str(restore), "--no-password", "--exit-on-error", "--no-owner",
                                 "--no-privileges", "--dbname", name, str(dump)],
                                env=env, capture_output=True, timeout=60)
        if result.returncode:
            raise RuntimeError("Archive restore failed; sensitive diagnostics not printed")
        restored = create_engine(admin.set(database=name), connect_args={"connect_timeout": 5})
        try:
            with restored.connect() as conn:
                conn.execute(text("SET TRANSACTION READ ONLY"))
                tables = ("knowledge_points", "questions", "question_attempts", "daily_plans", "chat_messages")
                facts["restored_row_counts"] = {table: conn.execute(text(f'SELECT count(*) FROM public."{table}"')).scalar() for table in tables}
                facts["restored_migration_revision"] = conn.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one()
                manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
                upload_prefix = settings.upload_dir.resolve().relative_to(ROOT.resolve()).as_posix()
                materials = conn.execute(text("SELECT stored_path, raw_hash, file_size FROM public.materials")).mappings().all()
                facts["material_asset_coverage"] = material_asset_coverage(materials, manifest["assets"], upload_prefix)
                facts["restore_passed"] = facts["material_asset_coverage"]["passed"]
        finally:
            restored.dispose()
    except Exception as exc:
        facts["error_type"] = type(exc).__name__
    finally:
        if created:
            try:
                with engine.connect() as conn:
                    # Exact validated name from this invocation, never a CLI target.
                    conn.execute(text(f'DROP DATABASE "{name}"'))
                facts["cleanup_passed"] = True
            except Exception as exc:
                facts["cleanup_error_type"] = type(exc).__name__
        engine.dispose()
    return facts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--pg-bin", type=Path, required=True)
    parser.add_argument("--admin-user", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "eval/reports") or output.exists():
        parser.error("Use a new local report under eval/reports")
    facts = drill(args.backup, args.pg_bin, admin_user=args.admin_user)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(facts, stream, ensure_ascii=False, indent=2)
    print(json.dumps(facts, ensure_ascii=False, indent=2))
    return 0 if facts["restore_passed"] and facts["cleanup_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
