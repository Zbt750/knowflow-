"""Seven-request, persistent, browser-scoped acceptance gate. Not a product API."""
import argparse
import asyncio
import contextvars
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.phase5_eval_meter import Meter, BudgetStop
from scripts.restore_naiwa_experience_20261020 import save, snapshot, MODULES, RUN, ORIGINAL

OUT = ROOT / "storage/quality-audits/naiwa-real-retest-20261020-budget7"
CAPS = {"AGENT": 4, "TEACH": 1, "GENERATE": 1, "EXPLAIN": 1}
SCENE = contextvars.ContextVar("naiwa_retest_scene", default=None)


class RetestMeter(Meter):
    def __init__(self, output=OUT, *, simulated=False):
        output.mkdir(parents=True, exist_ok=True)
        super().__init__(output, max_requests=7)
        self.simulated = simulated
        self.control = output / "control.json"
        if not self.control.exists():
            save(self.control, {"paid_enabled": False, "active_scene": None})
        ledger = output / "provider-ledger.json"
        if ledger.exists():
            old = json.loads(ledger.read_text(encoding="utf-8"))
            assert old["limits"]["max_requests"] == 7 and old["scene_limits"] == CAPS
            self.records, self.stop_reason = old["requests"], old["stop_reason"]
            if any(not r.get("finished") for r in self.records):
                self.stop_reason = "unfinished_physical_request_requires_reconciliation"
        self.flush()

    def flush(self):
        super().flush()
        path = self.output / "provider-ledger.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value.update(scene_limits=CAPS, simulated_zero_network=self.simulated,
                     scene_counts={s: sum(r["case_id"] == s for r in self.records) for s in CAPS})
        save(path, value)

    def close(self, reason):
        save(self.control, {"paid_enabled": False, "active_scene": None, "closed_reason": reason, "time": time.time()})

    def begin(self, request):
        with self.lock:
            control = json.loads(self.control.read_text(encoding="utf-8"))
            scene = SCENE.get()
            if request.url.host in {"localhost", "127.0.0.1", "testserver"}:
                return None
            if not control.get("paid_enabled") or scene not in CAPS or scene != control.get("active_scene"):
                raise BudgetStop("unapproved_browser_operation_or_paid_exit_closed")
            if sum(r["case_id"] == scene for r in self.records) >= CAPS[scene]:
                with (self.output / "blocked-before-send.jsonl").open("a", encoding="utf-8") as log:
                    log.write(json.dumps({"scene": scene, "reason": "scene_cap", "time": time.time()}) + "\n")
                raise BudgetStop("scene_physical_request_cap")
            if not self.simulated:
                try:
                    verify_originals()
                except Exception:
                    self.close("historical_integrity_check_failed")
                    raise
            self.case_id = scene
            record = super().begin(request)
            if record:
                record.update(stage=scene.lower(), started_at=time.time())
                self.flush()
            return record

    def finish(self, record, *args, **kwargs):
        super().finish(record, *args, **kwargs)
        if record and (record.get("error_type") or (record.get("http_status") or 599) >= 400):
            self.stop_reason = "network_or_provider_http_failure_stop"
        if self.stop_reason:
            self.close(self.stop_reason)
        self.flush()


def verify_originals():
    baseline = json.loads((OUT / "baseline.json").read_text(encoding="utf-8"))
    for name, digest in baseline["evidence_hashes"].items():
        assert hashlib.sha256((ORIGINAL / name).read_bytes()).hexdigest() == digest, "old_evidence_changed"
    current = json.loads(json.dumps(snapshot("retest-readonly-current"), default=str))
    for table in ("chat_messages", "questions", "question_versions", "practice_items", "question_attempts", "learning_events", "learning_tasks", "personal_generation_batches"):
        by_id = {row["id"]: row for row in current[table]}
        for row in baseline["database"][table]:
            assert by_id.get(row["id"]) == row, "historical_row_changed:" + table
    return current


