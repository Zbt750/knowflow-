"""Isolated real-inventory replay; requires explicit --isolated-pilot. No production apply."""
import argparse
from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path
from uuid import UUID,uuid4
import json
import re
import sys
from copy import deepcopy
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sqlalchemy import create_engine,text,select,insert,delete
from sqlalchemy.engine import make_url
from backend.config import get_settings
from backend.db import create_db_engine,create_session_factory
from backend.models import import_models
from backend.models.base import Base
from backend.models.learning import KnowledgePoint,Question,KpMasteryPolicy,KpState,QuestionAnswerConsistencyRun,QuestionSourceAttestation,QuestionAttempt
from backend.services.question_repair import local_pack_registry,identity_counts,restore_pack_binding
from backend.services.question_eligibility import question_eligibility
from backend.services.question_quality import audit_teaching_question
from backend.services.question_verification_upgrade import snapshot
from backend.services.golden_learning_slice import digest
from scripts.audit_question_quality import json_input,safe_output
from scripts.review_golden_slice import fingerprints


@contextmanager
def isolated_factory(url):
    parsed=make_url(url)
    if parsed.host not in {"127.0.0.1","localhost"} or not (parsed.database or "").endswith("_test"):
        raise ValueError("Only explicit local _test database allowed")
    schema="question_repair_"+uuid4().hex[:16]
    owner=create_db_engine(url); engine=None; created=False
    try:
        with owner.begin() as c:
            if not c.scalar(text("SELECT current_database()" )).endswith("_test"): raise ValueError("Not a test database")
            c.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            c.exec_driver_sql(f'COMMENT ON SCHEMA "{schema}" IS \'kaoyan-question-repair:v1\'')
        created=True
        engine=create_engine(url,connect_args={"connect_timeout":5,"options":f"-csearch_path={schema}"},pool_pre_ping=True)
        with engine.connect() as c:
            if c.scalar(text("SELECT current_schema()"))!=schema or "public" in c.scalar(text("SHOW search_path")):
                raise ValueError("Isolation has public fallback")
        import_models(); Base.metadata.create_all(engine)
        yield create_session_factory(engine),schema
    finally:
        if engine: engine.dispose()
        if created:
            with owner.begin() as c:
                marker=c.scalar(text("SELECT obj_description(oid,'pg_namespace') FROM pg_namespace WHERE nspname=:s"),{"s":schema})
                if marker!="kaoyan-question-repair:v1": raise ValueError("Isolation cleanup marker changed; do not delete")
                c.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        owner.dispose()


def decoded(model,rows):
    result=[]
    for row in rows:
        data=dict(row)
        for col in model.__table__.columns:
            value=data.get(col.name)
            if value is None: continue
            if col.type.python_type is UUID: data[col.name]=UUID(value)
            elif col.type.python_type is datetime: data[col.name]=datetime.fromisoformat(value)
        result.append(data)
    return result


def clone_inventory(factory,raw):
    with factory.begin() as db:
        pending=decoded(KnowledgePoint,raw["knowledge_points"]); done=set()
        while pending:
            batch=[r for r in pending if r["parent_id"] is None or r["parent_id"] in done]
            if not batch: raise ValueError("Knowledge parent cycle/missing parent")
            db.execute(insert(KnowledgePoint),batch); done.update(r["id"] for r in batch)
            pending=[r for r in pending if r["id"] not in done]
        # Core bulk insert bypasses the Question immutable-version ORM hook.
        # Recreate these frozen pre-f53 inventory rows through the ORM so every
        # isolated clone has a real version-1 snapshot before review fixtures
        # or submissions touch content-bound fields.
        question_rows=decoded(Question,raw["questions"])
        for row in question_rows:
            if "current_version_id" in row:
                row["current_version_id"]=None
            db.add(Question(**row))
        db.flush()
        db.execute(insert(KpMasteryPolicy),decoded(KpMasteryPolicy,raw["kp_mastery_policies"]))
        if raw["question_answer_consistency_runs"]:
            db.execute(insert(QuestionAnswerConsistencyRun),decoded(QuestionAnswerConsistencyRun,raw["question_answer_consistency_runs"]))
        if raw.get("question_source_attestations"):
            db.execute(insert(QuestionSourceAttestation),decoded(QuestionSourceAttestation,raw["question_source_attestations"]))
        db.add_all(KpState(kp_id=k,state="unseen") for k in done if any(UUID(r["id"])==k and r["is_assessable"] for r in raw["knowledge_points"]))
    # Intentionally no real learner history copied. Existing source pointers
    # remain as stored; newly emitted repair records are test-only.


