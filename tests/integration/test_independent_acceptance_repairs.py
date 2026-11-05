"""Disposable PG, real API contracts; no browser or paid model claims."""
from uuid import UUID
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select,delete,text
from tests.integration.test_learning_loop import session_factory,clean_database,clock
from backend.api.deps import get_time_provider
from backend.app import create_app
from backend.mastery.enums import MasteryState
from backend.models.learning import DailyPlan,PracticeItem,Question,KpState

@pytest.fixture
def client(clock):
    """Surface route exceptions instead of hiding them behind HTTP 500 responses."""
    app=create_app()
    app.dependency_overrides[get_time_provider]=lambda:clock
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()

def snapshot(factory):
    with factory() as db:
        tables=['knowledge_points','questions','kp_states','kp_mastery_policies','kp_graduation_question_set_versions','question_attempts',
            'learning_events','daily_plans','practice_items','practice_retry_requests','question_versions']
        return {table:sorted(str(row) for row in db.execute(text(f'SELECT to_jsonb(t) FROM {table} t')).scalars()) for table in tables}

def choice_item(factory):
    with factory.begin() as db:
        q=db.scalar(select(Question).where(Question.question_type=='single_choice',Question.is_active.is_(True)))
        assert q is not None and q.options
        db.execute(delete(KpState).where(KpState.kp_id==q.kp_id))
        plan=DailyPlan(study_date='2026-01-01',status='active');db.add(plan);db.flush()
        item=PracticeItem(plan_id=plan.id,kp_id=q.kp_id,question_id=q.id,ordinal=1);db.add(item);db.flush()
        return str(item.id),q.correct_answer,list(q.options)

def test_new_student_recommendations_include_unseen_nodes_and_get_never_bootstraps(client,session_factory,clean_database):
    with session_factory.begin() as db:db.execute(delete(KpState))
    before=snapshot(session_factory)
    for path in ['/api/plans/today','/api/plans/today/recommendations']*2:
        response=client.get(path);assert response.status_code==200,response.text
        rows=response.json()['recommendations'];assert rows
        assert all(r['state']=='unseen' for r in rows)
    assert snapshot(session_factory)==before

def test_mixed_recommendations_keep_unseen_nodes_and_existing_policy_state_read_only(client,session_factory,clean_database):
    with session_factory.begin() as db:
        db.execute(delete(KpState))
        q=db.scalar(select(Question).where(Question.is_active.is_(True)))
        assert q is not None
        kp_id=q.kp_id
        db.add(KpState(kp_id=kp_id,state=MasteryState.STUCK.value,assessment_basis='legacy_self_reported'))
    before=snapshot(session_factory)
    first=client.get('/api/plans/today/recommendations')
    second=client.get('/api/plans/today/recommendations')
    assert first.status_code==second.status_code==200
    rows=first.json()['recommendations'];assert rows==second.json()['recommendations']
    by_id={row['kp_id']:row for row in rows}
    assert by_id[str(kp_id)]['state']==MasteryState.STUCK.value
    assert any(row['state']=='unseen' for row in rows if row['kp_id']!=str(kp_id))
    assert snapshot(session_factory)==before

def test_recommendations_preserve_legacy_v3_transition_confirmation_without_binding(client,session_factory,clean_database):
    from backend.services.graduation_question_set import freeze_graduation_question_set
    with session_factory.begin() as db:
        q=db.scalar(select(Question).where(Question.is_active.is_(True)))
        assert q is not None
        kp_id=q.kp_id
        db.execute(delete(KpState).where(KpState.kp_id==kp_id))
        freeze_graduation_question_set(db,kp_id=q.kp_id,question_ids=[q.id],reason='SYNTHETIC UI directed-repair fixture')
        db.add(KpState(kp_id=kp_id,state=MasteryState.STUCK.value,assessment_basis='legacy_self_reported',
            graduation_set_binding_status='legacy_history_unbound'))
    before=snapshot(session_factory)
    response=client.get('/api/plans/today/recommendations')
    assert response.status_code==200,response.text
    row=next(row for row in response.json()['recommendations'] if row['kp_id']==str(kp_id))
    assert row['requires_graduation_set_confirmation'] is True
    assert snapshot(session_factory)==before

