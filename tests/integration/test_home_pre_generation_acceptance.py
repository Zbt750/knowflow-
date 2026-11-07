"""Independent real-PostgreSQL acceptance for the homepage before today's paper exists."""
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from backend.models.chat import ChatMessage
from backend.models.learning import DailyPlan, KnowledgePoint, PracticeItem, Question
from backend.models.learning_task import LearningTask
from backend.models.practice_request import PracticeRequest
from backend.schemas.learning_assistant import AssistantRequest, PlannerHandoff, StudyContext
from backend.services.assistant_data_queries import execute_read_only_data_query
from backend.services.learning_assistant_service import assistant_stream
from backend.services.question_availability import question_availability
from backend.services.question_versions import question_version_reference
from backend.services.practice_preview_reference import latest_preview
from backend.services.learning_assistant_service import prepare_planner
from backend.services.question_eligibility import question_eligibility
from tests.integration.test_learning_assistant import conversations, talk, reply, NOW
from tests.integration.test_learning_loop import client, session_factory, clock, clean_database, mark_isolated_question_trusted
from tests.integration.test_learning_tasks import clean_tasks
from tests.integration.test_home_recommendation import home, ROOT, read_home_domain
from tests.integration.test_learning_tasks import PlanningProvider


class NoModel:
    def __getattr__(self, name):
        raise AssertionError(f"model call is not allowed in this deterministic acceptance: {name}")


@pytest.mark.parametrize('explicit_candidate_version', [False, True])
def test_pending_workload_draft_remains_editable_without_losing_quantity_changes(
        client, home, session_factory, explicit_candidate_version):
    with session_factory.begin() as db:
        node, _ = _add_synthetic_topic(db, code='synthetic.pending.quantity', name='待确认题量验收')
        node_id = str(node.id)
    def edit(goal, **kw):
        response = client.post(ROOT, json={'session_id':home['session_id'], 'request_key':uuid4().hex,
            'action':'adjust', 'goal':goal, **kw})
        assert response.status_code == 200, response.text
        result = response.json()
        import json
        assert result['status'] == 'ready', json.dumps(result, ensure_ascii=False)
        return result
    initial = client.post(ROOT, json={'session_id':home['session_id'], 'request_key':uuid4().hex,
        'action':'default', 'goal':'', 'selected_kp_ids':[node_id], 'budget_minutes':10}).json()
    assert initial['status'] == 'ready', initial
    # A manual scope may itself exceed ten minutes when the canonical
    # recommendation already allocated this topic. Establish an accepted
    # baseline before testing dismissal of later unaccepted revisions.
    with session_factory() as db:
        initial_pending=bool(db.get(LearningTask,UUID(initial['task_id'])).context.get('workload_pending'))
    if initial_pending:
        accepted=client.post(ROOT,json={'session_id':home['session_id'],'request_key':uuid4().hex,
            'action':'accept_workload','goal':'','target_task_id':initial['task_id'],
            'expected_version':initial['draft_version']})
        assert accepted.status_code==200,accepted.text
        initial=accepted.json()
    count = initial['draft']['question_count']
    # The adaptive baseline may already allocate all five frozen fixture
    # questions. Add two explicitly synthetic qualified spare questions after
    # the baseline, so this tests pending-card composition rather than stock
    # exhaustion or the random UUID order of recommended topics.
    with session_factory.begin() as db:
        for index in range(2):
            question = Question(kp_id=UUID(node_id), question_type='single_choice',
                stem=f'SYNTHETIC pending spare {index}: 1+1=?', options={'A':'2','B':'3'},
                correct_answer='A', explanation='1+1=2', estimated_minutes=10,
                grading_mode='auto', grading_config={'verified':True,'method':'single_choice'}, is_active=True)
            mark_isolated_question_trusted(question, db=db)
    first = edit('增加一道待确认题量验收的题目。', budget_minutes=5)
    assert first['draft']['question_count'] == count + 1
    with session_factory() as db:
        assert db.get(LearningTask, UUID(first['task_id'])).context['workload_pending']
    second = edit('再增加一道待确认题量验收的题目。', budget_minutes=5,
        **({'expected_version':first['draft_version']} if explicit_candidate_version else {}))
    assert second['draft']['question_count'] == count + 2
    dismissed = client.post(ROOT, json={'session_id':home['session_id'], 'request_key':uuid4().hex,
        'action':'dismiss_workload', 'goal':'', 'target_task_id':second['task_id'],
        'expected_version':second['draft_version']})
    assert dismissed.status_code == 200, dismissed.text
    assert dismissed.json()['draft']['question_count'] == count
    assert dismissed.json()['draft']['selected_kp_ids']==initial['draft']['selected_kp_ids']
    after = formal_rows(session_factory)
    assert after['daily_plans'] == after['practice_items'] == 0


@pytest.fixture(autouse=True)
def _isolate_each_pregeneration_journey(clean_database, clean_tasks, conversations):
    """The standalone PRE_GENERATION group must not inherit POST_GENERATION state."""
    yield


def formal_rows(factory):
    with factory() as db:
        return {
            'daily_plans': db.scalar(select(func.count()).select_from(DailyPlan)),
            'practice_items': db.scalar(select(func.count()).select_from(PracticeItem)),
            'learning_tasks': db.scalar(select(func.count()).select_from(LearningTask)),
        }


def test_first_home_load_is_read_only_and_every_recommended_topic_has_real_eligible_count(client, home, session_factory, clock):
    before=formal_rows(session_factory)
    response=client.get('/api/plans/today/home-recommendation')
    assert response.status_code==200,response.text
    payload=response.json()
    inventory=payload['inventory']
    assert inventory['practice_eligible_count']>=0
    assert inventory['available_to_append_count']>=0
    counts={row['kp_id']:row for row in inventory['recommendation_nodes']}
    assert {row['kp_id'] for row in payload['recommendations']} <= set(counts)
    with session_factory() as db:
        for recommendation in payload['recommendations']:
            actual=question_availability(db,now=clock(),kp_ids=[UUID(recommendation['kp_id'])],limit=10000)
            assert counts[recommendation['kp_id']]['practice_eligible_count']==actual['practice_eligible_count']
    assert formal_rows(session_factory)==before
    assert 'stem' not in response.text and 'correct_answer' not in response.text
    with session_factory() as db:
        for question in db.scalars(select(Question)):
            assert question.stem not in response.text


def test_read_only_today_arrangement_preview_does_not_create_a_formal_paper(client, home, session_factory):
    before=formal_rows(session_factory)
    response=client.get('/api/plans/today/home-recommendation')
    assert response.status_code==200
    assert response.json()['initial_paper'] is None or response.json()['initial_paper']['questions']==[]
    assert formal_rows(session_factory)==before
    assert before['daily_plans']==0 and before['practice_items']==0


