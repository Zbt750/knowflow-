"""Actual isolated repaired content; only learner actions are TEST_FIXTURE."""
import json
from pathlib import Path
from datetime import datetime,timezone,timedelta
from uuid import UUID,uuid4
from sqlalchemy import DateTime,Uuid,select,func
from backend.models.learning import Question,KnowledgePoint,KpMasteryPolicy,KpState,QuestionAutoReviewEvent,DailyPlan,PracticeItem,QuestionAttempt
from backend.services.question_eligibility import question_eligibility
from backend.services.answer_submission_service import submit_answer
from backend.services.auto_question_review import current_auto_review
from scripts.run_question_repair_pilot import isolated_factory

def converted(model,row):
    result=dict(row)
    # This frozen pre-f53 export predates the per-learner v3 set-binding fields.
    # Their migration defaults are compatibility metadata, not changes to the
    # original mastery policy being protected by these assertions.
    if model is KpMasteryPolicy:
        result.setdefault('graduation_question_ids',[])
        result.setdefault('graduation_set_version',0)
    for column in model.__table__.columns:
        if result.get(column.name) is None:continue
        if isinstance(column.type,Uuid):result[column.name]=UUID(result[column.name])
        elif isinstance(column.type,DateTime):result[column.name]=datetime.fromisoformat(result[column.name])
    return result

def test_repaired_actual_math_and_408_submission_with_unchanged_policy(test_database_url):
    path=Path('storage/quality-audits/phase45hs-20261010/formal-bank-export.json')
    if not path.exists():
        import pytest
        pytest.skip('Private licensed historical inventory artifact unavailable')
    data=json.loads(path.read_text(encoding='utf-8'))
    ids={'d1691564-0c42-43c0-8ab2-b011fd88ac65','02879a3d-b32b-419b-8755-74199b2c3e11'}
    questions=[q for q in data['questions'] if q['id'] in ids];assert len(questions)==2
    with isolated_factory(test_database_url) as (factory,_):
        with factory.begin() as db:
            for row in questions:
                node_row=next(n for n in data['knowledge_points'] if n['id']==row['kp_id'])
                # Fixture owns learner state and a detached hierarchy, not source content.
                node_row={**node_row,'parent_id':None}
                db.add(KnowledgePoint(**converted(KnowledgePoint,node_row)));db.flush()
                policy_row=next(p for p in data['policies'] if p['kp_id']==row['kp_id'])
                db.add(KpMasteryPolicy(**converted(KpMasteryPolicy,policy_row)))
                db.add(KpState(kp_id=UUID(row['kp_id'])))
                event_id=UUID(row['auto_review_event_id'])
                question=Question(**converted(Question,{**row,'auto_review_event_id':None}))
                assert question.answer_verification_event_id is None
                db.add(question);db.flush()
                event_row=next(e for e in data['auto_review_events'] if e['id']==str(event_id))
                event=QuestionAutoReviewEvent(**converted(QuestionAutoReviewEvent,event_row));db.add(event);db.flush()
                question.current_auto_review=event;question.auto_review_event_id=event_id;db.flush()
                node=db.get(KnowledgePoint,question.kp_id)
                assert current_auto_review(question,node)
                assert question_eligibility(question,node).evidence_capability=='verified_objective'
            plan=DailyPlan(study_date='2026-10-10',status='active');db.add(plan);db.flush()
            for index,row in enumerate(questions,1):
                q=db.get(Question,UUID(row['id']));item=PracticeItem(plan_id=plan.id,question_id=q.id,kp_id=q.kp_id,ordinal=index)
                db.add(item);db.flush()
                result=submit_answer(db,item_id=item.id,raw_answer=q.correct_answer,
                    selected_option=q.correct_answer if q.question_type=='single_choice' else None,
                    idempotency_key='TEST_FIXTURE hs actual '+str(uuid4()),now=datetime(2026,10,10,2,tzinfo=timezone.utc))
                assert result.result=='right'
                assert db.get(KpState,q.kp_id).state!='mastered'
                policy=db.get(KpMasteryPolicy,q.kp_id)
                assert {c.name:getattr(policy,c.name) for c in KpMasteryPolicy.__table__.columns}==converted(KpMasteryPolicy,next(p for p in data['policies'] if p['kp_id']==str(q.kp_id)))
            assert db.scalar(select(func.count()).select_from(QuestionAttempt))==2

def test_actual_inventory_witnesses_reach_three_unchanged_policies(test_database_url):
    path=Path('storage/quality-audits/phase45hs-20261010/formal-bank-export.json')
    if not path.exists():
        import pytest
        pytest.skip('Private historical inventory unavailable')
    data=json.loads(path.read_text(encoding='utf-8'))
    coverage=json.loads(path.with_name('coverage.json').read_text(encoding='utf-8'))
    reachable=[row for row in coverage if row['status']=='CONDITIONAL_FUTURE_SUBMISSIONS']
    assert len(reachable)==3
    for witness in reachable:
        with isolated_factory(test_database_url) as (factory,_):
            with factory.begin() as db:
                node_row=next(n for n in data['knowledge_points'] if n['id']==witness['node_id'])
                node=KnowledgePoint(**converted(KnowledgePoint,{**node_row,'parent_id':None}));db.add(node);db.flush()
                policy_row=next(p for p in data['policies'] if p['kp_id']==witness['node_id'])
                policy=KpMasteryPolicy(**converted(KpMasteryPolicy,policy_row));db.add(policy)
                db.add(KpState(kp_id=node.id));db.flush()
                for index,qid in enumerate(witness['witness_question_ids']):
                    row=next(q for q in data['questions'] if q['id']==qid)
                    event_row=next(e for e in data['auto_review_events'] if e['id']==row['auto_review_event_id'])
                    question=Question(**converted(Question,{**row,'auto_review_event_id':None}));db.add(question);db.flush()
                    event=QuestionAutoReviewEvent(**converted(QuestionAutoReviewEvent,event_row));db.add(event);db.flush()
                    question.auto_review_event_id=event.id;question.current_auto_review=event;db.flush()
                    now=datetime(2026,10,10,2,tzinfo=timezone.utc)+timedelta(days=index)
                    plan=DailyPlan(study_date=now.date().isoformat(),status='active');db.add(plan);db.flush()
                    item=PracticeItem(plan_id=plan.id,question_id=question.id,kp_id=node.id,ordinal=1);db.add(item);db.flush()
                    result=submit_answer(db,item_id=item.id,raw_answer=question.correct_answer,
                        selected_option=question.correct_answer if question.question_type=='single_choice' else None,
                        idempotency_key='TEST_FIXTURE actual cross day '+str(uuid4()),now=now)
                    assert result.result=='right'
                    if index<len(witness['witness_question_ids'])-1:assert db.get(KpState,node.id).state!='mastered'
                state=db.get(KpState,node.id)
                assert state.state=='mastered',json.dumps({'node':witness['code'],'result':result.model_dump(mode='json'),
                    'window':state.evidence_window},ensure_ascii=False,default=str)
                assert {c.name:getattr(policy,c.name) for c in KpMasteryPolicy.__table__.columns}==converted(KpMasteryPolicy,policy_row)
