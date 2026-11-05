from copy import deepcopy
from uuid import UUID
from sqlalchemy import select,func
from backend.models.learning import LearningEvent,QuestionAttempt,PracticeItem,KpState
from backend.services.adaptive_schedule_projection import read_projection
from tests.integration.test_learning_loop import client,clock,session_factory,clean_database,leaf_codes,generate_plan,assess


def test_skip_is_durable_idempotent_activity_not_answer_or_mastery(client,clock,session_factory):
    kp=leaf_codes(session_factory)['math.calculus.limit.lhopital']
    plan=generate_plan(client,[kp]).json(); item=plan['items'][0]['id']
    with session_factory() as db:
        before=deepcopy(db.get(KpState,kp).evidence_window)
    for _ in range(2):
        response=assess(client,item,'skip','activity-skip-key')
        assert response.status_code==200,response.text
    fetched=client.get(f'/api/practice-items/{item}/activity')
    assert fetched.status_code==200
    assert len(fetched.json()['events'])==1
    assert fetched.json()['events'][0]['kind']=='skipped'
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(QuestionAttempt))==0
        assert db.get(PracticeItem,UUID(item)).completed_at is None
        assert db.get(KpState,kp).evidence_window==before
        projected=read_projection(db,clock(),[kp])
        assert projected.skills[str(kp)].skipped==1
        assert not projected.cards


def test_activity_same_key_different_payload_conflicts(client,session_factory):
    kp=leaf_codes(session_factory)['math.calculus.limit.lhopital']
    item=generate_plan(client,[kp]).json()['items'][0]['id']
    url=f'/api/practice-items/{item}/activity'
    first=client.post(url,json={'kind':'viewed','idempotency_key':'activity-view-key'})
    repeated=client.post(url,json={'kind':'viewed','idempotency_key':'activity-view-key'})
    assert first.status_code==repeated.status_code==200
    assert first.json()['event_id']==repeated.json()['event_id']
    conflict=client.post(url,json={'kind':'started','idempotency_key':'activity-view-key'})
    assert conflict.status_code==409,conflict.text
    assert len(client.get(url).json()['events'])==1
