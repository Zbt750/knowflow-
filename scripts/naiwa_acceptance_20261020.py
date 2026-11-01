"""Persistent owned-PG real-browser acceptance; shared 20 physical HTTP cap."""
from pathlib import Path
import argparse
from datetime import datetime, timedelta
import json
import os
import socket
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
HOME = ROOT / "storage/manual-experience/naiwa-real-20261020"
OUT = ROOT / "storage/quality-audits/naiwa-real-20261020"
LIMITS = {"A": 3, "B": 4, "C": 4, "D": 3, "E": 4, "R": 2}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temporary.replace(path)


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        value = sock.getsockname()[1]
    if value <= 18000:
        return port()
    return value


def manager():
    from desktop.postgres import ManagedPostgres
    from desktop.runtime_paths import RuntimePaths
    config = json.loads((HOME / "config.json").read_text(encoding="utf-8"))
    assert config["pg_port"] > 18000 and config["pg_port"] != 5433
    return ManagedPostgres(RuntimePaths.windows(resources=ROOT / "backend", local_app_data=HOME / "owned-pg"),
        Path("C:/Program Files/PostgreSQL/18/bin"), port=config["pg_port"])


def isolated_url(pg):
    from sqlalchemy.engine import make_url
    return make_url(pg.database_url).set(database="naiwa_experience_test").render_as_string(hide_password=False)


def fixture(url):
    from backend.db import create_db_engine, create_session_factory
    from tests.integration.query_followup_backend import prepare_fixture
    from backend.models.learning import DailyPlan, PracticeItem, Question, KnowledgePoint
    from sqlalchemy import select
    engine = create_db_engine(url)
    factory = create_session_factory(engine)
    specs = [
        {"stem": r"【测试来源分类样本，非真实历年题】求 $\lim_{x\to0}\frac{e^x-1-x}{x^2}$。", "options": {"A": "1/2", "B": "1", "C": "0", "D": "不存在"}, "explanation": r"分子分母均趋于0。两次洛必达后为 $e^x/2\to1/2$；也可用泰勒展开独立核对。"},
        {"stem": r"【测试来源分类样本，非真实历年题】求 $\lim_{x\to0}\frac{\sin x}{x}$。", "options": {"A": "1", "B": "0", "C": "2", "D": "不存在"}, "explanation": r"由基本极限为1；洛必达给出 $\cos x\to1$。"},
        {"stem": r"【测试原创题】求 $\lim_{x\to0}\frac{\ln(1+x)-x}{x^2}$。", "options": {"A": "-1/2", "B": "1/2", "C": "0", "D": "1"}, "explanation": r"泰勒展开 $\ln(1+x)=x-x^2/2+O(x^3)$，极限为-1/2。"},
        {"stem": "【未审核测试题，不计入可练数】求一个尚未核验的极限。"},
        {"stem": r"【测试原创题】函数 $f(x)=x^2$ 在 $x=1$ 处的导数是多少？", "options": {"A": "2", "B": "1", "C": "0", "D": "4"}, "explanation": "f'(x)=2x，代入x=1得到2。"},
        {"stem": "【408测试原创题】对顺序表使用二分查找，必须满足什么条件？", "options": {"A": "按关键字有序", "B": "所有元素相同", "C": "采用链式存储", "D": "只能存整数"}, "explanation": "二分查找要求按关键字有序，并支持高效随机访问。"},
    ]
    facts = prepare_fixture(factory, question_specs=specs)
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    with factory.begin() as db:
        old = db.scalar(select(DailyPlan))
        old.study_date = (now.date() - timedelta(days=1)).isoformat()
        for item in db.scalars(select(PracticeItem)):
            item.completed_at = now - timedelta(hours=12)
        today = DailyPlan(study_date=now.date().isoformat(), status="active")
        db.add(today); db.flush()
        from uuid import UUID
        for index in (0, 2, 5):
            q = db.get(Question, UUID(facts["question_ids"][index]))
            item = PracticeItem(plan_id=today.id, question_id=q.id, kp_id=q.kp_id, ordinal=(0,2,5).index(index)+1)
            db.add(item); db.flush()
            if index == 0:
                facts.update(current_question_id=str(q.id), current_version_id=str(q.current_version_id), current_item_id=str(item.id))
        node = db.get(KnowledgePoint, UUID(facts["lhopital_id"]))
        node.code = "math.calculus.limit.lhopital"
        facts["today_plan_id"] = str(today.id)
    # Zero-model setup only: an explicitly marked personal deterministic sample.
    from backend.schemas.personal_questions import PersonalGenerationRequest, GenerationTarget
    from backend.services.personal_question_service import run_generation
    from uuid import UUID, uuid4
    try:
        result = run_generation(factory, PersonalGenerationRequest(request_key=uuid4(), generation_mode="deterministic_fast",
            targets=[GenerationTarget(kp_id=UUID(facts["lhopital_id"]), count=1)], surface="chat"), now=now)
        facts["setup_personal_question"] = result
    except Exception as exc:
        facts["setup_personal_question_blocker"] = type(exc).__name__
    save(OUT / "fixture.json", facts)
    engine.dispose()


