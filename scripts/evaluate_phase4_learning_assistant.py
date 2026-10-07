"""Real inventory/service/model evaluation, with rollback and no private uploads.

--execute makes at most 40 model requests for the fixed 12 scenarios. Ordinary
QA receives public existing questions, builtin lessons and synthetic attempts;
Planner global-inventory feedback has learner usage fields redacted upstream.
"""
from __future__ import annotations
import argparse
import asyncio
from collections import Counter,defaultdict
from datetime import datetime,timedelta,timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
from threading import Lock
from uuid import UUID,uuid4

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from backend.config import get_settings
from backend.db import create_db_engine,create_session_factory
from backend.services.model_settings_service import load_local_settings
from backend.models.chat import ChatSession,ChatMessage
from backend.models.learning import Question,QuestionAttempt,KnowledgePoint,KpState,DailyPlan,PracticeItem
from backend.schemas.learning_assistant import StudyContext,AssistantRequest
from backend.schemas.learning_task import ConfirmTask
from backend.services.question_eligibility import question_eligibility
from backend.services.learning_assistant_service import assistant_stream
from backend.services.learning_task_service import confirm_task
from backend.services.answer_submission_service import submit_answer
from backend.chat.service import provider_from_settings
from scripts.expand_phase3b_inventory import protected_fingerprints,dump

DATASET=ROOT/"eval/learning-assistant/cases-v1.json"
LIMIT=40


class Alive:
    async def is_disconnected(self): return False


def scrub_planner_message(message):
    result=dict(message)
    if result.get("role") in {"user","tool"} and isinstance(result.get("content"),str):
        try: data=json.loads(result["content"])
        except ValueError: return result
        if isinstance(data,dict) and "recent_learning" in data: data["recent_learning"]=[]
        if isinstance(data,dict) and "practice_eligible_count" in data and "eligible_nodes" in data:
            for key in ("previously_attempted_count","unused_count"): data.pop(key,None)
            for node in data["eligible_nodes"]:
                for key in ("previously_attempted_count","unused_count"): node.pop(key,None)
            data["privacy_note"]="Learning-history usage is redacted for evaluation; inventory counts are real."
        result["content"]=json.dumps(data,ensure_ascii=False)
    return result