@pytest.mark.parametrize('payload,code',[
    ({'raw_answer':'A'},'selected_option_required'),
    ({},'selected_option_required'),
    ({'selected_option':'  '},'selected_option_required'),
    ({'selected_option':'Z'},'selected_option_invalid'),
    ({'selected_option':['A']},'selected_option_invalid'),
    ({'selected_option':{'value':'A'}},'selected_option_invalid'),
    ({'selected_option':7},'selected_option_invalid'),
    ({'selected_option':'A'*9},'selected_option_invalid'),
])
def test_choice_invalid_contract_is_422_without_attempt_or_partial_state(client,session_factory,clean_database,payload,code):
    item,correct,options=choice_item(session_factory)
    before=snapshot(session_factory)
    response=client.post(f'/api/practice-items/{item}/answer-submissions',json={'idempotency_key':'ind-invalid-choice',**payload})
    assert response.status_code==422,response.text
    assert response.json()['error']['code']==code
    assert snapshot(session_factory)==before
    body={'idempotency_key':'ind-valid-choice','selected_option':correct}
    accepted=client.post(f'/api/practice-items/{item}/answer-submissions',json=body)
    assert accepted.status_code==200 and accepted.json()['result']=='right',accepted.text
    assert client.post(f'/api/practice-items/{item}/answer-submissions',json=body).json()==accepted.json()

def test_new_nested_retry_is_rejected_and_original_retry_receipt_still_replays(client,session_factory,clean_database):
    item,correct,options=choice_item(session_factory)
    wrong=next(key for key in options if key!=correct)
    def submit(item,key):
        response=client.post(f'/api/practice-items/{item}/answer-submissions',json={'idempotency_key':key,'selected_option':wrong})
        assert response.status_code==200,response.text
    submit(item,'ind-root-wrong')
    assert client.post(f'/api/practice-items/{item}/answer-reveal',json={}).status_code==200
    body={'idempotency_key':'ind-root-retry'}
    created=client.post(f'/api/practice-items/{item}/retries',json=body);assert created.status_code==200,created.text
    child=created.json()['id'];submit(child,'ind-retry-wrong')
    before=snapshot(session_factory)
    response=client.post(f'/api/practice-items/{child}/retries',json={'idempotency_key':'ind-nested-retry'})
    assert response.status_code==409 and response.json()['error']['code']=='practice_retry_nested_not_allowed',response.text
    assert snapshot(session_factory)==before
    replay=client.post(f'/api/practice-items/{item}/retries',json=body)
    assert replay.status_code==200 and replay.json()['id']==child
    assert client.get(f'/api/practice-items/{child}/retry').json()['answer_submission']['result']=='wrong'
    assert len(client.get(f'/api/practice-items/{item}/answer-submissions').json()['items'])==1

def test_help_seen_in_retry_is_inherited_by_later_sibling_without_rewriting_original(client,session_factory,clean_database):
    item,correct,options=choice_item(session_factory)
    wrong=next(key for key in options if key!=correct)
    def submit(target,key,value):
        r=client.post(f'/api/practice-items/{target}/answer-submissions',json={'idempotency_key':key,'selected_option':value})
        assert r.status_code==200,r.text
        return r.json()
    original=submit(item,'sibling-root-wrong',wrong)
    first=client.post(f'/api/practice-items/{item}/retries',json={'idempotency_key':'sibling-first'}).json()['id']
    submit(first,'sibling-first-wrong',wrong)
    assert client.post(f'/api/practice-items/{first}/answer-reveal',json={}).status_code==200
    second=client.post(f'/api/practice-items/{item}/retries',json={'idempotency_key':'sibling-second'}).json()['id']
    assert second!=first
    receipt=submit(second,'sibling-next-correct',correct)
    assert receipt['assisted'] and receipt['effective_confirmation_count']==0
    assert client.get(f'/api/practice-items/{item}/answer-submissions').json()['items']==[original]