def app():
    from backend.config import get_settings
    from backend.chat.service import Provider
    from backend.app import create_app
    from backend.errors import AppError
    from scripts.phase5_eval_meter import Meter, BudgetStop
    from sqlalchemy.engine import make_url
    settings = get_settings()
    url = make_url(str(settings.active_database_url))
    assert settings.app_env == "test" and url.database == "naiwa_experience_test" and url.port > 18000
    assert settings.llm_model == "deepseek-flash" and settings.llm_base_url.rstrip("/") == "https://api.deepseek.com"
    meter = Meter(OUT, max_requests=20, max_input_tokens=1000000, max_output_tokens=240000, stop_cny="4.50")
    if (OUT / "provider-ledger.json").exists():
        previous = json.loads((OUT / "provider-ledger.json").read_text(encoding="utf-8"))
        assert previous["limits"]["max_requests"] == 20
        meter.records = previous["requests"]; meter.stop_reason = previous["stop_reason"]
    original_begin = meter.begin
    def guarded_begin(request):
        control = json.loads((HOME / "control.json").read_text(encoding="utf-8"))
        case = str(meter.case_id or "")
        if not control.get("paid_enabled"):
            with (OUT / "blocked-before-send.jsonl").open("a", encoding="utf-8") as log:
                log.write(json.dumps({"case": case, "reason": "paid_disabled", "time": time.time()})+"\n")
            raise BudgetStop("paid_disabled_zero_regression_or_sealed")
        group = case[:1]
        if group not in LIMITS or sum(r.get("case_id", "").startswith(group) for r in meter.records) >= LIMITS[group]:
            raise BudgetStop("scenario_physical_request_cap")
        record = original_begin(request)
        if record:
            record["stage"] = ("classifier" if record["output_limit"] == 48 else
                "agent" if group == "E" else "generation" if group == "C" and request.content.find(b'response_format') >= 0 else "qa")
            meter.flush()
        return record
    meter.begin = guarded_begin
    meter.install(); meter.flush()
    complete, stream, tool = Provider.complete, Provider.stream, Provider.tool_turn
    def once_complete(self, messages, *, attempt=1):
        if attempt != 1:
            raise AppError("generation_failed", detail="acceptance_auto_retry_disabled", retryable=False)
        return complete(self, messages, attempt=attempt)
    async def once_stream(self, messages, *, attempt=1):
        if attempt != 1:
            raise AppError("generation_failed", detail="acceptance_auto_retry_disabled", retryable=False)
        async for delta in stream(self, messages, attempt=attempt):
            yield delta
    def once_tool(self, *args, **kwargs):
        try:
            return tool(self, *args, **kwargs)
        except AppError as exc:
            exc.retryable = False
            raise
    Provider.complete, Provider.stream, Provider.tool_turn = once_complete, once_stream, once_tool
    application = create_app()
    @application.middleware("http")
    async def scoped(request, call_next):
        if request.method == "POST" and request.url.path.endswith(("/assistant:stream", "/answers:stream")):
            meter.case_id = request.headers.get("x-acceptance-case", "MANUAL-READONLY")
        response = await call_next(request)
        response.headers["X-Naiwa-Experience"] = "persistent-real-budget20"
        return response
    return application


