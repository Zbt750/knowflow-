"""Owned PostgreSQL cluster supervisor. Never adopts or deletes another cluster."""
from __future__ import annotations

import hashlib
import json
import locale
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import tempfile
import time
from uuid import uuid4

from desktop.runtime_paths import RuntimePaths

ADMIN = "kaoyan_admin"
APP_USER = "kaoyan_app"
DATABASE = "kaoyan_desktop"


def _subprocess_encodings():
    encodings = ["utf-8"]
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            for codepage in (kernel32.GetOEMCP(), kernel32.GetACP()):
                if codepage:
                    encodings.append(f"cp{codepage}")
        except (AttributeError, OSError):
            pass
    encodings.extend((locale.getencoding(), "mbcs"))
    return tuple(dict.fromkeys(encodings))


class PostgresCommandFailure(ValueError):
    """Safe, structured diagnostics for a failed owned PostgreSQL subprocess."""

    def __init__(self, code, diagnostic):
        self.code = code
        self.diagnostic = diagnostic
        super().__init__(code)


def _diagnostic_text(value, limit=8192):
    if value is None:
        return ""
    if isinstance(value, bytes):
        decoded = None
        for encoding in _subprocess_encodings():
            try:
                decoded = value.decode(encoding, errors="strict")
                break
            except (UnicodeError, LookupError):
                continue
        value = decoded if decoded is not None else value.decode("utf-8", errors="replace")
    import re
    text = str(value)[-limit:]
    text = re.sub(r"(?i)(password|passwd|token|secret|api[_-]?key)(\s*[:=]\s*)[^\s,;]+",
                  r"\1\2[REDACTED]", text)
    text = re.sub(r"(?i)(postgres(?:ql)?://[^:/\s]+:)[^@/\s]+@", r"\1[REDACTED]@", text)
    return text


def _safe_command(command):
    safe = []
    hide_next = False
    for value in command:
        item = str(value)
        if hide_next:
            safe.append("[PRIVATE_FILE]")
            hide_next = False
        elif item == "--pwfile":
            safe.append(item)
            hide_next = True
        elif item.startswith("--pwfile="):
            safe.append("--pwfile=[PRIVATE_FILE]")
        else:
            safe.append(item)
    return safe


def _command_diagnostic(command, *, stage, timeout, cwd, extra_env, returncode=None,
                        stdout=None, stderr=None, os_error=None):
    import os
    diagnostic = {
        "stage": stage,
        "executable": Path(str(command[0])).name if command else None,
        "argv": _safe_command(command),
        "cwd": str(Path(cwd).resolve()) if cwd else os.getcwd(),
        "timeout_seconds": timeout,
        "extra_environment_names": sorted((extra_env or {}).keys()),
    }
    if returncode is not None:
        diagnostic["returncode"] = returncode
    if stdout:
        diagnostic["stdout_tail"] = _diagnostic_text(stdout)
    if stderr:
        diagnostic["stderr_tail"] = _diagnostic_text(stderr)
    if os_error is not None:
        diagnostic["os_error_type"] = type(os_error).__name__
        diagnostic["errno"] = getattr(os_error, "errno", None)
        diagnostic["winerror"] = getattr(os_error, "winerror", None)
        diagnostic["os_error"] = _diagnostic_text(getattr(os_error, "strerror", None) or str(os_error), 2048)
        filename = getattr(os_error, "filename", None)
        if filename:
            diagnostic["filename"] = Path(str(filename)).name
    return diagnostic


