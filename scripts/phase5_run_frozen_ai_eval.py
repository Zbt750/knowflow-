"""Run the approved frozen 40 business turns through the real assistant API.

Only port 59271 owned test DBs, synthetic materials/history, official Provider.
No paid judge, no extra cases, no replay of an already sent case.
"""
from __future__ import annotations
import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from uuid import UUID, uuid4
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "storage/quality-audits/phase5-closeout-execution-20261015/ai-test"
DATA = ROOT / "eval/phase5-closeout-v1"
PORT = 59271
BASE = "phase5_closeout_base_test"


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def url(name):
    assert name.endswith("_test") and name != "kaoyan"
    return f"postgresql+psycopg://postgres@127.0.0.1:{PORT}/{name}"


def configure(name):
    os.environ.update(APP_ENV="test", DATABASE_URL=url(name), TEST_DATABASE_URL=url(name),
        KAOYAN_OWNED_TEST_PORT=str(PORT), UPLOAD_DIR=str(OUT / "test-uploads"), CHROMA_DIR=str(OUT / "test-chroma"),
        HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", ANONYMIZED_TELEMETRY="False", LLM_STREAM_INCLUDE_USAGE="true")
    from backend.config import get_settings
    get_settings.cache_clear()
    return get_settings()


def verify():
    import psycopg
    marker = json.loads((OUT / "owner.json").read_text(encoding="utf-8"))
    assert marker["port"] == PORT and marker["owner"] == "phase5-closeout-authorized-eval-v1"
    with psycopg.connect(host="127.0.0.1", port=PORT, dbname="postgres", user="postgres", connect_timeout=5, options="-c default_transaction_read_only=on") as c:
        assert c.execute("SELECT system_identifier::text FROM pg_control_system()").fetchone()[0] == marker["system_identifier"] != "7686825087296682120"
    previous = json.loads((ROOT / "storage/quality-audits/phase5-closeout-preparation-20261015-v2/preparation.json").read_text(encoding="utf-8"))
    for name, sha in previous["frozen_file_sha256"].items():
        if name.startswith("eval/phase5-closeout-v1/"):
            assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha, name
    return marker


def stack(settings):
    from backend.retrieval.stack import build_retrieval_stack
    result = build_retrieval_stack(embedding_model=settings.embedding_model, reranker_model=settings.reranker_model,
        chroma_dir=settings.chroma_dir, model_cache_dir=settings.model_cache_dir)
    assert result.available
    return result


def prepare():
    verify()
    assert not (OUT / "materials-ready.json").exists(), "Preserve prepared baseline"
    settings = configure(BASE)
    from backend.db import create_db_engine, create_session_factory
    from backend.models.learning import KpState, KpMasteryPolicy
    from sqlalchemy import select, text
    from backend.models.rag import Material, DocumentChunk
    from scripts.prepare_e2e_data import ingest_bytes
    retrieval = stack(settings)
    engine = create_db_engine(url(BASE))
    factory = create_session_factory(engine)
    with factory.begin() as db:
        assert db.scalar(text("SELECT count(*) FROM materials")) == 0
        for p in db.scalars(select(KpMasteryPolicy)):
            db.add(KpState(kp_id=p.kp_id))
    fixture = json.loads((DATA / "fixtures.json").read_text(encoding="utf-8"))
    materials = {}
    for spec in fixture["materials"]:
        with factory.begin() as db:
            chunks = ingest_bytes(db, title=spec["title"], filename=Path(spec["file"]).name,
                data=(DATA / spec["file"]).read_bytes(), source_type=spec["source_type"], root=settings.upload_dir,
                embedder=retrieval.embedder, vector_store=retrieval.vector_store)
            m = db.scalar(select(Material).where(Material.title == spec["title"]))
            materials[spec["key"]] = {"id": str(m.id), "chunks": chunks, "index_version": m.active_index_version,
                "content_hash": m.content_hash, "title": m.title}
    with factory() as db:
        retrieval.rebuild_keyword_index(db)
        chunks = [{"id": str(c.id), "material_id": str(c.material_id), "index_version": c.index_version,
                   "ordinal": c.ordinal, "heading_path": c.heading_path, "content": c.content} for c in db.scalars(select(DocumentChunk))]
        assert db.scalar(text("SELECT count(*) FROM question_attempts")) == 0
        assert db.scalar(text("SELECT count(*) FROM learning_events")) == 0
    write(OUT / "materials-ready.json", {"materials": materials, "chunks": chunks,
        "ingestion_method": "production save_upload_streaming/parse/chunk/build_index/activate services; not browser upload acceptance", "local_embedding": settings.embedding_model})
    engine.dispose()
    print(json.dumps({"status": "ISOLATED_MATERIALS_READY", "materials": len(materials), "chunks": len(chunks), "model_calls": 0}))


def clone(name):
    import psycopg
    from psycopg import sql
    with psycopg.connect(host="127.0.0.1", port=PORT, user="postgres", dbname="postgres", autocommit=True, connect_timeout=5) as c:
        assert c.execute("SELECT 1 FROM pg_database WHERE datname=%s", (name,)).fetchone() is None, "Never overwrite an existing case database"
        c.execute(sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(sql.Identifier(name), sql.Identifier(BASE)))


def learner_truth(factory, node_id):
    from sqlalchemy import text, select
    from backend.models.learning import KpState, QuestionAttempt, LearningEvent, KnowledgePoint
    from backend.services.learning_task_tools import TaskTools
    from backend.services.capability_service import read_capability_profile
    with factory() as db:
        state = db.get(KpState, node_id)
        result = {"state": {c.name: getattr(state, c.name) for c in state.__table__.columns},
            "attempts": [{"id": str(a.id), "question_id": str(a.question_id), "question_version_id": str(a.question_version_id),
                          "submitted_at": a.submitted_at, "result": a.objective_result, "evidence": a.grading_evidence}
                         for a in db.scalars(select(QuestionAttempt).where(QuestionAttempt.kp_id == node_id).order_by(QuestionAttempt.submitted_at, QuestionAttempt.id))],
            "counts": {t: db.scalar(text(f'SELECT count(*) FROM "{t}"')) for t in ("daily_plans", "practice_items", "question_attempts", "learning_events", "kp_states")}}
        profile = read_capability_profile(db, db.get(KnowledgePoint, node_id))
        result["capability_profile"] = profile.model_dump(mode="json") if profile else None
    return result


def seed_profile(factory, case, node_id, now):
    from sqlalchemy import select
    from backend.models.learning import Question, KpMasteryPolicy, KpState, DailyPlan, PracticeItem
    from backend.mastery.storage import policy_for_node
    from backend.services.answer_submission_service import submit_answer, record_answer_reveal
    from backend.services.practice_service import append_questions_to_plan
    from backend.services.question_eligibility import question_eligibility
    from backend.models.learning import KnowledgePoint
    profile = case["profile"]
    with factory() as db:
        p = db.get(KpMasteryPolicy, node_id)
        qids = sorted(p.graduation_question_ids)
        assert qids
        questions = [db.get(Question, UUID(qid)) for qid in qids]
        assert all(question_eligibility(q, db.get(KnowledgePoint, node_id)).evidence_capability == "verified_objective" for q in questions)
    if profile.startswith("fresh") or profile == "self_report_derivative":
        return
    with factory.begin() as db:
        policy_for_node(db, node_id, bind_if_unset=True, now=now-timedelta(days=5))

    def attempt(qid, day, right, item_id=None, reveal=False):
        moment = now + timedelta(days=day)
        with factory.begin() as db:
            q = db.get(Question, UUID(str(qid)))
            if item_id is None:
                date = moment.astimezone(timezone(timedelta(hours=8))).date().isoformat()
                plan = db.scalar(select(DailyPlan).where(DailyPlan.study_date == date))
                if plan is None:
                    plan = DailyPlan(study_date=date, status="active")
                    db.add(plan); db.flush()
                append_questions_to_plan(db, plan_id=plan.id, question_ids=[q.id])
                db.flush()
                item = db.scalar(select(PracticeItem).where(PracticeItem.plan_id == plan.id, PracticeItem.question_id == q.id))
            else:
                item = db.get(PracticeItem, item_id)
            if reveal:
                record_answer_reveal(db, item_id=item.id, now=moment-timedelta(seconds=1))
            answer = q.correct_answer if right else next((k for k in (q.options or {}) if k != q.correct_answer), "987654321")
            old = db.scalar(select(__import__('backend.models.learning', fromlist=['QuestionAttempt']).QuestionAttempt).where(
                __import__('backend.models.learning', fromlist=['QuestionAttempt']).QuestionAttempt.practice_item_id == item.id).order_by(
                __import__('backend.models.learning', fromlist=['QuestionAttempt']).QuestionAttempt.submitted_at.desc()).limit(1))
            response = submit_answer(db, item_id=item.id, raw_answer=answer if q.question_type != "single_choice" else None,
                selected_option=answer if q.question_type == "single_choice" else None, idempotency_key="TEST_FIXTURE:"+uuid4().hex,
                now=moment, expected_previous_attempt_id=old.id if old else None)
            assert response.result == ("right" if right else "wrong"), (qid, response.model_dump())
            return item.id

    def personal_fixtures(count, day):
        # Use the existing local deterministic production path and its actual
        # node/type registry. A fixture failure must never be repaired by
        # inventing an AI call, review event, receipt, or graduation record.
        from backend.services.personal_question_service import run_generation
        from backend.schemas.personal_questions import PersonalGenerationRequest, GenerationTarget
        from backend.services.personal_question_families import resolve_family
        with factory() as db:
            node=db.get(KnowledgePoint,node_id)
            types=[kind for kind in ("fill_blank","single_choice") if resolve_family(node.code,kind)]
        if not types:
            raise ValueError("FIXTURE_BLOCKED: no registered deterministic personal-question type for this node")
        outcomes=[]
        for kind in types:
            body = PersonalGenerationRequest(request_key=uuid4(), generation_mode="deterministic_fast", surface="chat",
                targets=[GenerationTarget(kp_id=node_id, count=count, question_type=kind)])
            result = run_generation(factory, body, None, now=now+timedelta(days=day))
            assert not result.get("calls"), "fixture must not call a Provider"
            ids = result.get("question_ids", [])
            if len(ids)==count:
                return ids
            outcomes.append({"question_type":kind,"status":result.get("status"),
                "provider_error":result.get("provider_error"),"failure_count":len(result.get("failures",[]))})
        raise ValueError(f"FIXTURE_BLOCKED: local deterministic generation yielded no verified item; outcomes={outcomes}")

    if profile == "reference_only_binary_search":
        # This local item is server-generated/unverified, not mislabelled as an
        # AI response. It supplies a low-trust personal-answer observation only.
        personal=personal_fixtures(1,-2)
        attempt(personal[0],-2,False)
        return

    if profile in {"weak_integral", "weak_replacement", "claimed_mastered_integral_wrong"}:
        for i in range(2): attempt(qids[i], i-2, False)
    elif profile == "recent_wrong_limit":
        assert len(qids) >= 3
        for i in range(3): attempt(qids[i], i-2, False)
    elif profile == "repeated_same_replacement":
        for i in range(3): attempt(qids[0], i-2, False)
    elif profile == "corrected_encoding":
        attempt(qids[0], -2, False); attempt(qids[0], -1, True)
    elif profile in {"solution_integral", "delayed_independent_determinant"}:
        day = -2 if profile.startswith("delayed") else 0
        item = attempt(qids[0], day, False)
        attempt(qids[0], day, True, item_id=item, reveal=True)
        if profile.startswith("delayed"): attempt(qids[0], -1, True)
    elif profile == "hint_tree":
        # Actual recorded assistance service needs an existing message, without a model call.
        from backend.models.chat import ChatSession, ChatMessage
        from backend.schemas.learning_assistant import StudyContext
        from backend.services.learning_qa_service import record_qa_assistance
        with factory.begin() as db:
            plan = DailyPlan(study_date=now.date().isoformat(), status="active"); db.add(plan); db.flush()
            append_questions_to_plan(db, plan_id=plan.id, question_ids=[UUID(qids[0])])
            db.flush()
            item = db.scalar(select(PracticeItem).where(PracticeItem.plan_id == plan.id))
            session = ChatSession(title="TEST_FIXTURE prior hint", mode="builtin", purpose="study")
            db.add(session); db.flush()
            message = ChatMessage(session_id=session.id, role="assistant", content="TEST_FIXTURE recorded assistance, not a model result", status="completed")
            db.add(message); db.flush()
            record_qa_assistance(db, context=StudyContext(question_id=UUID(qids[0]), practice_item_id=item.id, conversation_id=session.id),
                message_id=message.id, level="hint_1", now=now-timedelta(seconds=1))
            item_id = item.id
        attempt(qids[0], 0, True, item_id=item_id)
    elif profile.startswith("graduated") or profile == "personal_right_public_wrong_tree":
        if profile == "personal_right_public_wrong_tree":
            personal = personal_fixtures(3, -3)
            for i, qid in enumerate(personal): attempt(qid, -3 if i == 0 else -2, True)
            attempt(qids[0], -1, False); attempt(qids[1], 0, False)
            with factory() as db:
                assert db.get(KpState, node_id).mastered_at is None
        else:
            if profile == "graduated_determinant_prepersonal":
                for qid in personal_fixtures(2, -3): attempt(qid, -3, True)
            for qid in qids: attempt(qid, -2 if profile == "graduated_replacement_personal_wrong" else -1, True)
            with factory() as db:
                assert db.get(KpState, node_id).state == "mastered", "graduation_fixture_did_not_earn_mastery"
            if profile == "graduated_replacement_personal_wrong":
                attempt(personal_fixtures(1, -1)[0], -1, False)
    else:
        raise ValueError("unknown_profile")


def parse_events(raw):
    result = []
    for frame in raw.replace("\r\n", "\n").split("\n\n"):
        name, data = "message", []
        for line in frame.splitlines():
            if line.startswith("event:"): name = line[6:].strip()
            if line.startswith("data:"): data.append(line[5:].strip())
        if data:
            try: result.append({"event": name, "data": json.loads("\n".join(data))})
            except ValueError: result.append({"event":name, "raw": "\n".join(data)})
    return result


def execute(*, resume=False):
    verify()
    run_out = OUT / ("continuation-v4" if resume == "v4" else "continuation-v3" if resume == "v3" else "continuation-v2") if resume else OUT
    if resume:
        assert not run_out.exists(), "Never repeat a continuation"
        reconciliation = json.loads((OUT / ("v3-budget-reconciliation.json" if resume == "v4" else "q02-meter-reconciliation.json" if resume == "v3" else "q01-meter-reconciliation.json")).read_text(encoding="utf-8"))
        ledger_path = OUT/"continuation-v3/provider-ledger.json" if resume == "v4" else OUT/"continuation-v2/provider-ledger.json" if resume == "v3" else OUT/"provider-ledger.json"
        assert hashlib.sha256(ledger_path.read_bytes()).hexdigest() == reconciliation["original_ledger_sha256"]
        original_result = json.loads((OUT / "Q01/result.json").read_text(encoding="utf-8"))
        assert original_result["provider_requests"] == 1 and original_result["status"] == "COMPLETED"
        run_out.mkdir()
    else:
        assert not (OUT / "provider-ledger.json").exists() and not (OUT / "case-results.json").exists(), "Never replay sent requests"
    cases_data = json.loads((DATA / "cases.json").read_text(encoding="utf-8"))
    material_data = json.loads((OUT / "materials-ready.json").read_text(encoding="utf-8"))
    from scripts.phase5_eval_meter import Meter
    from sqlalchemy import select
    from backend.db import create_db_engine, create_session_factory
    from backend.models.learning import KnowledgePoint
    from backend.models.chat import ChatMessage
    from backend.models.learning_task import LearningTask
    from backend.api.deps import get_time_provider
    from backend.app import create_app
    from fastapi.testclient import TestClient
    from backend.services.personal_generation_intent import explicitly_generate
    from backend.services.model_settings_service import load_local_settings
    configure(BASE)
    settings = load_local_settings(configure(BASE))
    assert settings.llm_model == "deepseek-flash" and settings.llm_base_url.rstrip("/") == "https://api.deepseek.com"
    assert settings.llm_stream_include_usage
    retrieval = stack(settings)
    base_engine = create_db_engine(url(BASE))
    with create_session_factory(base_engine)() as db: retrieval.rebuild_keyword_index(db)
    base_engine.dispose()
    meter = Meter(run_out)
    if resume:
        meter.records = reconciliation["reconciled_records"] if resume in {"v3","v4"} else [reconciliation["reconciled_record"]]
    meter.install()
    results, sessions = ([{**original_result,"evidence_directory":"Q01","meter_version":"v1_reconciled"}] if resume else []), {}
    if resume == "v3":
        results.append(json.loads((OUT/"continuation-v2/Q02/result.json").read_text(encoding="utf-8")))
    elif resume == "v4":
        results = [r for r in json.loads((OUT/"continuation-v3/case-results.json").read_text(encoding="utf-8"))["results"] if r.get("provider_requests",0)>0]
        assert {r["id"] for r in results} == {"Q01","Q02","Q03","Q04","Q05","Q06","Q07","A01","A02"}
    already_sent = {r["id"] for r in results}
    now = datetime.now(timezone.utc).replace(microsecond=0)
    write(run_out / "runtime-version.json", {"clock":now,"cases_sha256":hashlib.sha256((DATA/"cases.json").read_bytes()).hexdigest(),
        "model":settings.llm_model,"endpoint":settings.llm_base_url,"stream_usage":True,
        "code_sha256":{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),ROOT/"scripts/phase5_eval_meter.py",ROOT/"backend/services/learning_task_service.py",ROOT/"backend/chat/service.py"]}})
    order = json.loads((DATA / "execution-plan.json").read_text(encoding="utf-8"))["batches"]
    by_id = {c["id"]:c for c in cases_data["cases"]}
    qa_name = "phase5_closeout_qa_test"
    if not resume: clone(qa_name)
    try:
        for batch in order:
            for cid in batch["qa"] + batch["agent"]:
                if cid in already_sent: continue  # Never resend a measured business turn.
                case = by_id[cid]
                row = {"id":cid,"track":case["track"],"category":case["category"],"input":case["input"],"quality_score":None,"status":"NOT_EXECUTED"}
                case_dir = run_out / cid; case_dir.mkdir()
                row["evidence_directory"] = str(case_dir.relative_to(OUT))
                row["meter_version"] = str(resume) if resume else "v1"
                if meter.stop_reason:
                    row.update(status="BUDGET_OR_PROVIDER_STOPPED", reason=meter.stop_reason)
                    results.append(row); write(case_dir/"result.json",row); continue
                if case["track"] == "agent" and explicitly_generate(case["input"]):
                    row.update(status="BLOCKED_UNEXPECTED_GENERATION_INTENT",reason="Frozen case would enter generation branch; no request sent")
                    results.append(row); write(case_dir/"result.json",row); continue
                name = qa_name if case["track"] == "qa" else f"phase5_closeout_{cid.lower()}{'_r4' if resume == 'v4' else ''}_test"
                if case["track"] == "agent": clone(name)
                current_settings = load_local_settings(configure(name))
                engine = create_db_engine(url(name)); factory = create_session_factory(engine)
                client = None
                try:
                    with factory() as db:
                        node = db.scalar(select(KnowledgePoint).where(KnowledgePoint.code == cases_data["node_keys"][case["node"]])) if case.get("node") else None
                        node_id = node.id if node else None
                        subject = node.subject if node else None
                    if case["track"] == "agent":
                        seed_profile(factory,case,node_id,now)
                        truth = learner_truth(factory,node_id); write(case_dir/"truth-before.json",truth)
                    else: truth = None
                    app = create_app(); app.state.settings=current_settings; app.state.engine=engine
                    app.state.session_factory=factory; app.state.retrieval_stack=retrieval; app.state.job_runner=None
                    app.dependency_overrides[get_time_provider] = lambda: lambda: now
                    # API requests use real routes/services. No lifespan side effects or fake Provider.
                    client = TestClient(app,base_url="http://127.0.0.1",raise_server_exceptions=False)
                    key = case.get("session_key",cid)
                    if key not in sessions:
                        body={"title":"Phase5 frozen "+key,"mode":case.get("mode","builtin"),"purpose":"study" if case["track"]=="agent" else "materials" if case.get("mode")=="user" else "qa",
                            "material_scope_ids":[material_data["materials"][k]["id"] for k in case.get("material_scope",[])]}
                        response=client.post("/api/chat/sessions",json=body); assert response.status_code==201,response.text
                        sessions[key]=response.json()["session_id"]
                    sid=sessions[key]
                    study_context={"surface":"study" if case["track"]=="agent" else "chat",
                        "knowledge_node_ids":[str(node_id)] if node_id else [],"subject":subject}
                    # Frozen budget_minutes is fixture context, not part of the
                    # frozen user wording. Bind it through an ordinary task so
                    # planner_handoff inherits the evaluated hard limit rather
                    # than silently defaulting to 90 minutes.
                    if case["track"] == "agent" and type(case.get("budget_minutes")) is int:
                        from backend.services.learning_task_service import create_task
                        from backend.schemas.learning_task import CreateTask
                        budget_context = create_task(factory, CreateTask(goal=case["input"],
                            budget_minutes=case["budget_minutes"], session_id=UUID(sid)), now=now)
                        study_context["task_id"] = str(budget_context.task_id)
                    request={"question":case["input"],"qa_action":"auto","request_key":str(uuid4()),"study_context":study_context}
                    write(case_dir/"business-request.json", {"session_id":sid,"body":request,"test_database":name})
                    meter.case_id=cid
                    start=len(meter.records); started=time.monotonic()
                    response=client.post(f"/api/chat/sessions/{sid}/assistant:stream",json=request)
                    row.update(http_status=response.status_code, latency_seconds=round(time.monotonic()-started,3), provider_requests=len(meter.records)-start)
                    (case_dir/"response.sse").write_text(response.text,encoding="utf-8")
                    events=parse_events(response.text); write(case_dir/"events.json",events)
                    history=client.get(f"/api/chat/sessions/{sid}/messages")
                    write(case_dir/"restored-history.json",history.json())
                    with factory() as db:
                        messages=list(db.scalars(select(ChatMessage).where(ChatMessage.session_id==UUID(sid),ChatMessage.role=="assistant").order_by(ChatMessage.seq)))
                        last=messages[-1] if messages else None
                        row.update(status=last.status.upper() if last else "NO_SAVED_ANSWER",answer=last.content if last else None,metadata=last.metadata_ if last else None)
                        task_id=(last.metadata_ or {}).get("planner_task_id") if last else None
                        if task_id:
                            task=db.get(LearningTask,UUID(task_id)); write(case_dir/"agent-task.json",{c.name:getattr(task,c.key) for c in task.__table__.columns})
                    if truth:
                        after=learner_truth(factory,node_id); write(case_dir/"truth-after.json",after)
                        row["learning_state_unchanged"] = truth["state"] == after["state"] and truth["counts"] == after["counts"]
                        if not row["learning_state_unchanged"]:
                            meter.stop_reason="unexpected_learning_mutation_stop"
                    row["model_called"] = row["provider_requests"] > 0
                except Exception as exc:
                    row.update(status="FIXTURE_OR_API_BLOCKED",error_type=type(exc).__name__,reason=str(exc)[:1200])
                finally:
                    if client: client.close()
                    engine.dispose()
                results.append(row); write(case_dir/"result.json",row)
                write(run_out/"case-results.json",{"results":results,"meter":meter.summary(),"stop_reason":meter.stop_reason})
                print(json.dumps({"id":cid,"status":row["status"],"calls":row.get("provider_requests",0),"total_calls":len(meter.records),"upper_cost":meter.summary()["peak_uncached_cost_upper_estimate_cny"]}),flush=True)
            write(run_out/f"batch-{batch['batch']}.json",{"case_ids":batch["qa"]+batch["agent"],"meter":meter.summary(),"stop_reason":meter.stop_reason})
    finally:
        meter.uninstall(); meter.flush()
        write(run_out/"case-results.json",{"results":results,"meter":meter.summary(),"stop_reason":meter.stop_reason})


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare",action="store_true")
    parser.add_argument("--execute-authorized-40",action="store_true")
    parser.add_argument("--resume-after-meter-reconciliation",action="store_true")
    parser.add_argument("--resume-meter-v3",action="store_true")
    parser.add_argument("--resume-meter-v4",action="store_true")
    args=parser.parse_args()
    assert sum([args.prepare,args.execute_authorized_40,args.resume_after_meter_reconciliation,args.resume_meter_v3,args.resume_meter_v4]) == 1
    prepare() if args.prepare else execute(resume="v4" if args.resume_meter_v4 else "v3" if args.resume_meter_v3 else args.resume_after_meter_reconciliation)