def test_chat_request_to_look_at_today_arrangement_only_returns_read_only_summary(client, home, session_factory):
    before=formal_rows(session_factory)
    with session_factory() as db:
        tasks=db.scalar(select(func.count()).select_from(LearningTask))
    response=client.post(ROOT,json={'session_id':home['session_id'],'request_key':uuid4().hex,
        'goal':'我先看看今天怎么安排。','action':'adjust'})
    assert response.status_code==200,response.text
    payload=response.json()
    assert payload.get('kind')=='explanation'
    assert '尚未创建今日卷' in payload['message']
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(LearningTask))==tasks
    assert formal_rows(session_factory)==before


def test_selected_topic_preview_shows_exact_count_and_time_without_question_identity(client, home, session_factory):
    before=formal_rows(session_factory)
    response=client.post(ROOT,json={'session_id':home['session_id'],'request_key':uuid4().hex,
        'goal':'','action':'default','selected_kp_ids':[home['linear']],'budget_minutes':90})
    assert response.status_code==200,response.text
    payload=response.json()
    inventory=payload['context']['inventory']
    selected=next(row for row in inventory['recommendation_nodes'] if row['kp_id']==home['linear'])
    assert selected['practice_eligible_count']==3
    assert inventory['practice_eligible_count']==3
    # The inventory is a count of all admitted choices; the editable proposal
    # can schedule a smaller subset under its own budget/selection policy.
    assert 0 < payload['draft']['question_count'] <= selected['practice_eligible_count']
    assert payload['draft']['total_minutes'] <= payload['draft']['budget_minutes']
    assert payload['draft']['budget_minutes']==90
    assert payload['draft']['questions']==[]
    assert 'question_id' not in response.text and 'question_version_id' not in response.text
    with session_factory() as db:
        for question in db.scalars(select(Question).where(Question.kp_id==UUID(home['linear']))):
            assert question.stem not in response.text
            assert (question.explanation or '') not in response.text
            assert str(question.id) not in response.text
    after=formal_rows(session_factory)
    assert after['daily_plans']==before['daily_plans']==0
    assert after['practice_items']==before['practice_items']==0
    assert after['learning_tasks']==before['learning_tasks']+1


def test_default_preview_pins_the_same_adaptive_question_versions_as_home_recommendation(client,home,session_factory):
    """Opening the editable homepage draft must preserve the visible FSRS/BKT recommendation."""
    before=formal_rows(session_factory)
    recommendation=client.get('/api/plans/today/home-recommendation')
    assert recommendation.status_code==200,recommendation.text
    shown=recommendation.json()
    canonical=shown['initial_paper']
    assert canonical and canonical['question_count']>0
    selected=[row['kp_id'] for row in shown['recommendations']]
    proposal=client.post(ROOT,json={'session_id':home['session_id'],'request_key':uuid4().hex,
        'goal':'','action':'default','selected_kp_ids':selected,'budget_minutes':90})
    assert proposal.status_code==200,proposal.text
    draft=proposal.json()['draft']
    assert proposal.json()['status']=='ready',proposal.json()
    with session_factory() as db:
        task=db.get(LearningTask,UUID(proposal.json()['task_id']))
        stored=task.draft
        from backend.services.home_public_view import public_paper
        stored_baseline=public_paper((task.context or {}).get('baseline'))
        diagnostic={'home_fingerprint':canonical['selection_fingerprint'],
            'draft_fingerprint':draft['selection_fingerprint'],
            'baseline_fingerprint':stored_baseline.get('selection_fingerprint') if stored_baseline else None,
            'draft_pairs':[(row['question_id'],row['question_version_id']) for row in stored['questions']],
            'baseline_pairs':[(row['question_id'],row['question_version_id']) for row in ((task.context or {}).get('baseline') or {}).get('questions',[])],
            'scope_ids':selected}
    assert draft['selection_fingerprint']==canonical['selection_fingerprint'],diagnostic
    assert draft['question_count']==canonical['question_count']
    assert draft['total_minutes']==canonical['total_minutes']
    assert draft['questions']==[]
    with session_factory() as db:
        task=db.get(LearningTask,UUID(proposal.json()['task_id']))
        stored=task.draft
        assert len(stored['questions'])==canonical['question_count']
        assert len({(row['question_id'],row['question_version_id']) for row in stored['questions']})==len(stored['questions'])
    default_plan=client.post(ROOT,json={'session_id':home['session_id'],'request_key':uuid4().hex,
        'goal':'','action':'default','budget_minutes':90})
    assert default_plan.status_code==200,default_plan.text
    assert default_plan.json()['status']=='ready',default_plan.json()
    assert default_plan.json()['draft']['selection_fingerprint']==canonical['selection_fingerprint']
    assert default_plan.json()['draft']['questions']==[]
    after=formal_rows(session_factory)
    assert after['daily_plans']==before['daily_plans']==0
    assert after['practice_items']==before['practice_items']==0
    assert after['learning_tasks']==before['learning_tasks']+2