def _run(command, *, timeout=45, extra_env=None, capture=True, stage=None, cwd=None, diagnostic_secrets=()):
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("PG")}
    env.update(extra_env or {})
    stage = stage or Path(str(command[0])).stem
    if stage=='initdb':
        from desktop.postgres_diagnostics import run_initialization
        return run_initialization(command,timeout=timeout,env=env,extra_env=extra_env,cwd=cwd,secrets=diagnostic_secrets)
    output_dir = cwd if cwd and Path(cwd).is_dir() else None
    if not capture:
        try:
            return subprocess.run(command, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout,
                env=env, shell=False, cwd=cwd,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except subprocess.TimeoutExpired as exc:
            diagnostic = _command_diagnostic(command, stage=stage, timeout=timeout, cwd=cwd,
                extra_env=extra_env)
            diagnostic["timed_out"] = True
            diagnostic["timeout_exception_type"] = type(exc).__name__
            raise PostgresCommandFailure("desktop_postgres_command_failed", diagnostic) from None
        except OSError as exc:
            diagnostic = _command_diagnostic(command, stage=stage, timeout=timeout, cwd=cwd,
                extra_env=extra_env, os_error=exc)
            diagnostic["failure_phase"] = "process_launch"
            raise PostgresCommandFailure("desktop_postgres_command_failed", diagnostic) from None
    launch_attempted = False
    try:
        # File-backed capture avoids Windows communicate() waiting for pipe
        # EOF when initdb's bootstrap child inherits stdout/stderr. A process
        # group lets the timeout path stop only this command's descendants.
        # Keep capture files in the owned temporary directory when available.
        with tempfile.TemporaryFile(dir=output_dir) as stdout_file, tempfile.TemporaryFile(dir=output_dir) as stderr_file:
            launch_attempted = True
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                stdout=stdout_file, stderr=stderr_file, env=env, shell=False, cwd=cwd,
                creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                    | (subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0),
                start_new_session=(os.name != "nt"))
            try:
                returncode = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                termination = _terminate_process_tree(process)
                stdout_file.seek(0); stderr_file.seek(0)
                diagnostic = _command_diagnostic(command, stage=stage, timeout=timeout, cwd=cwd,
                    extra_env=extra_env, stdout=stdout_file.read(), stderr=stderr_file.read())
                diagnostic.update({"timed_out": True, "timeout_exception_type": type(exc).__name__,
                    "process_id": process.pid, "descendant_cleanup": termination})
                raise PostgresCommandFailure("desktop_postgres_command_failed", diagnostic) from None
            stdout_file.seek(0); stderr_file.seek(0)
            return subprocess.CompletedProcess(command, returncode,
                stdout_file.read(), stderr_file.read())
    except OSError as exc:
        diagnostic = _command_diagnostic(command, stage=stage, timeout=timeout, cwd=cwd,
            extra_env=extra_env, os_error=exc)
        diagnostic["failure_phase"] = "process_launch" if launch_attempted else "capture_file_setup"
        raise PostgresCommandFailure("desktop_postgres_command_failed", diagnostic) from None


