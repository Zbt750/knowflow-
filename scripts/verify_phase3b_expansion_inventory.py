"""Real expansion inventory regression; all user workflow writes roll back."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from uuid import UUID, uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from backend.config import get_settings
from backend.db import create_db_engine, create_session_factory
from backend.models.learning import DailyPlan, KnowledgePoint, KpState, PracticeItem, Question
from backend.models.learning_task import LearningTask
from backend.schemas.learning_task import NodeIds, SearchKnowledge, FindQuestions, QuestionAvailabilityQuery, ValidatePlan
from backend.services.learning_task_tools import TaskTools
from backend.services.question_availability import question_availability
from backend.services.question_eligibility import question_eligibility
from backend.services.answer_submission_service import submit_answer
from scripts.expand_phase3b_inventory import dump, protected_fingerprints
from scripts.verify_phase3b_real_slice import _planner_preview_and_commit


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--run-dir",type=Path,required=True)
    args=parser.parse_args(); run_dir=args.run_dir.resolve()
    pre=json.loads((run_dir/"pre-audit.json").read_text(encoding="utf-8"))
    final=json.loads((run_dir/"final-audit.json").read_text(encoding="utf-8"))
    before={r["code"]:r for r in pre["assessable_node_coverage"]}
    new=[r for r in final["assessable_node_coverage"] if before[r["code"]]["practice_eligible_count"]==0 and 0<r["practice_eligible_count"]<=12]
    grew=[r for r in final["assessable_node_coverage"] if 0<before[r["code"]]["practice_eligible_count"]<r["practice_eligible_count"]<=12]
    zero=[r for r in final["assessable_node_coverage"] if r["practice_eligible_count"]==0]
    engine=create_db_engine(str(get_settings().active_database_url)); normal=create_session_factory(engine)
    with normal() as db:
        active_parent_ids={str(p) for p in db.scalars(select(KnowledgePoint.parent_id).where(KnowledgePoint.is_active.is_(True),KnowledgePoint.parent_id.is_not(None)))}
        baseline=protected_fingerprints(db)
        occupied=set(db.scalars(select(DailyPlan.study_date)))
    zero=[r for r in zero if r["node_id"] not in active_parent_ids]
    if not new or not grew or not zero: raise AssertionError("Required new/increased/zero inventory scenarios unavailable")
    selected=[new[0],grew[0],zero[0]]
    now=datetime(2099,2,1,4,tzinfo=timezone.utc)
    while now.date().isoformat() in occupied: now+=timedelta(days=1)
    connection=engine.connect(); outer=connection.begin()
    factory=sessionmaker(bind=connection,expire_on_commit=False,autoflush=False,join_transaction_mode="create_savepoint")
    report={"model_calls":0,"workflow_writes_committed":False,"checks":{},"node_cases":[{"code":r["code"],"name":r["name"],"before":before[r["code"]]["practice_eligible_count"],"after":r["practice_eligible_count"]} for r in selected]}
    def tools_for(node,count=1):
        tools=TaskTools(factory,budget_minutes=240,now=now,goal=f"恰好{count}道，范围 {node.code}")
        with factory() as db:
            tools.search_knowledge(db,SearchKnowledge(query=node.code))
            tools.get_learning_state(db,NodeIds(kp_ids=[node.id]))
            found=tools.find_questions(db,FindQuestions(kp_ids=[node.id]))
        return tools,found
    try:
        with factory() as db:
            nodes=[db.scalar(select(KnowledgePoint).where(KnowledgePoint.code==r["code"])) for r in selected]
            ids_by_code={n.code:[str(q.id) for q in db.scalars(select(Question).where(Question.kp_id==n.id)) if question_eligibility(q,n).practice_eligible] for n in nodes}
        new_node,grew_node,zero_node=nodes
        zero_tools,zero_found=tools_for(zero_node)
        with factory() as db:
            z=zero_tools.get_question_availability(db,QuestionAvailabilityQuery(kp_ids=[zero_node.id]))
            invalid=zero_tools.validate_plan(db,ValidatePlan(question_ids=[],rationale="inventory regression"))
        report["checks"]["still_zero_fail_closed"]=z["practice_eligible_count"]==0 and not zero_found["questions"] and not invalid["valid"]
        ids=ids_by_code[new_node.code]
        over_tools,over_found=tools_for(new_node,len(ids)+1)
        with factory() as db:
            invalid=over_tools.validate_plan(db,ValidatePlan(question_ids=[UUID(i) for i in ids],rationale="inventory shortage"))
        report["checks"]["over_available_rejected"]="question_count_constraint" in invalid.get("errors",[])
        planned=[]; plans=[]
        for node in (new_node,grew_node):
            node_ids=ids_by_code[node.code]
            receipt=_planner_preview_and_commit(factory,now=now,goal=f"恰好{len(node_ids)}道，范围 {node.code}",budget=240,
                search_terms=[node.code],node_codes=[node.code],expected_question_ids=node_ids)
            planned.extend(node_ids); plans.append(receipt)
        report["plans"]=plans
        report["checks"]["within_available_confirmed"]=all(p["preview_valid"] and p["first_confirm_added_count"]==len(p["preview_question_ids"]) for p in plans)
        report["checks"]["repeat_confirm_idempotent"]=all(p["second_confirm_idempotent"] for p in plans)
        with factory() as db:
            actual={str(i) for i in db.scalars(select(PracticeItem.question_id).where(PracticeItem.plan_id==UUID(plans[0]["plan_id"])))}
            availability=question_availability(db,now=now,kp_ids=[new_node.id])
        report["checks"]["preview_ids_equal_confirmed_ids"]=actual==set(planned)
        report["checks"]["current_plan_inventory_excludes_duplicates"]=availability["available_to_append_count"]==0
        duplicate_tools,duplicate_found=tools_for(new_node,len(ids))
        with factory() as db:
            duplicate=duplicate_tools.validate_plan(db,ValidatePlan(question_ids=[UUID(i) for i in ids],rationale="duplicate check"))
            excluded=duplicate_tools.get_question_availability(db,QuestionAvailabilityQuery(kp_ids=[new_node.id],exclude_kp_ids=[new_node.id]))
        report["checks"]["duplicate_validation_rejected"]="already_in_today_plan" in duplicate.get("errors",[])
        report["checks"]["exclusion_enforced"]=excluded["practice_eligible_count"]==0
        with factory.begin() as db:
            before_availability=question_availability(db,now=now,kp_ids=[new_node.id])
            item=db.scalar(select(PracticeItem).where(PracticeItem.question_id==UUID(ids[0]),PracticeItem.plan_id==UUID(plans[0]["plan_id"])))
            q=db.get(Question,item.question_id)
            if db.get(KpState,new_node.id) is None: db.add(KpState(kp_id=new_node.id)); db.flush()
            submission=submit_answer(db,item_id=item.id,raw_answer=q.correct_answer if q.question_type!="single_choice" else None,
                selected_option=q.correct_answer if q.question_type=="single_choice" else None,idempotency_key=str(uuid4()),now=now)
            after_availability=question_availability(db,now=now,kp_ids=[new_node.id])
            report["checks"]["attempted_unused_distinguished"]=after_availability["previously_attempted_count"]==before_availability["previously_attempted_count"]+1 and after_availability["unused_count"]==before_availability["unused_count"]-1
            report["checks"]["ai_attempt_nonconfirming"]=submission.effective_confirmation_count==0 and "nonconfirming" in submission.sequence_category
        report["all_checks_passed"]=all(report["checks"].values())
    finally: outer.rollback(); connection.close()
    with normal() as db:
        tasks_remaining=list(db.scalars(select(LearningTask.id).where(LearningTask.id.in_([UUID(p["task_id"]) for p in plans]))))
        report["temporary_tasks_remaining"]=len(tasks_remaining)
        report["rollback_verified"]=protected_fingerprints(db)==baseline and not tasks_remaining
    engine.dispose(); dump(run_dir/"planner-inventory-regression.json",report)
    print(json.dumps(report,ensure_ascii=True))
    if not report["all_checks_passed"] or not report["rollback_verified"]: raise AssertionError("inventory regression failed")
    return 0


if __name__=="__main__": raise SystemExit(main())