def test_real_home_preview_exposes_fsrs_due_question_after_wrong_answer(client,home,session_factory,clock):
    """A wrong public API answer becomes a due FSRS candidate in the actual homepage draft."""
    from backend.services.question_eligibility import question_eligibility
    from backend.services.adaptive_schedule_projection import read_projection
    from backend.models.learning import QuestionAttempt
    now=clock()
    with session_factory.begin() as db:
        node=db.get(KnowledgePoint,UUID(home['linear']))
        question=db.scalar(select(Question).where(Question.kp_id==node.id,
            Question.question_type=='single_choice',Question.is_active.is_(True)).order_by(Question.id))
        assert node and question and question_eligibility(question,node).practice_eligible
        assert question.current_version_id and question.options
        correct=str(question.correct_answer or '')
        wrong=next((key for key,value in question.options.items()
            if str(key)!=correct and str(value)!=correct),None)
        assert wrong is not None
        from backend.mastery.storage import policy_for_node
        policy_for_node(db,node.id,bind_if_unset=True,now=now)
        history_plan=DailyPlan(study_date=(now-timedelta(days=30)).date().isoformat(),status='active')
        db.add(history_plan);db.flush()
        history_item=PracticeItem(plan_id=history_plan.id,kp_id=node.id,question_id=question.id,ordinal=1)
        db.add(history_item);db.flush()
        history_item_id=history_item.id
        question_id=question.id;kp_id=node.id;question_version_id=question.current_version_id
    answer=client.post(f'/api/practice-items/{history_item_id}/answer-submissions',json={
        'raw_answer':None,'selected_option':wrong,'idempotency_key':'r40-home-fsrs-due-wrong-01'})
    assert answer.status_code==200,answer.text
    assert answer.json()['result']=='wrong',answer.json()
    attempt_id=UUID(answer.json()['attempt_id'])
    with session_factory() as db:
        receipt=db.get(QuestionAttempt,attempt_id)
        assert receipt and receipt.grading_evidence['evidence_capability']=='verified_objective'
        assert receipt.grading_evidence['adaptive_schedule']['algorithm']=='fsrs6.3.2-bkt-tempered-v2'
    clock.now=now+timedelta(days=30)
    sid=UUID(home['session_id'])
    with session_factory.begin() as db:
        db.get(__import__('backend.models.chat',fromlist=['ChatSession']).ChatSession,sid).study_date=clock().date().isoformat()
    recommendation=client.get('/api/plans/today/home-recommendation')
    assert recommendation.status_code==200,recommendation.text
    shown=recommendation.json();initial=shown['initial_paper']
    assert initial and initial['question_count']>0,shown
    recommendation_ids=[row['kp_id'] for row in shown['recommendations']]
    assert str(kp_id) in recommendation_ids
    with session_factory() as db:
        projection=read_projection(db,clock(),[kp_id])
        card=projection.cards[(str(question_id),str(question_version_id))]
        assert card.due<=clock(),card.to_dict()
    before=formal_rows(session_factory)
    preview=client.post(ROOT,json={'session_id':str(sid),'request_key':uuid4().hex,
        'goal':'','action':'default','selected_kp_ids':recommendation_ids,'budget_minutes':90})
    assert preview.status_code==200,preview.text
    assert preview.json()['status']=='ready',preview.json()
    assert preview.json()['draft']['selection_fingerprint']==initial['selection_fingerprint']
    with session_factory() as db:
        task=db.get(LearningTask,UUID(preview.json()['task_id']))
        planned=[(row['question_id'],row['question_version_id']) for row in task.draft['questions']]
        assert len(set(planned))==len(planned)
        assert (str(question_id),str(question_version_id)) in planned
    after=formal_rows(session_factory)
    assert after['daily_plans']==before['daily_plans']
    assert after['practice_items']==before['practice_items']
    assert after['learning_tasks']==before['learning_tasks']+1
    confirmation=client.post(f"{ROOT}/{preview.json()['task_id']}/confirm",json={
        'session_id':str(sid),'draft_version':preview.json()['draft_version']})
    assert confirmation.status_code==200,confirmation.text
    active=client.get('/api/plans/today')
    assert active.status_code==200,active.text
    actual=[(row['question_id'],row['question_version_id']) for row in active.json()['items']]
    assert actual==planned


def _add_synthetic_topic(db, *, code, name, subject='考研数学'):
    node=KnowledgePoint(code=code,name=name,subject=subject,is_assessable=True,is_active=True)
    db.add(node);db.flush()
    questions=[]
    stems=[
        '计算极限 lim(x→0) sin(x)/x。',
        '函数 f(x)=x² 在 x=3 处的导数是多少？',
        '计算定积分 ∫(0,1) x dx。',
        '数列满足 a₁=2 且 aₙ=2aₙ₋₁，求 a₃。',
        '矩阵 [[1,2],[3,4]] 的行列式是多少？',
    ]
    answers=['1','6','0.5','8','-2']
    for index in range(len(stems)):
        question=Question(kp_id=node.id,question_type='single_choice',
            stem=f'SYNTHETIC {code}: {stems[index]}',options={'A':answers[index],'B':'999'},
            correct_answer='A',explanation='Synthetic fixture only.',estimated_minutes=10,
            grading_mode='auto',grading_config={'verified':True,'method':'single_choice'},is_active=True)
        mark_isolated_question_trusted(question,db=db);questions.append(question)
    from backend.services.graduation_question_set import freeze_graduation_question_set
    freeze_graduation_question_set(db,kp_id=node.id,question_ids=[q.id for q in questions],
        reason='Synthetic PRE_GENERATION named topic quantity acceptance')
    return node,questions


def _sse_events(payload):
    events=[];event=None;data=[]
    for line in payload.splitlines():
        if line.startswith('event: '):
            event=line[7:];data=[]
        elif line.startswith('data: '):
            data.append(line[6:])
        elif not line and event and data:
            import json
            events.append((event,json.loads('\n'.join(data))))
            event=None;data=[]
    if event and data:
        import json
        events.append((event,json.loads('\n'.join(data))))
    return events