def real_app():
    from backend.config import get_settings
    from backend.chat.service import Provider
    from backend.errors import AppError
    from backend.app import create_app
    from sqlalchemy.engine import make_url
    settings = get_settings()
    url = make_url(str(settings.active_database_url))
    assert (url.host, url.port, url.database) == ("127.0.0.1", 63044, "naiwa_experience_test")
    assert settings.app_env == "test" and settings.llm_model == "deepseek-flash"
    assert settings.llm_base_url.rstrip("/") == "https://api.deepseek.com"
    assert json.loads((OUT / "counter-selftest.json").read_text())["status"] == "PASS"
    meter = RetestMeter()
    meter.close("startup_requires_explicit_scene_enable")
    meter.install()
    # Physical transport retries are zero by httpx default. Reject application retries too.
    complete, stream, tool = Provider.complete, Provider.stream, Provider.tool_turn
    def once_complete(self, messages, *, attempt=1):
        if attempt != 1:
            raise AppError("generation_failed", detail="retest_automatic_retry_disabled", retryable=False)
        try:
            return complete(self, messages, attempt=attempt)
        except AppError as exc:
            exc.retryable = False
            raise
    async def once_stream(self, messages, *, attempt=1):
        if attempt != 1:
            raise AppError("generation_failed", detail="retest_automatic_retry_disabled", retryable=False)
        try:
            async for delta in stream(self, messages, attempt=attempt):
                yield delta
        except AppError as exc:
            exc.retryable = False
            raise
    def once_tool(self, *args, **kwargs):
        try:
            return tool(self, *args, **kwargs)
        except AppError as exc:
            exc.retryable = False
            raise
    Provider.complete, Provider.stream, Provider.tool_turn = once_complete, once_stream, once_tool
    application = create_app()
    loaded = {str(Path(import_module(name).__file__).relative_to(ROOT)).replace("\\", "/"):
              hashlib.sha256(Path(import_module(name).__file__).read_bytes()).hexdigest() for name in MODULES}
    save(RUN / "loaded-code.json", {"pid": os.getpid(), "python": sys.executable, "workspace": str(ROOT),
         "source_sha256": loaded, "provider": "real-deepseek-browser-scoped-budget7", "ledger": str(OUT),
         "physical_limit": 7, "scene_limits": CAPS, "loaded_at": time.time()})
    class Scoped:
        async def __call__(self, scope, receive, send):
            headers = dict(scope.get("headers", []))
            scene = headers.get(b"x-naiwa-retest-case", b"").decode()
            nonce = headers.get(b"x-naiwa-retest-nonce", b"").decode()
            allowed = nonce == (OUT / "browser-nonce.txt").read_text().strip()
            token = SCENE.set(scene if allowed else None)
            async def labeled(message):
                if message["type"] == "http.response.start":
                    message.setdefault("headers", []).extend([(b"x-naiwa-experience", b"real-retest-budget7"),
                        (b"x-naiwa-backend-pid", str(os.getpid()).encode())])
                await send(message)
            try:
                await application(scope, receive, labeled)
            finally:
                SCENE.reset(token)
    return Scoped()


def import_module(name):
    import importlib
    return importlib.import_module(name)


