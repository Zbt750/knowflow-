import pytest
import json
from sqlalchemy import select, func
from uuid import UUID
from backend.models.chat import ChatSession
from backend.models.learning import Question, DailyPlan, KpMasteryPolicy, KpState
from tests.integration.test_home_recommendation import client, clock, session_factory, clean_database, home, post, counts, ROOT, read_home_domain
from tests.integration.test_learning_loop import mark_isolated_question_trusted


def _prepare_first_turn_add(monkeypatch, home, session_factory, addition_minutes=(5, 5)):
    from backend.api.routes import study
    from backend.schemas.practice import RecommendationItem
    with session_factory.begin() as db:
        for q in db.scalars(select(Question).where(Question.kp_id == UUID(home['lh']))):
            q.is_active = False
        for index, minutes in enumerate(addition_minutes):
            q = Question(kp_id=UUID(home['lh']), question_type='single_choice',
                stem=f'SYNTHETIC 洛必达追加题 {index}: 1+1=?', options={'A':'2','B':'3'},
                correct_answer='A', explanation='1+1=2', estimated_minutes=minutes,
                grading_mode='auto', grading_config={'verified':True,'method':'single_choice'},
                difficulty='medium', is_active=True)
            mark_isolated_question_trusted(q, db=db)
    monkeypatch.setattr(study, '_recommendations', lambda db, now: [RecommendationItem(
        kp_id=UUID(home['linear']), name='线代诊断（SYNTHETIC）', state='insufficient_evidence',
        reason='insufficient_evidence')])


def _assert_public_paper_is_blindbox(response, paper, key='draft'):
    wire = response.json()
    public = wire[key]
    assert public['questions'] == []
    assert public['question_count'] == len(paper['questions'])
    payload = json.dumps(wire, ensure_ascii=False)
    forbidden = {'question_id', 'question_version_id', 'stem', 'options',
        'correct_answer', 'answer', 'explanation'}
    def keys(value):
        if isinstance(value, dict):
            found = set(value)
            for item in value.values():
                found.update(keys(item))
            return found
        if isinstance(value, list):
            found = set()
            for item in value:
                found.update(keys(item))
            return found
        return set()
    assert forbidden.isdisjoint(keys(wire))
    for question in paper['questions']:
        assert question['question_id'] not in payload
        if question.get('stem'):
            assert question['stem'] not in payload


def test_first_turn_add_keeps_system_recommendation_and_confirms_exact_merged_paper(client,home,session_factory,monkeypatch):
    _prepare_first_turn_add(monkeypatch,home,session_factory)
    before=counts(session_factory)
    result=post(client,home,'帮我加入两道洛必达法则的题进来')
    assert result['status']=='ready',result
    scope=result['context']['bank_scope']
    assert scope=={'base_scope_ids':[home['linear']],'additional_scope_ids':[home['lh']],
        'selected_scope_ids':[home['linear'],home['lh']],'additional_count':2,'scope_mode':'append'}
    assert result['context']['bank_selection']['scope_mode']=='append'
    assert result['context']['bank_selection']['requested_count']==2
    assert result['context']['bank_selection']['base_scope_ids']==[home['linear']]
    assert result['context']['bank_selection']['additional_scope_ids']==[home['lh']]
    base_ids={q['question_id'] for q in result['context']['baseline']['questions']}
    added_ids=set(result['context']['bank_selection']['selected_addition_ids'])
    assert len(base_ids)==3 and len(added_ids)==2 and base_ids.isdisjoint(added_ids)
    assert set(result['draft']['selected_kp_ids'])=={home['linear'],home['lh']}
    assert {q['question_id'] for q in result['draft']['questions']}==base_ids|added_ids
    assert result['draft']['diff']['retained']==sorted(base_ids)
    assert result['draft']['diff']['added']==sorted(added_ids)
    assert result['draft']['diff']['removed']==[]
    assert result['draft']['total_minutes']==90 and result['draft']['budget_minutes']==90
    assert '已保留原系统推荐范围' in result['message']
    assert '本次按你的专项范围调整' not in result['message']
    assert {q['kp_id'] for q in result['draft']['questions'] if q['question_id'] in added_ids}=={home['lh']}
    assert counts(session_factory)==before
    recovered=client.get(ROOT,params={'session_id':home['session_id']})
    assert recovered.status_code==200
    assert recovered.json()['task_id']==result['task_id']
    _assert_public_paper_is_blindbox(recovered,result['draft'])
    recovered_domain=read_home_domain(client,home['session_id'])
    assert recovered_domain['draft']['questions']==result['draft']['questions']
    assert recovered_domain['context']['bank_scope']==scope

    confirm=client.post(ROOT+'/'+result['task_id']+'/confirm',json={
        'session_id':home['session_id'],'draft_version':result['draft_version']})
    assert confirm.status_code==200,confirm.text
    repeated=client.post(ROOT+'/'+result['task_id']+'/confirm',json={
        'session_id':home['session_id'],'draft_version':result['draft_version']})
    assert repeated.status_code==200 and repeated.json()['receipt']==confirm.json()['receipt']
    from backend.models.learning import PracticeItem
    with session_factory() as db:
        items=list(db.scalars(select(PracticeItem).order_by(PracticeItem.ordinal)))
        assert [(str(i.question_id),str(i.question_version_id)) for i in items]==[
            (q['question_id'],q['question_version_id']) for q in result['draft']['questions']]
        assert db.scalar(select(func.count()).select_from(DailyPlan))==1