def test_generic_planner_and_practice_request_hide_private_candidates_until_real_confirmation(
        client,home,session_factory,clock,monkeypatch):
    from backend.models.practice_request import PracticeRequest
    from backend.services.learning_task_service import get_task
    from backend.services.planning_public_view import public_task
    import backend.api.routes.chat as chat_routes
    import backend.api.routes.practice_requests as practice_request_routes

    monkeypatch.setattr(chat_routes,'_DeferredProvider',lambda _settings:PlanningProvider())
    monkeypatch.setattr(practice_request_routes,'provider_from_settings',lambda _settings:PlanningProvider())
    sid=UUID(home['session_id'])
    before=formal_rows(session_factory)
    request_key=uuid4()
    response=client.post(f'/api/chat/sessions/{sid}/assistant:stream?purpose=study',json={
        'question':'安排一道洛必达题，30分钟。',
        'study_context':{'surface':'study','conversation_id':str(sid)},
        'request_key':str(request_key)})
    assert response.status_code==200,response.text
    events=_sse_events(response.text)
    planner=next((value for event,value in events if event=='planner'),None)
    assert planner is not None,response.text
    assert planner['status']=='ready'
    assert planner['metrics']['pre_generation'] is True
    assert planner['draft']['questions']==[]
    assert planner['draft']['scope_nodes']
    node=planner['draft']['scope_nodes'][0]
    task_id=UUID(planner['task_id'])
    with session_factory() as db:
        raw_snapshot=db.get(LearningTask,task_id).draft
        selected_snapshot=raw_snapshot['questions'][0]
        private_stem=selected_snapshot['stem']
        private_question_id=selected_snapshot['question_id']
        private_version=selected_snapshot['question_version']
    with session_factory() as db:
        eligible=question_availability(db,now=clock(),kp_ids=[UUID(node['kp_id'])],limit=10000)
    assert node['practice_eligible_count']==eligible['practice_eligible_count']
    assert node['assigned_count']>=1
    assert private_stem not in response.text
    assert private_question_id not in response.text
    assert private_version not in response.text
    after_preview=formal_rows(session_factory)
    assert after_preview['daily_plans']==before['daily_plans']==0
    assert after_preview['practice_items']==before['practice_items']==0
    assert after_preview['learning_tasks']==before['learning_tasks']+1

    with session_factory.begin() as db:
        task=db.get(LearningTask,task_id)
        raw=task.draft
        assert raw and raw['questions']
        selected=raw['questions'][0]
        request_id=uuid4()
        task.context={**task.context,'practice_request_id':str(request_id),
            'baseline':{'questions':[selected]},'legacy_fallback':{'candidate':selected}}
        task.trace=[{'tool':'find_questions','candidate':selected}]
        task.metrics={**task.metrics,'legacy_nested_fallback':{'candidate':selected}}
        task.message='PRIVATE LEGACY MESSAGE '+private_stem
        request=PracticeRequest(id=request_id,status='proposed',source_conversation_id=sid,
            user_request='安排一道洛必达题',planner_task_id=task_id,
            request={'target_knowledge_node_ids':[str(selected['kp_id'])],
                'available_minutes':planner['budget_minutes'],'requested_question_count':1,
                'confirmation_a':True,'preview_draft':raw,
                'plan_preview':{'budget_minutes':planner['budget_minutes'],'eligible_count':99,
                    'message':'PRIVATE PLAN FALLBACK '+private_stem,
                    'activities':[{'type':'practice','title':'PRIVATE ACTIVITY '+private_stem,
                        'minutes':planner['budget_minutes'],'question_count':1}],
                    'nested_fallback':{'question':selected}},
                'preview_trace':[selected],'legacy_fallback':{'question':selected}},
            expires_at=clock()+timedelta(hours=1),created_at=clock())
        db.add(request)
        db.flush()
        # Simulate an older persisted assistant response whose prose and nested
        # metadata contained candidate data. GET must project it without rewriting it.
        task_message=db.scalar(select(ChatMessage).where(ChatMessage.session_id==sid,
            ChatMessage.role=='assistant',ChatMessage.metadata_['planner_task_id'].as_string()==str(task_id)))
        assert task_message is not None
        task_message.content='PRIVATE LEGACY CHAT '+private_stem
        task_message.metadata_={**task_message.metadata_,'qa_handoff':{'question_id':private_question_id},
            'evaluation_evidence':{'blocks':[{'question':private_stem}],'contexts':[private_stem]}}
        db.add(ChatMessage(session_id=sid,role='assistant',content='PRIVATE REQUEST CHAT '+private_stem,
            status='completed',metadata_={'practice_request_id':str(request_id),
                'selection_trace':[selected],'fallback':{'question':selected}}))
        orphan_request_id=uuid4()
        orphan_message=ChatMessage(session_id=sid,role='assistant',content='PRIVATE ORPHAN CHAT '+private_stem,
            status='completed',metadata_={'practice_request_id':str(orphan_request_id),
                'evaluation_evidence':{'contexts':[private_stem]},'fallback':{'question':selected}})
        db.add(orphan_message)
        db.flush()
        orphan_message_id=orphan_message.id

    public_task_response=client.get(f'/api/learning-tasks/{task_id}')
    assert public_task_response.status_code==200,public_task_response.text
    safe_task=public_task_response.json()
    assert safe_task['draft']['questions']==[]
    assert safe_task['metrics']=={'pre_generation':True,'planning_origin':'assistant'}
    assert private_stem not in public_task_response.text
    assert private_question_id not in public_task_response.text
    assert private_version not in public_task_response.text

    request_response=client.get(f'/api/practice-requests/{request_id}')
    assert request_response.status_code==200,request_response.text
    safe_request=request_response.json()
    assert safe_request['details']['pre_generation'] is True
    assert safe_request['details']['plan_summary']['scope_nodes'][0]['practice_eligible_count']==eligible['practice_eligible_count']
    for forbidden in (private_stem,private_question_id,private_version,'PRIVATE PLAN FALLBACK','PRIVATE ACTIVITY'):
        assert forbidden not in request_response.text
    listing=client.get('/api/practice-requests',params={'source_conversation_id':str(sid)})
    assert listing.status_code==200,listing.text
    assert private_stem not in listing.text and private_question_id not in listing.text
    client.raise_server_exceptions=True
    try:
        plan_response=client.post(f'/api/practice-requests/{request_id}/plan',json={'study_session_id':str(sid)})
    finally:
        client.raise_server_exceptions=False
    assert plan_response.status_code==200,plan_response.text
    assert plan_response.json()['task']['draft']['questions']==[]
    assert plan_response.json()['task']['metrics']['pre_generation'] is True
    assert private_stem not in plan_response.text and private_question_id not in plan_response.text

    replay=client.post(f'/api/chat/sessions/{sid}/assistant:stream?purpose=study',json={
        'question':'安排一道洛必达题，30分钟。',
        'study_context':{'surface':'study','conversation_id':str(sid)},
        'request_key':str(request_key)})
    assert replay.status_code==200,replay.text
    replay_events=_sse_events(replay.text)
    replay_task=next((value for event,value in replay_events if event=='planner'),None)
    assert replay_task and replay_task['draft']['questions']==[]
    assert private_stem not in replay.text and private_question_id not in replay.text and private_version not in replay.text

    with session_factory.begin() as db:
        task_message=db.scalar(select(ChatMessage).where(ChatMessage.session_id==sid,
            ChatMessage.role=='assistant',ChatMessage.metadata_['planner_task_id'].as_string()==str(task_id)))
        saved_metadata=dict(task_message.metadata_)
        task_message.content='PRIVATE ORPHAN REPLAY '+private_stem
        task_message.metadata_={**saved_metadata,'planner_task_id':None,
            'practice_request_id':str(uuid4())}
    orphan_replay=client.post(f'/api/chat/sessions/{sid}/assistant:stream?purpose=study',json={
        'question':'安排一道洛必达题，30分钟。',
        'study_context':{'surface':'study','conversation_id':str(sid)},
        'request_key':str(request_key)})
    assert orphan_replay.status_code==200,orphan_replay.text
    assert 'PRIVATE ORPHAN REPLAY' not in orphan_replay.text
    assert private_stem not in orphan_replay.text and private_question_id not in orphan_replay.text
    assert '无法重新核验' in orphan_replay.text
    with session_factory.begin() as db:
        task_message=db.get(ChatMessage,task_message.id)
        task_message.content='PRIVATE LEGACY CHAT '+private_stem
        task_message.metadata_=saved_metadata

    monkeypatch.setattr(client.app.state.settings,'capture_test_evidence',True)
    history=client.get(f'/api/chat/sessions/{sid}/messages?purpose=study')
    assert history.status_code==200,history.text
    assert private_stem not in history.text and private_question_id not in history.text
    rows=history.json()
    projected_task=next(item for item in rows if item.get('planner_task_id')==str(task_id))
    assert projected_task['qa_handoff'] is None
    assert projected_task['evaluation_evidence'] is None
    projected_request=next(item for item in rows if item.get('practice_request_id')==str(request_id))
    assert projected_request['practice_request_id']==str(request_id)
    projected_orphan=next(item for item in rows if item['message_id']==str(orphan_message_id))
    assert projected_orphan['practice_request_id'] is None
    assert projected_orphan['evaluation_evidence'] is None
    with session_factory() as db:
        task=db.get(LearningTask,task_id)
        assert task.message=='PRIVATE LEGACY MESSAGE '+private_stem
        assert task.draft==raw
        persisted=db.scalar(select(ChatMessage).where(ChatMessage.session_id==sid,
            ChatMessage.role=='assistant',ChatMessage.metadata_['practice_request_id'].as_string()==str(request_id)))
        assert persisted.content=='PRIVATE REQUEST CHAT '+private_stem
    assert formal_rows(session_factory)['daily_plans']==0

    confirmed=client.post(f'/api/learning-tasks/{task_id}/confirm',json={
        'draft_version':safe_task['draft_version'],'session_id':str(sid)})
    assert confirmed.status_code==200,confirmed.text
    assert confirmed.json()['metrics']['commit']['added_count']==1
    assert private_question_id in confirmed.text and private_stem in confirmed.text
    repeated=client.post(f'/api/learning-tasks/{task_id}/confirm',json={
        'draft_version':safe_task['draft_version'],'session_id':str(sid)})
    assert repeated.status_code==200,repeated.text
    assert repeated.json()['metrics']['commit']==confirmed.json()['metrics']['commit']
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(DailyPlan))==1
        assert db.scalar(select(func.count()).select_from(PracticeItem))==1
        assert db.get(PracticeRequest,request_id).status=='accepted'
    request_after=client.get(f'/api/practice-requests/{request_id}')
    assert request_after.status_code==200
    assert private_stem in request_after.text


