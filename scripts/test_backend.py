"""Run the backend suite against one persistent, owned PostgreSQL 18 test cluster.

The cluster lives only under tmp/managed-test-clusters/naiwa-stable-test-pg.
Each invocation starts it through desktop.ManagedPostgres, recreates only its
kaoyan_test database, runs migrations and pytest, then stops the exact instance
started by this invocation. It never falls back to DATABASE_URL.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from uuid import uuid4
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DATA_HOME = ROOT / "tmp" / "managed-test-clusters" / "naiwa-stable-test-pg"
PG_BIN = Path(os.environ.get("POSTGRES18_BIN", r"C:\Program Files\PostgreSQL\18\bin"))
PORT = 18761
DATABASE = "kaoyan_test"
MANIFEST_NAME = "postgres-test-runner.json"


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _validate_manifest(path: Path, *, cluster: Path, port: int, cluster_id: str | None = None) -> dict | None:
    if not path.exists():
        if (cluster / "PG_VERSION").exists():
            raise RuntimeError("owned_test_cluster_manifest_missing")
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if (value.get("format") != "naiwa-owned-test-pg18-v1"
                or value.get("cluster_directory") != str(cluster.resolve())
                or value.get("port") != port
                or value.get("database") != DATABASE
                or not re.fullmatch(r"[a-f0-9]{32}", value.get("cluster_id", ""))
                or not re.fullmatch(r"[0-9]+", str(value.get("system_identifier", "")))):
            raise ValueError
        if cluster_id is not None and value["cluster_id"] != cluster_id:
            raise ValueError
        return value
    except (OSError, ValueError, TypeError, KeyError):
        raise RuntimeError("owned_test_cluster_manifest_invalid") from None


def _counts(junit: Path) -> dict:
    result = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    if not junit.is_file():
        return result
    try:
        root = ET.parse(junit).getroot()
        suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
        for suite in suites:
            for key in result:
                result[key] += int(suite.attrib.get(key, 0))
    except (ET.ParseError, OSError, ValueError):
        result["junit_parse_error"] = True
    return result


def _run_logged(name: str, command: list[str], *, env: dict, output: Path, secrets: tuple[str, ...]) -> int:
    started = datetime.now(timezone.utc).isoformat()
    path = output / f"{name}.log"
    with path.open("x", encoding="utf-8") as log:
        completed = subprocess.run(command, cwd=ROOT, env=env, stdout=log,
            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, shell=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    text = path.read_text(encoding="utf-8", errors="replace")
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    if text != path.read_text(encoding="utf-8", errors="replace"):
        path.write_text(text, encoding="utf-8")
    print(f"{name}: exit={completed.returncode} log={path}", flush=True)
    return completed.returncode


def _reset_owned_test_database(manager) -> None:
    from psycopg import sql
    from desktop.postgres import ADMIN, APP_USER

    with manager._connect(user=ADMIN, database="postgres") as connection:
        row = connection.execute(
            "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=%s", (DATABASE,)
        ).fetchone()
        if row is not None:
            if row[0] != APP_USER:
                raise RuntimeError("owned_test_database_owner_mismatch")
            connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(DATABASE)))
        connection.execute(sql.SQL(
            "CREATE DATABASE {} OWNER {} TEMPLATE template0 ENCODING 'UTF8'"
        ).format(sql.Identifier(DATABASE), sql.Identifier(APP_USER)))


def _start_or_reuse_owned_cluster(manager, prior_manifest: dict | None) -> str:
    """Start a stopped owned cluster, or reuse only a live identity match.

    A live postmaster is adopted only after the locked owner marker, PID file,
    listener, SQL endpoint, data directory and system identifier all agree.
    Unknown state is a hard stop; this helper never kills a process by PID.
    """
    from desktop.postgres import ADMIN

    manager.preflight()
    manager.paths.ensure_data_dirs()
    manager.lock.acquire()
    try:
        manager._load_owner()
        manager._load_passwords()
        if prior_manifest is not None and manager.owner["cluster_id"] != prior_manifest["cluster_id"]:
            raise RuntimeError("owned_test_cluster_marker_mismatch")
        if not (manager.cluster / "postmaster.pid").exists():
            manager.lock.release()
            manager.start()
            return "started_owned_cluster"

        identity = manager._identity()
        process_state = manager.cluster_process_status()
        if identity is None:
            raise RuntimeError("owned_test_postmaster_identity_unknown")
        if process_state is False:
            # The stale PID record is bound to this exact marked test data path
            # and port. Confirm no listener before removing only this one file.
            with socket.socket() as probe:
                probe.settimeout(0.2)
                if probe.connect_ex(("127.0.0.1", PORT)) == 0:
                    raise RuntimeError("owned_test_stale_pid_port_has_listener")
            (manager.cluster / "postmaster.pid").unlink()
            manager.lock.release()
            manager.start()
            return "restarted_exact_owned_cluster_after_stale_pid"
        if process_state is not True or prior_manifest is None:
            raise RuntimeError("owned_test_postmaster_state_unknown")

        with manager._connect(user=ADMIN, database="postgres") as connection:
            row = connection.execute(
                "SELECT current_database(), current_user, host(inet_server_addr()), "
                "inet_server_port(), current_setting('data_directory'), "
                "(SELECT system_identifier::text FROM pg_control_system())"
            ).fetchone()
        expected_prefix = ("postgres", ADMIN, "127.0.0.1", PORT)
        try:
            server_data_directory = Path(row[4]).resolve()
        except (OSError, TypeError):
            server_data_directory = None
        if (row[:4] != expected_prefix or server_data_directory != manager.cluster.resolve()
                or row[5] != prior_manifest["system_identifier"] or identity[1] < 1):
            raise RuntimeError("owned_test_live_server_identity_mismatch")
        manager._owned_identity = identity
        manager._ensure_database()
        return "reused_verified_owned_cluster"
    except BaseException:
        if manager.lock.handle is not None and manager._owned_identity is None:
            manager.lock.release()
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--pytest-file", action="append", default=[])
    args = parser.parse_args(argv)
    if any(not re.fullmatch(r"tests/(?:unit|integration)/[a-zA-Z0-9_./-]+\.py(?:::[A-Za-z_][A-Za-z0-9_]*)?", item)
           for item in args.pytest_file):
        raise SystemExit("invalid_pytest_scope")

    from scripts.audit_question_quality import safe_output
    output = safe_output(args.output_dir or ROOT / "storage" / "quality-audits" /
                         ("backend-test-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]))
    output.mkdir(parents=True, exist_ok=False)
    summary = {
        "format": "naiwa-stable-backend-test-v1",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "database": DATABASE,
        "port": PORT,
        "cluster_data_directory": None,
        "system_identifier": None,
        "checks": [],
        "database_reset_scope": "only kaoyan_test on the path- and marker-owned local cluster",
        "provider": "offline fixture; no real model calls",
    }
    manager = None
    secrets: tuple[str, ...] = ()
    try:
        import desktop.postgres as postgres_module
        from desktop.postgres import ADMIN, APP_USER
        from desktop.runtime_paths import RuntimePaths
        # Reuse the reviewed cluster manager, while binding its application
        # database constant to the required *_test target for this runner.
        postgres_module.DATABASE = DATABASE
        paths = RuntimePaths.windows(resources=ROOT / "backend", local_app_data=DATA_HOME)
        manager = postgres_module.ManagedPostgres(paths, PG_BIN, port=PORT)

        # Refuse a port in use before touching the data directory. ManagedPostgres
        # repeats this check and validates its owner marker / PID / exact path.
        with socket.socket() as probe:
            probe.settimeout(0.2)
            if probe.connect_ex(("127.0.0.1", PORT)) == 0:
                raise RuntimeError("owned_test_postgres_port_in_use")

        cluster = manager.cluster.resolve()
        manifest_path = paths.data / "config" / MANIFEST_NAME
        prior = _validate_manifest(manifest_path, cluster=cluster, port=PORT)
        summary["cluster_data_directory"] = str(cluster)
        summary["existing_cluster_reused"] = prior is not None

        summary["stage"] = "postgres_start_or_reuse"
        summary["postgres_lifecycle"] = _start_or_reuse_owned_cluster(manager, prior)
        secrets = tuple(manager._passwords.values())
        with manager._connect(user=ADMIN, database="postgres") as connection:
            system_identifier = str(connection.execute(
                "SELECT system_identifier FROM pg_control_system()"
            ).fetchone()[0])
        if prior is not None and (prior["cluster_id"] != manager.owner["cluster_id"]
                                  or prior["system_identifier"] != system_identifier):
            raise RuntimeError("owned_test_cluster_identity_changed")
        if manager._identity() != manager._owned_identity:
            raise RuntimeError("owned_test_postmaster_identity_mismatch")
        with manager._connect(user=APP_USER, database="postgres") as connection:
            observed = connection.execute(
                "SELECT current_database(), current_user, host(inet_server_addr()), inet_server_port()"
            ).fetchone()
        if observed != ("postgres", APP_USER, "127.0.0.1", PORT):
            raise RuntimeError("owned_test_postgres_server_identity_mismatch")

        owner = manager.owner["cluster_id"]
        _validate_manifest(manifest_path, cluster=cluster, port=PORT, cluster_id=owner) if prior else None
        if prior is None:
            _atomic_json(manifest_path, {
                "format": "naiwa-owned-test-pg18-v1",
                "cluster_directory": str(cluster),
                "cluster_id": owner,
                "system_identifier": system_identifier,
                "port": PORT,
                "database": DATABASE,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        summary.update(cluster_id=owner, system_identifier=system_identifier,
                       database_host="127.0.0.1", database_role=APP_USER)

        summary["stage"] = "test_database_reset"
        _reset_owned_test_database(manager)
        with manager._connect(user=APP_USER, database=DATABASE) as connection:
            app_identity = connection.execute(
                "SELECT current_database(), current_user, host(inet_server_addr()), inet_server_port()"
            ).fetchone()
        if app_identity != (DATABASE, APP_USER, "127.0.0.1", PORT):
            raise RuntimeError("owned_test_database_identity_mismatch")
        app_url = __import__("sqlalchemy.engine", fromlist=["make_url"]).make_url(
            manager.database_url).set(database=DATABASE).render_as_string(hide_password=False)
        admin_url = __import__("sqlalchemy.engine", fromlist=["make_url"]).make_url(
            manager.database_url).set(username=ADMIN, password=manager._passwords[ADMIN],
                                      database=DATABASE).render_as_string(hide_password=False)
        env = {**os.environ, "APP_ENV": "test", "TEST_DATABASE_URL": app_url,
               "DATABASE_URL": app_url, "KAOYAN_OWNED_TEST_PORT": str(PORT),
               "PHASE45E_OWNED_TEST_PORT": str(PORT), "KAOYAN_TEST_ADMIN_DATABASE_URL": admin_url,
               "PYTHONIOENCODING": "utf-8", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
               "LLM_API_KEY": "", "LLM_BASE_URL": "http://127.0.0.1:9",
               "LLM_MODEL": "offline-test-fixture", "UPLOAD_DIR": str(output / "uploads"),
               "CHROMA_DIR": str(output / "chroma"),
               "MODEL_SETTINGS_PATH": str(output / "model-settings.bin")}
        (output / "uploads").mkdir()
        (output / "chroma").mkdir()

        summary["stage"] = "migration"
        migration_code = _run_logged("migration", [sys.executable, "-m", "alembic", "upgrade", "head"],
                                     env=env, output=output, secrets=secrets)
        summary["checks"].append({"name": "migration", "exit_code": migration_code,
                                  "log": "migration.log"})
        if migration_code == 0:
            summary["stage"] = "pytest"
            junit = output / "pytest-junit.xml"
            command = [sys.executable, "-m", "pytest", *(args.pytest_file or []), "-q",
                       "-o", "addopts=", f"--basetemp={output / 'pytest-temp'}",
                       f"--junitxml={junit}"]
            test_code = _run_logged("pytest", command, env=env, output=output, secrets=secrets)
            summary["checks"].append({"name": "pytest", "exit_code": test_code,
                                      "log": "pytest.log", "junit": "pytest-junit.xml"})
            summary["pytest_counts"] = _counts(junit)
        else:
            summary["checks"].append({"name": "pytest", "exit_code": None,
                                      "status": "BLOCKED_BY_MIGRATION"})
        summary["status"] = "PASS" if all(
            check.get("exit_code") == 0 for check in summary["checks"]
            if check.get("exit_code") is not None
        ) and all(check.get("exit_code") is not None for check in summary["checks"]) else "FAIL"
    except Exception as exc:
        summary["status"] = "BLOCKED" if isinstance(exc, (OSError, RuntimeError, ValueError)) else "FAIL"
        summary["failure"] = {"stage": summary.get("stage"), "type": type(exc).__name__,
                              "code": getattr(exc, "code", None) or str(exc)}
        diagnostic = getattr(exc, "diagnostic", None)
        if diagnostic:
            summary["failure"]["diagnostic"] = diagnostic
    finally:
        if manager is not None:
            try:
                if manager._owned_identity is not None:
                    manager.stop()
                    summary["postgres_stop"] = "stopped_exact_owned_instance"
                elif manager.lock.handle is not None:
                    manager.lock.release()
            except Exception as exc:
                summary["status"] = "BLOCKED"
                summary["postgres_stop"] = {"status": "failed_or_identity_changed",
                                             "type": type(exc).__name__,
                                             "code": getattr(exc, "code", None),
                                             "diagnostic": getattr(exc, "diagnostic", None)}
        summary["finished_at"] = datetime.now(timezone.utc).isoformat()
        (output / "test-summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": summary["status"], "output": str(output),
                      "checks": summary.get("checks"), "pytest_counts": summary.get("pytest_counts"),
                      "failure": summary.get("failure"),
                      "postgres_stop": summary.get("postgres_stop")}, ensure_ascii=False, indent=2))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    raise SystemExit(main())
