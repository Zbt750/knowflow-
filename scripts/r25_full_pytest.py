"""R25：显式传递测试环境的全量 pytest 运行器。

安全门不删除：先验证 63047 身份，再以子进程方式把 TEST_DATABASE_URL/APP_ENV
显式传给 pytest，避免 R24 出现的 375 个 "TEST_DATABASE_URL must be explicitly
set by an isolated test runner" 环境错误。
"""

import os
import subprocess
import sys

PROJECT = r"D:\考研跑通项目"
URL = "postgresql+psycopg://kaoyan_app@127.0.0.1:63047/naiwa_experience_test"


def _decode_server_directory(value) -> str:
    """Decode Windows PostgreSQL's native GUC path without accepting a new target.

    Some Windows builds expose data_directory in the OS ANSI code page even on
    UTF8 clusters. Read it as bytea, decode strictly, then perform the original
    exact resolved-path check. Never replace undecodable bytes or skip identity.
    """
    if isinstance(value, str):
        return value
    raw = bytes(value)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        if sys.platform != "win32":
            raise
        import ctypes
        return raw.decode(f"cp{ctypes.windll.kernel32.GetACP()}")


def verify_identity() -> dict:
    import psycopg
    from pathlib import Path

    with psycopg.connect("postgresql://kaoyan_app@127.0.0.1:63047/naiwa_experience_test",
                         connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute("select current_database(), inet_server_port(), current_user, "
                        "current_setting('data_directory')::bytea, "
                        "(select system_identifier::text from pg_control_system())")
            database, port, user, directory, identifier = cur.fetchone()
            directory = _decode_server_directory(directory)
            if (database, port, user) != ("naiwa_experience_test", 63047, "kaoyan_app"):
                raise RuntimeError("test_database_identity_mismatch")
            if (Path(directory).resolve() != (Path(PROJECT) / "tmp/pg63047").resolve()
                    or identifier != "7703578443208394676"):
                raise RuntimeError("test_cluster_identity_mismatch")
            cur.execute("select version_num from alembic_version order by version_num")
            revisions = [row[0] for row in cur.fetchall()]
            if revisions != ["f58d22ab41c7"]:
                raise RuntimeError("test_schema_revision_mismatch")
            # Use the same application-instance key. Reject a server holding
            # this test DB before spawning hundreds of failing TestClients.
            cur.execute("select pg_try_advisory_lock(75020260927)")
            if cur.fetchone()[0] is not True:
                raise RuntimeError("test_database_backend_instance_running")
            cur.execute("select pg_advisory_unlock(75020260927)")
            if cur.fetchone()[0] is not True:
                raise RuntimeError("test_database_instance_probe_unlock_failed")
    return {"database": database, "port": port, "user": user,
            "alembic": revisions, "system_identifier": identifier}


def main() -> int:
    identity = verify_identity()
    print("TEST_DB_IDENTITY", identity, flush=True)
    env = dict(os.environ)
    env.update({
        "TEST_DATABASE_URL": URL,
        "DATABASE_URL": URL,
        "APP_ENV": "test",
        "KAOYAN_OWNED_TEST_PORT": "63047",
        "PYTHONIOENCODING": "utf-8",
    })
    proc = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q"],
                          cwd=PROJECT, env=env)
    print("PYTEST_EXIT", proc.returncode, flush=True)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