def test_first_turn_add_short_inventory_reports_actual_count_and_keeps_base(client,home,session_factory,monkeypatch):
    _prepare_first_turn_add(monkeypatch,home,session_factory,addition_minutes=(5,))
    before=counts(session_factory)
    result=post(client,home,'帮我加入两道洛必达法则的题进来')
    assert result['status']=='needs_info' and result['draft'] is None,result
    assert result['error_code']=='bank_candidates_insufficient'
    assert result['context']['bank_scope']['base_scope_ids']==[home['linear']]
    assert result['context']['bank_scope']['additional_scope_ids']==[home['lh']]
    assert len(result['context']['baseline']['questions'])==3
    evidence=result['context']['bank_selection']
    assert evidence['requested_count']==2 and len(evidence['candidate_ids'])==1
    assert '可新增 1 道，少于所需 2 道' in result['message']
    assert counts(session_factory)==before


def test_over_budget_continue_keeps_original_confirmable_and_refreshes_without_formal_writes(client,home,session_factory,monkeypatch):
    _prepare_first_turn_add(monkeypatch,home,session_factory,addition_minutes=(10,10))
    before=counts(session_factory)
    proposed=post(client,home,'帮我加入两道洛必达法则的题进来')
    assert proposed['context']['workload_pending'] is True
    original=proposed['fallback_preview']
    dismissed=post(client,home,action='dismiss_workload',target_task_id=proposed['task_id'],expected_version=proposed['draft_version'])
    assert dismissed['task_id']==original['task_id']
    assert dismissed['draft']['questions']==original['draft']['questions']
    assert dismissed['status']=='ready' and counts(session_factory)==before
    refreshed=client.get(ROOT,params={'session_id':home['session_id']})
    assert refreshed.status_code==200
    _assert_public_paper_is_blindbox(refreshed,original['draft'])
    assert read_home_domain(client,home['session_id'])['draft']==original['draft']
    confirmed=client.post(ROOT+'/'+original['task_id']+'/confirm',json={
        'session_id':home['session_id'],'draft_version':original['draft_version']})
    assert confirmed.status_code==200,confirmed.text


