"""Safely apply pending Alembic migrations to this checkout's local dev DB.

The dev launcher starts the project-owned PostgreSQL data directory under
.pgdata.  This helper refuses remote databases, unexpected local databases,
test mode, and a listener that cannot be matched to the owned cluster's
postmaster.pid before it runs migrations.
"""
from __future__ import annotations

import json
import os
import hashlib
import subprocess
from datetime import datetime
from pathlib import Path
from typing import NoReturn

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


ROOT = Path(__file__).resolve().parents[1]
DATABASE_NAME = "kaoyan"
DATABASE_PORT = 5433
SOFT_REMOVE_REVISION = "f59e33bc52d8"
PG_DUMP = Path(r"C:\Program Files\PostgreSQL\18\bin\pg_dump.exe")


def fail(message: str) -> NoReturn:
    print(json.dumps({"status": "BLOCKED", "reason": message}, ensure_ascii=False))
    raise SystemExit(1)


def identity_for(url):
    return {
        "database": url.database,
        "user": url.username,
        "host": url.host,
        "port": url.port or 5432,
    }


def get_schema_state(url) -> tuple[dict, str, bool, list[str], int]:
    engine = create_engine(
        url,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": 5,
            "options": "-c default_transaction_read_only=on",
        },
    )
    try:
        with engine.connect() as connection:
            identity = dict(
                zip(
                    ("database", "user", "host", "port"),
                    connection.execute(
                        text(
                            "SELECT current_database(), current_user, "
                            "host(inet_server_addr()), inet_server_port()"
                        )
                    ).one(),
                )
            )
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one_or_none()
            has_removed_at = connection.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name='practice_items' "
                    "AND column_name='removed_at')"
                )
            ).scalar_one()
            fk_definitions = list(
                connection.execute(
                    text(
                        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                        "WHERE conrelid='public.question_attempts'::regclass "
                        "AND contype='f' "
                        "AND pg_get_constraintdef(oid) ILIKE '%practice_item_id%'"
                    )
                ).scalars()
            )
            start_epoch = connection.execute(
                text("SELECT floor(extract(epoch FROM pg_postmaster_start_time()))::bigint")
            ).scalar_one()
            return identity, revision, bool(has_removed_at), fk_definitions, int(start_epoch)
    finally:
        engine.dispose()


def verify_owned_cluster(start_epoch: int) -> None:
    data_dir = (ROOT / ".pgdata").resolve()
    if not (data_dir / "PG_VERSION").is_file():
        fail("本项目 .pgdata 缺少 PG_VERSION；拒绝迁移未知 PostgreSQL 实例")
    pid_file = data_dir / "postmaster.pid"
    if not pid_file.is_file():
        fail("本项目 .pgdata 没有 postmaster.pid；当前数据库无法确认属于本项目")
    raw_pid_file = pid_file.read_bytes()
    encodings = ["utf-8-sig"]
    if os.name == "nt":
        # Windows PostgreSQL writes postmaster.pid using the active ANSI code page;
        # the data directory may contain Chinese characters and is not UTF-8 there.
        encodings.append("mbcs")
    owned_pid_file = False
    for encoding in encodings:
        try:
            lines = raw_pid_file.decode(encoding).splitlines()
            if len(lines) < 4:
                continue
            pid = int(lines[0].strip())
            pid_data_dir = Path(lines[1].strip()).resolve()
            pid_start_epoch = int(lines[2].strip())
            pid_port = int(lines[3].strip())
        except (UnicodeDecodeError, ValueError, OSError):
            continue
        if (
            pid > 0
            and os.path.normcase(str(pid_data_dir)) == os.path.normcase(str(data_dir))
            and pid_port == DATABASE_PORT
            and pid_start_epoch == start_epoch
        ):
            owned_pid_file = True
            break
    if not owned_pid_file:
        fail("5433 当前监听实例与本项目 postmaster.pid 不一致；拒绝迁移未知数据库")


