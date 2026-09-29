"""Run the four-metric chat benchmark with only approved fixtures in a disposable schema."""
from __future__ import annotations

import argparse
import asyncio
from collections import deque
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _cleanup_orphaned_eval_schemas(connection) -> list[str]:
    """Remove only schemas created by this script on this host whose owner is gone."""
    local_host = socket.gethostname()
    rows = connection.exec_driver_sql(
        "SELECT n.nspname, obj_description(n.oid, 'pg_namespace') "
        "FROM pg_namespace AS n WHERE n.nspname LIKE 'ragas_chat_%'"
    ).all()
    removed: list[str] = []
    for schema, comment in rows:
        if not re.fullmatch(r"ragas_chat_[0-9a-f]{16}", str(schema)):
            continue
        match = re.fullmatch(
            r"kaoyan-isolated-ragas:v1:([A-Za-z0-9._-]{1,255}):(\d+)",
            str(comment or ""),
        )
        if not match or match.group(1) != local_host:
            continue
        owner_pid = int(match.group(2))
        if _pid_is_running(owner_pid):
            continue
        connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        removed.append(str(schema))
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="隔离数据库、向量索引与上传目录运行四项问答评测")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--serve-ui", action="store_true", help="仅启动获准资料的隔离 API 与 5176 前端，供真实浏览器测试；不运行裁判")
    parser.add_argument("--multifile-browser", action="store_true", help="运行获准验收文件及合成多文件的真实前端评测；不调用外部裁判")
    parser.add_argument("--ui-seconds", type=int, default=900, help="隔离前端最多运行秒数，到时清理并退出")
    args = parser.parse_args()
    if not 1 <= args.limit <= 9:
        parser.error("--limit 必须在 1–9 之间")

    os.environ["APP_ENV"] = "test"
    from backend.config import get_settings
    get_settings.cache_clear()
    settings = get_settings()
    from backend.db import create_db_engine
    from backend.models import import_models
    from backend.models.base import Base
    from sqlalchemy import text
    import httpx
    if not args.serve_ui and not args.multifile_browser:
        from scripts.run_ragas_chat_eval import DEFAULT_DATASET, run

    admin = create_db_engine(str(settings.active_database_url))
    schema = "ragas_chat_" + uuid4().hex[:16]
    assert re.fullmatch(r"ragas_chat_[0-9a-f]{16}", schema)
    scratch = Path(tempfile.mkdtemp(prefix="kaoyan-four-metrics-"))
    previous_options = os.environ.get("PGOPTIONS")
    process = None
    frontend = None
    log_thread = None
    log_tail = deque(maxlen=30)
    created_schema = False
    with admin.connect() as connection:
        before = tuple(connection.execute(text("SELECT id FROM public.materials ORDER BY id")).scalars())
    try:
        with admin.begin() as connection:
            stale_schemas = _cleanup_orphaned_eval_schemas(connection)
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            comment = f"kaoyan-isolated-ragas:v1:{socket.gethostname()}:{os.getpid()}"
            connection.exec_driver_sql(
                f'COMMENT ON SCHEMA "{schema}" IS '
                f"'{comment.replace(chr(39), chr(39) * 2)}'"
            )
        created_schema = True
        if stale_schemas:
            print(f"Removed {len(stale_schemas)} abandoned isolated schema(s).", flush=True)
        os.environ["PGOPTIONS"] = f"-c search_path={schema}"
        isolated = create_db_engine(str(settings.active_database_url))
        import_models()
        Base.metadata.create_all(isolated)
        isolated.dispose()
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        environment = os.environ.copy()
        environment.update(
            UPLOAD_DIR=str(scratch / "uploads"),
            CHROMA_DIR=str(scratch / "chroma"),
            MODEL_CACHE_DIR=str((ROOT / settings.model_cache_dir).resolve()),
            PYTHONIOENCODING="utf-8",
            ANONYMIZED_TELEMETRY="False",
        )
        # Test the model currently selected by the user, including local overrides.
        from backend.services.model_settings_service import load_local_settings
        effective = load_local_settings(settings.model_copy(update={"app_env": "dev"}))
        for field in ("llm_base_url", "llm_model", "llm_timeout_seconds", "llm_max_output_tokens", "llm_retry_max_output_tokens"):
            value = getattr(effective, field)
            environment[field.upper()] = str(value) if value is not None else ""
        environment["LLM_API_KEY"] = effective.llm_api_key.get_secret_value() if effective.llm_api_key else ""
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.app:create_app", "--factory", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
            cwd=ROOT, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        def drain_logs():
            if process.stdout:
                for line in process.stdout:
                    log_tail.append(line)
        log_thread = threading.Thread(target=drain_logs, daemon=True)
        log_thread.start()
        base = f"http://127.0.0.1:{port}/api"
        print("Starting isolated test API; shared databases and indexes are not used.", flush=True)
        with httpx.Client(timeout=5.0, trust_env=False) as client:
            for _ in range(120):
                if process.poll() is not None:
                    raise RuntimeError("隔离 API 启动失败：" + "".join(log_tail)[-2000:])
                try:
                    health = client.get(base + "/health")
                    if health.status_code == 200 and health.json().get("retrieval") == "ready":
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.5)
            else:
                raise RuntimeError("隔离 API 未能在时限内就绪：" + "".join(log_tail)[-2000:])

            fixtures = (
                ("builtin", "高等数学核心考点讲义", ROOT / "eval/fixtures/math_core.md"),
                ("user", "阶段A验收笔记", ROOT / "eval/fixtures/stage_a.md"),
            )
            if args.multifile_browser:
                benchmark = json.loads((ROOT / "eval/dataset/multifile_benchmark.json").read_text(encoding="utf-8"))
                original = client.get("http://127.0.0.1:8000/api/materials/1326d8f8-223d-40b2-827e-9c830e80aa50/content")
                original.raise_for_status()
                source = original.json()
                if source["title"] != "验收":
                    raise RuntimeError("获准验收资料标识与标题不一致")
                documents = [{"title": "验收", "mode": "user", "text": source["text"]}, *benchmark["documents"]]
                report_source = ROOT / "eval/reports/multifile-source-snapshot.json"
                report_source.write_text(json.dumps({"documents": documents}, ensure_ascii=False, indent=2), encoding="utf-8")
                uploads = [(d["mode"], d["title"], f"benchmark-{i}.md", d["text"].encode("utf-8")) for i, d in enumerate(documents)]
            else:
                uploads = [(mode, title, path.name, path.read_bytes()) for mode, title, path in fixtures]
            for source_type, title, filename, body in uploads:
                response = client.post(base + "/materials", params={"source_type": source_type, "title": title}, files={"file": (filename, body, "text/markdown")})
                response.raise_for_status()
            for _ in range(240):
                response = client.get(base + "/materials", params={"limit": 100})
                response.raise_for_status()
                items = response.json()["items"]
                if len(items) == len(uploads) and all(item["status"] == "ready" for item in items):
                    break
                if any(item["status"] == "failed" for item in items):
                    raise RuntimeError("测试讲义索引失败")
                time.sleep(0.5)
            else:
                raise RuntimeError("测试讲义索引超时")
        print(f"Exactly {len(uploads)} approved documents indexed; " + ("starting isolated real-model browser UI." if args.serve_ui or args.multifile_browser else "starting real model evaluation."), flush=True)
        if args.serve_ui or args.multifile_browser:
            frontend_environment = environment.copy()
            frontend_environment["VITE_API_PROXY_TARGET"] = f"http://127.0.0.1:{port}"
            ui_port = 5178 if args.multifile_browser else 5176
            frontend = subprocess.Popen(
                [shutil.which("node"), str(ROOT / "frontend/node_modules/vite/bin/vite.js"), "--host", "127.0.0.1", "--port", str(ui_port), "--strictPort"],
                cwd=ROOT / "frontend", env=frontend_environment,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            print(f"Isolated UI: http://127.0.0.1:{ui_port}/chat ; API: {base}", flush=True)
            if args.multifile_browser:
                for _ in range(60):
                    try:
                        if client.is_closed:
                            with httpx.Client(timeout=2, trust_env=False) as ui_client:
                                if ui_client.get(f"http://127.0.0.1:{ui_port}").status_code == 200:
                                    break
                    except httpx.HTTPError:
                        pass
                    if frontend.poll() is not None:
                        raise RuntimeError("隔离前端启动失败")
                    time.sleep(0.5)
                else:
                    raise RuntimeError("隔离前端未就绪")
                browser_env = frontend_environment.copy()
                browser_env.update(E2E_LIVE_CHAT="1", LIVE_CHAT_BASE_URL=f"http://127.0.0.1:{ui_port}")
                return subprocess.call([shutil.which("node"), str(ROOT / "frontend/node_modules/@playwright/test/cli.js"), "test", "--config", "playwright.live.config.ts", "multifile-depth.spec.ts"], cwd=ROOT / "frontend", env=browser_env)
            import signal
            shutdown = threading.Event()
            signal.signal(signal.SIGINT, lambda *_: shutdown.set())
            signal.signal(signal.SIGTERM, lambda *_: shutdown.set())
            ui_deadline = time.monotonic() + min(max(args.ui_seconds, 30), 3600)
            while not shutdown.wait(0.5) and time.monotonic() < ui_deadline:
                if process.poll() is not None or frontend.poll() is not None:
                    raise RuntimeError("隔离 UI/API 意外停止")
            return 0
        report = asyncio.run(run(argparse.Namespace(
            api_base=base, dataset=str(DEFAULT_DATASET), limit=args.limit,
            judge_model=None, judge_max_tokens=8000, metric_timeout=120,
        )))
        output = args.output or ROOT / "eval/reports" / f"chat_ragas_four_metrics_{time.strftime('%Y%m%d_%H%M%S')}.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Report: " + str(output.resolve()), flush=True)
        print(json.dumps(report["summary"], ensure_ascii=False, indent=2), flush=True)
        return 1 if report["summary"]["case_errors"] or report["summary"]["metric_errors"] else 0
    finally:
        cleanup_errors: list[str] = []
        for child in (frontend, process):
            if child is None:
                continue
            try:
                if child.poll() is None:
                    child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=10)
            except Exception as error:
                cleanup_errors.append(type(error).__name__)
            if child is process and child.stdout:
                try:
                    if log_thread is not None:
                        log_thread.join(timeout=2)
                    child.stdout.close()
                except Exception as error:
                    cleanup_errors.append(type(error).__name__)
        try:
            if previous_options is None:
                os.environ.pop("PGOPTIONS", None)
            else:
                os.environ["PGOPTIONS"] = previous_options
        except Exception as error:
            cleanup_errors.append(type(error).__name__)
        try:
            if created_schema:
                with admin.begin() as connection:
                    connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        except Exception as error:
            cleanup_errors.append(type(error).__name__)
            print(f"Cleanup warning: isolated schema may remain ({type(error).__name__}).", file=sys.stderr, flush=True)
        try:
            with admin.connect() as connection:
                after = tuple(connection.execute(text("SELECT id FROM public.materials ORDER BY id")).scalars())
            if before != after:
                cleanup_errors.append("shared_materials_changed")
        except Exception as error:
            cleanup_errors.append(type(error).__name__)
        finally:
            admin.dispose()
            target = scratch.resolve()
            if target.parent == Path(tempfile.gettempdir()).resolve() and target.name.startswith("kaoyan-four-metrics-"):
                try:
                    shutil.rmtree(target)
                except OSError as error:
                    cleanup_errors.append(type(error).__name__)
        if cleanup_errors:
            print("Cleanup warnings: " + ", ".join(cleanup_errors), file=sys.stderr, flush=True)
        else:
            print("Isolated API stopped, schema and temporary indexes removed; shared materials unchanged.", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
