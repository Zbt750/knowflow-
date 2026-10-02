"""备份后执行本轮增量迁移；不删除学习历史，也不重灌数据库。"""
import argparse
from datetime import datetime
import os
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from backend.config import get_settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if settings.app_env not in {"dev", "test"}:
        raise SystemExit("Only local dev/test is supported; use a reviewed release migration in production")
    if not args.apply:
        print("Dry run: backup active local database, then alembic upgrade head. No reset or seed.")
        return
    binary = shutil.which("pg_dump")
    if not binary and os.name == "nt":
        candidate = Path(r"C:\Program Files\PostgreSQL\18\bin\pg_dump.exe")
        binary = str(candidate) if candidate.exists() else None
    if not binary:
        raise SystemExit("pg_dump unavailable; migration not started")
    url = make_url(str(settings.active_database_url))
    destination = ROOT / "storage" / "backups" / f"before-answer-evidence-{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:8]}.dump"
    destination.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PGPASSWORD": url.password or ""}
    result = subprocess.run([
        binary, "--no-password", "--format=custom", "--host", url.host or "127.0.0.1",
        "--port", str(url.port or 5432), "--username", url.username or "postgres",
        "--dbname", url.database or "", "--file", str(destination),
    ], env=env, capture_output=True, timeout=120)
    if result.returncode or not destination.exists() or destination.stat().st_size == 0:
        raise SystemExit("Backup failed; migration not started. Check PostgreSQL locally.")
    print(f"Backup saved: {destination}")
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(config, "head")
    print("Upgrade complete; existing attempts and mastery projections preserved")


if __name__ == "__main__":
    main()
