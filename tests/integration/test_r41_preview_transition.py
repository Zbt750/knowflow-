"""Owned PostgreSQL regression; synthetic fixture, never real learner evidence."""
from uuid import UUID, uuid4
from sqlalchemy import select,func
from backend.models.learning import KpState,DailyPlan,Question
from tests.integration.test_home_recommendation import home,ROOT
from tests.integration.test_learning_loop import client,clock,session_factory,clean_database,mark_isolated_question_trusted


def test_difficulty_and_request_replay_keep_current_transition_consent(client,home,session_factory):
    node=UUID(home['linear'])
    with session_factory.begin() as db:
        state=db.get(KpState,node)
        if state is None:
            state=KpState(kp_id=node);db.add(state)
        state.graduation_set_version=None
        state.graduation_set_binding_status='legacy_history_unbound'
    preview=client.post(ROOT,json={'session_id':home['session_id'],'request_key':uuid4().hex,'action':'default',
        'goal':'','selected_kp_ids':[str(node)],'budget_minutes':90})
    assert preview.status_code==200,preview.text
    wire=preview.json()
    assert wire['context']['required_graduation_set_transition_ids']==[str(node)]
    with session_factory.begin() as db:
        for i in range(wire['draft']['question_count']):
            question=Question(kp_id=node,question_type='single_choice',stem=f'SYNTHETIC adjacent difficulty {i}: 2+2=?',
                options={'A':'4','B':'5'},correct_answer='A',explanation='2+2=4',estimated_minutes=10,
                difficulty='medium',grading_mode='auto',grading_config={'verified':True,'method':'single_choice'},is_active=True)
            mark_isolated_question_trusted(question,db=db)
    endpoint=f"{ROOT}/{wire['task_id']}/difficulty"
    body={'session_id':home['session_id'],'direction':'harder','request_key':uuid4().hex}
    for _ in range(2):
        response=client.post(endpoint,json=body)
        assert response.status_code==200,response.text
        changed=response.json()
        assert changed['context']['required_graduation_set_transition_ids']==[str(node)]
        assert changed['draft']['questions']==[]
        assert changed['difficulty_change_count']==wire['draft']['question_count']
        assert 'difficulty_changes' not in changed
        recovered=client.get(ROOT,params={'session_id':home['session_id']})
        assert recovered.status_code==200,recovered.text
        assert recovered.json()['context']['required_graduation_set_transition_ids']==[str(node)]
    denied=client.post(f"{ROOT}/{wire['task_id']}/confirm",json={'session_id':home['session_id'],'draft_version':changed['draft_version']})
    assert denied.status_code==409 and denied.json()['error']['code']=='graduation_set_transition_confirmation_required'
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(DailyPlan))==0
        assert db.get(KpState,node).graduation_set_version is None
