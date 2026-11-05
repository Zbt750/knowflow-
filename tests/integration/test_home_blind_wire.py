from uuid import UUID,uuid4
from backend.models.learning_task import LearningTask
from tests.integration.test_home_recommendation import client,clock,session_factory,clean_database,home,ROOT


def test_home_wire_is_blind_but_confirmation_uses_full_pinned_draft(client,home,session_factory):
    response=client.post(ROOT,json={'session_id':home['session_id'],'request_key':uuid4().hex,
        'goal':'','action':'default','selected_kp_ids':[home['linear']],'budget_minutes':90})
    assert response.status_code==200,response.text
    public=response.json()
    with session_factory() as db:
        saved=db.get(LearningTask,UUID(public['task_id'])).draft
        pairs=[(q['question_id'],q['question_version_id']) for q in saved['questions']]
    assert pairs
    assert public['draft']['questions']==[]
    assert public['draft']['question_count']==len(pairs)
    assert sum(n['assigned_count'] for n in public['draft']['scope_nodes'])==len(pairs)
    recovered=client.get(ROOT,params={'session_id':home['session_id']})
    assert recovered.status_code==200
    for wire in (response,recovered,client.get('/api/plans/today/home-recommendation')):
        assert wire.status_code==200
        for q in saved['questions']:
            assert q['question_id'] not in wire.text
            assert q['question_version_id'] not in wire.text
            assert q['stem'] not in wire.text
    confirmed=client.post(f"{ROOT}/{public['task_id']}/confirm",json={
        'session_id':home['session_id'],'draft_version':public['draft_version'],
        'confirm_legacy_set_transition_ids':[]})
    assert confirmed.status_code==200,confirmed.text
    actual=client.get('/api/plans/today').json()
    assert [(q['question_id'],q['question_version_id']) for q in actual['items']]==pairs
