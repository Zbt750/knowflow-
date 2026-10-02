"""Owned PostgreSQL cluster supervisor. Never adopts or deletes another cluster."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import time
from uuid import uuid4

from desktop.runtime_paths import RuntimePaths

ADMIN = "kaoyan_admin"
APP_USER = "kaoyan_app"
DATABASE = "kaoyan_desktop"


def _run(command, *, timeout=45, extra_env=None, capture=True):
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("PG")}
    env.update(extra_env or {})
    try:
        return subprocess.run(command, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                              stderr=subprocess.PIPE if capture else subprocess.DEVNULL,
                              timeout=timeout, env=env, shell=False,
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("desktop_postgres_command_failed") from None


def _private_file(path: Path):
    if os.name != "nt":
        raise ValueError("desktop_windows_credentials_required")
    # File exists but contains no secret until ACL restriction succeeds.
    identity = _run(["whoami", "/user", "/fo", "csv", "/nh"], timeout=10)
    match = re.search(rb"S-1-[0-9-]+", identity.stdout)
    if identity.returncode or match is None:
        raise ValueError("desktop_credentials_acl_failed")
    acl = _run(["icacls", str(path), "/inheritance:r", "/grant:r", "*" + match.group().decode("ascii") + ":(F)"], timeout=10)
    if acl.returncode:
        raise ValueError("desktop_credentials_acl_failed")


def atomic_json(path: Path, payload: dict):
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class DataDirectoryLock:
    def __init__(self, data: Path):
        self.path = data / "config" / "desktop-database.lock"
        self.handle = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            if self.path.stat().st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            raise ValueError("desktop_data_in_use") from None
        self.handle = handle

    def release(self):
        if self.handle is not None:
            self.handle.close()  # OS lock released; stale file is harmless.
            self.handle = None


class ManagedPostgres:
    def __init__(self, paths: RuntimePaths, binary_dir: Path, *, port=18760):
        self.paths = paths
        self.binary_dir = binary_dir
        self.port = port
        self.cluster = paths.data / "postgres" / "cluster"
        self.marker = paths.data / "config" / "postgres-owner.json"
        self.credentials = paths.data / "config" / "postgres-credentials.bin"
        self.lock = DataDirectoryLock(paths.data)
        self.owner = None
        self._passwords = None
        self._owned_identity = None

    def binary(self, name):
        return str(self.binary_dir / (name + ".exe" if os.name == "nt" else name))

    def preflight(self):
        if not isinstance(self.port, int) or isinstance(self.port, bool) or not 18000 <= self.port <= 65535:
            raise ValueError("desktop_postgres_port_invalid")
        if not self.binary_dir.is_absolute() or not self.paths.data.is_absolute():
            raise ValueError("desktop_postgres_path_invalid")
        for path in (self.cluster, self.marker, self.credentials, self.lock.path):
            if not path.resolve().is_relative_to(self.paths.data.resolve()):
                raise ValueError("desktop_postgres_path_escape")
            if any(parent.is_symlink() for parent in (path, *path.parents) if parent != self.paths.data):
                raise ValueError("desktop_postgres_links_forbidden")
        for name in ("postgres", "initdb", "pg_ctl", "pg_dump", "pg_restore"):
            path = Path(self.binary(name))
            if not path.is_file() or path.is_symlink():
                raise ValueError("desktop_postgres_binaries_missing")
        version = _run([self.binary("postgres"), "--version"], timeout=10)
        match = re.search(rb"PostgreSQL\) (\d+)", version.stdout)
        if version.returncode or match is None or match.group(1) != b"18":
            raise ValueError("desktop_postgres_version_unsupported")

    def _identity(self):
        try:
            lines = (self.cluster / "postmaster.pid").read_text(encoding="utf-8").splitlines()
            if Path(lines[1]).resolve() != self.cluster.resolve() or int(lines[3]) != self.port:
                return None
            return int(lines[0]), int(lines[2])
        except (OSError, ValueError, IndexError):
            return None

    def _load_owner(self):
        root_hash = hashlib.sha256(str(self.cluster.resolve()).encode("utf-8")).hexdigest()
        if self.marker.exists():
            try:
                owner = json.loads(self.marker.read_text(encoding="utf-8"))
                if (owner["format"] != 1 or owner["root_hash"] != root_hash or owner["major"] != 18
                        or not re.fullmatch(r"[a-f0-9]{32}", owner["cluster_id"])):
                    raise ValueError()
            except (OSError, ValueError, KeyError, TypeError):
                raise ValueError("desktop_postgres_owner_invalid") from None
        else:
            if self.credentials.exists() or (self.cluster.exists() and any(self.cluster.iterdir())):
                raise ValueError("desktop_postgres_unowned_cluster")
            owner = {"format": 1, "root_hash": root_hash, "major": 18, "cluster_id": uuid4().hex}
            atomic_json(self.marker, owner)
        self.owner = owner

    def _load_passwords(self):
        if os.name != "nt":
            raise ValueError("desktop_windows_credentials_required")
        from backend.services.model_settings_service import _dpapi
        try:
            if self.credentials.exists():
                data = self.credentials.read_bytes()
                if not data.startswith(b"PGDPAPI1\n"):
                    raise ValueError()
                payload = json.loads(_dpapi(data[9:], decrypt=True))
                if payload["cluster_id"] != self.owner["cluster_id"]:
                    raise ValueError()
                passwords = payload["passwords"]
                if set(passwords) != {ADMIN, APP_USER} or any(not re.fullmatch(r"[A-Za-z0-9_-]{32,100}", p) for p in passwords.values()):
                    raise ValueError()
            else:
                if self.cluster.exists() and any(self.cluster.iterdir()):
                    raise ValueError()
                passwords = {ADMIN: secrets.token_urlsafe(36), APP_USER: secrets.token_urlsafe(36)}
                payload = json.dumps({"cluster_id": self.owner["cluster_id"], "passwords": passwords}).encode()
                protected = b"PGDPAPI1\n" + _dpapi(payload)
                temporary = self.credentials.with_name("pg-credentials-" + uuid4().hex + ".tmp")
                try:
                    with temporary.open("xb") as handle:
                        _private_file(temporary)
                        handle.write(protected)
                        handle.flush()
                        os.fsync(handle.fileno())
                    temporary.replace(self.credentials)
                finally:
                    temporary.unlink(missing_ok=True)
            self._passwords = passwords
        except (OSError, ValueError, KeyError, TypeError):
            raise ValueError("desktop_postgres_credentials_unavailable") from None

    def _initialize(self):
        version = self.cluster / "PG_VERSION"
        if version.exists():
            if version.read_text(encoding="ascii").strip() != "18":
                raise ValueError("desktop_postgres_cluster_version_mismatch")
            return
        if self.cluster.exists() and any(self.cluster.iterdir()):
            raise ValueError("desktop_postgres_partial_cluster")
        password_file = self.paths.data / "config" / ("pg-init-" + uuid4().hex + ".tmp")
        try:
            with password_file.open("xb") as handle:
                _private_file(password_file)
                handle.write((self._passwords[ADMIN] + "\n").encode("ascii"))
                handle.flush()
                os.fsync(handle.fileno())
            result = _run([self.binary("initdb"), "-D", str(self.cluster), "--username=" + ADMIN,
                           "--encoding=UTF8", "--no-locale", "--auth-host=scram-sha-256",
                           "--auth-local=scram-sha-256", "--pwfile=" + str(password_file)], timeout=90)
            if result.returncode or not version.is_file():
                raise ValueError("desktop_postgres_initialization_failed")
        finally:
            password_file.unlink(missing_ok=True)

    def _connect(self, user=ADMIN, database="postgres"):
        import psycopg
        # libpq treats service='' as a named (missing) service, not as disabled.
        # Never consult an inherited service file; refuse rather than mutating
        # the process environment while other request threads may be using it.
        if os.environ.get("PGSERVICE"):
            raise ValueError("desktop_postgres_inherited_service_forbidden")
        return psycopg.connect(host="127.0.0.1", hostaddr="127.0.0.1", port=self.port,
                               user=user, password=self._passwords[user], dbname=database,
                               passfile="", sslmode="disable", connect_timeout=5,
                               autocommit=True)

    def _ensure_database(self):
        from psycopg import sql
        try:
            with self._connect() as connection:
                actual = connection.execute("SHOW data_directory").fetchone()[0]
                if Path(actual).resolve() != self.cluster.resolve():
                    raise ValueError("desktop_postgres_instance_mismatch")
                role = connection.execute("SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication FROM pg_roles WHERE rolname=%s", (APP_USER,)).fetchone()
                if role is None:
                    connection.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}").format(sql.Identifier(APP_USER), sql.Literal(self._passwords[APP_USER])))
                elif any(role):
                    raise ValueError("desktop_postgres_application_role_invalid")
                database = connection.execute("SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=%s", (DATABASE,)).fetchone()
                if database is None:
                    connection.execute(sql.SQL("CREATE DATABASE {} OWNER {} TEMPLATE template0 ENCODING 'UTF8'").format(sql.Identifier(DATABASE), sql.Identifier(APP_USER)))
                elif database[0] != APP_USER:
                    raise ValueError("desktop_postgres_database_owner_invalid")
            with self._connect(APP_USER, DATABASE) as connection:
                connection.execute("SELECT 1").fetchone()
        except ValueError:
            raise
        except Exception:
            raise ValueError("desktop_postgres_database_unavailable") from None

    @property
    def database_url(self):
        if self._passwords is None:
            raise ValueError("desktop_postgres_not_started")
        from sqlalchemy.engine import URL
        return URL.create("postgresql+psycopg", username=APP_USER, password=self._passwords[APP_USER],
                          host="127.0.0.1", port=self.port, database=DATABASE).render_as_string(hide_password=False)

    def start(self):
        self.preflight()
        self.paths.ensure_data_dirs()
        self.lock.acquire()
        try:
            if (self.cluster / "postmaster.pid").exists():
                raise ValueError("desktop_postgres_already_running_or_stale_pid")
            with socket.socket() as probe:
                probe.settimeout(0.2)
                if probe.connect_ex(("127.0.0.1", self.port)) == 0:
                    raise ValueError("desktop_postgres_port_in_use")
            self._load_owner()
            self._load_passwords()
            self._initialize()
            started_at = int(time.time())
            try:
                result = _run([self.binary("pg_ctl"), "-D", str(self.cluster), "-l", str(self.paths.data / "logs/postgres.log"),
                               "-o", f"-p {self.port} -c listen_addresses=127.0.0.1 -c log_statement=none -c log_min_error_statement=panic",
                               "-w", "-t", "30", "start"], timeout=45, capture=False)
            finally:
                identity = self._identity()
                if identity is not None and identity[1] >= started_at - 1:
                    self._owned_identity = identity
            if result.returncode or self._owned_identity is None:
                raise ValueError("desktop_postgres_start_failed")
            self._ensure_database()
        except BaseException:
            try:
                self.stop()
            finally:
                self.lock.release()
            raise
        return self

    def stop(self):
        try:
            if self._owned_identity is not None:
                if self._identity() != self._owned_identity:
                    raise ValueError("desktop_postgres_shutdown_identity_changed")
                result = _run([self.binary("pg_ctl"), "-D", str(self.cluster), "-m", "fast", "-w", "-t", "20", "stop"], timeout=30, capture=False)
                if result.returncode:
                    raise ValueError("desktop_postgres_shutdown_failed")
                self._owned_identity = None
        finally:
            self.lock.release()

    def backup(self):
        if self._owned_identity is None or self._identity() != self._owned_identity:
            raise ValueError("desktop_postgres_backup_requires_owned_instance")
        destination = self.paths.data / "backups" / ("before-schema-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8] + ".dump")
        temporary = destination.with_suffix(".dump.part")
        with temporary.open("xb"):
            _private_file(temporary)
        result = _run([self.binary("pg_dump"), "--no-password", "--format=custom", "--host=127.0.0.1",
                       "--port=" + str(self.port), "--username=" + APP_USER, "--dbname=" + DATABASE,
                       "--file=" + str(temporary)], timeout=120, extra_env={"PGPASSWORD": self._passwords[APP_USER]})
        if result.returncode or temporary.stat().st_size == 0:
            raise ValueError("desktop_postgres_backup_failed")
        verified = _run([self.binary("pg_restore"), "--list", str(temporary)], timeout=20)
        if verified.returncode:
            raise ValueError("desktop_postgres_backup_failed")
        temporary.replace(destination)
        return destination

    def __enter__(self):
        return self.start()

    def __exit__(self, *_):
        self.stop()