def test_first_turn_add_over_budget_reports_shortfall_without_dropping_base(client,home,session_factory,monkeypatch):
    _prepare_first_turn_add(monkeypatch,home,session_factory,addition_minutes=(10,10))
    before=counts(session_factory)
    result=post(client,home,'帮我加入两道洛必达法则的题进来')
    assert result['status']=='ready' and result['draft'] is not None,result
    assert result['error_code'] is None
    assert result['context']['bank_scope']['base_scope_ids']==[home['linear']]
    assert result['context']['bank_scope']['additional_scope_ids']==[home['lh']]
    evidence=result['context']['bank_selection']
    assert len(evidence['base_question_ids'])==3
    assert len(evidence['selected_addition_ids'])==2
    assert evidence['combined_minutes']==100 and evidence['budget_minutes']==90
    assert evidence['workload']['extra_minutes']==10
    assert result['draft']['total_minutes']==100
    refused=client.post(ROOT+'/'+result['task_id']+'/confirm',json={'session_id':home['session_id'],'draft_version':result['draft_version']})
    assert refused.status_code==422
    assert '比原预算90分钟多10分钟' in result['message']
    assert set(evidence['base_question_ids']).issubset(q['question_id'] for q in result['draft']['questions'])
    assert counts(session_factory)==before

    assert result['context']['workload_pending'] is True
    active=client.get(ROOT,params={'session_id':home['session_id']}).json()
    assert active['task_id']==result['fallback_preview']['task_id']
    assert active['workload_candidate']['task_id']==result['task_id']
    accepted=post(client,home,action='accept_workload',target_task_id=result['task_id'],expected_version=result['draft_version'])
    assert accepted['task_id']==result['task_id'] and accepted['context']['workload_accepted'] is True
    assert accepted['draft']['questions']==result['draft']['questions']
    assert counts(session_factory)==before  # Acceptance is not formal generation.
    confirmed=client.post(ROOT+'/'+result['task_id']+'/confirm',json={'session_id':home['session_id'],'draft_version':result['draft_version'],'accept_workload_increase':True})
    assert confirmed.status_code==200,confirmed.text
    repeated=client.post(ROOT+'/'+result['task_id']+'/confirm',json={'session_id':home['session_id'],'draft_version':result['draft_version'],'accept_workload_increase':True})
    assert repeated.status_code==200 and repeated.json()['receipt']==confirmed.json()['receipt']
    from backend.models.learning import PracticeItem
    with session_factory() as db:
        items=list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id==confirmed.json()['receipt']['plan_id']).order_by(PracticeItem.ordinal)))
        assert [(str(i.question_id),str(i.question_version_id)) for i in items]==[(q['question_id'],q['question_version_id']) for q in result['draft']['questions']]


def test_addition_overlapping_base_scope_excludes_original_questions_from_candidates(client,home,session_factory,monkeypatch):
    _prepare_first_turn_add(monkeypatch,home,session_factory,addition_minutes=())
    before=counts(session_factory)
    result=post(client,home,'帮我加入一道题进来',budget_minutes=90,selected_kp_ids=[home['linear']])
    assert result['status']=='needs_info',result
    assert result['error_code']=='bank_candidates_insufficient'
    retained=set(result['context']['bank_selection']['base_question_ids'])
    candidates=set(result['context']['bank_selection']['candidate_ids'])
    assert len(retained)==3 and candidates.isdisjoint(retained)
    assert result['context']['bank_selection']['requested_count']==1
    assert result['context']['bank_scope']['selected_scope_ids']==[home['linear']]
    assert counts(session_factory)==before


def test_additive_preview_recovers_only_in_its_own_session(client,home,session_factory,monkeypatch):
    _prepare_first_turn_add(monkeypatch,home,session_factory)
    result=post(client,home,'帮我加入两道洛必达法则的题进来')
    with session_factory.begin() as db:
        other=ChatSession(mode='builtin',purpose='study',study_date='2026-01-01',title='SYNTHETIC other session')
        db.add(other);db.flush();other_id=str(other.id)
    assert client.get(ROOT,params={'session_id':other_id}).status_code==200
    assert client.get(ROOT,params={'session_id':other_id}).json() is None
    assert client.post(ROOT+'/'+result['task_id']+'/confirm',json={
        'session_id':other_id,'draft_version':result['draft_version']}).status_code==404
    restored=client.get(ROOT,params={'session_id':home['session_id']})
    assert restored.status_code==200
    assert restored.json()['task_id']==result['task_id']
    _assert_public_paper_is_blindbox(restored,result['draft'])
    restored_domain=read_home_domain(client,home['session_id'])
    assert restored_domain['context']['bank_scope']==result['context']['bank_scope']
    assert restored_domain['draft']['questions']==result['draft']['questions']


def test_addition_does_not_claim_success_when_system_base_cannot_be_built(client,home,session_factory,monkeypatch):
    _prepare_first_turn_add(monkeypatch,home,session_factory)
    from backend.services import home_recommendation_service as service
    original=service._paper
    calls={'count':0}
    def fail_initial_baseline(*args,**kwargs):
        calls['count']+=1
        if calls['count']==1:
            raise ValueError('synthetic baseline selector failure')
        return original(*args,**kwargs)
    monkeypatch.setattr(service,'_paper',fail_initial_baseline)
    before=counts(session_factory)
    result=post(client,home,'帮我加入两道洛必达法则的题进来')
    assert result['status']=='needs_info' and result['draft'] is None,result
    assert result['error_code']=='system_baseline_unavailable'
    assert result['context']['bank_selection']['baseline_error']=='synthetic baseline selector failure'
    assert calls['count']==1
    assert '没有追加题目或生成预览' in result['message']
    assert counts(session_factory)==before