def backup_database(url) -> dict:
    if not PG_DUMP.is_file():
        fail(f"备份工具不存在：{PG_DUMP}")
    backup_dir = ROOT / "storage" / "db-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"kaoyan-before-f59e33bc52d8-{timestamp}.dump"
    env = dict(os.environ)
    if url.password is not None:
        env["PGPASSWORD"] = url.password
    else:
        env.pop("PGPASSWORD", None)
    result = subprocess.run(
        [
            str(PG_DUMP),
            "--host", str(url.host),
            "--port", str(url.port or 5432),
            "--username", str(url.username),
            "--dbname", str(url.database),
            "--format=custom",
            "--no-owner",
            "--no-acl",
            "--file", str(backup_path),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=False,
    )
    if result.returncode != 0 or not backup_path.is_file() or backup_path.stat().st_size == 0:
        fail(f"数据库预迁移备份失败（pg_dump exit={result.returncode}）；未执行 Alembic 迁移")
    digest = hashlib.sha256(backup_path.read_bytes()).hexdigest()
    metadata = {
        "backup_file": str(backup_path.relative_to(ROOT)),
        "sha256": digest,
        "size_bytes": backup_path.stat().st_size,
        "identity": identity_for(url),
    }
    (backup_path.with_suffix(".json")).write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return metadata


def main() -> None:
    values = dotenv_values(ROOT / ".env")
    raw_url = values.get("DATABASE_URL")
    if not raw_url:
        fail(".env 未配置 DATABASE_URL；拒绝猜测迁移目标")

    try:
        url = make_url(raw_url)
    except Exception as exc:
        fail(f"无法解析 .env 的 DATABASE_URL（{type(exc).__name__}）；拒绝迁移")

    target = identity_for(url)
    if (
        url.drivername not in {"postgresql", "postgresql+psycopg"}
        or url.host not in {"127.0.0.1", "localhost", "::1"}
        or target["port"] != DATABASE_PORT
        or url.database != DATABASE_NAME
        or url.username != "kaoyan"
    ):
        fail("DATABASE_URL 不是本项目预期的本机 kaoyan@127.0.0.1:5433/kaoyan；拒绝迁移")

    identity, revision, has_removed_at, fk_definitions, start_epoch = get_schema_state(url)
    expected = {"database": DATABASE_NAME, "user": "kaoyan", "host": "127.0.0.1", "port": DATABASE_PORT}
    if identity != expected:
        fail(f"活动数据库身份与项目 .env 不一致；期望 {expected}，实际 {identity}")
    verify_owned_cluster(start_epoch)

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        fail(f"迁移目录不是单一 head（{heads}）；拒绝自动升级")
    head = heads[0]
    script = ScriptDirectory.from_config(config)
    all_revisions = {revision.revision for revision in script.iterate_revisions(head, "base")}
    if revision not in all_revisions:
        fail(f"数据库迁移版本不属于当前项目的迁移链（revision={revision}）；拒绝升级")

    if revision == head:
        if not has_removed_at or not any("ON DELETE RESTRICT" in definition.upper() for definition in fk_definitions):
            fail("数据库版本已是 head，但软移除列或历史外键约束缺失；拒绝静默修补漂移")
        print(json.dumps({"status": "CURRENT", "identity": identity, "revision": revision}, ensure_ascii=False))
        return

    soft_remove_ancestors = {
        item.revision for item in script.iterate_revisions(SOFT_REMOVE_REVISION, "base")
    }
    soft_remove_descendants = {
        item.revision for item in script.iterate_revisions(head, SOFT_REMOVE_REVISION)
    }
    if (revision in soft_remove_ancestors and revision != SOFT_REMOVE_REVISION and has_removed_at) or (
        revision in soft_remove_descendants and not has_removed_at
    ):
        fail(
            "当前数据库版本与软移除列状态不一致 "
            f"（revision={revision}, removed_at={has_removed_at}）；拒绝自动修补漂移"
        )
    before_revision = revision

    backup = backup_database(url)

    # Alembic and FastAPI share Settings.active_database_url. Override only this
    # child process so a parent test environment can never redirect the upgrade.
    os.environ["APP_ENV"] = "dev"
    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
    os.environ.pop("TEST_DATABASE_URL", None)
    command.upgrade(config, "head")

    identity, revision, has_removed_at, fk_definitions, start_epoch = get_schema_state(url)
    verify_owned_cluster(start_epoch)
    if revision != head or not has_removed_at:
        fail(f"迁移后校验不完整（revision={revision}, removed_at={has_removed_at}）")
    if not any("ON DELETE RESTRICT" in definition.upper() for definition in fk_definitions):
        fail("迁移后 QuestionAttempt 历史外键未变为 RESTRICT")
    print(
        json.dumps(
            {
                "status": "UPGRADED",
                "identity": identity,
                "from_revision": before_revision,
                "to_revision": revision,
                "removed_at_present": has_removed_at,
                "question_attempt_fk": "ON DELETE RESTRICT",
                "backup": backup,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