def selftest():
    import httpx
    import tempfile
    payload = {"model": "deepseek-flash", "max_tokens": 100, "messages": [{"role": "user", "content": "zero network"}]}
    reply = {"model": "deepseek-flash", "choices": [{"message": {"content": "mock"}, "finish_reason": "stop"}],
             "usage": {"prompt_tokens": 20, "completion_tokens": 10}}
    count = [0]
    def transport(request):
        count[0] += 1
        return httpx.Response(200, json=reply)
    checks = []
    with tempfile.TemporaryDirectory(prefix="naiwa-counter-", dir=OUT) as directory:
        directory = Path(directory)
        meter = RetestMeter(directory, simulated=True)
        meter.install()
        def enable(scene):
            SCENE.set(scene); save(meter.control, {"paid_enabled": True, "active_scene": scene})
        try:
            enable("AGENT")
            with httpx.Client(transport=httpx.MockTransport(transport)) as client:
                for _ in range(4):
                    client.post("https://api.deepseek.com/chat/completions", json=payload)
                try:
                    client.post("https://api.deepseek.com/chat/completions", json=payload)
                    raise AssertionError("cap not enforced")
                except BudgetStop:
                    assert count[0] == 4
            checks.append("sync physical send and Agent cap4")
        finally:
            meter.uninstall()
        meter = RetestMeter(directory, simulated=True)
        assert len(meter.records) == 4
        checks.append("restart recovers four reservations without resetting")
        meter.install()
        async def remaining():
            class MockStream(httpx.AsyncByteStream):
                async def __aiter__(self):
                    yield ("data: " + json.dumps(reply) + "\n\ndata: [DONE]\n\n").encode()
            async def async_transport(request):
                count[0] += 1
                return httpx.Response(200, stream=MockStream(), headers={"content-type": "text/event-stream"})
            for scene in ("TEACH", "GENERATE", "EXPLAIN"):
                enable(scene)
                async with httpx.AsyncClient(transport=httpx.MockTransport(async_transport)) as client:
                    async with client.stream("POST", "https://api.deepseek.com/chat/completions", json=payload) as response:
                        await response.aread()
                    try:
                        await client.post("https://api.deepseek.com/chat/completions", json=payload)
                        raise AssertionError("per scene not blocked")
                    except BudgetStop:
                        pass
        try:
            asyncio.run(remaining())
            assert count[0] == len(meter.records) == 7
            checks.append("async streaming and independent scene caps1/1/1; total7")
            meter.close("selftest closed")
            enable("AGENT")
            try:
                with httpx.Client(transport=httpx.MockTransport(transport)) as client:
                    client.post("https://api.deepseek.com/chat/completions", json=payload)
            except BudgetStop:
                assert count[0] == 7
            else:
                raise AssertionError("overflow sent")
            checks.append("eighth physical send blocked with no network")
        finally:
            meter.uninstall()
        # Independent fault test, never touches the real ledger.
        fault = RetestMeter(directory / "fault", simulated=True)
        SCENE.set("TEACH"); save(fault.control, {"paid_enabled": True, "active_scene": "TEACH"})
        def network_failure(request):
            raise httpx.ConnectError("simulated no network", request=request)
        fault.install()
        try:
            with httpx.Client(transport=httpx.MockTransport(network_failure)) as client:
                try:
                    client.post("https://api.deepseek.com/chat/completions", json=payload)
                except httpx.ConnectError:
                    pass
            assert len(fault.records) == 1 and not json.loads(fault.control.read_text())["paid_enabled"]
            checks.append("network failure retains reservation and seals paid exit")
        finally:
            fault.uninstall()
        save(OUT / "counter-selftest.json", {"status": "PASS", "checks": checks,
             "transport": "httpx.MockTransport; no sockets or real Provider", "real_physical_requests": 0})
    print(json.dumps({"status": "PASS", "checks": checks}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["selftest", "prepare", "seal", "check", "report"])
    action = parser.parse_args().action
    OUT.mkdir(parents=True, exist_ok=True)
    if action == "selftest":
        return selftest()
    if action == "prepare":
        assert not (OUT / "baseline.json").exists(), "never overwrite retained baseline"
        before = snapshot("retest-baseline")
        active = {t: [str(r["id"]) for r in before[t] if r.get("status") in {"running", "generating", "streaming", "pending"}]
                  for t in ("chat_messages", "learning_tasks", "personal_generation_batches")}
        assert not any(active.values()), active
        save(OUT / "baseline.json", {"database": before, "active": active,
            "evidence_hashes": {name: hashlib.sha256((ORIGINAL / name).read_bytes()).hexdigest()
                for name in ("provider-ledger.json", "journeys.json", "sessions.json")}})
        import secrets
        (OUT / "browser-nonce.txt").write_text(secrets.token_hex(24))
        RetestMeter().close("prepared_not_enabled")
        print("Prepared; historical records retained; paid exit closed.")
    elif action == "seal":
        RetestMeter().close("test_complete_or_interrupted")
        print("Paid exit closed.")
    elif action == "report":
        return report()
    else:
        current = verify_originals()
        meter = RetestMeter()
        print(json.dumps({"historical_rows_unchanged": True, "counts": {t: len(current[t]) for t in ("chat_messages", "questions", "learning_tasks")},
                          "physical_requests": len(meter.records), "control": json.loads(meter.control.read_text())}))


def report():
    """Offline, independent symbolic review and retained-database reconciliation."""
    import sympy as sp
    import shutil
    meter = RetestMeter()
    meter.close("real_retest_finished_no_more_authorized_calls")
    current = verify_originals()
    baseline = json.loads((OUT / "baseline.json").read_text(encoding="utf-8"))["database"]
    journeys = json.loads((OUT / "journeys.json").read_text(encoding="utf-8"))
    x = sp.symbols("x", real=True)
    numerator = sp.exp(x) - 1 - x - x*x/2
    denominator = x - sp.log(1+x)
    review = {"correct": False, "status": "FAIL", "scope": "exact stem returned by physical request5; not the rewritten stem inside its explanation",
              "numerator": str(numerator), "denominator": str(denominator),
              "numerator_series": str(sp.series(numerator, x, 0, 5)),
              "denominator_series": str(sp.series(denominator, x, 0, 5)),
              "left_limit": str(sp.limit(numerator/denominator, x, 0, dir="-")),
              "right_limit": str(sp.limit(numerator/denominator, x, 0, dir="+")),
              "model_correct_answer": "A", "model_option_A_value": "1", "model_final_value": "1/2",
              "conflicts": ["actual limit0 absent from options1,2,3,1/2", "correct_answer A=1 differs from final_value1/2",
                  "explanation repeatedly changes denominator to a different problem"],
              "followup_explanation": "BLOCKED; no additional generation or explanation requested"}
    assert review["left_limit"] == review["right_limit"] == "0"
    save(OUT / "independent-math-review.json", review)
    table_diff = {}
    for table in baseline:
        if table not in current or not isinstance(baseline[table], list):
            continue
        original = {str(r.get("id", r.get("kp_id"))): r for r in baseline[table]}
        latest = {str(r.get("id", r.get("kp_id"))): r for r in current[table]}
        table_diff[table] = {"before": len(original), "after": len(latest),
            "new_ids": sorted(latest.keys()-original.keys()), "missing_ids": sorted(original.keys()-latest.keys()),
            "changed_ids": sorted(k for k in original.keys() & latest.keys() if original[k] != latest[k])}
    save(OUT / "database-diff.json", table_diff)
    save(OUT / "database-after-real.json", current)
    for name in ("runtime.json", "loaded-code.json"):
        shutil.copy2(RUN / name, OUT / ("real-" + name))
    sessions = sorted({r["session_id"] for r in journeys if r.get("session_id")})
    text = ["# 本轮真实 Vue 聊天完整记录", "", "真实 DeepSeek 共5次物理请求；未使用Mock。原19次账本保持不变。", ""]
    for sid in sessions:
        session = next(r for r in current["chat_sessions"] if r["id"] == sid)
        text.extend([f"## {session['title']} · {sid}", f"用途：{session.get('purpose')}；模式：{session.get('mode')}", ""])
        for message in sorted((m for m in current["chat_messages"] if m["session_id"] == sid), key=lambda m:m["seq"]):
            text.extend([f"### {message['seq']} · {message['role']} · {message['status']}", message["content"] or "", ""])
    (OUT / "FULL_CHAT_RECORDS.md").write_text("\n".join(text), encoding="utf-8")
    agent = next(f["data"] for f in journeys[0]["frames"] if f["event"] == "planner")
    save(OUT / "agent-final-answer.json", agent)
    quality = {"AGENT": {"engineering": "PASS", "quality": "FAIL", "browser": "PASS",
                    "reason": "3 calls terminate with evidence, but explicit mathematics2 scope narrows to current LHopital leaf; insufficient full90min recommendation"},
               "TEACH": {"engineering": "PASS", "quality": "PASS", "browser": "PASS", "reason": "complete correct conditions and independently checked oscillatory counterexample"},
               "GENERATE": {"engineering": "PASS", "quality": "FAIL", "browser": "PASS", "reason": "1 physical call and confirmed wrong answer rejected;0 new Questions/versions/items"},
               "EXPLAIN": {"engineering": "BLOCKED", "quality": "BLOCKED", "browser": "BLOCKED", "reason": "generated mathematics failed; user explicitly prohibits followup"}}
    save(OUT / "scene-results.json", quality)
    rows = ["# 奶蛙真实 DeepSeek 最小复验结果", "", "总体：PARTIAL。真实数学质量未通过；错误题被成功拦截。", "",
            "## 预算与隔离", "", "本轮实际5/7次：Agent3/4、教学1/1、生成1/1、后续讲解0/1。未用的2次不转移、不补调用。",
            "仅63044/63045/63046，数据库naiwa_experience_test；旧19次账本和原消息/题目/学习记录逐行未变。", "",
            "## 场景结果", "", "|场景|工程|真实回答质量|浏览器|", "|---|---|---|---|"]
    rows += [f"|{s}|{r['engineering']}|{r['quality']}|{r['browser']}|" for s,r in quality.items()]
    rows += ["", "## Agent最终原文", "", agent["message"], "", "问题：当前题上下文优先于用户明确的数学二范围，未形成满意的整体复习安排。未用第4次盲目补答。", "",
             "## 数学核验", "", "生成题：(e^x−1−x−x²/2)/(x−ln(1+x))，x→0。分子x³/6+O(x⁴)，分母x²/2+O(x³)，比值x/3+O(x²)→0。",
             "模型选A=1、final_value=1/2，选项没有0；解析还反复修改题干。质量门以answer_final_value_conflict拒绝保存。后续讲解取消。", "",
             "教学中的x²sin(1/x)/sin(x)→0，可由|sin x|≥|x|/2（充分小x）夹逼；导数比振荡，没有把法则失效误说成原极限不存在。", "",
             "## 实际物理请求", "", "|编号|场景|耗时秒|输入Token|输出Token|finish_reason|", "|---|---|---:|---:|---:|---|"]
    rows += [f"|{r['number']}|{r['case_id']}|{r.get('latency_seconds','未知')}|{r.get('usage',{}).get('prompt_tokens','未知')}|{r.get('usage',{}).get('completion_tokens','未知')}|{r.get('finish_reason','未知')}|" for r in meter.records]
    rows += ["", "## 持久化核对", "", "|表|之前|之后|", "|---|---:|---:|"]
    rows += [f"|{t}|{d['before']}|{d['after']}|" for t,d in table_diff.items()]
    rows += ["", "仅新增测试会话/消息、1个建议任务和1个失败出题批次审计。生成0题，新增版本0，今日卷/作答/学习事件无变化。",
             "QA旧会话仅追加本轮教学，原正文未篡改；study新会话隔离。刷新截图及持久化消息保存于同目录。", "",
             "## 证据入口", "", "- provider-ledger.json：物理请求、脱敏请求/回复全文、usage、耗时及finish_reason。",
             "- FULL_CHAT_RECORDS.md：本轮涉及会话的完整持久化原文，包括旧QA上下文。",
             "- journeys.json：真实Vue发送内容、HTTP/SSE帧、持久化消息、刷新前后可见文本。",
             "- agent-final-answer.json：最终建议与全部工具结果/调用轨迹。",
             "- independent-math-review.json：独立SymPy极限/展开及矛盾核对。",
             "- database-diff.json、database-after-real.json：只读数据库证据。",
             "- counter-selftest.json：零网络硬限额/恢复/异常封闭测试通过。",
             "- AGENT-1.png、TEACH-2.png、GENERATE-4.png及对应-refresh.png：系统Chrome真实界面。", "",
             "本轮只增加验收计数/启动包装/浏览器脚本，不宣称修好了此次发现的Agent范围或真实模型数学错误；未改业务质量门。"]
    (OUT / "REPORT.md").write_text("\n".join(rows), encoding="utf-8")
    print(json.dumps({"physical": len(meter.records), "math_limit": review["left_limit"], "scenes": quality}, ensure_ascii=False))


if __name__ == "__main__":
    main()