def test_named_multi_topic_count_adjustment_builds_one_editable_proposal(client, home, session_factory):
    sid=UUID(home['session_id'])
    prior=client.post(ROOT,json={'session_id':str(sid),'request_key':uuid4().hex,'goal':'','action':'default',
        'selected_kp_ids':[home['linear']],'budget_minutes':90})
    assert prior.status_code==200,prior.text
    with session_factory.begin() as db:
        lhopital,_=_add_synthetic_topic(db,code='synthetic.pregen.lhopital',name='洛必达法则（验收样例）')
        implicit,_=_add_synthetic_topic(db,code='synthetic.pregen.implicit',name='隐函数求导（验收样例）')
        left,right=str(lhopital.id),str(implicit.id)
    before=formal_rows(session_factory)
    initial=client.post(ROOT,json={'session_id':str(sid),'request_key':uuid4().hex,'goal':'','action':'default',
        'selected_kp_ids':[left,right],'budget_minutes':90,'expected_version':prior.json()['draft_version']})
    assert initial.status_code==200,initial.text
    proposal=initial.json()
    initial_counts={row['kp_id']:row['assigned_count'] for row in proposal['draft']['scope_nodes']}
    assert initial_counts[left]==1 and initial_counts[right]==1
    assert formal_rows(session_factory)['daily_plans']==0

    edited=client.post(ROOT,json={'session_id':str(sid),'request_key':uuid4().hex,
        'goal':'帮我减少几道洛必达法则的题目，增加几道隐函数的题目。','action':'adjust',
        'expected_version':proposal['draft_version']})
    assert edited.status_code==200,edited.text
    result=edited.json()
    assert result['status']=='ready',{key:result.get(key) for key in ('status','message','error_code','context')}
    assert result['draft']['selected_kp_ids']==[left,right]
    counts={row['kp_id']:row['assigned_count'] for row in result['draft']['scope_nodes']}
    assert counts[left]==initial_counts[left]-1 and counts[right]==initial_counts[right]+1
    assert result['draft']['question_count']==proposal['draft']['question_count']
    assert '洛必达法则' in result['message'] and '减少1道' in result['message']
    assert '隐函数求导' in result['message'] and '增加1道' in result['message']
    assert '每个“几道”先按1道' in result['message']
    assert result['draft']['questions']==[]
    after=formal_rows(session_factory)
    assert after['daily_plans']==before['daily_plans']==0
    assert after['practice_items']==before['practice_items']==0
    assert after['learning_tasks']==before['learning_tasks']+2
    reread=client.get(f'{ROOT}',params={'session_id':str(sid)})
    assert reread.status_code==200 and reread.json()['draft']==result['draft']


def test_same_topic_quantity_correction_and_unknown_easy_level_keep_context_without_guessing(client, home, session_factory):
    sid=UUID(home['session_id'])
    initial=client.post(ROOT,json={'session_id':str(sid),'request_key':uuid4().hex,'goal':'','action':'default',
        'selected_kp_ids':[home['lh']],'budget_minutes':90})
    assert initial.status_code==200,initial.text
    before_counts={row['kp_id']:row['assigned_count'] for row in initial.json()['draft']['scope_nodes']}
    assert before_counts[home['lh']]>=1
    current=initial.json()
    if before_counts[home['lh']]<2:
        # Ensure the correction follows a real multi-item state even when the
        # fixture selector starts with only one L'Hopital item.
        current=client.post(ROOT,json={'session_id':str(sid),'request_key':uuid4().hex,
            'goal':'那给我增加一道洛必达法则的题目。','action':'adjust',
            'expected_version':current['draft_version']}).json()
        assert current['status']=='ready',current
    append_counts={row['kp_id']:row['assigned_count'] for row in current['draft']['scope_nodes']}
    assert append_counts[home['lh']]>=2
    refreshed=client.get(ROOT,params={'session_id':str(sid)})
    assert refreshed.status_code==200
    assert refreshed.json()['draft_version']==current['draft_version']
    assert refreshed.json()['draft']==current['draft']
    before=formal_rows(session_factory)

    corrected=client.post(ROOT,json={'session_id':str(sid),'request_key':uuid4().hex,
        'goal':'帮我减少两道洛必达法则的题目，减少1道吧。','action':'adjust',
        'expected_version':current['draft_version']})
    assert corrected.status_code==200,corrected.text
    wire=corrected.json()
    assert wire['status']=='ready',wire
    assert wire['draft']['questions']==[]
    plan=read_home_domain(client,sid)
    after_counts={row['kp_id']:row['assigned_count'] for row in plan['draft']['scope_nodes']}
    assert after_counts[home['lh']]==append_counts[home['lh']]-1
    assert '洛必达法则' in plan['message'] and '减少1道' in plan['message']
    task_count=formal_rows(session_factory)['learning_tasks']

    ambiguous=client.post(ROOT,json={'session_id':str(sid),'request_key':uuid4().hex,
        'goal':'减少一道比较简单的吧。','action':'adjust','expected_version':plan['draft_version']})
    assert ambiguous.status_code==200,ambiguous.text
    clarification=ambiguous.json()
    assert clarification.get('kind')=='explanation'
    assert '没有可核验的逐题难度依据' in clarification['message']
    reread=client.get(ROOT,params={'session_id':str(sid)})
    assert reread.status_code==200 and reread.json()['draft']==wire['draft']
    assert read_home_domain(client,sid)['draft']==plan['draft']
    after=formal_rows(session_factory)
    assert after['daily_plans']==before['daily_plans']==0
    assert after['practice_items']==before['practice_items']==0
    assert after['learning_tasks']==task_count


