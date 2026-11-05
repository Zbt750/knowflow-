"""Private logical DB + selected source-data backup; no live PG directory copying.

Output stays in ignored storage/backups. No secrets/config/model files are copied.
This is a local recovery artifact, not a public distribution or installer.
"""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.config import get_settings
from sqlalchemy.engine import make_url


def safe_output(path: Path) -> Path:
    path = path.resolve()
    allowed = (ROOT / "storage/backups").resolve()
    if not path.is_relative_to(allowed) or path == allowed or path.exists():
        raise ValueError("Use a new directory under ignored storage/backups")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = safe_output(args.output)
    settings = get_settings()
    if settings.app_env != "dev":
        raise ValueError("This backup entry is for the development database only")
    pg_bin = args.pg_bin.resolve()
    suffix = ".exe" if os.name == "nt" else ""
    dump, restore = pg_bin / ("pg_dump" + suffix), pg_bin / ("pg_restore" + suffix)
    if not dump.is_file() or not restore.is_file():
        raise ValueError("PostgreSQL client binaries required")
    output.mkdir(parents=True)
    if os.name == "nt":
        account = f"{os.environ.get('USERDOMAIN', '.')}\\{getpass.getuser()}"
        acl = subprocess.run(["icacls", str(output), "/inheritance:r", "/grant:r", account + ":(OI)(CI)F"], capture_output=True)
        if acl.returncode:
            raise RuntimeError("Could not restrict the new private backup directory; no data copied")
    url = make_url(str(settings.active_database_url))
    env = os.environ.copy()
    for key, value in {"PGHOST": url.host, "PGPORT": str(url.port or 5432), "PGUSER": url.username,
                       "PGPASSWORD": url.password, "PGDATABASE": url.database}.items():
        if value is not None:
            env[key] = value
    db_file = output / "database.dump"
    result = subprocess.run([str(dump), "--format=custom", "--no-password", "--file", str(db_file)], env=env, capture_output=True)
    if result.returncode:
        raise RuntimeError("Logical database dump failed; partial local artifacts retained, credentials not printed")
    result = subprocess.run([str(restore), "--list", str(db_file)], capture_output=True)
    if result.returncode:
        raise RuntimeError("Database archive listing verification failed")
    roots = [settings.upload_dir.resolve(), ROOT / "storage/question-intake", ROOT / "eval/reports"]
    rows = []
    total = 0
    with zipfile.ZipFile(output / "private-assets.zip", "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for folder in roots:
            if not folder.is_relative_to(ROOT):
                raise ValueError("Source data root must remain inside this project")
            for path in sorted(folder.rglob("*")) if folder.exists() else []:
                if path.is_symlink() or not path.resolve().is_relative_to(folder):
                    raise ValueError("Source links not allowed")
                if not path.is_file():
                    continue
                before = path.stat()
                if before.st_size > 64 * 1024 * 1024 or total + before.st_size > 1024**3:
                    raise ValueError("Backup data size limit exceeded")
                data = path.read_bytes()
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError("Source changed during backup; partial local artifacts retained")
                name = path.relative_to(ROOT).as_posix()
                archive.writestr(name, data)
                rows.append({"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
                total += len(data)
    with zipfile.ZipFile(output / "private-assets.zip") as archive:
        if archive.testzip() is not None:
            raise ValueError("Private asset archive CRC failed")
    packages = subprocess.check_output([sys.executable, "-m", "pip", "list", "--format=json"])
    (output / "observed-python-packages.json").write_bytes(packages)
    manifest = {"format": "development-checkpoint-backup-v1", "created_at": datetime.now(timezone.utc).isoformat(),
        "source_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip(),
        "database_sha256": hashlib.sha256(db_file.read_bytes()).hexdigest(),
        "assets": rows, "excluded": ["credentials", "model-settings", "models", "chroma", "live_pgdata", "external_desktop_papers"],
        "limitations": ["not_a_cross_database_file_atomic_snapshot", "not_restore_tested", "observed_packages_not_dependency_lock"]}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"database_archive_valid": True, "private_files": len(rows), "private_bytes": total,
                      "output": str(output), "restore_tested": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
