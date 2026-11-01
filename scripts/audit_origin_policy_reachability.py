"""Read-only audit of the four Phase 4.5A.1 candidates after origin migration."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sqlalchemy import select,text
from backend.config import get_settings
from backend.db import create_db_engine,create_session_factory
from backend.models.learning import KnowledgePoint,KpMasteryPolicy,Question,QuestionAttempt
from backend.mastery.storage import policy_from_storage
from backend.services.answer_grading import available_grading_method
from backend.services.answer_verification import current_answer_verification
from backend.services.question_eligibility import question_eligibility
from backend.services.evidence_pool import assess_evidence_pool
from scripts.answer_trust_migration_preflight import local_database_url,private_output

NODE_CODES=("math.exam.fd2f9e3739d9","math.exam.e90535214807",
    "cs408.ds.topic.ee1ca2a45d19","cs408.ds.topic.1efaf3d00b50")


def potential_method(q):
    for method in ("single_choice","numeric_final","logarithm_final"):
        result=available_grading_method(question_type=q.question_type,
            config={"verified":True,"method":method},expected=q.correct_answer,options=q.options)
        if result: return result
    return None


def build_report(db):
    nodes={n.code:n for n in db.scalars(select(KnowledgePoint).where(KnowledgePoint.code.in_(NODE_CODES)))}
    result=[]
    for code in NODE_CODES:
        node=nodes.get(code)
        if node is None:
            result.append({"node_code":code,"blockers":["NODE_MISSING"]}); continue
        row=db.get(KpMasteryPolicy,node.id); policy=policy_from_storage(row)
        questions=list(db.scalars(select(Question).where(Question.kp_id==node.id,Question.is_active.is_(True))))
        eligibility={q.id:question_eligibility(q,node) for q in questions}
        attempted=set(db.scalars(select(QuestionAttempt.question_id).where(QuestionAttempt.kp_id==node.id)))
        pool=assess_evidence_pool(questions=questions,eligibility_by_id=eligibility,
            attempted_question_ids=attempted,known=node.is_active and node.is_assessable,policy=policy)
        real=[q for q in questions if q.question_provenance=="real_exam"]
        source=[q for q in real if q.content_trust=="verified" and q.source_status=="verified"
            and q.content_reviewed_by and q.content_reviewed_at]
        answers=[q for q in real if current_answer_verification(q)]
        supported=[q for q in real if potential_method(q)]
        objective=[q for q in real if eligibility[q.id].practice_eligible and eligibility[q.id].evidence_capability=="verified_objective"]
        needed=policy.required_question_origins.get("real_exam",0)
        reachable=policy.policy_version==2 and needed>0 and "external_exam" not in policy.required_question_types
        blockers=[]
        if len(objective)<max(needed,policy.min_confirmations,policy.min_real_questions): blockers.append("BLOCKED_BY_VERIFIED_INVENTORY")
        if len(source)<needed: blockers.append("BLOCKED_BY_SOURCE_TRUST")
        if len(answers)<needed: blockers.append("BLOCKED_BY_ANSWER_TRUST")
        if len(supported)<needed: blockers.append("BLOCKED_BY_GRADER_CAPABILITY")
        if pool.status!="SUFFICIENT": blockers.append("INSUFFICIENT_EVIDENCE_POOL")
        result.append({"node_code":code,"name":node.name,"policy_version":policy.policy_version,
            "required_question_types":dict(policy.required_question_types),
            "required_question_origins":dict(policy.required_question_origins),
            "min_confirmations":policy.min_confirmations,"min_real_questions":policy.min_real_questions,
            "required_variant_count":policy.required_variant_count,"required_skill_tags":sorted(policy.required_skill_tags),
            "min_day_span":policy.min_day_span,"review_intervals_days":list(policy.review_intervals_days),
            "semantic_reachability":"POLICY_SEMANTICALLY_REACHABLE" if reachable else "POLICY_SEMANTICS_NOT_MIGRATED",
            "active_question_count":len(questions),"real_exam_question_count":len(real),
            "source_verified_real_exam_count":len(source),"current_answer_verified_real_exam_count":len(answers),
            "potential_supported_comparer_count":len(supported),"verified_objective_real_exam_count":len(objective),
            "question_type_distribution":dict(Counter(q.question_type for q in questions)),
            "evidence_pool":pool.public_dict(),"blockers":blockers,
            "learner_graduation_claim":"NOT_INFERRED_FROM_POLICY_OR_INVENTORY"})
    return {"format":"origin-policy-reachability-v1","created_at":datetime.now(timezone.utc).isoformat(),
        "read_only":True,"model_calls":0,"nodes":result,
        "limits":["Semantic reachability is conditional on future trusted independent confirmations, not current graduation.",
            "Potential supported comparers do not verify an answer or activate a grader.",
            "No question text, reference answer, learner answer or private receipt is exported."]}


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--output",type=Path,required=True)
    args=p.parse_args(); output=private_output(args.output)
    engine=create_db_engine(str(local_database_url(get_settings())))
    try:
        with create_session_factory(engine)() as db:
            db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            if db.scalar(text("SELECT version_num FROM public.alembic_version"))!="f46b2c8d901a":
                raise ValueError("The guarded policy migration must be active before reachability audit")
            report=build_report(db); db.rollback()
        output.parent.mkdir(parents=True,exist_ok=True)
        with output.open("x",encoding="utf-8") as stream: json.dump(report,stream,ensure_ascii=False,indent=2)
        print(json.dumps({"node_count":len(report["nodes"]),"output":str(output),"read_only":True},ensure_ascii=False))
    finally: engine.dispose()


if __name__=="__main__": main()