def test_single_topic_addition_changes_the_live_draft_by_one_formally_eligible_question(client, home, session_factory):
    sid=UUID(home['session_id'])
    before=formal_rows(session_factory)
    initial=client.post(ROOT,json={'session_id':str(sid),'request_key':uuid4().hex,'goal':'','action':'default',
        'selected_kp_ids':[home['lh']],'budget_minutes':90})
    assert initial.status_code==200,initial.text
    before_count=initial.json()['draft']['question_count']
    assert before_count>=1

    changed=client.post(ROOT,json={'session_id':str(sid),'request_key':uuid4().hex,
        'goal':'那给我增加一道洛必达法则的题目。','action':'adjust',
        'expected_version':initial.json()['draft_version']})
    assert changed.status_code==200,changed.text
    result=changed.json()
    assert result['status']=='ready',result
    assert result['draft']['question_count']==before_count+1
    assert result['draft']['questions']==[]
    draft=read_home_domain(client,sid)['draft']
    target_node=next((node for node in draft['scope_nodes'] if node['kp_id']==home['lh']),None)
    assert target_node is not None and target_node['assigned_count']==before_count+1
    assert len(draft['questions'])==before_count+1 and all(q['kp_id']==home['lh'] for q in draft['questions'])
    after=formal_rows(session_factory)
    assert after['daily_plans']==before['daily_plans']==0
    assert after['practice_items']==before['practice_items']==0
    assert after['learning_tasks']==before['learning_tasks']+2


@pytest.mark.parametrize('initial_goal', [
    '帮我把当前这些内容都换成408的题目，我今天打算做1个小时408的。',
    '今天安排一个小时的408。',
    '根据我没有做过的知识点安排六个408知识点，60分钟左右。',
])
def test_cross_subject_replacement_uses_six_low_history_408_topics_and_keeps_math_out(client, home, session_factory, initial_goal):
    sid=UUID(home['session_id'])
    initial=client.post(ROOT,json={'session_id':str(sid),'request_key':uuid4().hex,'goal':'','action':'default',
        'selected_kp_ids':[home['linear']],'budget_minutes':90})
    assert initial.status_code==200,initial.text
    baseline_ids=set(initial.json()['draft']['selected_kp_ids'])
    with session_factory.begin() as db:
        for index in range(6):
            _add_synthetic_topic(db,code=f'synthetic.pregen.cs408.unseen.{index}',
                name=f'408未学习验收知识点{index+1}',subject='408')
    before=formal_rows(session_factory)

    first=client.post(ROOT,json={'session_id':str(sid),'request_key':uuid4().hex,
        'goal':initial_goal,'action':'adjust',
        'expected_version':initial.json()['draft_version']})
    assert first.status_code==200,first.text
    proposal=first.json()
    assert proposal.get('status')=='ready', {
        'kind':proposal.get('kind'),'message':proposal.get('message'),
        'intent_trace':proposal.get('intent_trace'),'response':proposal,
    }
    assert len(proposal['draft']['selected_kp_ids'])==6
    assert set(proposal['draft']['selected_kp_ids']).isdisjoint(baseline_ids)
    assert all(node['assigned_count']>=1 for node in proposal['draft']['scope_nodes'])
    assert 50<=proposal['draft']['total_minutes']<=60
    assert proposal['draft']['question_count']>=6
    with session_factory() as db:
        selected=[db.get(KnowledgePoint,UUID(value)) for value in proposal['draft']['selected_kp_ids']]
        assert all(node and (node.subject in {'408','cs408','计算机学科专业基础'} or node.code.startswith('cs408')) for node in selected)
        assert db.scalar(select(func.count()).select_from(DailyPlan))==0
        assert db.scalar(select(func.count()).select_from(PracticeItem))==0

    second=client.post(ROOT,json={'session_id':str(sid),'request_key':uuid4().hex,
        'goal':'根据我没有做过的知识点来进行安排题目就好，把当前的题目都换了，你安排6个知识点的408题目，题量是1个小时左右的。',
        'action':'adjust','expected_version':proposal['draft_version']})
    assert second.status_code==200,second.text
    revised=second.json()
    assert revised['status']=='ready',revised
    assert len(revised['draft']['selected_kp_ids'])==6
    assert set(revised['draft']['selected_kp_ids']).isdisjoint(baseline_ids)
    assert all(node['assigned_count']>=1 for node in revised['draft']['scope_nodes'])
    with session_factory() as db:
        from backend.models.learning_task import LearningTask
        stored=db.get(LearningTask,UUID(revised['task_id']))
        assert all(topic['attempt_count']==0 for topic in stored.context['subject_plan']['topics'])
    assert '安排6个知识点' in revised['message'] and '尚未生成正式今日卷' in revised['message']
    with session_factory() as db:
        from backend.models.learning import QuestionAttempt
        assert db.scalar(select(func.count()).select_from(QuestionAttempt).where(
            QuestionAttempt.kp_id.in_([UUID(value) for value in revised['draft']['selected_kp_ids']])))==0
    after=formal_rows(session_factory)
    assert after['daily_plans']==before['daily_plans']==0
    assert after['practice_items']==before['practice_items']==0
    assert after['learning_tasks']==before['learning_tasks']+2