class LimitedProvider:
    def __init__(self,base,limit=LIMIT): self.base=base; self.calls=0; self.lock=Lock();self.limit=limit
    def __getattr__(self,name): return getattr(self.base,name)
    def count(self):
        with self.lock:
            if self.calls>=self.limit: raise RuntimeError("phase4_model_budget_exhausted")
            self.calls+=1
    def complete(self,*args,**kwargs): self.count(); return self.base.complete(*args,**kwargs)
    async def stream(self,*args,**kwargs):
        self.count()
        async for delta in self.base.stream(*args,**kwargs): yield delta
    def tool_turn(self,messages,tools,*,timeout):
        self.count(); return self.base.tool_turn([scrub_planner_message(m) for m in messages],tools,timeout=timeout)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--execute",action="store_true");parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--dataset",type=Path,default=DATASET)
    parser.add_argument("--max-requests",type=int,default=LIMIT)
    args=parser.parse_args();output=args.output.resolve()
    if not 1<=args.max_requests<=LIMIT: parser.error("max-requests must be 1..40")
    dataset=json.loads(args.dataset.read_text(encoding="utf-8"))
    if not output.is_relative_to(ROOT/"tmp") or output.exists(): parser.error("new report under tmp/ required")
    output.parent.mkdir(parents=True,exist_ok=True)
    settings=load_local_settings(get_settings());engine=create_db_engine(str(settings.active_database_url));normal=create_session_factory(engine)
    with normal() as db:
        baseline=protected_fingerprints(db); occupied=set(db.scalars(select(DailyPlan.study_date)))
        attempted_nodes=set(db.scalars(select(QuestionAttempt.kp_id).distinct()))
        candidates=defaultdict(list)
        for q in db.scalars(select(Question)):
            n=db.get(KnowledgePoint,q.kp_id); state=db.get(KpState,q.kp_id)
            if q.kp_id in attempted_nodes or (state and (state.node_self_grade is not None or state.evidence_window or state.manual_credit_count)): continue
            if question_eligibility(q,n).practice_eligible: candidates[n.id].append(q)
        def choose(subject):
            pools=[(db.get(KnowledgePoint,nid),qs) for nid,qs in candidates.items() if len(qs)>=2 and ("408" in db.get(KnowledgePoint,nid).subject)==(subject=="cs408")]
            if not pools: raise RuntimeError("No >=2-question unused public slice available")
            n,qs=sorted(pools,key=lambda item:item[0].code)[0]
            qs.sort(key=lambda q:(q.question_type!="single_choice",str(q.id)))
            return {"node_id":str(n.id),"code":n.code,"subject":n.subject,"question_ids":[str(q.id) for q in qs[:2]]}
        slices={"math":choose("math"),"cs408":choose("cs408")}
        proof=db.scalar(select(Question).where(Question.question_type.in_(["proof","program","discussion","subjective"]),Question.kp_id.not_in(attempted_nodes or {UUID(int=0)})).order_by(Question.id))
        if proof: slices["proof"]={"node_id":str(proof.kp_id),"question_ids":[str(proof.id)]}
        eligible=sum(question_eligibility(q,db.get(KnowledgePoint,q.kp_id)).practice_eligible for q in db.scalars(select(Question)))
    report={"dataset_version":dataset["version"],"dataset_sha256":sha256(args.dataset.read_bytes()).hexdigest(),"inventory_practice_eligible":eligible,"slices":slices,
        "model":settings.llm_model,"maximum_model_requests":args.max_requests,"private_uploads_sent":False,"real_user_attempts_sent":False,
        "retrieval_quality_evaluation":"NOT_RUN; QA uses existing questions and builtin lesson context; RAG compatibility tested separately",
        "planner_history_redaction":True,"cases":[],"workflow_writes_committed":False}
    if not args.execute: dump(output,{**report,"mode":"dry_run","model_calls":0}); print(json.dumps(report,ensure_ascii=True)); return
    connection=engine.connect();outer=connection.begin();factory=sessionmaker(bind=connection,expire_on_commit=False,autoflush=False,join_transaction_mode="create_savepoint")
    provider=LimitedProvider(provider_from_settings(settings),limit=args.max_requests)
    now=datetime(2099,3,1,4,tzinfo=timezone.utc)
    while now.date().isoformat() in occupied: now+=timedelta(days=1)
    with factory.begin() as db:
        session=ChatSession(mode="builtin",title="Phase4 isolated real-model evaluation");plan=DailyPlan(study_date=now.date().isoformat(),status="active")
        db.add_all([session,plan]);db.flush();sid=session.id
        contexts={}; item_ids={}; ordinal=0
        for kind in ("math","cs408"):
            ids=slices[kind]["question_ids"]
            for index,raw in enumerate(ids):
                q=db.get(Question,UUID(raw));ordinal+=1
                item=PracticeItem(plan_id=plan.id,question_id=q.id,kp_id=q.kp_id,ordinal=ordinal);db.add(item);db.flush()
                if db.get(KpState,q.kp_id) is None: db.add(KpState(kp_id=q.kp_id));db.flush()
                label=kind if index==0 else kind+"_hint"
                contexts[label]=StudyContext(surface="study",practice_item_id=item.id,question_id=q.id,daily_plan_id=plan.id,knowledge_node_ids=[q.kp_id])
                item_ids[label]=item.id
        # Keep the second CS question out of today's plan so Planner can append it.
        extra=db.get(PracticeItem,item_ids["cs408_hint"]);db.delete(extra);db.flush()
        if "proof" in slices: contexts["proof"]=StudyContext(question_id=UUID(slices["proof"]["question_ids"][0]),knowledge_node_ids=[UUID(slices["proof"]["node_id"])])
        contexts["none"]=StudyContext()
    attempts={}
    def submit(label,correct=False,previous=None):
        with factory.begin() as db:
            q=db.get(Question,contexts[label].question_id)
            value=q.correct_answer if correct else next((k for k in (q.options or {}) if k!=q.correct_answer),"987654321")
            result=submit_answer(db,item_id=item_ids[label],raw_answer=value if not q.options else None,selected_option=value if q.options else None,
                idempotency_key=str(uuid4()),now=now,expected_previous_attempt_id=previous)
        contexts[label].attempt_id=result.attempt_id;attempts[label]=result
        return result
    submit("math")
    async def execute_case(case):
        kind=case["surface"];context=contexts.get(kind,contexts["none"])
        if case["id"] in {"hint_one","hint_two","solution"}: context=contexts["math_hint"]
        before=provider.calls;frames=[]
        async for raw in assistant_stream(factory,request=Alive(),session_id=sid,
            body=AssistantRequest(question=case["question"],study_context=context,qa_action=case.get("action","auto"),current_work=case.get("current_work")),stack=None,provider=provider,now=now):
            lines=raw.decode().splitlines();frames.append((lines[0].removeprefix("event: "),json.loads(lines[1].removeprefix("data: "))))
        final=next((data for event,data in reversed(frames) if event=="done"),{})
        error=next((data for event,data in frames if event=="error"),None)
        routed=next((data for event,data in frames if event=="route"),{})
        message_id=final.get("message_id")
        with factory() as db:
            row=db.get(ChatMessage,UUID(message_id)) if message_id else None
            metadata=dict(row.metadata_ or {}) if row else {}
        entry={"id":case["id"],"expected_route":case["route"],"actual_route":routed.get("capability"),
            "status":"error" if error or final.get("status")=="failed" else "completed","error_code":(error or {}).get("code"),
            "model_requests":provider.calls-before,"answer":final.get("answer", ""),"learning_trace":metadata.get("learning_trace"),
            "generation_trace":metadata.get("generation_trace"),"assistance_level":metadata.get("assistance_level"),"hint_guard_blocked":metadata.get("hint_guard_blocked"),
            "planner_handoff_present":bool(metadata.get("planner_handoff")),"source_message_preserved":bool(metadata.get("source_user_message_id"))}
        task=next((data for event,data in frames if event=="planner"),None)
        if task:
            entry["planner"]={k:task.get(k) for k in ("status","error_code","message","metrics")}
            entry["planner"]["tools"]=[{"tool":t.get("tool"),"result_summary":t.get("result_summary")} for t in task["trace"]]
            entry["planner"]["draft_question_ids"]=(task.get("draft") or {}).get("selected_question_ids",[])
            if case["id"]=="qa_to_planner" and task["status"]=="ready":
                result=confirm_task(factory,UUID(task["task_id"]),ConfirmTask(draft_version=task["draft_version"]),now=now)
                second=confirm_task(factory,result.task_id,ConfirmTask(draft_version=task["draft_version"]),now=now)
                entry["planner"]["confirmed_added_count"]=result.metrics["commit"]["added_count"]
                entry["planner"]["repeat_confirm_idempotent"]=result.metrics["commit"]==second.metrics["commit"]
        return entry
    try:
        for case in dataset["cases"]:
            entry=asyncio.run(execute_case(case)); report["cases"].append(entry)
            if case["id"]=="hint_one": submit("math_hint")
            elif case["id"]=="hint_two": submit("math_hint",previous=attempts["math_hint"].attempt_id)
            elif case["id"]=="solution":
                final_attempt=submit("math_hint",correct=True,previous=attempts["math_hint"].attempt_id)
                report["learning_loop"]={"attempt_number":final_attempt.attempt_number,"assistance_level":final_attempt.assistance_level,
                    "sequence_category":final_attempt.sequence_category,"effective_confirmation_count":final_attempt.effective_confirmation_count}
            report["model_calls"]=provider.calls;dump(output,report)
            print(json.dumps({"case":entry["id"],"status":entry["status"],"route":entry["actual_route"],"model_calls":provider.calls}),flush=True)
            if provider.calls>=args.max_requests: break
    finally: outer.rollback();connection.close()
    with normal() as db:
        report["rollback_verified"]=protected_fingerprints(db)==baseline
        report["temporary_conversation_remaining"]=db.get(ChatSession,sid) is not None
    report["workflow_writes_committed"]=not report["rollback_verified"]
    dump(output,report);engine.dispose()
    print(json.dumps({"cases":len(report["cases"]),"calls":provider.calls,"rollback_verified":report["rollback_verified"]}))


if __name__=="__main__": main()
