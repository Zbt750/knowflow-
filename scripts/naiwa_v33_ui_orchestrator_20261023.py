"""Same-process controller for the authorized V33 real-Chrome retest.

All chat messages are entered by the visible system Chrome driver.  This
controller starts only the retained isolated runtime and fails closed if the
canonical provider ledger or scene authorization is inconsistent.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)
NODE = Path(r"D:\应用安装包\node.exe")
SCRIPT = ROOT / "scripts/naiwa_v33_paid_continuation_20261023.py"
TAG = os.environ.get("NAIWA_V33_CONTINUATION_TAG", "")
if not TAG or not TAG.replace("-", "").isalnum() or len(TAG) > 24:
    raise SystemExit("A valid NAIWA_V33_CONTINUATION_TAG is required")

OUT = ROOT / f"storage/quality-audits/naiwa-v33-closeout-20261023/paid-continuation-{TAG}"
RUN = ROOT / f"storage/manual-experience/naiwa-real-20261020/agent-full-v33-continue-20261023-{TAG}"
LEDGER = ROOT / "storage/quality-audits/naiwa-freeze-preflight-20261021/round40-agent-full-v2-20261021/provider-ledger.json"
CONTROL = OUT / "control.json"
MAX_GLOBAL = 40


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def emit(value):
    print(json.dumps(value, ensure_ascii=False, default=str), flush=True)


def cli(*args: str):
    env = os.environ.copy()
    env["NAIWA_V33_CONTINUATION_TAG"] = TAG
    return subprocess.run([PYTHON, str(SCRIPT), *args], cwd=ROOT, env=env,
                          text=True, encoding="utf-8", capture_output=True, timeout=45)


def ledger_rows():
    ledger = read(LEDGER)
    rows = ledger.get("requests", [])
    if len(rows) > MAX_GLOBAL or ledger.get("stop_reason") or any(not row.get("finished") for row in rows):
        raise RuntimeError("canonical_ledger_not_safe_to_continue")
    return ledger, rows


def main():
    if not OUT.is_dir() or not RUN.is_dir() or not (OUT / "preparation-verification.json").is_file():
        raise RuntimeError("continuation_not_prepared")
    ledger, rows = ledger_rows()
    if len(rows) != 1:
        raise RuntimeError(f"unexpected_inherited_ledger_count:{len(rows)}")
    start_hashes = read(RUN / "active-source-hashes.json")["source_sha256"]
    env = os.environ.copy()
    env["NAIWA_V33_CONTINUATION_TAG"] = TAG
    sup_out = OUT / "orchestrator-supervisor.stdout.log"
    if sup_out.exists():
        raise RuntimeError("supervisor_log_exists_refusing_overwrite")
    service_log = sup_out.open("x", encoding="utf-8")
    service = subprocess.Popen([PYTHON, str(SCRIPT), "serve"], cwd=ROOT, env=env,
                               stdin=subprocess.DEVNULL, stdout=service_log,
                               stderr=subprocess.STDOUT,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    driver = None
    active_scene = None
    try:
        import httpx

        client = httpx.Client(trust_env=False, timeout=4, follow_redirects=False)
        health = None
        for _ in range(150):
            if service.poll() is not None:
                raise RuntimeError("isolated_supervisor_exited_before_health")
            try:
                response = client.get("http://127.0.0.1:63046/api/health")
                if response.status_code == 200 and response.headers.get("x-naiwa-experience") == "naiwa-v3-20261022":
                    health = response.json()
                    if health.get("database") != "connected":
                        raise RuntimeError("isolated_database_health_not_connected")
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        else:
            raise RuntimeError("isolated_runtime_health_timeout")
        client.close()

        now_hashes = read(RUN / "active-source-hashes.json")["source_sha256"]
        if start_hashes != now_hashes:
            raise RuntimeError("loaded_source_hash_epoch_changed")
        if read(CONTROL).get("paid_enabled"):
            raise RuntimeError("paid_exit_not_closed_before_browser_ready")

        driver_env = os.environ.copy()
        driver_env["NAIWA_V33_CONTINUATION_TAG"] = TAG
        driver_out = OUT / "chrome-driver.stdout.log"
        driver_err = OUT / "chrome-driver.stderr.log"
        if driver_out.exists() or driver_err.exists():
            raise RuntimeError("chrome_log_exists_refusing_overwrite")
        driver = subprocess.Popen([str(NODE), "frontend/acceptance/naiwa-v33-paid-continuation.cjs"],
                                  cwd=ROOT, env=driver_env, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=driver_err.open("x", encoding="utf-8"),
                                  text=True, encoding="utf-8", bufsize=1,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        output_queue: queue.Queue[str | None] = queue.Queue()

        def read_stdout():
            assert driver is not None and driver.stdout is not None
            for line in driver.stdout:
                output_queue.put(line.rstrip("\r\n"))
            output_queue.put(None)

        threading.Thread(target=read_stdout, daemon=True).start()
        ready_line = output_queue.get(timeout=180)
        ready = json.loads(ready_line) if ready_line else {}
        if not ready.get("ready") or ready.get("browser") != "visible-system-chrome":
            raise RuntimeError(f"visible_chrome_not_ready:{ready}")
        with driver_out.open("x", encoding="utf-8") as f:
            f.write(ready_line + "\n")
        emit({"ready": True, "tag": TAG, "health": health, "chrome": ready,
              "ledger_count": len(rows), "ledger_sha256": __import__("hashlib").sha256(LEDGER.read_bytes()).hexdigest(),
              "paid_enabled": False, "instruction": "Send JSON UI actions on stdin. Scene must be opened explicitly first."})

        for raw in sys.stdin:
            raw = raw.strip()
            if not raw:
                continue
            action = json.loads(raw)
            op = action.get("op")
            if op == "scene":
                scene = str(action.get("scene", ""))
                result = cli("open", scene)
                if result.returncode != 0:
                    active_scene = None
                    emit({"ok": False, "op": "scene", "scene": scene,
                          "reason": result.stderr or result.stdout,
                          "paid_enabled": read(CONTROL).get("paid_enabled")})
                    continue
                if driver is None or driver.stdin is None:
                    raise RuntimeError("visible_chrome_driver_missing")
                driver.stdin.write(json.dumps(action, ensure_ascii=False) + "\n")
                driver.stdin.flush()
                active_scene = scene
            elif op == "send":
                if active_scene is None:
                    raise RuntimeError("no_authorized_scene_open")
                if not read(CONTROL).get("paid_enabled") or read(CONTROL).get("active_scene") != active_scene:
                    raise RuntimeError("scene_gate_not_open")
                before, old_rows = ledger_rows()
                if len(old_rows) >= MAX_GLOBAL:
                    raise RuntimeError("global_cap_reached")
                if driver is None or driver.stdin is None:
                    raise RuntimeError("visible_chrome_driver_missing")
                driver.stdin.write(json.dumps(action, ensure_ascii=False) + "\n")
                driver.stdin.flush()
                line = output_queue.get(timeout=210)
                if line is None:
                    raise RuntimeError("chrome_driver_eof_unknown_request_state")
                result = json.loads(line)
                after, new_rows = ledger_rows()
                added = new_rows[len(old_rows):]
                if len(new_rows) > MAX_GLOBAL:
                    raise RuntimeError("global_cap_breached")
                closed = cli("close")
                active_scene = None
                emit({"op": "send_result", "ui": result,
                      "physical_reservations_added": len(added),
                      "new_ledger_rows": added,
                      "ledger_count_after": len(new_rows),
                      "ledger_sha256_after": __import__("hashlib").sha256(LEDGER.read_bytes()).hexdigest(),
                      "paid_enabled_after": read(CONTROL).get("paid_enabled"),
                      "close_exit_code": closed.returncode,
                      "close_output": (closed.stdout + closed.stderr).strip()})
                continue
            elif op == "close_paid":
                result = cli("close")
                active_scene = None
            elif op == "shutdown":
                if active_scene is not None:
                    cli("close")
                    active_scene = None
                if driver is not None and driver.stdin is not None and driver.poll() is None:
                    driver.stdin.write(json.dumps({"op": "close"}) + "\n")
                    driver.stdin.flush()
                    driver.stdin.close()
                    try:
                        output_queue.get(timeout=20)
                    except queue.Empty:
                        pass
                    driver.wait(timeout=20)
                stop_result = cli("stop")
                try:
                    service.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    emit({"ok": False, "op": "shutdown", "reason": "supervisor_did_not_stop_safely",
                          "paid_enabled": read(CONTROL).get("paid_enabled")})
                    return 2
                final, final_rows = ledger_rows()
                manifest = read(OUT / "runtime-v2.json")
                emit({"ok": service.returncode == 0 and not read(CONTROL).get("paid_enabled"),
                      "op": "shutdown", "supervisor_exit": service.returncode,
                      "stop_command_exit": stop_result.returncode,
                      "runtime_status": manifest.get("status"),
                      "ledger_count": len(final_rows),
                      "paid_enabled": read(CONTROL).get("paid_enabled")})
                return 0 if service.returncode == 0 and not read(CONTROL).get("paid_enabled") else 1
            else:
                if driver is None or driver.stdin is None:
                    raise RuntimeError("visible_chrome_driver_missing")
                driver.stdin.write(json.dumps(action, ensure_ascii=False) + "\n")
                driver.stdin.flush()
            line = output_queue.get(timeout=210 if op in {"goto", "refresh", "inspect", "click", "clickRole", "viewport"} else 30)
            if line is None:
                raise RuntimeError("chrome_driver_eof")
            emit({"op": op, "ui": json.loads(line),
                  "paid_enabled": read(CONTROL).get("paid_enabled"),
                  "ledger_count": len(ledger_rows()[1])})
    except Exception as exc:
        try:
            if active_scene is not None:
                cli("close")
        except Exception:
            pass
        emit({"fatal": type(exc).__name__, "detail": str(exc),
              "ledger_count": len(read(LEDGER).get("requests", [])),
              "paid_enabled": read(CONTROL).get("paid_enabled", False)})
        return 1
    finally:
        if driver is not None and driver.poll() is None:
            try:
                if driver.stdin is not None:
                    driver.stdin.write(json.dumps({"op": "close"}) + "\n")
                    driver.stdin.flush()
                driver.wait(timeout=15)
            except Exception:
                pass
        if service.poll() is None:
            try:
                cli("close")
                cli("stop")
                service.wait(timeout=50)
            except Exception:
                # Leave the isolated supervisor intact rather than killing it
                # forcibly; its owned runtime must be stopped via stop.request.
                pass
        service_log.close()


if __name__ == "__main__":
    raise SystemExit(main())