def test_home_study_question_lookup_is_blindbox_and_does_not_create_a_plan(home, session_factory):
    sid=UUID(home['session_id'])
    context=StudyContext(surface='study',conversation_id=sid,knowledge_node_ids=[UUID(home['lh'])])
    with session_factory() as db:
        q=db.scalar(select(Question).where(Question.kp_id==UUID(home['lh'])).order_by(Question.id))
        assert q is not None
        secret=(q.stem,q.correct_answer,q.explanation,str(q.id))
        options=list((q.options or {}).values())
    before=formal_rows(session_factory)
    talk(session_factory,sid,AssistantRequest(question='给我看一道洛必达法则的练习题，先不要加入今日卷。',
        study_context=context),NoModel())
    answer=reply(session_factory,sid)
    assert '符合正式准入条件' in answer.content
    assert '今日正式学习卷尚未生成' in answer.content
    assert 'preview_questions' in answer.metadata_['read_only_data_query']
    assert answer.metadata_['read_only_data_query']['preview_questions']==[]
    assert answer.metadata_['read_only_data_query']['returned_preview_count']==0
    assert all(value not in answer.content for value in secret if value)
    assert all(value not in answer.content for value in options if value)
    assert formal_rows(session_factory)==before


def test_followup_candidate_endpoint_cannot_reveal_question_before_generation(client, home, session_factory):
    sid=UUID(home['session_id'])
    with session_factory() as db:
        q=db.scalar(select(Question).where(Question.kp_id==UUID(home['lh'])).order_by(Question.id))
        assert q is not None
        secret=(q.stem,str(q.id))
    with session_factory.begin() as db:
        db.add(ChatMessage(session_id=sid,role='assistant',status='completed',content='可继续练习。',
            matched_kp_id=UUID(home['lh']),metadata_={'study_context':{'surface':'study'}}))
    before=formal_rows(session_factory)
    response=client.post(f'/api/chat/sessions/{sid}/followup-candidates',params={'purpose':'study'},json={})
    assert response.status_code==200,response.text
    assert response.json()['candidates']==[]
    assert all(value not in response.text for value in secret if value)
    assert formal_rows(session_factory)==before


def test_legacy_home_preview_history_is_redacted_by_messages_api_before_generation(client, home, session_factory, monkeypatch):
    sid=UUID(home['session_id'])
    with session_factory() as db:
        q=db.scalar(select(Question).where(Question.kp_id==UUID(home['lh'])).order_by(Question.id))
        question_version=question_version_reference(q)
        sentinel=f'PRIVATE_PREGEN_STEM_{q.id}'
    with session_factory.begin() as db:
        db.add(ChatMessage(session_id=sid,role='assistant',status='completed',content=sentinel+' OPTION_SECRET',
            metadata_={'read_only_data_query':{'query_type':'find','preview_generated_at':NOW.isoformat(),
                'question_id':str(q.id),'preview_questions':[{'question_id':str(q.id),
                    'question_version':question_version,'kp_id':str(q.kp_id)}]},
                'personal_generation':{'question':sentinel+' NESTED_QUESTION_SECRET'},
                'current_work':{'stem':'NESTED_STEM_SECRET'},
                'web_sources':[{'title':'NESTED_SOURCE_SECRET'}],
                'generation_trace':{'selected_question':'NESTED_TRACE_SECRET'}}))
    monkeypatch.setattr(client.app.state.settings,'capture_test_evidence',True)
    response=client.get(f'/api/chat/sessions/{sid}/messages',params={'purpose':'study'})
    assert response.status_code==200,response.text
    wire=response.text
    assert sentinel not in wire and 'OPTION_SECRET' not in wire
    for secret in ('NESTED_QUESTION_SECRET','NESTED_STEM_SECRET','NESTED_SOURCE_SECRET','NESTED_TRACE_SECRET'):
        assert secret not in wire
    assert '今日正式学习卷尚未生成' in wire
    assert str(q.id) not in wire and question_version not in wire


def test_legacy_candidate_cannot_be_resurrected_as_a_question_reference_before_generation(home, session_factory):
    sid=UUID(home['session_id'])
    with session_factory() as db:
        q=db.scalar(select(Question).where(Question.kp_id==UUID(home['lh'])).order_by(Question.id))
        ref={'question_id':str(q.id),'question_version':question_version_reference(q),'kp_id':str(q.kp_id)}
    with session_factory.begin() as db:
        db.add(ChatMessage(session_id=sid,role='assistant',status='completed',content='旧版遗留候选',
            metadata_={'read_only_data_query':{'query_type':'find','preview_generated_at':NOW.isoformat(),
                'preview_questions':[ref]}}))
    result,notice=latest_preview(session_factory,sid,'把刚才那道题加入今天的学习',NOW+timedelta(minutes=1))
    assert result is None
    assert '尚未生成' in notice
    assert formal_rows(session_factory)['daily_plans']==0


def test_explicit_confirmation_is_the_only_transition_to_formal_today_paper_and_repeat_is_idempotent(client, home, session_factory):
    response=client.post(ROOT,json={'session_id':home['session_id'],'request_key':uuid4().hex,
        'goal':'','action':'default','selected_kp_ids':[home['linear']],'budget_minutes':90})
    assert response.status_code==200,response.text
    preview=response.json()
    assert preview['draft']['questions']==[]
    assert formal_rows(session_factory)['daily_plans']==0
    confirmation={'session_id':home['session_id'],'draft_version':preview['draft_version'],
        'confirm_legacy_set_transition_ids':[]}
    first=client.post(f"{ROOT}/{preview['task_id']}/confirm",json=confirmation)
    assert first.status_code==200,first.text
    second=client.post(f"{ROOT}/{preview['task_id']}/confirm",json=confirmation)
    assert second.status_code==200,second.text
    assert second.json()['receipt']==first.json()['receipt']
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(DailyPlan))==1
        saved=db.get(LearningTask,UUID(preview['task_id']))
        expected=[(q['question_id'],q['question_version_id']) for q in saved.draft['questions']]
        assert db.scalar(select(func.count()).select_from(PracticeItem))==len(expected)
    active=client.get('/api/plans/today')
    assert active.status_code==200,active.text
    assert [(row['question_id'],row['question_version_id']) for row in active.json()['items']]==expected