def _failed_result(code, command, result, *, stage, timeout, cwd=None, extra_env=None):
    diagnostic = getattr(result,'diagnostic',None) or _command_diagnostic(command, stage=stage, timeout=timeout, cwd=cwd,
        extra_env=extra_env, returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
    raise PostgresCommandFailure(code, diagnostic)


def _terminate_process_tree(process, *, windows=None):
    """Stop only the timed-out utility process and descendants it created."""
    import signal
    windows = os.name == "nt" if windows is None else windows
    details = {"root_process_id": process.pid}
    if windows:
        taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
        env = {key: value for key, value in os.environ.items() if not key.upper().startswith("PG")}
        try:
            result = subprocess.run([str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=10, env=env, shell=False,
                creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            details["tree_kill_exit_code"] = result.returncode
            if result.stderr:
                details["tree_kill_stderr"] = _diagnostic_text(result.stderr, 2048)
        except (OSError, subprocess.TimeoutExpired) as exc:
            details["tree_kill_error_type"] = type(exc).__name__
            details["tree_kill_errno"] = getattr(exc, "errno", None)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    return details


def _process_alive(process_id):
    if not isinstance(process_id, int) or process_id <= 0:
        return None
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel32.WaitForSingleObject.restype = ctypes.c_uint32
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.OpenProcess(0x00100000 | 0x1000, 0, process_id)
        if not handle:
            return False if ctypes.get_last_error() == 87 else None
        try:
            state = kernel32.WaitForSingleObject(handle, 0)
            if state == 0x00000102:  # WAIT_TIMEOUT: process is still alive.
                return True
            if state == 0x00000000:  # WAIT_OBJECT_0: process has exited.
                return False
            return None
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(process_id, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None


def _private_file(path: Path):
    if os.name != "nt":
        raise ValueError("desktop_windows_credentials_required")
    # File exists but contains no secret until ACL restriction succeeds.
    identity = _run(["whoami", "/user", "/fo", "csv", "/nh"], timeout=10)
    match = re.search(rb"S-1-[0-9-]+", identity.stdout)
    if identity.returncode or match is None:
        raise ValueError("desktop_credentials_acl_failed")
    permission = ":(OI)(CI)F" if path.is_dir() else ":(F)"
    acl = _run(["icacls", str(path), "/inheritance:r", "/grant:r", "*" + match.group().decode("ascii") + permission], timeout=10)
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
            raw = (self.cluster / "postmaster.pid").read_bytes()
        except OSError:
            return None
        # Windows PostgreSQL writes its data path using the local code page.
        # A Chinese user directory therefore need not be UTF-8. Decode strictly:
        # replacement characters would prevent us from checking the exact owner
        # path and could leave a successfully started process untracked.
        for encoding in _subprocess_encodings():
            try:
                lines = raw.decode(encoding).splitlines()
                if Path(lines[1]).resolve() != self.cluster.resolve() or int(lines[3]) != self.port:
                    continue
                return int(lines[0]), int(lines[2])
            except (UnicodeError, ValueError, IndexError, LookupError):
                continue
        return None

    def cluster_process_status(self):
        """Return True/False for a pid file bound to this cluster, else None."""
        try:
            raw = (self.cluster / "postmaster.pid").read_bytes()
        except FileNotFoundError:
            return False
        except OSError:
            return None
        expected = self.cluster.resolve()
        for encoding in _subprocess_encodings():
            try:
                lines = raw.decode(encoding).splitlines()
                process_id = abs(int(lines[0]))
                if not process_id or Path(lines[1]).resolve() != expected:
                    continue
                break
            except (UnicodeError, ValueError, IndexError, LookupError, OSError):
                continue
        else:
            return None
        return _process_alive(process_id)

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
        # An interrupted or failed run is evidence, never permission to retry
        # the same owned directory even if initdb removed its partial files.
        for manifest in (self.paths.data/'logs').glob('initdb-*/run.json'):
            try:
                prior=json.loads(manifest.read_text(encoding='utf-8'))
                completed=(prior.get('initialization_state')=='exited_ok'
                           and prior.get('root_returncode')==0 and not prior.get('log_collection_errors'))
            except (OSError,ValueError,TypeError):
                completed=False
            if not completed:
                raise ValueError('desktop_postgres_initialization_attempt_exists')
        version = self.cluster / "PG_VERSION"
        if version.exists():
            if version.read_text(encoding="ascii").strip() != "18":
                raise ValueError("desktop_postgres_cluster_version_mismatch")
            if not all((self.cluster/name).is_file() and (self.cluster/name).stat().st_size>0
                       for name in ('global/pg_control','postgresql.conf','pg_hba.conf')):
                raise ValueError('desktop_postgres_partial_cluster')
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
                           "--auth-local=scram-sha-256", "--pwfile=" + str(password_file)],
                           timeout=90, stage="initdb", cwd=self.paths.data,
                           diagnostic_secrets=tuple(self._passwords.values()))
            if result.returncode:
                _failed_result("desktop_postgres_initialization_failed",
                    [self.binary("initdb"), "-D", str(self.cluster), "--username=" + ADMIN,
                     "--encoding=UTF8", "--no-locale", "--auth-host=scram-sha-256",
                     "--auth-local=scram-sha-256", "--pwfile=" + str(password_file)],
                    result, stage="initdb", timeout=90, cwd=self.paths.data)
            if not version.is_file():
                raise PostgresCommandFailure("desktop_postgres_initialization_failed", {
                    "stage": "initdb_verify", "executable": "initdb.exe", "returncode": result.returncode,
                    "cluster_version_file_created": False, "cluster_directory": str(self.cluster.resolve()),
                    "stderr_tail": _diagnostic_text(result.stderr),
                })
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
                # Do not fetch data_directory as text: PostgreSQL on Windows
                # can expose the OS path using the local code page, which is
                # not necessarily UTF-8 for a Chinese user-data directory.
                # start() already captured a strict postmaster.pid identity
                # (PID, exact resolved cluster path, port, and start time); it
                # must still match immediately before we use the connection.
                if self._owned_identity is None or self._identity() != self._owned_identity:
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
                command = [self.binary("pg_ctl"), "-D", str(self.cluster), "-l", str(self.paths.data / "logs/postgres.log"),
                               "-o", f"-p {self.port} -c listen_addresses=127.0.0.1 -c log_statement=none -c log_min_error_statement=panic",
                               "-w", "-t", "30", "start"]
                result = _run(command, timeout=45, capture=True, stage="pg_ctl_start", cwd=self.paths.data)
            finally:
                identity = self._identity()
                if identity is not None and identity[1] >= started_at - 1:
                    self._owned_identity = identity
            if result.returncode or self._owned_identity is None:
                _failed_result("desktop_postgres_start_failed", command, result,
                    stage="pg_ctl_start", timeout=45, cwd=self.paths.data)
            self._ensure_database()
        except BaseException as startup_error:
            try:
                self.stop()
            except BaseException as cleanup_error:
                # Preserve the actionable startup failure. Cleanup trouble is
                # useful context, but must not replace the initdb/pg_ctl cause.
                if hasattr(startup_error, "add_note"):
                    startup_error.add_note(
                        f"PostgreSQL startup cleanup also failed: {type(cleanup_error).__name__}"
                    )
            finally:
                self.lock.release()
            raise
        return self

    def stop(self):
        try:
            if self._owned_identity is not None:
                if self._identity() != self._owned_identity:
                    raise ValueError("desktop_postgres_shutdown_identity_changed")
                command = [self.binary("pg_ctl"), "-D", str(self.cluster), "-m", "fast", "-w", "-t", "20", "stop"]
                result = _run(command, timeout=30, capture=True, stage="pg_ctl_stop", cwd=self.paths.data)
                if result.returncode:
                    _failed_result("desktop_postgres_shutdown_failed", command, result,
                        stage="pg_ctl_stop", timeout=30, cwd=self.paths.data)
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