def choose_pilot(report,limit=30):
    blocked=[r for r in report["questions"] if not r["production_eligibility"]["practice_eligible"]]
    result={}
    def add(row):
        if len(result)<limit: result.setdefault(row["question_id"],row)
    for row in blocked:
        if row["automatic_answer_proof_available"] and row["pack_link"] and row["pack_link"]["usable"]: add(row)
    for category,cap in (("C",6),("D",6),("B",4),("A",12)):
        pool=[r for r in blocked if r["category"]==category]
        # Alternate subjects to keep the batch representative, never select
        # only the easy questions that the new validators happen to solve.
        groups=[[r for r in pool if r["subject"]==s] for s in ("408","考研数学")]
        count=0
        for i in range(max([len(g) for g in groups] or [0])):
            for group in groups:
                if i<len(group) and count<cap: add(group[i]); count+=1
    for row in blocked: add(row)
    return list(result.values())


def run(args):
    output=safe_output(args.output_dir); report=json_input(args.diagnosis/"report.json")
    raw=json_input(args.diagnosis/"inventory-snapshot.json")
    if digest(raw)!=report.get("inventory_snapshot_sha256"):
        raise ValueError("Frozen inventory snapshot hash mismatch")
    if report["database"].endswith("_test") or report["feature_flag"]:
        raise ValueError("Use an unchanged feature-off development diagnosis as source")
    plans=choose_pilot(report)
    if args.question_id:
        wanted=set(args.question_id); indexed={r["question_id"]:r for r in report["questions"]}
        if not wanted or len(wanted)>40 or not wanted.issubset(indexed): raise ValueError("Invalid explicit IDs")
        plans=[indexed[i] for i in sorted(wanted)]
        if any(p["production_eligibility"]["practice_eligible"] for p in plans): raise ValueError("Repair pilot must originate from blocked questions")
    settings=get_settings()
    dev_engine=create_db_engine(str(settings.active_database_url))
    with create_session_factory(dev_engine)() as db:
        db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")); current=fingerprints(db); db.rollback()
    dev_engine.dispose()
    if current!=report["protection"]["after"]: raise ValueError("Live development fingerprint changed since diagnosis")
    url=str(settings.test_database_url) if settings.test_database_url else make_url(str(settings.database_url)).set(database="kaoyan_test").render_as_string(hide_password=False)
    registry,_=local_pack_registry(ROOT)
    output.mkdir(parents=True,exist_ok=False)
    receipts=[]; protected=[]; previous=settings.teaching_practice_enabled
    try:
        with isolated_factory(url) as (factory,schema):
            clone_inventory(factory,raw)
            with factory() as db:
                policies=[{c.name:str(getattr(p,c.name)) for c in KpMasteryPolicy.__table__.columns} for p in db.scalars(select(KpMasteryPolicy).order_by(KpMasteryPolicy.kp_id))]
                qs=list(db.scalars(select(Question).order_by(Question.id))); identities=identity_counts(qs)
                expected={r["question_id"]:r["before_snapshot_sha256"] for r in report["questions"]}
                if any(digest(snapshot(q))!=expected.get(str(q.id)) for q in qs): raise ValueError("Cloned question version mismatch")
                original={q.id:{c.name:getattr(q,c.name) for c in Question.__table__.columns} for q in qs}
                original_q=snapshot(qs[0])
                original_sources={r.id:{c.name:getattr(r,c.name) for c in QuestionSourceAttestation.__table__.columns} for r in db.scalars(select(QuestionSourceAttestation))}
            settings.teaching_practice_enabled=True
            for plan in plans:
                with factory.begin() as db:
                    q=db.get(Question,UUID(plan["question_id"])); node=db.get(KnowledgePoint,q.kp_id)
                    before=question_eligibility(q,node,teaching_enabled=True).public_dict()
                    if plan["pack_link"] and plan["pack_link"]["usable"] and not before["source_attestation_current"]:
                        result=restore_pack_binding(db,q,node,plan,registry,identities)
                        replay=restore_pack_binding(db,q,node,plan,registry,identities)
                        if replay["status"]!="NOOP": raise ValueError("Repair was not idempotent")
                    else: result={"status":"WITHHELD","question_id":str(q.id),"reason":"no_exact_safe_link_or_already_bound"}
                    after=question_eligibility(q,node,teaching_enabled=True).public_dict()
                    receipts.append({"plan":plan,"before_eligibility":before,"repair":result,"after_eligibility":after})
            with factory() as db:
                newly=[r for r in receipts if not r["before_eligibility"]["practice_eligible"] and r["after_eligibility"]["practice_eligible"]]
                reference=next((q for q in db.scalars(select(Question).order_by(Question.id)) if question_eligibility(q,db.get(KnowledgePoint,q.kp_id),teaching_enabled=True).teaching_use=="REFERENCE_ONLY"),None)
                protected_q={str(q.id):snapshot(q) for q in db.scalars(select(Question))}
                off_before_business=sum(question_eligibility(q,db.get(KnowledgePoint,q.kp_id),teaching_enabled=False).practice_eligible for q in db.scalars(select(Question)))
                on_before_business=sum(question_eligibility(q,db.get(KnowledgePoint,q.kp_id),teaching_enabled=True).practice_eligible for q in db.scalars(select(Question)))
            business=business_check(factory,[r["plan"]["question_id"] for r in newly],str(reference.id) if reference else None)
            with factory() as db:
                assert policies==[{c.name:str(getattr(p,c.name)) for c in KpMasteryPolicy.__table__.columns} for p in db.scalars(select(KpMasteryPolicy).order_by(KpMasteryPolicy.kp_id))]
                assert all(question_eligibility(q,db.get(KnowledgePoint,q.kp_id),teaching_enabled=True).evidence_capability!="verified_objective" for q in db.scalars(select(Question)))
                after_ids={str(q.id):snapshot(q) for q in db.scalars(select(Question))}
                assert protected_q==after_ids
                assert all({c.name:getattr(db.get(QuestionSourceAttestation,k),c.name) for c in QuestionSourceAttestation.__table__.columns}==v for k,v in original_sources.items())
                settings.teaching_practice_enabled=False
                assert sum(question_eligibility(q,db.get(KnowledgePoint,q.kp_id)).practice_eligible for q in db.scalars(select(Question)))==off_before_business
                settings.teaching_practice_enabled=True
            # Demonstrate restore of precisely our repair changes, never user history.
            with factory.begin() as db:
                for receipt in receipts:
                    if receipt["repair"]["status"]!="APPLIED_IN_ISOLATION": continue
                    q=db.get(Question,UUID(receipt["plan"]["question_id"]))
                    for field in receipt["repair"]["changed_fields"]: setattr(q,field,original[q.id][field])
                    q.updated_at=original[q.id]["updated_at"]
                    db.execute(delete(QuestionSourceAttestation).where(QuestionSourceAttestation.attestation_key==receipt["repair"]["source_record_key"],
                        QuestionSourceAttestation.attestation_source=="b3_isolated_exact_pack_restore_not_human_review"))
            with factory() as db:
                assert all(snapshot(db.get(Question,k))==snapshot(Question(**v)) for k,v in original.items())
                assert {r.id:{c.name:getattr(r,c.name) for c in QuestionSourceAttestation.__table__.columns} for r in db.scalars(select(QuestionSourceAttestation))}==original_sources
            result={"status":"PHASE45B3_PILOT_IMPLEMENTED","schema":schema,"environment":"fresh_test_schema_real_inventory_copy",
                "history":"No development attempts/states/learning events copied; new test actions only",
                "dataset_sha256":digest([p["before_snapshot_sha256"] for p in plans]),"pilot_count":len(plans),
                "applied_in_isolation":sum(r["repair"]["status"]=="APPLIED_IN_ISOLATION" for r in receipts),
                "new_practice_in_isolation":len(newly),"still_ineligible":sum(not r["after_eligibility"]["practice_eligible"] for r in receipts),
                "isolated_inventory_flag_off":off_before_business,"isolated_inventory_flag_on":on_before_business,
                "actually_activated_in_development":0,"model_calls":0,"receipts":receipts,"business":business,
                "policy_unchanged":True,"question_content_unchanged":True,"rollback_verified":True,"idempotency_verified":True}
            result["old_source_history_preserved"]=len(original_sources)
    finally: settings.teaching_practice_enabled=previous
    dev_engine=create_db_engine(str(settings.active_database_url))
    with create_session_factory(dev_engine)() as db:
        db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")); after=fingerprints(db); db.rollback()
    dev_engine.dispose()
    if current!=after: raise ValueError("Development fingerprint drift; do not claim protected")
    result["protection"]={"before":current,"after":after,"equal":True,"schema_removed":True,"production_flag":settings.teaching_practice_enabled}
    (output/"report.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding="utf-8")
    lines=["# 隔离真实题修复试点","",f"试点{len(plans)}题，关联修复{result['applied_in_isolation']}题，新增可练{result['new_practice_in_isolation']}题；开发库新增0。", "",
        "| ID | 科目 | 节点 | 原分类 | 修复结果 | 后用途 | 后阻塞 |", "|---|---|---|---|---|---|---|"]
    for row in receipts:
        p=row["plan"]; a=row["after_eligibility"]
        lines.append(f"| {p['question_id']} | {p['subject']} | {p['node_name']} | {p['category']} | {row['repair']['status']} | {a['teaching_use']} | {', '.join(a['blocking_reasons'])} |")
    (output/"report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k not in {"receipts","protection","business"}},ensure_ascii=False,indent=2))
    return result


def business_check(factory,new_ids,reference_id):
    if not new_ids: return {"status":"NO_NEWLY_ELIGIBLE_QUESTION","model_calls":0}
    from fastapi.testclient import TestClient
    from backend.app import create_app
    from backend.config import Settings
    from backend.services.learning_task_tools import TaskTools
    app=create_app(); app.state.session_factory=factory
    url=factory.kw["bind"].url.render_as_string(hide_password=False)
    app.state.settings=Settings(_env_file=None,app_env="test",database_url=url,test_database_url=url,teaching_practice_enabled=True)
    # No lifespan/embedding/model startup: real REST handlers use only this marked schema.
    client=TestClient(app,base_url="http://127.0.0.1:8003",headers={"Origin":"http://127.0.0.1:5174"})
    with factory() as db:
        selected=db.get(Question,UUID(new_ids[0])); kp_id=str(selected.kp_id)
    response=client.post("/api/plans/today/generate",json={"selected_kp_ids":[kp_id]})
    if not response.is_success: raise ValueError("Real generate route failed: "+response.text)
    plan=response.json(); plan_id=plan["plan_id"]
    ids=[*new_ids,*([reference_id] if reference_id else [])]
    missing=[i for i in ids if i not in {str(item["question_id"]) for item in plan["items"]}]
    if missing:
        response=client.post(f"/api/plans/{plan_id}/questions",json={"question_ids":missing})
        if not response.is_success: raise ValueError("Real append route failed: "+response.text)
    ui_plan=client.get("/api/plans/today").json()
    items=ui_plan["items"]
    submitted=[]; ui_answers={}; ui_receipts={}
    for item in items:
        if item["question_id"] not in ids: continue
        answer=client.get(f"/api/practice-items/{item['id']}/answer")
        if answer.status_code!=200: raise ValueError("Answer/solution read failed")
        data=answer.json(); payload={"idempotency_key":"b3-pilot-"+item["id"]}
        ui_answers[item["id"]]=data
        if item["question_type"]=="single_choice": payload["selected_option"]=next(k for k in item["options"] if k!=data["correct_answer"].strip())
        else: payload["raw_answer"]="0"
        # GET above is read-only, not a solution reveal; don't invent assistance.
        response=client.post(f"/api/practice-items/{item['id']}/answer-submissions",json=payload)
        if response.status_code!=200: raise ValueError("Actual submission failed: "+response.text)
        receipt=response.json(); trust=item["question_trust"]
        ui_receipts[item["id"]]=receipt
        expected="unknown" if trust["teaching_use"]=="REFERENCE_ONLY" else "wrong"
        if receipt["result"]!=expected or receipt["effective_confirmation_count"]!=0: raise ValueError("Feedback or strict boundary failed")
        retry_cases=[]
        if trust["teaching_use"]!="REFERENCE_ONLY":
            invalid={"idempotency_key":"b3-unsupported-"+item["id"],"expected_previous_attempt_id":receipt["attempt_id"]}
            invalid["selected_option" if item["question_type"]=="single_choice" else "raw_answer"]="Z" if item["question_type"]=="single_choice" else "untrusted(x)"
            unsupported=client.post(f"/api/practice-items/{item['id']}/answer-submissions",json=invalid)
            if not unsupported.is_success or unsupported.json()["result"]!="unknown": raise ValueError("Unsupported answer incorrectly graded")
            assisted=len(submitted)==0
            if assisted:
                reveal=client.post(f"/api/practice-items/{item['id']}/answer-reveal")
                if not reveal.is_success: raise ValueError("Solution assistance recording failed")
            correct={"idempotency_key":"b3-correct-"+item["id"],"expected_previous_attempt_id":unsupported.json()["attempt_id"]}
            correct["selected_option" if item["question_type"]=="single_choice" else "raw_answer"]=data["correct_answer"]
            fixed=client.post(f"/api/practice-items/{item['id']}/answer-submissions",json=correct)
            if (not fixed.is_success or fixed.json()["result"]!="right" or fixed.json()["effective_confirmation_count"]!=0
                    or fixed.json()["assisted"]!=assisted): raise ValueError("Correct/assisted boundary or graduation isolation failed")
            retry_cases=[{"result":unsupported.json()["result"]},{"result":fixed.json()["result"],"assisted":fixed.json()["assisted"],"confirmation_count":0}]
        node=client.get(f"/api/knowledge/{item['kp_id']}")
        if node.status_code!=200: raise ValueError("Knowledge/progress read failed")
        p=node.json()["capability_profile"]["learning_progress"]
        if p["status"]=="STABLE_PRACTICE": raise ValueError("Incorrect stable certification")
        tools=TaskTools(factory,budget_minutes=180,now=datetime.now(timezone.utc),goal="根据实际学习情况推荐练习")
        tools.nodes.add(UUID(item["kp_id"]))
        facts=tools.execute("get_learning_state",{"kp_ids":[item["kp_id"]]})
        if "learning_progress" not in facts["states"][0]: raise ValueError("Agent did not consume progress")
        pool=tools.execute("find_questions",{"kp_ids":[item["kp_id"]]})
        if pool.get("practice_eligible_count",-1)<1: raise ValueError("Agent inventory cannot see eligible question")
        if any(q["question_trust"]["evidence_capability"]=="verified_objective" for q in pool["questions"]): raise ValueError("Agent falsely treats new ordinary feedback as strict")
        submitted.append({"question_id":item["question_id"],"result":receipt["result"],"reference_result":receipt.get("reference_result"),
            "confirmation_count":receipt["effective_confirmation_count"],"progress":p["status"],"agent_tool_progress":facts["states"][0]["learning_progress"]["status"],
            "source_label":trust["presentation_label"],"answer_and_explanation_available":bool(data["correct_answer"] and data["explanation"]),
            "retry_cases":retry_cases,"agent_inventory_count":pool["practice_eligible_count"]})
    with factory() as db:
        count=len(list(db.scalars(select(QuestionAttempt))))
    return {"status":"PASS","real_rest_handlers":True,"attempt_count":count,"cases":submitted,
        "ui_capture":{"plan":ui_plan,"answers":ui_answers,"first_submissions":ui_receipts},
        "agent_validation":"actual deterministic tool facts only; no LLM calls","model_calls":0}


if __name__=="__main__":
    if hasattr(sys.stdout,"reconfigure"): sys.stdout.reconfigure(encoding="utf-8")
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--diagnosis",type=Path,required=True); p.add_argument("--output-dir",type=Path,required=True)
    p.add_argument("--isolated-pilot",action="store_true",required=True)
    p.add_argument("--question-id",action="append")
    args=p.parse_args(); run(args)
