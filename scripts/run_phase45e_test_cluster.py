"""Run acceptance in a new owned temporary PG18 cluster; never touch .pgdata."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import shutil

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from desktop.runtime_paths import RuntimePaths
from desktop.postgres import ManagedPostgres, ADMIN, APP_USER
from sqlalchemy.engine import make_url
from psycopg import sql


def execution_context():
    """Read execution identity without collecting credentials or environment values."""
    context={"process_id":os.getpid(),"parent_process_id":os.getppid(),
        "python_executable":sys.executable,"python_version":sys.version.split()[0],
        "cwd":str(Path.cwd().resolve()),"platform":sys.platform}
    if os.name=="nt":
        import ctypes
        from ctypes import wintypes
        kernel32=ctypes.WinDLL("kernel32",use_last_error=True)
        advapi32=ctypes.WinDLL("advapi32",use_last_error=True)
        kernel32.GetCurrentProcess.restype=wintypes.HANDLE
        kernel32.IsProcessInJob.argtypes=[wintypes.HANDLE,wintypes.HANDLE,ctypes.POINTER(wintypes.BOOL)]
        kernel32.IsProcessInJob.restype=wintypes.BOOL
        advapi32.OpenProcessToken.argtypes=[wintypes.HANDLE,wintypes.DWORD,ctypes.POINTER(wintypes.HANDLE)]
        advapi32.OpenProcessToken.restype=wintypes.BOOL
        advapi32.IsTokenRestricted.argtypes=[wintypes.HANDLE]
        advapi32.IsTokenRestricted.restype=wintypes.BOOL
        kernel32.CloseHandle.argtypes=[wintypes.HANDLE]
        in_job=wintypes.BOOL()
        if kernel32.IsProcessInJob(kernel32.GetCurrentProcess(),None,ctypes.byref(in_job)):
            context["windows_process_in_job"]=bool(in_job.value)
        token=wintypes.HANDLE()
        if advapi32.OpenProcessToken(kernel32.GetCurrentProcess(),0x0008,ctypes.byref(token)):
            try:context["windows_token_restricted"]=bool(advapi32.IsTokenRestricted(token))
            finally:kernel32.CloseHandle(token)
        else:context["token_diagnostic_winerror"]=ctypes.get_last_error()
    return context


def _preserve_temporary_data_on_failure(args, results):
    """Keep this run's owned cluster when an opt-in diagnostic run fails."""
    if not getattr(args, "preserve_temp_on_failure", False):
        return False
    return bool(
        results.get("failure")
        or results.get("cleanup_failure")
        or results.get("pytest_has_failures")
        or any(check.get("exit_code") != 0 for check in results.get("checks", []))
    )


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir",type=Path,default=ROOT/"storage/quality-audits/phase45e-isolated-run")
    parser.add_argument("--focused",action="store_true")
    parser.add_argument("--tests-only",action="store_true",help="Run explicit isolated tests without replaying frozen Phase E assets")
    parser.add_argument("--workspace-temp",action="store_true",help="Keep the disposable owned PostgreSQL cluster under this repository's tmp/managed-test-clusters directory")
    parser.add_argument("--preserve-temp-on-failure",action="store_true",
        help="Preserve this run's owned temporary cluster if initialization, tests, or cleanup fail")
    parser.add_argument('--public-bank-rehearsal',action='store_true',help='Reaudit intact frozen export and rehearse H only in a marked private schema')
    parser.add_argument("--pytest-file",action="append",default=[],
        help="Explicit pytest file, optionally narrowed to one function with ::test_name")
    parser.add_argument("--browser",action="store_true")
    parser.add_argument("--browser-only",action="store_true")
    parser.add_argument("--capture-report",type=Path)
    parser.add_argument("--browser-file",action="append",default=[])
    parser.add_argument("--browser-backend", choices=["scripts.e2e_backend:create_e2e_app", "tests.integration.generation_journey_backend:create_e2e_app", "tests.integration.knowledge_loading_backend:create_e2e_app", "tests.integration.query_followup_backend:create_e2e_app", "tests.integration.scope_math_backend:create_e2e_app"],
        default="scripts.e2e_backend:create_e2e_app", help="Explicitly bounded offline browser backend factory")
    args=parser.parse_args()
    import re
    if any(not re.fullmatch(r"(?:e2e|acceptance)/[a-z0-9._-]+\.spec\.ts",p) for p in args.browser_file):
        raise ValueError("Invalid explicit browser spec path")
    if any(not re.fullmatch(
            r"tests/(?:integration|unit)/[a-z0-9_/-]+\.py(?:::[A-Za-z_][A-Za-z0-9_]*)?", p
        ) for p in args.pytest_file):
        raise ValueError("Invalid explicit pytest path")
    from scripts.audit_question_quality import safe_output
    output=safe_output(args.output_dir)
    output.mkdir(parents=True,exist_ok=False)
    temporary=None
    manager=None
    private_values=set()
    results={"original_cluster_touched":False,"temporary_user_directory":None,"port":None,
        "checks":[],"stage":"runner_setup","execution_context":execution_context(),
        "temporary_postgres_stopped":False}
    def redact_artifact(path):
        if not path.is_file():return
        content=path.read_text(encoding="utf-8",errors="replace")
        safe=content
        for secret in private_values:
            if secret:safe=safe.replace(secret,"[REDACTED]")
        if safe!=content:path.write_text(safe,encoding="utf-8")
    def execute(name,command,env,cwd=ROOT):
        results["stage"]=name
        with (output/(name+".log")).open("w",encoding="utf-8") as log:
            completed=subprocess.run(command,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
        redact_artifact(output/(name+".log"))
        results["checks"].append({"name":name,"exit_code":completed.returncode,"log":name+".log"})
        print(name+": "+str(completed.returncode),flush=True)
        return completed.returncode
    try:
        results["stage"]="temporary_parent_prepare"
        temporary_parent=(ROOT/"tmp"/"managed-test-clusters") if args.workspace_temp else None
        if temporary_parent is not None:
            temporary_parent.mkdir(parents=True,exist_ok=True)
        results["stage"]="temporary_directory_create"
        temporary=Path(tempfile.mkdtemp(prefix="kaoyan-phase45e-",dir=temporary_parent))
        results["temporary_user_directory"]=str(temporary)
        results["stage"]="temporary_port_select"
        with socket.socket() as listener:
            listener.bind(("127.0.0.1",0)); port=listener.getsockname()[1]
        if port<18000:raise ValueError("temporary_port_outside_manager_range")
        results["port"]=port
        # RuntimePaths deliberately forbids mutable data under immutable resources.
        # In workspace-temp test mode use the separated backend package subtree as
        # the resource sentinel; the managed test runner does not read resource files.
        resource_root=ROOT/"backend" if args.workspace_temp else ROOT
        paths=RuntimePaths.windows(resources=resource_root,local_app_data=temporary)
        manager=ManagedPostgres(paths,Path("C:/Program Files/PostgreSQL/18/bin"),port=port)
        results["stage"]="postgres_start"
        with manager:
            private_values.update(manager._passwords.values())
            with manager._connect() as connection:
                results["database_identity"]={"cluster_id":manager.owner["cluster_id"],
                    "system_identifier":str(connection.execute("SELECT system_identifier FROM pg_control_system()").fetchone()[0]),
                    "cluster_directory":str(manager.cluster.resolve()),
                    "postmaster_identity":manager._owned_identity}
                connection.execute(sql.SQL("CREATE DATABASE {} OWNER {} TEMPLATE template0 ENCODING 'UTF8'").format(
                    sql.Identifier("kaoyan_test"),sql.Identifier(APP_USER)))
            with manager._connect(user=APP_USER,database="kaoyan_test") as connection:
                # inet's text cast includes /32; host() returns the exact IP
                # without weakening the loopback/database/user/port checks.
                actual=connection.execute("SELECT current_database(),current_user,host(inet_server_addr()),inet_server_port()").fetchone()
                results["database_identity"]["observed_app_identity"]=list(actual)
                if actual!=("kaoyan_test",APP_USER,"127.0.0.1",port):
                    raise ValueError("isolated_test_database_identity_mismatch")
                results["database_identity"].update(database=actual[0],user=actual[1],host=actual[2],port=actual[3])
            test_url=make_url(manager.database_url).set(database="kaoyan_test").render_as_string(hide_password=False)
            # Only the disposable test-cluster bootstrap role may create the
            # least-privilege runtime role used by ACL integration tests. Keep
            # this credential in the child environment; never print it.
            admin_url=make_url(manager.database_url).set(
                username=ADMIN, password=manager._passwords[ADMIN], database="kaoyan_test"
            ).render_as_string(hide_password=False)
            env={**os.environ,"APP_ENV":"test","TEST_DATABASE_URL":test_url,"DATABASE_URL":test_url,
                "KAOYAN_OWNED_TEST_PORT":str(port),
                "PHASE45E_OWNED_TEST_PORT":str(port),
                "PHASE45E_TEST_DATABASE_URL":test_url,"KAOYAN_TEST_ADMIN_DATABASE_URL":admin_url,
                "PYTHONIOENCODING":"utf-8","HF_HUB_OFFLINE":"1","TRANSFORMERS_OFFLINE":"1",
                "UPLOAD_DIR":str(output/"test-resources/uploads"),"CHROMA_DIR":str(output/"test-resources/chroma"),
                "MODEL_SETTINGS_PATH":str(output/"test-resources/config/model-settings.bin")}
            env.update(LLM_API_KEY="",LLM_BASE_URL="http://127.0.0.1:9",LLM_MODEL="offline-test-fixture")
            if args.tests_only:
                env.update(PHASE45I_CLOSE_OFFLINE="1",PHASE45I_CLOSE_OUTPUT=str(output))
            if args.browser_backend in {'tests.integration.query_followup_backend:create_e2e_app','tests.integration.scope_math_backend:create_e2e_app'}:
                env.update(QUERY_FOLLOWUP_OUTPUT=str(output), QUERY_FOLLOWUP_PYTHON=sys.executable)
            # Model calls are not part of this phase; all integration providers are fixtures.
            scope=args.pytest_file or (["tests/integration/test_agent_learning_journey.py","tests/integration/test_golden_learning_slice.py",
                "tests/integration/test_learning_agent_eval.py","tests/integration/test_online_reference_resolution.py",
                "tests/integration/test_p5_adaptive_journey.py","tests/integration/test_unverified_adaptive_journey.py",
                "tests/integration/test_phase45e_current_graduation.py","tests/integration/test_policy_origin_semantics.py",
                "tests/integration/test_question_pack_import.py","tests/unit/test_chat_context_screening.py",
                "tests/unit/test_chat_multifile_scope.py","tests/unit/test_chat_stage_scope.py"] if args.focused else [])
            replay_dir=output/"bank-acceptance"
            if args.public_bank_rehearsal:
                if execute('public-bank-rehearsal',[sys.executable,'scripts/run_public_bank_h.py','--rehearse','--output-dir',str(output/'public-bank')],env):
                    raise ValueError('Public-bank rehearsal failed; no original database operations allowed')
            if not args.browser_only:
                # Every run already owns a mkdtemp directory. Using only the
                # audit basename here made unrelated run-01 jobs share pytest
                # handles and allowed one worker to remove another's temp dir.
                pytest_temp=temporary/"pytest"
                results["pytest_temporary_directory"]=str(pytest_temp)
                rc=execute("pytest",[sys.executable,"-m","pytest",*scope,"-q","-o","addopts=",
                    "--basetemp",str(pytest_temp),"--junitxml",str(output/"pytest-junit.xml")],env)
                redact_artifact(output/"pytest-junit.xml")
                if rc:results["pytest_has_failures"]=True
                baseline_env={**env,"APP_ENV":"dev"}
                baseline=1 if args.tests_only else execute("baseline",[sys.executable,"scripts/run_phase45e_acceptance.py","--output-dir",str(replay_dir),"--baseline-only","--offline-baseline"],baseline_env)
                if baseline==0:
                    execute("frozen-bank-replay",[sys.executable,"scripts/run_phase45e_acceptance.py","--output-dir",str(replay_dir)],baseline_env)
            else:
                if not args.capture_report or not args.capture_report.is_file():raise ValueError("Existing successful API capture required")
                if execute("migration",[sys.executable,"-m","alembic","upgrade","head"],env):raise ValueError("Test migration failed")
                if execute("browser-seed",[sys.executable,"scripts/prepare_phase45e_browser.py"],env):raise ValueError("Test seed failed")
            if args.browser or args.browser_only:
                if args.tests_only and not args.browser_only and args.browser_backend not in {'tests.integration.knowledge_loading_backend:create_e2e_app', 'tests.integration.query_followup_backend:create_e2e_app','tests.integration.scope_math_backend:create_e2e_app'}:
                    # pytest会各自重置合成题库；浏览器随后必须重建合法审核和v3绑定。
                    # 只对显式的独立测试模式执行，不影响封版库复演路径。
                    if execute("e2e-learning-prepare",[sys.executable,"scripts/prepare_e2e_learning.py","--apply"],env):
                        raise ValueError("Isolated E2E formal fixture preparation failed")
                with socket.socket() as listener:
                    listener.bind(("127.0.0.1",0)); api_port=listener.getsockname()[1]
                env.update(E2E_API_BASE=f"http://127.0.0.1:{api_port}",
                    E2E_WEB_BASE="http://127.0.0.1:5174",
                    PHASE45E_CAPTURE_REPORT=str(args.capture_report.resolve() if args.capture_report else replay_dir/"replay/acceptance.json"))
                dedicated_backend = args.browser_backend.startswith("tests.integration.")
                if dedicated_backend:
                    # A protocol suite can own 5174 concurrently. This journey
                    # must not reuse its Vite proxy to a different/dead backend.
                    with socket.socket() as web_listener:
                        web_listener.bind(("127.0.0.1",0)); web_port=web_listener.getsockname()[1]
                    env['E2E_WEB_BASE']=f'http://127.0.0.1:{web_port}'
                    env['ALLOWED_WEB_ORIGINS']=json.dumps([env['E2E_WEB_BASE']])
                prepared=(0 if dedicated_backend else
                    execute("e2e-prepare",[sys.executable,"scripts/prepare_e2e_data.py","--apply"],env))
                if prepared==0:
                    import httpx
                    with (output/"backend.log").open("w",encoding="utf-8") as log:
                        server=subprocess.Popen([sys.executable,"-m","uvicorn",args.browser_backend,
                            "--factory","--host","127.0.0.1","--port",str(api_port)],cwd=ROOT,env=env,
                            stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
                        try:
                            ready=False
                            deadline=time.monotonic()+120
                            while time.monotonic()<deadline:
                                if server.poll() is not None:break
                                try:
                                    health=httpx.get(env["E2E_API_BASE"]+"/api/health",timeout=2,trust_env=False).json()
                                    if health.get("environment")=="test" and health.get("llm_model")=="e2e-offline-fixture":
                                        ready=True;break
                                except Exception as exc:results["last_health_error_type"]=type(exc).__name__
                                time.sleep(0.5)
                            if ready:
                                env["PLAYWRIGHT_JSON_OUTPUT_NAME"]=str(output/"browser-report.json")
                                browser_config = (["--config=playwright.scope-math.config.ts"]
                                    if args.browser_backend == "tests.integration.scope_math_backend:create_e2e_app" else ["--config=playwright.query-followup.config.ts"]
                                    if args.browser_backend == "tests.integration.query_followup_backend:create_e2e_app" else ["--config=playwright.knowledge-performance.config.ts"]
                                    if args.browser_backend == "tests.integration.knowledge_loading_backend:create_e2e_app" else
                                    ["--config=playwright.generation.config.ts"] if dedicated_backend else [])
                                execute("playwright",["npx.cmd","playwright","test",*browser_config,*args.browser_file,"--output="+str(output/"browser-artifacts"),"--reporter=list,json"],env,ROOT/"frontend")
                            else:results["browser_blocker"]="offline_backend_not_ready"
                        finally:
                            server.terminate();server.wait(timeout=20)
    except Exception as exc:
        diagnostic=getattr(exc,"diagnostic",None)
        failure={"stage":results.get("stage"),"exception_type":type(exc).__name__}
        code=getattr(exc,"code",None)
        if code:
            failure["code"]=code
        elif isinstance(exc,OSError):
            failure.update({"code":"runner_os_error","errno":getattr(exc,"errno",None),
                "winerror":getattr(exc,"winerror",None),
                "os_error":getattr(exc,"strerror",None) or type(exc).__name__,
                "filename":Path(str(getattr(exc,"filename",""))).name if getattr(exc,"filename",None) else None})
        else:
            failure["code"]="test_runner_setup_failed"
            if isinstance(exc, ValueError) and str(exc) in {"isolated_test_database_identity_mismatch", "temporary_port_outside_manager_range"}:
                failure["code"]=str(exc)
        if diagnostic:
            failure["diagnostic"]=diagnostic
            stage_name=re.sub(r"[^a-zA-Z0-9_-]","_",str(diagnostic.get("stage","postgres")))[:48]
            for stream, suffix in (("stdout_tail", "stdout"), ("stderr_tail", "stderr")):
                captured=diagnostic.get(stream)
                if captured:
                    stream_path=output/f"postgres-{stage_name}.{suffix}.log"
                    stream_path.write_text(captured,encoding="utf-8")
                    failure[f"{suffix}_log"]=stream_path.name
        results["failure"]=failure
    finally:
        try:
            process_state=("not_started" if manager is None else manager.cluster_process_status())
            results["temporary_postgres_process_state"]=process_state
            # A stale bootstrap postmaster.pid is not proof of a live server.
            # Only preserve the temp tree when an exact-cluster PID is live or
            # its state cannot be determined safely.
            results["temporary_postgres_stopped"]=(True if manager is None else process_state is False)
            expected_temp_parents={Path(tempfile.gettempdir()).resolve()}
            if args.workspace_temp:
                expected_temp_parents.add((ROOT/"tmp"/"managed-test-clusters").resolve())
            if _preserve_temporary_data_on_failure(args, results):
                results["owned_temporary_data_preserved_due_to_failure"] = True
            elif (temporary is not None and results["temporary_postgres_stopped"]
                    and temporary.resolve().parent in expected_temp_parents
                    and temporary.name.startswith("kaoyan-phase45e-")):
                marker=(manager.marker if manager is not None else temporary/"KaoyanStudy"/"config"/"postgres-owner.json")
                owned=(manager is not None and manager.owner and marker.is_file()
                    and json.loads(marker.read_text(encoding="utf-8"))["cluster_id"]==manager.owner["cluster_id"])
                try:
                    empty=not any(temporary.iterdir())
                except FileNotFoundError:
                    empty=False
                if owned or empty:
                    shutil.rmtree(temporary)
                    results["owned_temporary_data_removed"]=True
        except Exception as exc:
            # Keep the original command/initdb failure and record cleanup
            # trouble separately; never turn a useful diagnostic into a bare
            # desktop_postgres_command_failed result.
            results["cleanup_failure"]={"exception_type":type(exc).__name__,
                "errno":getattr(exc,"errno",None),"winerror":getattr(exc,"winerror",None),
                "filename":Path(str(getattr(exc,"filename",""))).name if getattr(exc,"filename",None) else None}
        (output/"run-summary.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(results,ensure_ascii=False,indent=2))
    return int(any(check["exit_code"]!=0 for check in results["checks"])
        or bool(results.get("browser_blocker")) or bool(results.get("failure"))
        or bool(results.get("cleanup_failure"))
        or not results["temporary_postgres_stopped"])


if __name__=="__main__":
    if hasattr(sys.stdout,"reconfigure"):sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
