"""TEST_FIXTURE only: persisted graduation, current trust, tree and Agent agree."""
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import get_settings
from backend.models.learning import KpState
from backend.services.answer_verification import revoke_answer_verification, answer_version_sha256
from backend.services.learning_task_tools import TaskTools
from tests.integration.test_policy_origin_semantics import make_origin_slice, attempt, DAY
from tests.integration.test_learning_loop import session_factory, clean_database
import pytest


def fixture_submission(db,node,q,day,*,assisted=False,answer="A"):
    from sqlalchemy import select,func
    from backend.models.learning import DailyPlan,PracticeItem
    from backend.services.answer_submission_service import submit_answer
    # Simulate the persisted-question read of an actual later HTTP request,
    # including PostgreSQL's timestamp timezone representation.
    db.flush();db.refresh(q)
    plan=db.scalar(select(DailyPlan).where(DailyPlan.study_date==day.date().isoformat()))
    if plan is None:
        plan=DailyPlan(study_date=day.date().isoformat(),status="active");db.add(plan);db.flush()
    ordinal=(db.scalar(select(func.count()).select_from(PracticeItem).where(PracticeItem.plan_id==plan.id)) or 0)+1
    item=PracticeItem(plan_id=plan.id,kp_id=node.id,question_id=q.id,ordinal=ordinal,
        answer_revealed_at=day-timedelta(minutes=1) if assisted else None)
    db.add(item);db.flush()
    return submit_answer(db,item_id=item.id,raw_answer=None,selected_option=answer,
        idempotency_key="phase45e-fixture-"+uuid4().hex,now=day)


@pytest.mark.parametrize("case,expected_count,mastered",[
    ("no_evidence",0,False),("few",2,False),("same_day",3,False),
    ("skill_gap",3,False),("repeat",1,False),("solution",2,False),("complete",3,True),
])
def test_strict_graduation_matrix_uses_persisted_receipts(case,expected_count,mastered,session_factory,clean_database):
    with session_factory() as db:
        node,policy,questions=make_origin_slice(db)
        if case=="skill_gap":policy.required_skill_tags=["topic","missing_skill"]
        db.flush()
        count=0
        total=0 if case=="no_evidence" else 2 if case=="few" else 3
        for index in range(total):
            q=questions[0] if case=="repeat" else questions[index]
            day=DAY if case=="same_day" else DAY+timedelta(days=index)
            result=fixture_submission(db,node,q,day,assisted=case=="solution" and index==0)
            count=result.effective_confirmation_count
        assert count==expected_count
        assert (db.get(KpState,node.id).state=="mastered")==mastered
        node_id=node.id;db.commit()
    app=create_app();app.state.session_factory=session_factory;app.state.settings=get_settings()
    client=TestClient(app,base_url="http://127.0.0.1:8003")
    node_view=client.get(f"/api/knowledge/{node_id}").json()["node"]
    assert (node_view["state"]=="mastered")==mastered
    tools=TaskTools(session_factory,budget_minutes=30,now=DAY+timedelta(days=4),goal="根据实际学习情况推荐")
    tools.nodes.add(node_id)
    facts=tools.execute("get_learning_state",{"kp_ids":[str(node_id)]})["states"][0]
    assert facts["state"]==node_view["state"] and facts["effective_confirmation_count"]==expected_count


def test_imported_ai_original_without_current_auto_review_is_not_public_practice_eligible(session_factory,clean_database):
    from sqlalchemy import select
    from backend.models.learning import Question,KnowledgePoint
    from backend.services.question_pack import QuestionPack,import_pack
    from backend.services.question_eligibility import question_eligibility
    from tests.integration.test_question_pack_import import pack_data
    data=pack_data()
    data["questions"][0]["source"].update(content_origin="AI_GENERATED",source_type="original")
    pack=QuestionPack.model_validate(data)
    with session_factory() as db:
        import_pack(db,pack,apply=True)
        q=db.scalar(select(Question).where(Question.stem==pack.questions[0].stem))
        assert q.question_provenance=="ai_generated_practice" and q.source_status=="not_applicable"
        eligibility=question_eligibility(q,db.get(KnowledgePoint,q.kp_id))
        assert not eligibility.practice_eligible
        assert "public_formal_review_required" in eligibility.blocking_reasons
        assert question_eligibility(q,db.get(KnowledgePoint,q.kp_id)).evidence_capability!="verified_objective"
        assert import_pack(db,pack,apply=True)["unchanged"]==1
        db.rollback()


def test_current_graduation_agrees_across_api_and_agent_after_withdrawal(session_factory,clean_database):
    with session_factory() as db:
        node,policy,questions=make_origin_slice(db)
        for i,q in enumerate(questions):
            result=fixture_submission(db,node,q,DAY+timedelta(days=i))
        assert result.state=="mastered"
        node_id=node.id
        db.commit()
    app=create_app();app.state.session_factory=session_factory;app.state.settings=get_settings()
    client=TestClient(app,base_url="http://127.0.0.1:8003")
    assert client.get(f"/api/knowledge/{node_id}").json()["node"]["state"]=="mastered"
    tools=TaskTools(session_factory,budget_minutes=30,now=DAY+timedelta(days=3),goal="根据实际学习情况推荐")
    tools.nodes.add(node_id)
    assert tools.execute("get_learning_state",{"kp_ids":[str(node_id)]})["states"][0]["state"]=="mastered"
    with session_factory() as db:
        state=db.get(KpState,node_id);old_window=deepcopy(state.evidence_window)
        q=db.get(type(questions[0]),questions[0].id)
        revoke_answer_verification(db,question_id=q.id,expected_event_id=q.answer_verification_event_id,
            expected_answer_sha256=answer_version_sha256(q),verifier="isolated-synthetic-test-fixture",
            method="TEST_FIXTURE withdrawal",note="Isolated test, not human review.",
            idempotency_key="phase45e-test-revoke-"+uuid4().hex)
        db.commit()
    detail=client.get(f"/api/knowledge/{node_id}").json()["node"]
    facts=tools.execute("get_learning_state",{"kp_ids":[str(node_id)]})["states"][0]
    assert detail["effective_confirmation_count"]==facts["effective_confirmation_count"]==2
    assert detail["state"]==facts["state"]=="consolidating"
    assert facts["historical_state"]=="mastered"
    with session_factory() as db:
        state=db.get(KpState,node_id)
        assert state.state=="mastered" and state.evidence_window==old_window