def test_medium_add_keeps_existing_preview_and_confirms_exact_versions(client, home, session_factory):
    with session_factory.begin() as db:
        qs=list(db.scalars(select(Question).where(Question.kp_id==home['linear']).order_by(Question.estimated_minutes,Question.id)))
        for q in qs: q.difficulty='medium'
    base=post(client,home,'线性代数90分钟，只做1道题')
    before=counts(session_factory)
    result=post(client,home,'给我从那添加一道到今日卷里难度中等的。',expected_version=base['draft_version'])
    assert result['status']=='ready', result
    questions=result['draft']['questions']
    assert len(questions)==2
    assert set(q['question_id'] for q in base['draft']['questions']).issubset(q['question_id'] for q in questions)
    retained={q['question_id']:q['question_version_id'] for q in base['draft']['questions']}
    assert {q['question_id']:q['question_version_id'] for q in questions if q['question_id'] in retained}==retained
    additions=[q for q in questions if q['question_id'] not in retained]
    assert len(additions)==1 and additions[0]['kp_id']==home['linear'] and additions[0]['difficulty']=='medium'
    assert counts(session_factory)==before
    assert result['context']['bank_selection']['tool']=='find_questions'
    assert all(q['question_version_id'] for q in questions)
    stale=client.post(ROOT+'/'+base['task_id']+'/confirm',json={'session_id':home['session_id'],'draft_version':base['draft_version']})
    assert stale.status_code==409
    confirmed=client.post(ROOT+'/'+result['task_id']+'/confirm',json={'session_id':home['session_id'],'draft_version':result['draft_version']})
    assert confirmed.status_code==200, confirmed.text
    repeated=client.post(ROOT+'/'+result['task_id']+'/confirm',json={'session_id':home['session_id'],'draft_version':result['draft_version']})
    assert repeated.status_code==200
    assert counts(session_factory)['practice_items']==2


def test_medium_shortage_is_not_generic_qa_or_success(client,home,session_factory):
    base=post(client,home,'线性代数90分钟，只做1道题')
    before=counts(session_factory)
    result=post(client,home,'从当前推荐范围选一道题，难度中等。',expected_version=base['draft_version'])
    assert result['status']=='needs_info' and result['draft'] is None, result
    assert result['error_code']=='bank_candidates_insufficient'
    assert counts(session_factory)==before
    assert '通用知识' not in result['message']


def test_reference_without_scope_clarifies_and_does_not_choose_other_session(client,home,session_factory,clock):
    from backend.services.home_recommendation_service import adjust
    from backend.schemas.home_recommendation import HomeRecommendationRequest
    from uuid import uuid4
    # No recommendation and no same-session preview: never infer another topic.
    with session_factory.begin() as db:
        result=adjust(db, HomeRecommendationRequest(session_id=home['session_id'],request_key=uuid4().hex,goal='给我从那添加一道到今日卷里难度中等的。'),[],clock.now)
        assert result['status']=='needs_info' and result['draft'] is None
        assert result['error_code']=='bank_scope_needed'


def test_bank_tool_outage_is_failed_and_not_generic_qa(client,home,session_factory,monkeypatch):
    from backend.services.learning_task_tools import TaskTools
    base=post(client,home,'线性代数90分钟，只做1道题')
    before=counts(session_factory)
    def fail(*args,**kwargs): raise RuntimeError('synthetic bank outage')
    monkeypatch.setattr(TaskTools,'find_questions',fail)
    result=post(client,home,'给我从那添加一道到今日卷里难度中等的。',expected_version=base['draft_version'])
    assert result['status']=='failed' and result['error_code']=='bank_query_error'
    assert result['context']['bank_diagnostics']['stage']=='query'
    assert result['context']['bank_diagnostics']['exception_type']=='RuntimeError'
    assert result['context']['bank_diagnostics']['diagnostic_id']
    assert result['draft'] is None and counts(session_factory)==before
    assert result['fallback_preview']['task_id']==base['task_id']
    recovered=client.get(ROOT,params={'session_id':home['session_id']})
    assert recovered.status_code==200 and recovered.json()['task_id']==base['task_id']
    confirmed=client.post(ROOT+'/'+base['task_id']+'/confirm',json={'session_id':home['session_id'],'draft_version':base['draft_version']})
    assert confirmed.status_code==200,confirmed.text
    from backend.models.learning import PracticeItem
    with session_factory() as db:
        items=list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id==confirmed.json()['receipt']['plan_id']).order_by(PracticeItem.ordinal)))
        assert [(str(i.question_id),str(i.question_version_id)) for i in items]==[(q['question_id'],q['question_version_id']) for q in base['draft']['questions']]