def test_question_conditional_delay_and_negation_never_generate_a_formal_paper(client, home, session_factory):
    base=client.post(ROOT,json={'session_id':home['session_id'],'request_key':uuid4().hex,
        'goal':'','action':'default','selected_kp_ids':[home['lh']],'budget_minutes':90})
    assert base.status_code==200,base.text
    current=base.json()
    before=formal_rows(session_factory)
    for text in ('能不能加入一道洛必达法则的题目？','要不要加入这道题？','先预览再决定。',
        '先不要加入今日卷。','不要生成今日卷。','等我确认以后再生成。'):
        response=client.post(ROOT,json={'session_id':home['session_id'],'request_key':uuid4().hex,
            'goal':text,'action':'adjust','expected_version':current['draft_version']})
        assert response.status_code==200,response.text
        payload=response.json()
        assert payload.get('kind')=='explanation' or payload.get('status') in {'ready','needs_info'}
        if payload.get('status')=='ready':
            current=payload
        assert payload.get('draft',{}).get('questions',[])==[]
        counts=formal_rows(session_factory)
        assert counts['daily_plans']==0
        assert counts['practice_items']==0
    after=formal_rows(session_factory)
    assert after['daily_plans']==before['daily_plans']==0
    assert after['practice_items']==before['practice_items']==0


def test_home_task_generic_api_cannot_leak_candidates_or_bypass_home_confirmation(client,home,session_factory,clock):
    import re
    from copy import deepcopy
    from backend.services.learning_task_service import get_task
    from backend.services.planning_public_view import public_task
    response=client.post(ROOT,json={'session_id':home['session_id'],'request_key':uuid4().hex,
        'goal':'','action':'default','selected_kp_ids':[home['lh']],'budget_minutes':90})
    assert response.status_code==200,response.text
    proposal=response.json();task_id=UUID(proposal['task_id'])
    with session_factory.begin() as db:
        task=db.get(LearningTask,task_id)
        private=deepcopy(task.draft)
        question=db.get(Question,UUID(private['questions'][0]['question_id']))
        hidden_stem=question.stem
        task.trace=[{'result':{'questions':deepcopy(private['questions'])}}]
        task.metrics={**(task.metrics or {}),'fallback':{'baseline':deepcopy(private)}}
        task.message=hidden_stem
        snapshot=(deepcopy(task.draft),deepcopy(task.trace),deepcopy(task.metrics),task.message)
    # Exercise the projection directly before the HTTP response serializes it;
    # this also preserves a full traceback if the domain view fails.
    public_task_response_view=public_task(session_factory,get_task(session_factory,task_id),now=clock())
    assert public_task_response_view.metrics['pre_generation'] is True
    read=client.get(f'/api/learning-tasks/{task_id}')
    assert read.status_code==200,read.text
    public=read.json()
    assert public['draft']['questions']==[]
    assert public['draft']['question_count']==len(private['questions'])
    assert public['draft_version']==proposal['draft_version']
    assert public['trace']==[] and public['metrics']=={'pre_generation':True,'planning_origin':'homepage'}
    assert hidden_stem not in read.text
    assert not re.search(r'"(?:question_id|question_version_id|stem|options|correct_answer|explanation)"',read.text)
    for ref in private['questions']:
        assert ref['question_id'] not in read.text and ref['question_version_id'] not in read.text
    with session_factory() as db:
        for node in public['draft']['scope_nodes']:
            actual=question_availability(db,now=clock(),kp_ids=[UUID(node['kp_id'])],limit=10000)
            assert node['name'] and node['practice_eligible_count']==actual['practice_eligible_count']
    for method,path,body in [
        ('patch',f'/api/learning-tasks/{task_id}',{'goal':'改成其他内容','budget_minutes':60}),
        ('post',f'/api/learning-tasks/{task_id}/cancel',None),
        ('post',f'/api/learning-tasks/{task_id}/run',None),
        ('post',f'/api/learning-tasks/{task_id}/confirm',{'draft_version':proposal['draft_version'],'session_id':home['session_id']}),
    ]:
        blocked=getattr(client,method)(path,**({'json':body} if body is not None else {}))
        assert blocked.status_code==409,blocked.text
    assert formal_rows(session_factory)['daily_plans']==0
    with session_factory() as db:
        task=db.get(LearningTask,task_id)
        assert (task.draft,task.trace,task.metrics,task.message)==snapshot
    # An old persisted chat reply must not resurrect the same hidden candidate
    # through history or idempotent SSE replay. Its private record is retained.
    import json
    from backend.services.learning_assistant_service import begin_turn
    from tests.integration.test_learning_assistant import talk
    body=AssistantRequest(question='先预览方案',request_key=uuid4(),study_context=StudyContext(
        surface='study',conversation_id=UUID(home['session_id']),task_id=task_id))
    _,message_id,_,replayed=begin_turn(session_factory,session_id=UUID(home['session_id']),body=body,now=clock())
    assert not replayed
    with session_factory.begin() as db:
        stored=db.get(ChatMessage,message_id)
        stored.status='completed';stored.content=hidden_stem
        stored.metadata_={**stored.metadata_,'planner_task_id':str(task_id),
            'qa_handoff':{'question_id':private['questions'][0]['question_id']}}
    history=client.get(f"/api/chat/sessions/{home['session_id']}/messages?purpose=study")
    assert history.status_code==200,history.text
    assert hidden_stem not in history.text
    entry=next(item for item in history.json() if item['message_id']==str(message_id))
    assert entry['planner_task_id']==str(task_id) and entry['qa_handoff'] is None
    frames=talk(session_factory,UUID(home['session_id']),body,NoModel())
    wire=json.dumps(frames,ensure_ascii=False)
    assert frames[-1][0]=='done' and hidden_stem not in wire
    assert not re.search(r'"(?:question_id|question_version_id|stem|options|correct_answer|explanation)"',wire)
    rejected=talk(session_factory,UUID(home['session_id']),AssistantRequest(
        question='少一点',request_key=uuid4(),study_context=body.study_context),NoModel())
    assert rejected[-1][0]=='done' and rejected[-1][1]['notice_code']=='home_planning_workflow_required',rejected
    assert '今日学习首页' in rejected[-1][1]['answer']
    assert hidden_stem not in json.dumps(rejected,ensure_ascii=False)
    with session_factory() as db:
        assert db.get(ChatMessage,message_id).content==hidden_stem
        task=db.get(LearningTask,task_id)
        assert (task.draft,task.trace,task.metrics,task.message)==snapshot
    confirmed=client.post(f'{ROOT}/{task_id}/confirm',json={
        'session_id':home['session_id'],'draft_version':proposal['draft_version'],
        'confirm_legacy_set_transition_ids':[]})
    assert confirmed.status_code==200,confirmed.text
    assert formal_rows(session_factory)['daily_plans']==1
    generated=client.get(f'/api/learning-tasks/{task_id}')
    assert generated.status_code==200,generated.text
    assert [row['question_id'] for row in generated.json()['draft']['questions']]==[
        row['question_id'] for row in private['questions']]