def serve():
    import httpx
    from sqlalchemy.engine import make_url
    from backend.config import get_settings
    from backend.services.model_settings_service import load_local_settings
    from psycopg import sql
    effective = load_local_settings(get_settings())  # Local config only; no dev DB connection.
    assert effective.llm_api_key and effective.llm_model == "deepseek-flash"
    config = json.loads((HOME / "config.json").read_text(encoding="utf-8"))
    pg = manager(); children=[]; logs=[]
    try:
        pg.start()
        with pg._connect() as connection:
            if not connection.execute("SELECT 1 FROM pg_database WHERE datname=%s", ("naiwa_experience_test",)).fetchone():
                from desktop.postgres import APP_USER
                connection.execute(sql.SQL("CREATE DATABASE {} OWNER {} TEMPLATE template0 ENCODING 'UTF8'").format(
                    sql.Identifier("naiwa_experience_test"), sql.Identifier(APP_USER)))
        url = isolated_url(pg)
        env = {**os.environ, "APP_ENV":"test", "DATABASE_URL":url, "TEST_DATABASE_URL":url,
            "KAOYAN_OWNED_TEST_PORT":str(pg.port), "PHASE45E_OWNED_TEST_PORT":str(pg.port),
            "LLM_API_KEY":effective.llm_api_key.get_secret_value(), "LLM_BASE_URL":effective.llm_base_url,
            "LLM_MODEL":effective.llm_model, "LLM_STREAM_INCLUDE_USAGE":"true", "PYTHONIOENCODING":"utf-8",
            "MODEL_SETTINGS_PATH":str(HOME / "model-settings.bin"), "UPLOAD_DIR":str(HOME / "uploads"),
            "CHROMA_DIR":str(HOME / "chroma"), "MODEL_CACHE_DIR":str(ROOT / "storage/models"),
            "HF_HUB_OFFLINE":"1", "TRANSFORMERS_OFFLINE":"1", "ANONYMIZED_TELEMETRY":"False",
            "ALLOWED_WEB_ORIGINS":json.dumps([f"http://127.0.0.1:{config['web_port']}"]),
            "VITE_API_PROXY_TARGET":f"http://127.0.0.1:{config['api_port']}"}
        if not (HOME / "initialized.json").exists():
            with (OUT / "migration.log").open("w", encoding="utf-8") as log:
                subprocess.run([sys.executable,"-m","alembic","upgrade","head"], cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
            fixture_env = {**env, "NAIWA_PREPARE_URL":url}
            subprocess.run([sys.executable,str(Path(__file__)),"prepare"],cwd=ROOT,env=fixture_env,check=True)
            save(HOME / "initialized.json", {"database":"naiwa_experience_test", "synthetic_test_data":True})
        commands = [[sys.executable,"-m","uvicorn","scripts.naiwa_acceptance_20261020:app","--factory","--host","127.0.0.1","--port",str(config["api_port"])],
            ["node","node_modules/vite/bin/vite.js","--host","127.0.0.1","--port",str(config["web_port"]),"--strictPort"]]
        for name, command, cwd in zip(("backend","frontend"),commands,(ROOT,ROOT/"frontend")):
            log=(OUT / (name+".log")).open("a",encoding="utf-8"); logs.append(log)
            children.append(subprocess.Popen(command,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW))
        runtime={**config,"workspace":str(ROOT),"supervisor_pid":os.getpid(),"backend_pid":children[0].pid,
            "frontend_pid":children[1].pid,"postgres_pid":pg._identity()[0],"cluster":str(pg.cluster),"cluster_id":pg.owner["cluster_id"],
            "database":"naiwa_experience_test","api_url":f"http://127.0.0.1:{config['api_port']}",
            "frontend_url":f"http://127.0.0.1:{config['web_port']}","commands":commands,"status":"starting","data_retained":True}
        import hashlib
        runtime["source_sha256"]={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
            ("backend/chat/service.py", "backend/services/assistant_data_queries.py",
             "backend/services/learning_assistant_service.py", "backend/services/learning_task_service.py",
             "backend/services/personal_generation_intent.py", "backend/services/personal_question_general.py",
             "backend/services/personal_question_service.py", "backend/services/generation_formula_consistency.py",
             "backend/services/question_generation.py")}
        save(HOME / "runtime.json",runtime)
        for _ in range(150):
            assert all(p.poll() is None for p in children), "isolated_child_exited"
            try:
                health=httpx.get(runtime["frontend_url"]+"/api/health",timeout=3,trust_env=False)
                if health.status_code==200 and health.json().get("database")=="connected":
                    runtime.update(status="running",health=health.json());save(HOME/"runtime.json",runtime);break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        else:
            raise RuntimeError("isolated_startup_timeout")
        while not (HOME/"stop.request").exists():
            assert all(p.poll() is None for p in children), "isolated_child_exited"
            time.sleep(1)
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate();child.wait(timeout=25)
        for log in logs:log.close()
        pg.stop()
        if (HOME/"runtime.json").exists():
            state=json.loads((HOME/"runtime.json").read_text(encoding="utf-8"));state["status"]="stopped";save(HOME/"runtime.json",state)


def main():
    action=argparse.ArgumentParser();action.add_argument("action",choices=["start","serve","status","stop","enable-paid","seal","prepare","snapshot"])
    args=action.parse_args()
    if args.action=="prepare":return fixture(os.environ["NAIWA_PREPARE_URL"])
    HOME.mkdir(parents=True,exist_ok=True);OUT.mkdir(parents=True,exist_ok=True)
    if args.action=="snapshot":
        from sqlalchemy import create_engine, text
        pg=manager();pg._load_owner();pg._load_passwords()
        engine=create_engine(isolated_url(pg))
        with engine.connect() as conn:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            data={name:[dict(row._mapping) for row in conn.execute(text("SELECT * FROM "+name))] for name in
                ("chat_sessions","chat_messages","questions","question_versions","daily_plans","practice_items",
                 "question_attempts","learning_events","learning_tasks","personal_generation_batches","materials","document_chunks","message_citations","kp_states")}
            data["identity"]=dict(conn.execute(text("SELECT current_database() db,current_user role,current_setting('port') port")).one()._mapping)
        engine.dispose();save(OUT/"database-latest.json",data);print("Owned database snapshot saved");return
    if args.action=="serve":return serve()
    if args.action=="status":print((HOME/"runtime.json").read_text(encoding="utf-8"));return
    if args.action=="stop":(HOME/"stop.request").touch();print("Only this experience environment will stop; all data retained.");return
    if args.action in {"enable-paid","seal"}:
        if args.action=="enable-paid":
            zero=json.loads((OUT/"zero-results.json").read_text(encoding="utf-8"))
            assert zero["status"]=="PASS" and zero["physical_requests"]==0
        save(HOME/"control.json",{"paid_enabled":args.action=="enable-paid","total_limit":20,"groups":LIMITS})
        print(args.action);return
    if not (HOME/"config.json").exists():
        save(HOME/"config.json",{"pg_port":port(),"api_port":port(),"web_port":port()})
        save(HOME/"control.json",{"paid_enabled":False,"total_limit":20,"groups":LIMITS})
    config=json.loads((HOME/"config.json").read_text(encoding="utf-8"))
    for value in config.values():
        with socket.socket() as sock:sock.bind(("127.0.0.1",value))
    (HOME/"stop.request").unlink(missing_ok=True)
    with (OUT/"supervisor.log").open("a",encoding="utf-8") as log:
        child=subprocess.Popen([sys.executable,str(Path(__file__)),"serve"],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
    print(json.dumps({"supervisor_pid":child.pid,"frontend_url":f"http://127.0.0.1:{config['web_port']}","paid_enabled":False}))


if __name__=="__main__":main()