def test_legacy_failed_task_retains_baseline_and_restores_before_exact_confirm(client,home,session_factory):
    from backend.models.learning_task import LearningTask
    from backend.models.learning import PracticeItem
    base=post(client,home,'线性代数90分钟，只做1道题')
    # Historical failure shape: no fallback pointer, but the original snapshot
    # was persisted. This setup is allowed only in the guarded isolated fixture.
    with session_factory.begin() as db:
        row=db.get(LearningTask,UUID(base['task_id']))
        row.context={**row.context,'baseline':row.draft}
        row.status='failed';row.error_code='bank_lookup_failed';row.draft=None
    before=counts(session_factory)
    recovered=client.get(ROOT,params={'session_id':home['session_id']})
    assert recovered.status_code==200
    failed=recovered.json()
    assert failed['status']=='failed' and failed['draft'] is None
    _assert_public_paper_is_blindbox(recovered,base['draft'],key='retained_baseline')
    failed_domain=read_home_domain(client,home['session_id'])
    assert failed_domain['retained_baseline']['questions']==base['draft']['questions']
    assert counts(session_factory)==before
    restored=post(client,home,action='restore',expected_version=failed['draft_version'])
    assert restored['status']=='ready' and restored['draft']['questions']==base['draft']['questions']
    assert counts(session_factory)==before
    body={'session_id':home['session_id'],'draft_version':restored['draft_version']}
    confirmed=client.post(ROOT+'/'+restored['task_id']+'/confirm',json=body)
    assert confirmed.status_code==200,confirmed.text
    repeated=client.post(ROOT+'/'+restored['task_id']+'/confirm',json=body)
    assert repeated.status_code==200 and repeated.json()['receipt']==confirmed.json()['receipt']
    with session_factory() as db:
        items=list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id==confirmed.json()['receipt']['plan_id']).order_by(PracticeItem.ordinal)))
        assert [(str(i.question_id),str(i.question_version_id)) for i in items]==[(q['question_id'],q['question_version_id']) for q in base['draft']['questions']]


def test_adding_named_node_preserves_old_scope_and_reports_actual_difficulty(client,home,session_factory):
    with session_factory.begin() as db:
        for q in db.scalars(select(Question).where(Question.kp_id==home['lh'])): q.difficulty='medium'
    base=post(client,home,'线性代数90分钟，只做1道题')
    result=post(client,home,'帮我找一道洛必达法则的题加入今日卷，难度中等。',expected_version=base['draft_version'])
    assert result['status']=='ready',result
    assert set(q['question_id'] for q in base['draft']['questions']).issubset(q['question_id'] for q in result['draft']['questions'])
    additions=[q for q in result['draft']['questions'] if q['question_id'] not in {q['question_id'] for q in base['draft']['questions']}]
    assert len(additions)==1 and additions[0]['kp_id']==home['lh'] and additions[0]['difficulty']=='medium'


def test_existing_formal_paper_is_not_overwritten_by_home_bank_request(client,home,session_factory):
    base=post(client,home,action='default',selected_kp_ids=[home['linear']],budget_minutes=90)
    response=client.post(ROOT+'/'+base['task_id']+'/confirm',json={'session_id':home['session_id'],'draft_version':base['draft_version']})
    assert response.status_code==200,response.text
    from uuid import uuid4
    from backend.models.chat import ChatSession
    other={**home,'session_id':str(uuid4())}
    with session_factory.begin() as db: db.add(ChatSession(id=other['session_id'],mode='builtin',purpose='study',study_date='2026-01-01',title='SYNTHETIC second topic'))
    before=counts(session_factory)
    blocked=client.post(ROOT,json={'session_id':other['session_id'],'request_key':str(uuid4()),
        'goal':'再加一道矩阵的秩，难度中等。','action':'adjust'})
    assert blocked.status_code==409 and blocked.json()['error']['code']=='plan_already_generated'
    assert counts(session_factory)==before


