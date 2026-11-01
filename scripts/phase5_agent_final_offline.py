"""Read-only isolated evidence checks and offline request replay. No Provider."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from uuid import UUID

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
SOURCE=ROOT/"storage/quality-audits/phase5-ai-real-retest-20261015-v1"
OUT=ROOT/"storage/quality-audits/phase5-agent-final-repair-20261015"


def load(p):return json.loads(p.read_text(encoding="utf-8"))
def byte_size(payload):return len(json.dumps(payload,ensure_ascii=False,separators=(",", ":")).encode("utf-8"))


def main():
    from backend.services.learning_task_context import compact_model_messages
    from backend.services.learning_task_service import SYSTEM_PROMPT
    ledger=load(SOURCE/"provider-ledger.json")
    result={"provider_requests":0,"previous_requests":[],"reconstructed_blocked_rounds":[],"readonly_learning_progress":[]}
    for record in ledger["requests"]:
        if not record["case_id"].startswith("A"):continue
        payload=deepcopy(record["request"])
        payload["messages"][0]["content"]=SYSTEM_PROMPT
        payload["messages"]=compact_model_messages(payload["messages"])
        size=byte_size(payload)
        result["previous_requests"].append({"case":record["case_id"],"number":record["number"],
            "original_bytes":record["request_bytes"],"compacted_bytes":size,
            "within_reservation":size+2048<=64000 and byte_size({k:payload[k] for k in ("messages","tools") if k in payload})<=60000})
    for cid in ("A01","A08","A11","A14","A15","A16","A19","A20"):
        task=load(SOURCE/cid/"agent-task.json")
        previous=[r for r in ledger["requests"] if r["case_id"]==cid][-1]
        payload=deepcopy(previous["request"])
        response=json.loads(previous["response_text"])["choices"][0]["message"]
        calls=response["tool_calls"]
        payload["messages"].append({"role":"assistant","content":None,"tool_calls":calls})
        successful=task["metrics"]["calls"][-2]["round"]
        rows=[t for t in task["trace"] if t["round"]==successful]
        assert len(rows)==len(calls)
        for call,row in zip(calls,rows):
            payload["messages"].append({"role":"tool","tool_call_id":call["id"],"content":json.dumps(row["result"],ensure_ascii=False)})
        if task["metrics"].get("planner_factual_summary"):
            summary=task["metrics"]["planner_factual_summary"]
            payload["messages"]=[m for m in payload["messages"] if not(m.get("role")=="user" and str(m.get("content","")).startswith("AUTHORITATIVE_PLANNER_FACTUAL_SUMMARY"))]
            payload["messages"].append({"role":"user","content":"AUTHORITATIVE_PLANNER_FACTUAL_SUMMARY\n"+json.dumps(summary,ensure_ascii=False)})
        if task["metrics"]["calls"][-1]["round"]==6:
            payload["messages"].append({"role":"user","content":"已到最后一轮。不要再调用工具；若已有validate_plan通过的草案，简短总结；否则明确说明现有工具结果的限制，needs_clarification=true。只返回约定JSON，不声称已加入。"})
            payload["tools"]=[]
        original=byte_size(payload)
        payload["messages"][0]["content"]=SYSTEM_PROMPT
        payload["messages"]=compact_model_messages(payload["messages"])
        size=byte_size(payload)
        result["reconstructed_blocked_rounds"].append({"case":cid,"reconstructed_original_bytes":original,
            "compacted_bytes":size,"within_reservation":size+2048<=64000 and byte_size({k:payload[k] for k in ("messages","tools") if k in payload})<=60000})
    # All reads stay on the existing owned test cluster. Current profile code
    # reads old bound versions; it does not backfill receipts or learner state.
    from sqlalchemy import create_engine,select
    from sqlalchemy.orm import sessionmaker
    from backend.models.learning import KnowledgePoint,KpState,QuestionAttempt
    from backend.services.capability_service import read_capability_profile
    preflight=load(SOURCE/"fixture-preflight.json")
    for cid in ("A04","A09","A10","A12","A13"):
        fixture=next(r for r in preflight["cases"] if r["id"]==cid)
        name=fixture["database"]
        assert name.endswith("_test")
        engine=create_engine(f"postgresql+psycopg://postgres@127.0.0.1:59271/{name}",connect_args={"options":"-c default_transaction_read_only=on"})
        with sessionmaker(engine)() as db:
            kp=UUID(fixture["node_id"]);node=db.get(KnowledgePoint,kp)
            state=db.get(KpState,kp)
            before=deepcopy({c.name:getattr(state,c.name) for c in state.__table__.columns})
            receipts={str(a.id):deepcopy(a.grading_evidence) for a in db.scalars(select(QuestionAttempt).where(QuestionAttempt.kp_id==kp))}
            p=read_capability_profile(db,node)
            after={c.name:getattr(state,c.name) for c in state.__table__.columns}
            assert before==after
            assert receipts=={str(a.id):a.grading_evidence for a in db.scalars(select(QuestionAttempt).where(QuestionAttempt.kp_id==kp))}
            original_profile=load(SOURCE/cid/"truth-before.json")["capability_profile"]
            graduation=p.graduation_progress.model_dump(mode="json") if p.graduation_progress else None
            assert original_profile.get("graduation_progress")==graduation
            result["readonly_learning_progress"].append({"case":cid,"previous_progress":original_profile["learning_progress"],
                "progress":p.learning_progress.model_dump(mode="json"),"graduation_progress_unchanged":True,
                "state_and_receipts_unchanged":True})
        engine.dispose()
    result["all_replayed_inputs_fit"]=all(r["within_reservation"] for k in ("previous_requests","reconstructed_blocked_rounds") for r in result[k])
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/"offline-evidence.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"past_requests":len(result["previous_requests"]),"all_fit":result["all_replayed_inputs_fit"],
        "blocked_rounds":result["reconstructed_blocked_rounds"],"progress":[{"case":r["case"],"status":r["progress"]["status"],"reference_wrong":r["progress"]["reference_wrong_count"],"reliable_wrong":r["progress"]["reliable_wrong_count"]} for r in result["readonly_learning_progress"]]},ensure_ascii=False,indent=2))


if __name__=="__main__":main()
