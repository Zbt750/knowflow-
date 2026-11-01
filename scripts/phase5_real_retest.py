"""Independent authorized rerun of unchanged phase5-closeout-v1 cases.

Reuses the frozen evaluator's production API and fixture helpers. No requests
are sent by --prepare. --execute consumes only this run's approved budget.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import phase5_run_frozen_ai_eval as prior

REQUEST = ROOT / "eval/phase5-retest-v1/execution-request.json"
CONFIG = json.loads(REQUEST.read_text(encoding="utf-8"))
OUT = ROOT / CONFIG["evidence_output"]
BASE = "phase5_final_retest_base_20261015_test"
QA = "phase5_final_retest_qa_20261015_test"
DATA = prior.DATA
OLD_OUT = prior.OUT


def case_db(case):
    return QA if case["track"] == "qa" else f"phase5_final_retest_{case['id'].lower()}_20261015_test"


def verify():
    marker = prior.verify()
    for name, key in (("cases.json", "cases_sha256"), ("fixtures.json", "fixtures_sha256"), ("rubric.md", "rubric_sha256")):
        assert hashlib.sha256((DATA/name).read_bytes()).hexdigest() == CONFIG[key]
    return marker


def setup_helpers():
    prior.BASE, prior.OUT = BASE, OUT


def prepare():
    marker = verify()
    assert not OUT.exists(), "A new run must never overwrite existing evidence"
    OUT.mkdir(parents=True)
    prior.write(OUT/"authorization.json", {"source":"user explicit approval of 2026-10-15 proposal",
        "approved_at":datetime.now(timezone.utc), "request_sha256":hashlib.sha256(REQUEST.read_bytes()).hexdigest(),
        "limits":CONFIG["proposed_limits_requiring_authorization"], "owner":marker})
    prior.clone(BASE)
    setup_helpers()
    settings = prior.configure(BASE)
    env = dict(os.environ)
    migration = subprocess.run([sys.executable,"-m","alembic","upgrade","head"],cwd=ROOT,env=env,capture_output=True,text=True)
    (OUT/"isolated-migration.log").write_text(migration.stdout+ migration.stderr,encoding="utf-8")
    assert migration.returncode == 0
    for name in ("test-chroma", "test-uploads"):
        src=OLD_OUT/name
        if src.exists(): shutil.copytree(src,OUT/name)
    shutil.copy2(OLD_OUT/"materials-ready.json",OUT/"materials-ready.json")
    from sqlalchemy import select,text
    from backend.db import create_db_engine,create_session_factory
    from backend.models.learning import KnowledgePoint,Question,KpState,QuestionAttempt
    from backend.services.question_eligibility import question_eligibility
    now=datetime.now(timezone.utc).replace(microsecond=0)
    cases=json.loads((DATA/"cases.json").read_text(encoding="utf-8"))
    by_id={c["id"]:c for c in cases["cases"]}
    engine=create_db_engine(prior.url(BASE))
    with create_session_factory(engine)() as db:
        assert all(db.scalar(text(f'SELECT count(*) FROM "{t}"'))==0 for t in ("question_attempts","learning_events","daily_plans","practice_items"))
        assert db.scalar(text("SELECT count(*) FROM questions WHERE bank_scope='personal'"))==0
        revision=db.scalar(text("SELECT version_num FROM alembic_version"))
    engine.dispose()
    prior.clone(QA)
    rows=[]
    for cid in CONFIG["execution_order"]:
        case=by_id[cid]
        row={"id":cid,"database":case_db(case),"status":"READY"}
        if case["track"]=="qa":
            rows.append(row); continue
        if cid=="A07":
            row.update(status="FIXTURE_BLOCKED",reason="Frozen fixture requires AI-reference-answer history; local server_generated provenance cannot substitute.")
            rows.append(row); continue
        prior.clone(row["database"])
        prior.configure(row["database"])
        engine=create_db_engine(prior.url(row["database"]))
        factory=create_session_factory(engine)
        try:
            with factory() as db:
                node=db.scalar(select(KnowledgePoint).where(KnowledgePoint.code==cases["node_keys"][case["node"]]))
                assert node is not None
                node_id=node.id
            if case["profile"]=="fresh_ieee_no_inventory":
                with factory.begin() as db:
                    for q in db.scalars(select(Question).where(Question.kp_id==node_id)):
                        q.is_active=False
                with factory() as db:
                    assert not any(question_eligibility(q,db.get(KnowledgePoint,node_id)).practice_eligible for q in db.scalars(select(Question).where(Question.kp_id==node_id)))
            prior.seed_profile(factory,case,node_id,now)
            truth=prior.learner_truth(factory,node_id)
            row.update(node_id=str(node_id),subject=node.subject,truth=truth)
            with factory() as db:
                personal=list(db.scalars(select(Question).where(Question.bank_scope=="personal")))
                if personal:
                    assert all(question_eligibility(q,db.get(KnowledgePoint,q.kp_id)).evidence_capability != "verified_objective" for q in personal)
        except Exception as exc:
            row.update(status="FIXTURE_BLOCKED",reason=str(exc)[:1500],error_type=type(exc).__name__)
        finally: engine.dispose()
        rows.append(row)
        print(json.dumps({"fixture":cid,"status":row["status"],"reason":row.get("reason")},ensure_ascii=False),flush=True)
    prior.write(OUT/"fixture-preflight.json",{"clock":now,"revision":revision,"cases":rows,"provider_requests":0})


def execute():
    verify()
    assert not (OUT/"provider-ledger.json").exists(), "Never replay a paid run"
    authorization=json.loads((OUT/"authorization.json").read_text(encoding="utf-8"))
    assert authorization["request_sha256"]==hashlib.sha256(REQUEST.read_bytes()).hexdigest()
    preflight=json.loads((OUT/"fixture-preflight.json").read_text(encoding="utf-8"))
    by_fixture={r["id"]:r for r in preflight["cases"]}
    setup_helpers()
    from backend.services.model_settings_service import load_local_settings
    settings=load_local_settings(prior.configure(BASE))
    assert settings.llm_model=="deepseek-flash" and settings.llm_base_url.rstrip("/")=="https://api.deepseek.com"
    assert settings.llm_stream_include_usage
    retrieval=prior.stack(settings)
    from backend.db import create_db_engine,create_session_factory
    from sqlalchemy import select
    from backend.models.learning import KnowledgePoint
    from backend.models.chat import ChatMessage
    from backend.models.learning_task import LearningTask
    from backend.api.deps import get_time_provider
    from backend.app import create_app
    from backend.services.personal_generation_intent import explicitly_generate
    from fastapi.testclient import TestClient
    from scripts.phase5_eval_meter import Meter
    engine=create_db_engine(prior.url(BASE))
    with create_session_factory(engine)() as db: retrieval.rebuild_keyword_index(db)
    engine.dispose()
    cases=json.loads((DATA/"cases.json").read_text(encoding="utf-8"))
    by_id={c["id"]:c for c in cases["cases"]}
    materials=json.loads((OUT/"materials-ready.json").read_text(encoding="utf-8"))
    now=datetime.fromisoformat(preflight["clock"])
    files=[Path(__file__),ROOT/"scripts/phase5_eval_meter.py",ROOT/"scripts/phase5_run_frozen_ai_eval.py",
        ROOT/"backend/chat/service.py",ROOT/"backend/services/assistant_router.py",ROOT/"backend/services/learning_task_service.py",
        ROOT/"backend/services/learning_task_tools.py",ROOT/"backend/services/personal_generation_intent.py"]
    versions={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    prior.write(OUT/"runtime-version.json",{"clock":now,"model":settings.llm_model,"endpoint":settings.llm_base_url,
        "runtime_sha256":versions,"source_dataset":str(DATA),"cases_sha256":CONFIG["cases_sha256"],"fixture_sha256":CONFIG["fixtures_sha256"]})
    meter=Meter(OUT,max_requests=160)
    results=[];sessions={}
    meter.install()
    try:
        for cid in CONFIG["execution_order"]:
            assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==sha for p,sha in versions.items()), "Runtime changed during paid evaluation"
            case=by_id[cid]; fixture=by_fixture[cid]
            directory=OUT/cid;directory.mkdir()
            row={"id":cid,"track":case["track"],"input":case["input"],"quality_score":None,"provider_requests":0}
            if meter.stop_reason or fixture["status"]!="READY":
                row.update(status="BUDGET_STOPPED" if meter.stop_reason else "FIXTURE_BLOCKED",reason=meter.stop_reason or fixture.get("reason"))
                results.append(row);prior.write(directory/"result.json",row);continue
            if case["track"]=="agent" and explicitly_generate(case["input"]):
                meter.stop_reason="unexpected_generation_intent"
                row.update(status="BLOCKED_UNEXPECTED_GENERATION_INTENT")
                results.append(row);prior.write(directory/"result.json",row);continue
            current_settings=load_local_settings(prior.configure(fixture["database"]))
            engine=create_db_engine(prior.url(fixture["database"]));factory=create_session_factory(engine)
            client=None; start=len(meter.records)
            try:
                with factory() as db:
                    node=db.scalar(select(KnowledgePoint).where(KnowledgePoint.code==cases["node_keys"][case["node"]])) if case.get("node") else None
                    node_id=node.id if node else None;subject=node.subject if node else None
                truth=prior.learner_truth(factory,node_id) if case["track"]=="agent" else None
                if truth: prior.write(directory/"truth-before.json",truth)
                app=create_app();app.state.settings=current_settings;app.state.engine=engine
                app.state.session_factory=factory;app.state.retrieval_stack=retrieval;app.state.job_runner=None
                app.dependency_overrides[get_time_provider]=lambda:lambda:now
                client=TestClient(app,base_url="http://127.0.0.1",raise_server_exceptions=False)
                key=case.get("session_key",cid)
                if key not in sessions:
                    body={"title":"Phase5 retest "+key,"mode":case.get("mode","builtin"),
                        "purpose":"study" if case["track"]=="agent" else "materials" if case.get("mode")=="user" else "qa",
                        "material_scope_ids":[materials["materials"][k]["id"] for k in case.get("material_scope",[])]}
                    response=client.post("/api/chat/sessions",json=body)
                    assert response.status_code==201,response.text
                    sessions[key]=response.json()["session_id"]
                sid=sessions[key]
                context={"surface":"study" if case["track"]=="agent" else "chat","knowledge_node_ids":[str(node_id)] if node_id else [],"subject":subject}
                if case["track"]=="agent" and type(case.get("budget_minutes")) is int:
                    from backend.services.learning_task_service import create_task
                    from backend.schemas.learning_task import CreateTask
                    task=create_task(factory,CreateTask(goal=case["input"],budget_minutes=case["budget_minutes"],session_id=UUID(sid)),now=now)
                    context["task_id"]=str(task.task_id)
                request={"question":case["input"],"qa_action":"auto","request_key":str(uuid4()),"study_context":context}
                prior.write(directory/"business-request.json",{"session_id":sid,"body":request,"test_database":fixture["database"]})
                meter.case_id=cid; started=time.monotonic()
                response=client.post(f"/api/chat/sessions/{sid}/assistant:stream",json=request)
                row.update(http_status=response.status_code,latency_seconds=round(time.monotonic()-started,3),provider_requests=len(meter.records)-start)
                (directory/"response.sse").write_text(response.text,encoding="utf-8")
                prior.write(directory/"events.json",prior.parse_events(response.text))
                prior.write(directory/"restored-history.json",client.get(f"/api/chat/sessions/{sid}/messages").json())
                with factory() as db:
                    messages=list(db.scalars(select(ChatMessage).where(ChatMessage.session_id==UUID(sid),ChatMessage.role=="assistant").order_by(ChatMessage.seq)))
                    last=messages[-1] if messages else None
                    row.update(status=last.status.upper() if last else "NO_SAVED_ANSWER",answer=last.content if last else None,metadata=last.metadata_ if last else None)
                    tid=(last.metadata_ or {}).get("planner_task_id") if last else None
                    if tid:
                        task=db.get(LearningTask,UUID(tid))
                        prior.write(directory/"agent-task.json",{c.name:getattr(task,c.key) for c in task.__table__.columns})
                if truth:
                    after=prior.learner_truth(factory,node_id);prior.write(directory/"truth-after.json",after)
                    row["learning_state_unchanged"]=truth["state"]==after["state"] and truth["counts"]==after["counts"]
                    if not row["learning_state_unchanged"]:meter.stop_reason="unexpected_learning_mutation_stop"
            except Exception as exc:
                row.update(status="API_OR_PROVIDER_ERROR",reason=str(exc)[:1500],error_type=type(exc).__name__,provider_requests=len(meter.records)-start)
            finally:
                if client:client.close()
                engine.dispose()
            row["model_called"]=row["provider_requests"]>0
            results.append(row);prior.write(directory/"result.json",row)
            prior.write(OUT/"case-results.json",{"results":results,"meter":meter.summary(),"stop_reason":meter.stop_reason})
            print(json.dumps({"id":cid,"status":row["status"],"calls":row["provider_requests"],"total_calls":len(meter.records),"cost":meter.summary()["peak_uncached_cost_upper_estimate_cny"],"stop":meter.stop_reason}),flush=True)
    finally:
        meter.uninstall();meter.flush()
        prior.write(OUT/"case-results.json",{"results":results,"meter":meter.summary(),"stop_reason":meter.stop_reason})


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prepare",action="store_true")
    group.add_argument("--execute",action="store_true")
    args=parser.parse_args()
    prepare() if args.prepare else execute()