def test_addition_does_not_overrun_current_budget(client,home,session_factory):
    with session_factory.begin() as db:
        for q in db.scalars(select(Question).where(Question.kp_id==home['linear'])):q.difficulty='medium'
    base=post(client,home,'线性代数30分钟，只做1道题')
    assert base['budget_minutes']==30 and base['draft']['budget_minutes']==30
    before=counts(session_factory)
    result=post(client,home,'给我从那添加一道到今日卷里难度中等的。',expected_version=base['draft_version'])
    assert result['status']=='ready' and result['draft'] is not None,result
    assert result['error_code'] is None
    assert result['draft']['budget_minutes']==30
    if result['draft']['total_minutes']>30:
        assert result['context'].get('workload',{}).get('requires_confirmation') is True, {
            'total_minutes':result['draft']['total_minutes'],
            'budget_minutes':result['draft']['budget_minutes'],
            'bank_selection_workload':(result['context'].get('bank_selection') or {}).get('workload'),
            'validation':(result['context'].get('bank_selection') or {}).get('validation'),
        }
    else:
        assert not result['context'].get('workload')
    assert {q['question_id'] for q in base['draft']['questions']}.issubset(q['question_id'] for q in result['draft']['questions'])
    assert counts(session_factory)==before


def test_actual_study_stream_add_phrase_runs_bank_tools_without_generic_qa(client,home,session_factory):
    from tests.integration.test_learning_assistant import talk,reply,QAProvider
    from backend.schemas.learning_assistant import AssistantRequest,StudyContext
    from backend.models.chat import ChatSession
    from backend.models.learning import PracticeItem
    from uuid import uuid4
    with session_factory.begin() as db:
        # The system may choose any recommended leaf. Give that real selected
        # scope deterministic medium inventory before materializing its versions.
        for q in db.scalars(select(Question).where(Question.bank_scope=='public')): q.difficulty='medium'
    base=post(client,home,'线性代数90分钟，只做1道题')
    confirmed=client.post(ROOT+'/'+base['task_id']+'/confirm',json={'session_id':home['session_id'],'draft_version':base['draft_version']})
    assert confirmed.status_code==200,confirmed.text
    sid=uuid4()
    with session_factory.begin() as db:
        item=db.scalar(select(PracticeItem).where(PracticeItem.plan_id==confirmed.json()['receipt']['plan_id']))
        state=db.get(KpState,item.kp_id)
        policy=db.get(KpMasteryPolicy,item.kp_id)
        assert policy is not None and policy.policy_version==3 and policy.graduation_set_version>0
        assert state is not None and state.graduation_set_binding_status=='bound'
        assert state.graduation_set_version==policy.graduation_set_version
        plan_id=item.plan_id
        original=[(str(row.id),str(row.question_id),str(row.question_version_id),row.ordinal,row.completed_at)
            for row in db.scalars(select(PracticeItem).where(PracticeItem.plan_id==plan_id).order_by(PracticeItem.ordinal))]
        # Provide one additional, genuinely eligible synthetic candidate in
        # the current topic. Difficulty metadata alone does not make the seed's
        # other unreviewed items formally admissible.
        candidate=Question(kp_id=item.kp_id,question_type='single_choice',
            stem='SYNTHETIC stream append candidate: 3+4=?',options={'A':'6','B':'7'},
            correct_answer='B',explanation='SYNTHETIC: 3+4=7.',estimated_minutes=5,
            grading_mode='auto',grading_config={'verified':True,'method':'single_choice'},
            difficulty='medium',is_active=True)
        mark_isolated_question_trusted(candidate,db=db)
        db.add(ChatSession(id=sid,mode='builtin',purpose='study',study_date='2026-01-01'))
        ctx=StudyContext(surface='study',question_id=item.question_id,practice_item_id=item.id,daily_plan_id=item.plan_id,knowledge_node_ids=[item.kp_id])
    before=counts(session_factory)
    provider=QAProvider('不应调用的通用知识回答')
    frames=talk(session_factory,sid,AssistantRequest(question='给我从那添加一道到今日卷里难度中等的。',study_context=ctx),provider)
    assert provider.prompts==[]
    saved=reply(session_factory,sid)
    assert saved.metadata_['capability_route']['reason']=='explicit_bank_selection'
    assert saved.metadata_.get('planner_task_id'),frames
    with session_factory() as db:
        task=db.get(__import__('backend.models.learning_task',fromlist=['LearningTask']).LearningTask,saved.metadata_['planner_task_id'])
        assert task.status=='ready',task.message+' | trace='+repr(task.trace)
        assert len(task.draft['questions'])==1
        assert task.draft['questions'][0]['difficulty']=='medium'
        assert task.context['daily_plan_operation']=='append'
        assert task.context['planner_handoff']['constraints']['daily_plan_operation']=='append'
        assert task.context['current_plan_id']==str(plan_id)
        assert any(step['tool']=='find_questions' for step in task.trace)
    assert counts(session_factory)==before
    assert any(name=='done' for name,_ in frames)
    task_id=saved.metadata_['planner_task_id']
    preview_question=task.draft['questions'][0]
    other_session=uuid4()
    with session_factory.begin() as db:
        db.add(ChatSession(id=other_session,mode='builtin',purpose='study',study_date='2026-01-01'))
    wrong_session=client.post('/api/learning-tasks/'+task_id+'/confirm',json={
        'draft_version':__import__('backend.services.learning_task_service',fromlist=['_draft_version'])._draft_version(task),
        'session_id':str(other_session)})
    assert wrong_session.status_code==404
    missing_session=client.post('/api/learning-tasks/'+task_id+'/confirm',json={
        'draft_version':__import__('backend.services.learning_task_service',fromlist=['_draft_version'])._draft_version(task)})
    assert missing_session.status_code==404
    assert counts(session_factory)==before
    response=client.post('/api/learning-tasks/'+task_id+'/confirm',json={
        'draft_version':task.draft and __import__('backend.services.learning_task_service',fromlist=['_draft_version'])._draft_version(task),
        'session_id':str(sid)})
    assert response.status_code==200,response.text
    committed=response.json()['metrics']['commit']
    assert committed['plan_id']==str(plan_id) and committed['added_count']==1
    repeated=client.post('/api/learning-tasks/'+task_id+'/confirm',json={
        'draft_version':response.json()['draft_version'],'session_id':str(sid)})
    assert repeated.status_code==200 and repeated.json()['metrics']['commit']==committed
    from backend.models.learning import DailyPlan
    with session_factory() as db:
        current=[(str(row.id),str(row.question_id),str(row.question_version_id),row.ordinal,row.completed_at)
            for row in db.scalars(select(PracticeItem).where(PracticeItem.plan_id==plan_id).order_by(PracticeItem.ordinal))]
        assert current[:len(original)]==original
        assert len(current)==len(original)+1
        assert current[-1][1]==preview_question['question_id']
        assert current[-1][2]==preview_question['question_version']
        assert current[-1][3]==len(original)+1
        assert db.scalar(select(func.count()).select_from(DailyPlan))==1
    assert counts(session_factory)['practice_items']==before['practice_items']+1


def test_legacy_medium_difficulty_is_queried_without_guessing(client,home,session_factory):
    with session_factory.begin() as db:
        for q in db.scalars(select(Question).where(Question.kp_id==home['linear'])):q.difficulty='improved'
    base=post(client,home,'线性代数90分钟，只做1道题')
    result=post(client,home,'给我从那添加一道到今日卷里难度中等的。',expected_version=base['draft_version'])
    assert result['status']=='ready',result
    assert len(result['draft']['questions'])==2
    retained={q['question_id']:q['question_version_id'] for q in base['draft']['questions']}
    assert {q['question_id']:q['question_version_id'] for q in result['draft']['questions'] if q['question_id'] in retained}==retained
    additions=[q for q in result['draft']['questions'] if q['question_id'] not in retained]
    assert len(additions)==1 and additions[0]['kp_id']==home['linear']
    # Medium is a query alias for the stored legacy value "improved". The
    # unchanged baseline can include other real system recommendations with
    # different difficulty values; only the newly selected candidate is bound
    # to this request, and its stored value must be reported without guessing.
    assert additions[0]['difficulty']=='improved'


def test_manual_scope_save_has_no_dialogue_and_next_chat_uses_saved_scope_not_original_baseline(client,home,session_factory,monkeypatch):
    from backend.models.chat import ChatMessage
    _prepare_first_turn_add(monkeypatch,home,session_factory,addition_minutes=(5,5,5))
    def messages_count():
        with session_factory() as db:
            return db.scalar(select(func.count()).select_from(ChatMessage).where(ChatMessage.session_id==UUID(home['session_id'])))
    before_messages=messages_count();before_business=counts(session_factory)
    initial=post(client,home,action='default',selected_kp_ids=[home['linear']],budget_minutes=90)
    assert initial['status']=='ready' and messages_count()==before_messages
    saved=post(client,home,action='default',selected_kp_ids=[home['lh']],budget_minutes=5,expected_version=initial['draft_version'])
    assert saved['status']=='ready' and saved['draft']['selected_kp_ids']==[home['lh']]
    assert saved['context']['request_origin']=='system' and messages_count()==before_messages
    assert counts(session_factory)==before_business
    recovered=client.get(ROOT,params={'session_id':home['session_id']})
    assert recovered.status_code==200
    _assert_public_paper_is_blindbox(recovered,saved['draft'])
    assert read_home_domain(client,home['session_id'])['draft']==saved['draft']
    history_path=f"/api/chat/sessions/{home['session_id']}/messages?purpose=study"
    history=client.get(history_path)
    assert history.status_code==200 and history.json()==[]
    chatted=post(client,home,'再帮我加入一道洛必达法则的题目。',expected_version=saved['draft_version'])
    assert chatted['status']=='ready' and chatted['context']['request_origin']=='chat'
    assert chatted['context']['bank_scope']['base_scope_ids']==[home['lh']]
    assert {q['question_id'] for q in saved['draft']['questions']}.issubset(q['question_id'] for q in chatted['draft']['questions'])
    assert home['linear'] not in chatted['draft']['selected_kp_ids']  # Explicit manual removal stays removed.
    assert messages_count()==before_messages+2 and counts(session_factory)==before_business
    assert all(m['content']!='查看系统推荐' for m in client.get(history_path).json())


@pytest.mark.parametrize('goal',['帮我增加一道洛必达法则的题目。','帮我加入一道洛必达法则的题目','洛必达法则的题你再给我加一道'])
def test_increase_one_from_five_keeps_original_ids_versions_order_and_confirms_exactly(client,home,session_factory,monkeypatch,goal):
    from backend.models.learning import PracticeItem
    _prepare_first_turn_add(monkeypatch,home,session_factory,addition_minutes=(5,5,5,5,5))
    base=post(client,home,action='default',selected_kp_ids=[home['linear']],budget_minutes=90)
    before=counts(session_factory)
    result=post(client,home,goal,expected_version=base['draft_version'])
    assert result['status']=='ready' and result['context']['bank_scope']['scope_mode']=='append',result
    assert result['context']['bank_selection']['requested_count']==1
    assert len(result['context']['bank_selection']['candidate_ids'])==5
    assert len(result['context']['bank_selection']['selected_addition_ids'])==1
    assert result['draft']['questions'][:len(base['draft']['questions'])]==base['draft']['questions']
    assert len(result['draft']['questions'])==len(base['draft']['questions'])+1
    assert set(base['draft']['selected_kp_ids']).issubset(result['draft']['selected_kp_ids'])
    assert counts(session_factory)==before
    recovered=client.get(ROOT,params={'session_id':home['session_id']})
    assert recovered.status_code==200
    _assert_public_paper_is_blindbox(recovered,result['draft'])
    assert read_home_domain(client,home['session_id'])['draft']==result['draft']
    body={'session_id':home['session_id'],'draft_version':result['draft_version']}
    confirmed=client.post(ROOT+'/'+result['task_id']+'/confirm',json=body)
    assert confirmed.status_code==200,confirmed.text
    repeated=client.post(ROOT+'/'+result['task_id']+'/confirm',json=body)
    assert repeated.status_code==200 and repeated.json()['receipt']==confirmed.json()['receipt']
    with session_factory() as db:
        items=list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id==confirmed.json()['receipt']['plan_id']).order_by(PracticeItem.ordinal)))
        assert [(str(i.question_id),str(i.question_version_id)) for i in items]==[(q['question_id'],q['question_version_id']) for q in result['draft']['questions']]
