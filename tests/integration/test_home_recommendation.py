"""New runner-owned PG only; no model/provider, no browser claims."""
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo
import pytest
from sqlalchemy import select, func
from backend.models.chat import ChatSession
from backend.models.learning import KnowledgePoint, Question, DailyPlan, PracticeItem, QuestionAttempt, LearningEvent, KpState
from backend.models.learning_task import LearningTask
from backend.services.graduation_question_set import freeze_graduation_question_set
from backend.services.question_eligibility import question_eligibility
from tests.integration.test_learning_loop import client, clock, session_factory, clean_database, mark_isolated_question_trusted

ROOT = '/api/plans/today/home-preview'


@pytest.fixture
def home(client, session_factory):
    with session_factory.begin() as db:
        root = db.scalar(select(KnowledgePoint).where(KnowledgePoint.name=='线性代数'))
        assert root is not None
        tree = select(KnowledgePoint.id).where(KnowledgePoint.id==root.id).cte('fixture_linear',recursive=True)
        tree=tree.union(select(KnowledgePoint.id).join(tree,KnowledgePoint.parent_id==tree.c.id))
        # Deterministic inventory: use exactly the three explicit synthetic
        # questions, not an accidental mix with syllabus demo questions.
        for q in db.scalars(select(Question).where(Question.kp_id.in_(select(tree.c.id)))):
            q.is_active=False
        linear = KnowledgePoint(code='synthetic.home.linear', name='线代诊断（SYNTHETIC）',parent_id=root.id,
            subject='考研数学', is_assessable=True, is_active=True)
        db.add(linear); db.flush()
        for index, minutes in enumerate([30, 30, 20]):
            q = Question(kp_id=linear.id, question_type='single_choice', stem=f'SYNTHETIC 线代诊断 {index}: 1+1=?',
                options={'A':'2','B':'3'}, correct_answer='A', explanation='1+1=2', estimated_minutes=minutes,
                grading_mode='auto', grading_config={'verified':True,'method':'single_choice'}, is_active=True)
            mark_isolated_question_trusted(q, db=db)
        db.flush()
        for node in db.scalars(select(KnowledgePoint).where(KnowledgePoint.is_assessable.is_(True))):
            ids = [q.id for q in db.scalars(select(Question).where(Question.kp_id == node.id,
                Question.is_active.is_(True)).order_by(Question.id))
                if question_eligibility(q, node).evidence_capability == 'verified_objective'
                and question_eligibility(q, node).grading_capability == 'deterministic']
            if ids:
                freeze_graduation_question_set(db, kp_id=node.id, question_ids=ids,
                    reason='SYNTHETIC home preview integration fixture, no student evidence')
        sid = uuid4(); db.add(ChatSession(id=sid, mode='builtin', purpose='study', study_date='2026-01-01', title='首页推荐调整'))
        lh = db.scalar(select(KnowledgePoint).where(KnowledgePoint.name=='洛必达法则', KnowledgePoint.is_assessable.is_(True)))
        assert lh is not None, 'seed must contain the actual named Lhopital leaf'
        result={'session_id':str(sid),'linear':str(linear.id),'lh':str(lh.id)}
    return result


def post(client, home, goal='', action='adjust', **kw):
    r=client.post(ROOT,json={'session_id':home['session_id'],'request_key':uuid4().hex,'goal':goal,'action':action,**kw})
    assert r.status_code == 200, r.text
    import os, json
    from pathlib import Path
    if os.environ.get('PHASE45I_CLOSE_OUTPUT'):
        with (Path(os.environ['PHASE45I_CLOSE_OUTPUT'])/'home-responses.jsonl').open('a',encoding='utf-8') as log:
            log.write(json.dumps({'goal':goal,'action':action,'response':r.json()},ensure_ascii=False)+'\n')
    return r.json()


def counts(factory):
    with factory() as db:
        return {cls.__tablename__: db.scalar(select(func.count()).select_from(cls))
            for cls in [DailyPlan,PracticeItem,QuestionAttempt,LearningEvent,KpState]}


@pytest.mark.parametrize('goal,expected_count', [('把当前题量补足到90分钟',4),('第2道题换一道同知识点的题',3)])
def test_exact_bank_revision_api_persists_and_formally_confirms_same_identities(client,home,session_factory,goal,expected_count):
    # Requires the existing guarded isolated PostgreSQL fixture. Never run against dev.
    original=post(client,home,action='default',selected_kp_ids=[home['linear']])
    a=original['draft']['questions']
    assert len(a)==3 and sum(q['minutes'] for q in a)==80
    with session_factory.begin() as db:
        q=Question(kp_id=UUID(home['linear']),question_type='single_choice',stem='SYNTHETIC target 2+3=?',
            options={'A':'5','B':'6'},correct_answer='A',explanation='2+3=5',estimated_minutes=10,
            grading_mode='auto',grading_config={'verified':True,'method':'single_choice'},is_active=True)
        mark_isolated_question_trusted(q,db=db);db.flush();new_id=str(q.id)
        ids=list(db.scalars(select(Question.id).where(Question.kp_id==UUID(home['linear']),Question.is_active.is_(True))))
        freeze_graduation_question_set(db,kp_id=UUID(home['linear']),question_ids=ids,reason='SYNTHETIC exact bank revision')
    changed=post(client,home,goal,expected_version=original['draft_version'])
    b=changed['draft']['questions']
    assert len(b)==expected_count and new_id in [q['question_id'] for q in b]
    if expected_count==4:
        assert b[:len(a)]==a and changed['draft']['total_minutes']==90
    else:
        assert b[0]==a[0] and b[2]==a[2] and b[1]['question_id']==new_id
    assert changed['draft']['selected_kp_ids']==original['draft']['selected_kp_ids']
    reread=client.get(ROOT,params={'session_id':home['session_id']}).json()
    assert reread['draft']==changed['draft']
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(DailyPlan))==0
    payload={'session_id':home['session_id'],'draft_version':changed['draft_version']}
    first=client.post(f"{ROOT}/{changed['task_id']}/confirm",json=payload)
    assert first.status_code==200,first.text
    repeat=client.post(f"{ROOT}/{changed['task_id']}/confirm",json=payload)
    assert repeat.status_code==200 and repeat.json()['receipt']==first.json()['receipt']
    active=client.get('/api/plans/today').json()
    assert [(q['question_id'],q['question_version_id']) for q in active['items']]==[(q['question_id'],q['question_version_id']) for q in b]
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(DailyPlan))==1
        assert db.scalar(select(func.count()).select_from(PracticeItem))==expected_count


@pytest.mark.parametrize('text',['今天推荐我学什么？','当前方案有多少道题，预计多久？','查询推荐理由'])
def test_home_recommendation_query_reads_saved_facts_without_new_plan(client,home,session_factory,text):
    base=post(client,home,action='default',selected_kp_ids=[home['linear']])
    before=counts(session_factory)
    with session_factory() as db:
        task_count=db.scalar(select(func.count()).select_from(LearningTask))
    response=post(client,home,text)
    assert response['kind']=='explanation'
    assert '暂时无法可靠理解' not in response['message']
    if '理由' not in text:
        assert f"{len(base['draft']['questions'])} 道题" in response['message']
        assert f"{base['draft']['total_minutes']} 分钟" in response['message']
    else:
        assert '推荐依据' in response['message']
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(LearningTask))==task_count
    assert counts(session_factory)==before
    assert client.get(ROOT,params={'session_id':home['session_id']}).json()['draft']==base['draft']


def test_negated_home_edit_preserves_persisted_preview(client,home,session_factory):
    base=post(client,home,action='default',selected_kp_ids=[home['linear']])
    before=counts(session_factory)
    for text in ('不要删除第1道题','别恢复原来的推荐方案','不要只练洛必达法则'):
        answer=post(client,home,text)
        assert answer['kind']=='explanation' and answer['intent_trace']['operation']=='clarify'
        read=client.get(ROOT,params={'session_id':home['session_id']}).json()
        assert read['task_id']==base['task_id'] and read['draft']==base['draft']
    assert counts(session_factory)==before


def test_generic_append_searches_all_nine_saved_knowledge_nodes(client,home,session_factory):
    # Freeze the original recommendation before inserting the new inventory;
    # otherwise the recommender can already select some new nodes as its base.
    post(client,home,action='default',selected_kp_ids=[home['linear']])
    ids=[]
    with session_factory.begin() as db:
        for i in range(9):
            node=KnowledgePoint(code=f'synthetic.audit.scope{i}',name=f'审计节点{i}',subject='考研数学',is_assessable=True,is_active=True)
            db.add(node);db.flush();ids.append(str(node.id));questions=[]
            for j in range(2):
                q=Question(kp_id=node.id,stem=f'SYNTHETIC {i}-{j}: 2+2=?',question_type='single_choice',
                    options={'A':'4','B':'5'},correct_answer='A',explanation='SYNTHETIC 2+2=4',estimated_minutes=5,
                    grading_mode='auto',grading_config={'verified':True,'method':'single_choice'},is_active=True)
                db.add(q);db.flush();mark_isolated_question_trusted(q,db=db);questions.append(q.id)
            freeze_graduation_question_set(db,kp_id=node.id,question_ids=questions,reason='SYNTHETIC nine-node regression')
    base=post(client,home,action='default',selected_kp_ids=ids)
    assert len(base['draft']['questions'])==9
    changed=post(client,home,'再加一道当前范围的题',expected_version=base['draft_version'])
    changed=changed.get('workload_candidate',changed)
    assert len(changed['draft']['questions'])==10
    assert changed['draft']['questions'][:9]==base['draft']['questions']
    assert set(changed['draft']['selected_kp_ids'])==set(ids)


def test_home_request_key_cannot_replay_a_different_payload(client,home):
    body={'session_id':home['session_id'],'request_key':'scenario-payload-0001',
        'action':'default','selected_kp_ids':[home['linear']],'budget_minutes':90}
    first=client.post(ROOT,json=body)
    assert first.status_code==200,first.text
    replay=client.post(ROOT,json=body)
    assert replay.status_code==200 and replay.json()['task_id']==first.json()['task_id']
    conflict=client.post(ROOT,json={**body,'budget_minutes':60})
    assert conflict.status_code==409,conflict.text
    current=client.get(ROOT,params={'session_id':home['session_id']}).json()
    assert current['draft']==first.json()['draft']


def test_yesterday_home_session_cannot_be_reused_for_new_adjustments(client,home,session_factory):
    base=post(client,home,action='default',selected_kp_ids=[home['linear']])
    with session_factory.begin() as db:
        session=db.get(ChatSession,UUID(home['session_id']))
        session.study_date='2025-12-31'
    before=counts(session_factory)
    denied=client.post(ROOT,json={'session_id':home['session_id'],'request_key':'yesterday-home-0001',
        'action':'adjust','goal':'再加一道洛必达法则题'})
    assert denied.status_code==409 and denied.json()['error']['code']=='study_session_expired'
    assert counts(session_factory)==before
    with session_factory() as db:
        old=db.get(LearningTask,UUID(base['task_id']))
        assert old.draft==base['draft'] and old.status=='ready'


def test_home_preview_to_formal_answer_and_refresh_is_one_persisted_flow(client,home,session_factory):
    preview=post(client,home,action='default',selected_kp_ids=[home['linear']])
    confirmation=client.post(f"{ROOT}/{preview['task_id']}/confirm",json={
        'session_id':home['session_id'],'draft_version':preview['draft_version']})
    assert confirmation.status_code==200,confirmation.text
    active=client.get('/api/plans/today').json()
    identities=lambda qs:[(q['question_id'],q['question_version_id']) for q in qs]
    assert identities(active['items'])==identities(preview['draft']['questions'])
    item=active['items'][0]
    assert 'correct_answer' not in item and 'explanation' not in item
    endpoint=f"/api/practice-items/{item['id']}/answer-submissions"
    invalid=client.post(endpoint,json={'idempotency_key':'audit-empty-option-001'})
    assert invalid.status_code==422,invalid.text
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(QuestionAttempt))==0
    payload={'idempotency_key':'audit-answer-flow-0001','selected_option':'A'}
    answer=client.post(endpoint,json=payload)
    assert answer.status_code==200,answer.text
    repeat=client.post(endpoint,json=payload)
    assert repeat.status_code==200 and repeat.json()==answer.json()
    conflict=client.post(endpoint,json={**payload,'selected_option':'B'})
    assert conflict.status_code==409
    refreshed=client.get('/api/plans/today').json()
    assert refreshed['plan_id']==active['plan_id'] and refreshed['completed_count']==1
    assert identities(refreshed['items'])==identities(active['items'])
    saved=next(q for q in refreshed['items'] if q['id']==item['id'])
    assert saved['answer_submission']['attempt_id']==answer.json()['attempt_id']
    denied=client.post(ROOT,json={'session_id':home['session_id'],'request_key':'audit-restore-after-formal','action':'restore'})
    assert denied.status_code==409
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(DailyPlan))==1
        assert db.scalar(select(func.count()).select_from(QuestionAttempt))==1
        assert db.scalar(select(func.count()).select_from(PracticeItem))==len(active['items'])


def test_two_explicit_append_requests_with_same_words_each_add_one(client,home):
    base=post(client,home,action='default',selected_kp_ids=[home['linear']])
    goal='帮我加入一道洛必达法则的题目'
    first=post(client,home,goal,expected_version=base['draft_version'])
    first=first.get('workload_candidate',first)
    if first.get('context',{}).get('workload',{}).get('requires_confirmation'):
        first=post(client,home,action='accept_workload',target_task_id=first['task_id'],expected_version=first['draft_version'])
    second=post(client,home,goal,expected_version=first['draft_version'])
    second=second.get('workload_candidate',second)
    assert second['task_id']!=first['task_id']
    a=base['draft']['questions']; b=first['draft']['questions']; c=second['draft']['questions']
    assert len(b)==len(a)+1 and len(c)==len(b)+1
    assert c[:len(b)]==b and b[:len(a)]==a
    assert len({q['question_id'] for q in c})==len(c)


def test_manual_scope_allocation_retains_existing_questions_and_survives_readback(client,home,session_factory):
    from backend.models.chat import ChatMessage
    first=post(client,home,action='default',selected_kp_ids=[home['linear']])
    original=first['draft']['questions']
    with session_factory() as db:
        messages=db.scalar(select(func.count()).select_from(ChatMessage))
    revised=post(client,home,action='default',selected_kp_ids=[home['linear'],home['lh']],expected_version=first['draft_version'])
    candidate=revised.get('workload_candidate',revised)
    if not candidate.get('draft') and revised.get('fallback_preview'):
        candidate=revised
    assert candidate['status']=='ready',candidate
    draft=candidate['draft']
    assert draft['questions'][:len(original)]==original
    additions=draft['questions'][len(original):]
    assert len(additions)==1 and additions[0]['kp_id']==home['lh']
    assert set(draft['selected_kp_ids'])=={home['linear'],home['lh']}
    assert draft['total_minutes']==sum(q['minutes'] for q in draft['questions'])
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(ChatMessage))==messages
        assert db.scalar(select(func.count()).select_from(DailyPlan))==0
        for ref in draft['questions']:
            actual=db.get(Question,UUID(ref['question_id']))
            assert str(actual.current_version_id)==ref['question_version_id']
    if candidate['context'].get('workload_pending'):
        accepted=post(client,home,action='accept_workload',target_task_id=candidate['task_id'],expected_version=candidate['draft_version'])
        assert accepted['draft']==draft
        candidate=accepted
    refreshed=client.get(ROOT,params={'session_id':home['session_id']})
    assert refreshed.status_code==200 and refreshed.json()['draft']==draft
    body={'session_id':home['session_id'],'draft_version':candidate['draft_version']}
    response=client.post(f"{ROOT}/{candidate['task_id']}/confirm",json=body)
    assert response.status_code==200,response.text
    assert client.post(f"{ROOT}/{candidate['task_id']}/confirm",json=body).json()['receipt']==response.json()['receipt']
    with session_factory() as db:
        items=list(db.scalars(select(PracticeItem).order_by(PracticeItem.ordinal)))
        assert [(str(i.question_id),str(i.question_version_id)) for i in items]==[(q['question_id'],q['question_version_id']) for q in draft['questions']]


def test_implicit_function_short_alias_appends_one_real_bank_question(client,home,session_factory):
    with session_factory() as db:
        node=db.scalar(select(KnowledgePoint).where(KnowledgePoint.code=='math.calculus.differential.implicit',
            KnowledgePoint.is_active.is_(True),KnowledgePoint.is_assessable.is_(True)))
        assert node is not None, 'isolated seed must contain the assessable implicit-differentiation node'
        node_id=str(node.id)
        eligible=[q for q in db.scalars(select(Question).where(Question.kp_id==node.id,Question.is_active.is_(True)))
            if question_eligibility(q,node).practice_eligible]
        assert eligible, 'isolated seed must contain a qualified real-bank implicit question'
    base=post(client,home,action='default',selected_kp_ids=[home['linear']],budget_minutes=90)
    original=base['draft']['questions']
    result=post(client,home,'给我来一道隐函数的题目',expected_version=base['draft_version'])
    candidate=result.get('workload_candidate') or result
    assert candidate['status']=='ready',candidate
    final=candidate['draft']['questions']
    assert final[:len(original)]==original
    assert len(final)==len(original)+1
    added=final[-1]
    assert added['kp_id']==node_id and added['question_id'] in {str(q.id) for q in eligible}
    with session_factory() as db:
        actual=db.get(Question,UUID(added['question_id']))
        assert actual is not None and str(actual.current_version_id)==added['question_version_id']
        assert question_eligibility(actual,node).practice_eligible
        assert db.scalar(select(func.count()).select_from(DailyPlan))==0


def test_manual_multiple_nodes_partial_stock_are_traced_without_chat_or_formal_writes(client,home,session_factory):
    from backend.models.chat import ChatMessage
    with session_factory.begin() as db:
        empty=KnowledgePoint(code='synthetic.manual.empty',name='无题节点（SYNTHETIC）',subject='考研数学',is_assessable=True,is_active=True)
        extra=KnowledgePoint(code='synthetic.manual.additional',name='另一个新增节点（SYNTHETIC）',subject='考研数学',is_assessable=True,is_active=True)
        db.add_all([empty,extra]);db.flush()
        q=Question(kp_id=extra.id,question_type='single_choice',stem='SYNTHETIC 2+2=?',options={'A':'4','B':'5'},
            correct_answer='A',explanation='2+2=4',estimated_minutes=5,grading_mode='auto',
            grading_config={'verified':True,'method':'single_choice'},is_active=True)
        mark_isolated_question_trusted(q,db=db);db.flush()
        freeze_graduation_question_set(db,kp_id=extra.id,question_ids=[q.id],reason='SYNTHETIC isolated manual allocation test')
        selected=[home['linear'],home['lh'],str(empty.id),str(extra.id)];extra_id=str(q.id)
    first=post(client,home,action='default',selected_kp_ids=[home['linear']])
    before=first['draft']['questions']
    with session_factory() as db:
        messages=db.scalar(select(func.count()).select_from(ChatMessage))
    candidate=post(client,home,action='default',selected_kp_ids=selected,expected_version=first['draft_version'])
    assert candidate['status']=='ready',candidate
    paper=candidate['draft'];trace=candidate['context']['manual_allocation']
    assert paper['questions'][:len(before)]==before
    assert len(paper['questions'])==len(before)+2
    assert extra_id in paper['candidate_question_ids']
    assert sum(n['assigned_count'] for n in paper['scope_nodes'])==len(paper['questions'])
    assert paper['total_minutes']==sum(q['minutes'] for q in paper['questions'])
    entries={n['kp_id']:n for n in trace['nodes']}
    assert entries[selected[2]]['query_attempted'] and entries[selected[2]]['assigned']==0
    assert entries[selected[2]]['candidates_found']==0
    assert entries[selected[1]]['assigned']==entries[selected[3]]['assigned']==1
    assert trace['new_assignment_count']==2
    recovered=client.get(ROOT,params={'session_id':home['session_id']}).json()
    restored=recovered.get('workload_candidate',recovered)
    assert restored['draft']==paper
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(ChatMessage))==messages
        assert db.scalar(select(func.count()).select_from(DailyPlan))==0


def test_unified_home_removal_and_budget_do_not_replace_unrelated_questions(client,home,session_factory):
    original=post(client,home,action='default',selected_kp_ids=[home['linear'],home['lh']])
    if original['context'].get('workload_pending'):
        original=post(client,home,action='accept_workload',target_task_id=original['task_id'],expected_version=original['draft_version'])
    a=original['draft']
    budget=post(client,home,'预算改成10分钟。',expected_version=original['draft_version'])
    assert budget['draft']['questions']==a['questions']
    assert budget['draft']['selected_kp_ids']==a['selected_kp_ids']
    assert budget['context']['workload_pending'] and budget['draft']['total_minutes']>10
    returned=post(client,home,action='dismiss_workload',target_task_id=budget['task_id'],expected_version=budget['draft_version'])
    recovered=client.get(ROOT,params={'session_id':home['session_id']}).json()
    assert recovered['draft']['questions']==a['questions']
    removed=post(client,home,'把洛必达法则这个知识点移除。',expected_version=recovered['draft_version'])
    expected=[q for q in a['questions'] if q['kp_id']!=home['lh']]
    assert removed['draft']['questions']==expected
    assert removed['draft']['selected_kp_ids']==[home['linear']]
    one=post(client,home,'删除第1道题。',expected_version=removed['draft_version'])
    assert one['draft']['questions']==expected[1:]
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(DailyPlan))==0
        assert db.scalar(select(func.count()).select_from(PracticeItem))==0


def test_default_recommendation_preview_reads_formal_selector_without_business_writes(client,home,session_factory):
    before=counts(session_factory)
    initial=client.get('/api/plans/today/home-recommendation').json()['initial_paper']
    expected=[q for q in initial['questions'] if q['kp_id']==home['linear']]
    task=post(client,home,action='default',selected_kp_ids=[home['linear']],budget_minutes=90)
    assert task['status']=='ready' and expected, task
    assert task['draft']['questions']==expected
    assert task['draft']['total_minutes']==sum(q['minutes'] for q in expected)
    assert task['context']['system_recommendations']
    assert counts(session_factory)==before
    assert all(q['question_version_id'] and 'correct_answer' not in q for q in task['draft']['questions'])


def test_linear_algebra_90_is_real_diagnostic_paper_not_activity_schedule(client,home,session_factory):
    before=counts(session_factory)
    t=post(client,home,'今天只练线性代数，安排90分钟。')
    assert t['status']=='ready' and t['draft']['total_minutes']==80, t
    assert {q['kp_id'] for q in t['draft']['questions']}=={home['linear']}
    assert t['context']['evidence']['states'][0]['recent_attempts']==[]
    assert '初始诊断' in t['message']
    assert counts(session_factory)==before


def test_lhopital_scope_conflict_and_shortage_are_real(client,home):
    base=post(client,home,action='default',selected_kp_ids=[home['linear']],budget_minutes=90)
    t=post(client,home,'只练洛必达法则，安排90分钟。',expected_version=base['draft_version'])
    assert t['status']=='ready'
    assert all(q['kp_id']==home['lh'] for q in t['draft']['questions'])
    assert t['draft']['diff']['removed'] and t['draft']['diff']['added']
    assert t['draft']['total_minutes'] < 90 and '少于预算' in t['message']


def test_budget_revision_invalidates_old_version_and_cancel_writes_nothing(client,home,session_factory):
    before=counts(session_factory)
    first=post(client,home,'只练线性代数，90分钟')
    second=post(client,home,'刚才90分钟太长了，改成60分钟。',expected_version=first['draft_version'])
    assert second['status']=='ready' and second['budget_minutes']==60
    assert second['draft']['questions']==first['draft']['questions']
    assert second['context']['workload_pending']
    blocked=client.post(f"{ROOT}/{second['task_id']}/confirm",json={'session_id':home['session_id'],'draft_version':second['draft_version']})
    assert blocked.status_code==422
    second=post(client,home,action='accept_workload',target_task_id=second['task_id'],expected_version=second['draft_version'])
    rejected=client.post(f"{ROOT}/{first['task_id']}/confirm",json={'session_id':home['session_id'],'draft_version':first['draft_version']})
    assert rejected.status_code==409
    post(client,home,action='cancel',expected_version=second['draft_version'])
    assert counts(session_factory)==before


def test_restore_recomputes_original_recommendation(client,home,session_factory):
    before=counts(session_factory)
    original=post(client,home,action='default',selected_kp_ids=[home['linear']],budget_minutes=90)
    post(client,home,'只练洛必达法则，安排90分钟。')
    restored=post(client,home,'算了，还是按原来的推荐吧。')
    # Original means the actual canonical system recommendation baseline,
    # not a second independent assistant ranking.
    assert restored['status']=='ready', restored
    assert restored['draft']['questions']==original['context']['baseline']['questions']
    assert counts(session_factory)==before


def test_restore_same_system_snapshot_is_idempotent_and_never_creates_formal_paper(client,home,session_factory):
    original=post(client,home,action='default',selected_kp_ids=[home['linear']],budget_minutes=90)
    post(client,home,'只练洛必达法则，安排90分钟。')
    restored=post(client,home,action='restore')
    baseline=original['context']['baseline']
    identity=lambda paper:[(q['question_id'],q['question_version_id'],q['minutes']) for q in paper['questions']]
    assert restored['draft']['selected_kp_ids']==baseline['selected_kp_ids']
    assert identity(restored['draft'])==identity(baseline)
    assert restored['draft']['budget_minutes']==baseline['budget_minutes']
    assert restored['draft']['total_minutes']==baseline['total_minutes']
    with session_factory() as db:
        tasks_before=db.scalar(select(func.count()).select_from(LearningTask))
    repeated=post(client,home,action='restore')
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(LearningTask))==tasks_before
        assert db.scalar(select(func.count()).select_from(DailyPlan))==0
    assert repeated['task_id']==restored['task_id']
    assert repeated['draft']['selected_kp_ids']==baseline['selected_kp_ids']
    assert identity(repeated['draft'])==identity(baseline)
    assert repeated['draft']['budget_minutes']==baseline['budget_minutes']
    assert repeated['draft']['total_minutes']==baseline['total_minutes']


def test_confirm_matches_exact_preview_and_replay_is_idempotent(client,home,session_factory):
    t=post(client,home,'只练线性代数，60分钟')
    body={'session_id':home['session_id'],'draft_version':t['draft_version']}
    a=client.post(f"{ROOT}/{t['task_id']}/confirm",json=body)
    assert a.status_code==200,a.text
    b=client.post(f"{ROOT}/{t['task_id']}/confirm",json=body)
    assert b.status_code==200 and b.json()['receipt']==a.json()['receipt']
    with session_factory() as db:
        items=list(db.scalars(select(PracticeItem).order_by(PracticeItem.ordinal)))
        assert [(str(i.question_id),str(i.question_version_id)) for i in items]==[(q['question_id'],q['question_version_id']) for q in t['draft']['questions']]
        assert db.scalar(select(func.count()).select_from(DailyPlan))==1


def test_refresh_session_and_request_replay_do_not_duplicate_tasks(client,home,session_factory):
    body={'session_id':home['session_id'],'request_key':'replay-home-00001','goal':'只练线性代数，90分钟'}
    a=client.post(ROOT,json=body).json();b=client.post(ROOT,json=body).json()
    assert a['task_id']==b['task_id']
    restored=client.get(ROOT,params={'session_id':home['session_id']})
    assert restored.status_code==200 and restored.json()['draft_version']==a['draft_version']
    with session_factory.begin() as db:
        s=ChatSession(mode='builtin',purpose='study',study_date='2026-01-01',title='other');db.add(s);db.flush();sid=str(s.id)
    assert client.get(ROOT,params={'session_id':sid}).json() is None
    assert client.post(f"{ROOT}/{a['task_id']}/confirm",json={'session_id':sid,'draft_version':a['draft_version']}).status_code==404


def test_unknown_scope_keeps_previous_valid_preview_confirmable(client,home,session_factory):
    before=counts(session_factory)
    old=post(client,home,'只练线性代数，90分钟')
    unknown=post(client,home,'请练习不存在的火星代数90分钟')
    assert unknown['kind']=='explanation' and unknown['intent_trace']['operation']=='clarify'
    latest=client.get(ROOT,params={'session_id':home['session_id']})
    assert latest.status_code==200 and latest.json()['task_id']==old['task_id'] and latest.json()['draft']==old['draft']
    assert counts(session_factory)==before
    confirmed=client.post(f"{ROOT}/{old['task_id']}/confirm",json={'session_id':home['session_id'],'draft_version':old['draft_version']})
    assert confirmed.status_code==200,confirmed.text
    assert client.get('/api/plans/today').status_code==200


def test_budget_too_small_does_not_create_formal_write(client,home,session_factory):
    before=counts(session_factory)
    too_small=post(client,home,'只练线性代数，5分钟')
    assert too_small['status'] in {'needs_info','failed'} and too_small['draft'] is None,too_small
    assert counts(session_factory)==before


def test_changed_version_is_rejected_without_partial_plan(client,home,session_factory):
    t=post(client,home,'只练线性代数，90分钟')
    with session_factory.begin() as db:
        q=db.get(Question,UUID(t['draft']['questions'][0]['question_id']));q.stem+=' changed'
    before=counts(session_factory)
    r=client.post(f"{ROOT}/{t['task_id']}/confirm",json={'session_id':home['session_id'],'draft_version':t['draft_version']})
    assert r.status_code in (409,422),r.text
    assert counts(session_factory)==before


def test_selector_outage_invalidates_preview_and_reports_failure(client,home,session_factory,monkeypatch):
    old=post(client,home,'只练线性代数，90分钟');before=counts(session_factory)
    from backend.services import home_recommendation_service as service
    monkeypatch.setattr(service,'_paper',lambda *a,**kw: (_ for _ in ()).throw(RuntimeError('synthetic selector unavailable')))
    failed=post(client,home,'只练线性代数，60分钟')
    assert failed['status']=='failed' and failed['draft'] is None
    assert client.get(ROOT,params={'session_id':home['session_id']}).json()['draft']==old['draft']
    denied=client.post(f"{ROOT}/{old['task_id']}/confirm",json={'session_id':home['session_id'],'draft_version':old['draft_version']})
    assert denied.status_code==503
    assert denied.json()['error']['code']=='home_selection_unavailable'
    assert counts(session_factory)==before


def test_explanation_keeps_objective_records_separate_from_self_report(client,home,session_factory,clock):
    # Legitimate answer evidence via the existing formal API, not inserted Attempts.
    t=post(client,home,'只练线性代数，60分钟')
    made=client.post(f"{ROOT}/{t['task_id']}/confirm",json={'session_id':home['session_id'],'draft_version':t['draft_version']})
    assert made.status_code==200,made.text
    item=made.json()['receipt']['item_ids'][0]
    answer=client.post(f'/api/practice-items/{item}/answer-submissions',json={'idempotency_key':'synthetic-home-wrong-0001','selected_option':'B'})
    assert answer.status_code==200 and answer.json()['result']=='wrong',answer.text
    from datetime import timedelta
    clock.now+=timedelta(days=1)
    other=home.copy()
    with session_factory.begin() as db:
        s=ChatSession(mode='builtin',purpose='study',study_date=clock.now.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat(),title='首页推荐调整');db.add(s);db.flush();other['session_id']=str(s.id)
    current=post(client,other,'只练线性代数，安排90分钟；我感觉线性代数比较差')
    assert current['status']=='ready', current
    before=counts(session_factory)
    explained=post(client,other,'你为什么给我安排这些题？哪些是根据我的错题判断的？')
    assert explained['task_id']==current['task_id']
    assert answer.json()['attempt_id'] in explained['message']
    assert '未经独立核验' in explained['message']
    assert explained['context']['evidence']['self_reports']
    assert all(r['source']=='self_report' and not r['independently_verified'] for r in explained['context']['evidence']['self_reports'])
    assert counts(session_factory)==before


def test_home_recommendation_history_is_not_exposed_as_qa(client, home, session_factory):
    """Real homepage preview messages belong to the study surface, not Q&A history."""
    preview = post(client, home, '只练线性代数，60分钟')
    assert preview['status'] == 'ready'
    home_id = home['session_id']

    qa_rows = client.get('/api/chat/sessions', params={'mode': 'builtin', 'purpose': 'qa'})
    assert qa_rows.status_code == 200, qa_rows.text
    assert home_id not in {row['session_id'] for row in qa_rows.json()}

    study_rows = client.get('/api/chat/sessions', params={'mode': 'builtin', 'purpose': 'study'})
    assert study_rows.status_code == 200, study_rows.text
    assert home_id in {row['session_id'] for row in study_rows.json()}

    qa_read = client.get(f'/api/chat/sessions/{home_id}/messages', params={'purpose': 'qa'})
    assert qa_read.status_code == 404, qa_read.text
    study_read = client.get(f'/api/chat/sessions/{home_id}/messages', params={'purpose': 'study'})
    assert study_read.status_code == 200, study_read.text
    assert any('试卷预览' in message['content'] for message in study_read.json())


def test_home_recommendation_rejects_ordinary_qa_session_without_writes(client, session_factory):
    """The homepage workflow cannot silently adopt a normal Q&A conversation."""
    from uuid import uuid4
    from backend.models.chat import ChatMessage

    with session_factory.begin() as db:
        session = ChatSession(mode='builtin', purpose='qa', title='普通问答')
        db.add(session)
        db.flush()
        session_id = session.id
        db.add(ChatMessage(session_id=session_id, role='user', content='洛必达法则是什么？', status='completed'))
    before = counts(session_factory)

    recovered = client.get('/api/plans/today/home-preview', params={'session_id': str(session_id)})
    assert recovered.status_code == 404
    adjusted = client.post(ROOT, json={'session_id': str(session_id), 'request_key': uuid4().hex,
        'goal': '只练线性代数，60分钟', 'action': 'adjust'})
    assert adjusted.status_code == 404
    assert counts(session_factory) == before
    with session_factory() as db:
        assert db.get(ChatSession, session_id).purpose == 'qa'
        assert db.scalar(select(func.count()).select_from(ChatMessage).where(
            ChatMessage.session_id == session_id)) == 1


def test_qa_session_history_remains_independent_of_home_preview(client, home, session_factory):
    """An ordinary Q&A session remains readable and is not merged with home messages."""
    from tests.integration.test_learning_assistant import NOW, QAProvider, talk, reply
    from backend.schemas.learning_assistant import AssistantRequest

    preview = post(client, home, '只练线性代数，60分钟')
    response = client.post('/api/chat/sessions', json={
        'title': '独立问答', 'mode': 'builtin', 'purpose': 'qa',
    })
    assert response.status_code == 201, response.text
    qa_id = response.json()['session_id']
    provider = QAProvider('洛必达法则需要满足相应未定式条件。')
    talk(session_factory, qa_id, AssistantRequest(question='洛必达法则有什么条件？'), provider)

    home_history = client.get(f"/api/chat/sessions/{home['session_id']}/messages", params={'purpose': 'study'})
    qa_history = client.get(f'/api/chat/sessions/{qa_id}/messages', params={'purpose': 'qa'})
    assert home_history.status_code == 200, home_history.text
    assert qa_history.status_code == 200, qa_history.text
    assert any('试卷预览' in message['content'] for message in home_history.json())
    assert all('试卷预览' not in message['content'] for message in qa_history.json())
    assert any('洛必达法则' in message['content'] for message in qa_history.json())
    assert provider.prompts == []
    assert preview['task_id']

    # Deleting the Q&A conversation cannot remove today's recommendation flow.
    qa_message_ids = {row['message_id'] for row in qa_history.json()}
    home_message_ids = {row['message_id'] for row in home_history.json()}
    deleted = client.delete(f'/api/chat/sessions/{qa_id}', params={'purpose': 'qa'})
    assert deleted.status_code == 204
    assert client.get(f'/api/chat/sessions/{qa_id}/messages', params={'purpose': 'qa'}).status_code == 404
    still_home = client.get(f"/api/chat/sessions/{home['session_id']}/messages", params={'purpose': 'study'})
    assert still_home.status_code == 200
    assert {row['message_id'] for row in still_home.json()} == home_message_ids
    with session_factory() as db:
        assert db.get(ChatSession, UUID(home['session_id'])) is not None
        assert db.get(LearningTask, UUID(preview['task_id'])).status == 'ready'
    assert qa_message_ids


def test_expired_preview_and_concurrent_confirm_are_safe(client,home,session_factory,clock):
    from datetime import timedelta
    expired=post(client,home,'只练线性代数，90分钟')
    clock.now+=timedelta(minutes=31)
    r=client.post(f"{ROOT}/{expired['task_id']}/confirm",json={'session_id':home['session_id'],'draft_version':expired['draft_version']})
    assert r.status_code==409
    t=post(client,home,'只练线性代数，60分钟')
    from concurrent.futures import ThreadPoolExecutor
    def send():return client.post(f"{ROOT}/{t['task_id']}/confirm",json={'session_id':home['session_id'],'draft_version':t['draft_version']})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:send(),range(2)))
    assert [r.status_code for r in results]==[200,200],[r.text for r in results]
    assert results[0].json()['receipt']==results[1].json()['receipt']
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(DailyPlan))==1
        assert db.scalar(select(func.count()).select_from(PracticeItem))==len(t['draft']['questions'])


def test_original_generate_endpoint_keeps_existing_formal_behavior(client,home,session_factory):
    result=client.post('/api/plans/today/generate',json={'selected_kp_ids':[home['linear']],'budget':'standard'})
    assert result.status_code==201,result.text
    paper=result.json()
    assert paper['total_count']==3 and paper['estimated_minutes']==80
    again=client.post('/api/plans/today/generate',json={'selected_kp_ids':[home['linear']],'budget':'standard'})
    assert again.status_code==409
    assert client.get('/api/plans/today').json()['total_count']==3


def test_empty_inventory_and_missing_version_are_explicit_and_read_only(client,home,session_factory):
    with session_factory.begin() as db:
        empty=KnowledgePoint(code='synthetic.home.empty',name='空题库节点（SYNTHETIC）',subject='考研数学',is_assessable=True,is_active=True)
        db.add(empty);db.flush();eid=str(empty.id)
    before=counts(session_factory)
    t=post(client,home,action='default',selected_kp_ids=[eid],budget_minutes=90)
    assert t['status']=='needs_info' and t['draft'] is None
    assert t['context']['inventory']['practice_eligible_count']==0
    assert counts(session_factory)==before

    # A selector returning a question with no immutable version must not create
    # a confirmable paper, even if the ordinary active flag is true.
    from backend.services import home_recommendation_service as service
    from unittest.mock import patch
    real_get=service._paper
    def invalid(*args,**kw):
        value=real_get(*args,**kw)
        raise ValueError('question_version_or_eligibility_invalid')
    with patch.object(service,'_paper',invalid):
        bad=post(client,home,'只练线性代数，90分钟')
    assert bad['draft'] is None and 'question_version_or_eligibility_invalid' in bad['message']
    assert counts(session_factory)==before


def test_handoff_fixture_uses_only_empty_owned_database_and_seeds_no_learning_evidence(session_factory):
    from scripts.naiwa_home_recommendation_station import seed_home_fixture
    from sqlalchemy import text
    from tests.integration.test_learning_loop import BUSINESS_TABLES
    engine=session_factory.kw['bind']
    with pytest.raises(RuntimeError,match='exact_owned_test_database'):
        seed_home_fixture(session_factory,database='wrong_test',port=engine.url.port)
    with pytest.raises(RuntimeError,match='empty_new_database'):
        seed_home_fixture(session_factory,database=engine.url.database,port=engine.url.port)
    with session_factory.begin() as db:
        db.execute(text('TRUNCATE TABLE '+', '.join(BUSINESS_TABLES)+' RESTART IDENTITY CASCADE'))
    result=seed_home_fixture(session_factory,database=engine.url.database,port=engine.url.port)
    assert result['attempts_seeded']==0 and result['real_model_requests']==0
    with session_factory() as db:
        assert all('SYNTHETIC' in n.name for n in db.scalars(select(KnowledgePoint)))
        assert db.scalar(select(func.count()).select_from(QuestionAttempt))==0
        assert db.scalar(select(func.count()).select_from(LearningEvent))==0


def test_home_confirmation_consumes_task_and_only_equivalent_same_topic_previews(client,home,session_factory):
    import copy
    t=post(client,home,'只练线性代数，90分钟')
    with session_factory.begin() as db:
        source=db.get(LearningTask,UUID(t['task_id']))
        other=ChatSession(mode='builtin',purpose='study',study_date='2026-01-01',title='another topic');db.add(other);db.flush()
        same=LearningTask(session_id=source.session_id,goal='旧的等价预览',budget_minutes=90,status='ready',
            draft=copy.deepcopy(source.draft),context=copy.deepcopy(source.context),metrics={},trace=[])
        unrelated=LearningTask(session_id=other.id,goal='其他话题预览',budget_minutes=90,status='ready',
            draft=copy.deepcopy(source.draft),context=copy.deepcopy(source.context),metrics={},trace=[])
        db.add_all([same,unrelated]);db.flush();same_id,other_id=same.id,unrelated.id
    body={'session_id':home['session_id'],'draft_version':t['draft_version']}
    first=client.post(f"{ROOT}/{t['task_id']}/confirm",json=body)
    assert first.status_code==200,first.text
    assert first.json()['status']=='answered'
    replay=client.post(f"{ROOT}/{t['task_id']}/confirm",json=body)
    assert replay.status_code==200 and replay.json()['receipt']==first.json()['receipt']
    with session_factory() as db:
        assert db.get(LearningTask,UUID(t['task_id'])).status=='answered'
        assert db.get(LearningTask,same_id).status=='cancelled'
        assert db.get(LearningTask,other_id).status=='ready'
        assert db.scalar(select(func.count()).select_from(DailyPlan))==1
        assert db.scalar(select(func.count()).select_from(PracticeItem))==len(t['draft']['questions'])


def test_failed_home_confirmation_rolls_back_plan_and_task_terminal_state(client,home,session_factory,monkeypatch):
    from backend.services import home_recommendation_service as service
    t=post(client,home,'只练线性代数，90分钟');before=counts(session_factory)
    original=service.create_initial_plan
    def fail_after_creation(*args,**kwargs):
        original(*args,**kwargs)
        raise ValueError('question_pool_incomplete')
    monkeypatch.setattr(service,'create_initial_plan',fail_after_creation)
    r=client.post(f"{ROOT}/{t['task_id']}/confirm",json={'session_id':home['session_id'],'draft_version':t['draft_version']})
    assert r.status_code>=400
    assert counts(session_factory)==before
    with session_factory() as db:
        task=db.get(LearningTask,UUID(t['task_id']))
        assert task.status=='ready' and not task.metrics.get('commit')


def test_new_home_topic_has_independent_messages_and_preview(client,home,session_factory):
    first=post(client,home,'只练线性代数，90分钟')
    qa=client.post('/api/chat/sessions',json={'title':'独立问答','mode':'builtin','purpose':'qa'})
    assert qa.status_code in (200,201),qa.text
    qa_id=qa.json()['session_id']
    denied=client.get(ROOT,params={'session_id':qa_id})
    assert denied.status_code==404 and denied.json()['error']['code']=='chat_session_not_found'
    denied_write=client.post(ROOT,json={'session_id':qa_id,'request_key':'qa-cannot-create-home-preview','goal':'只练洛必达法则','action':'adjust'})
    assert denied_write.status_code==404
    assert client.get(f"/api/chat/sessions/{qa_id}/messages",params={'purpose':'qa'}).json()==[]
    created=client.post('/api/chat/sessions',json={'title':'另一个今日学习话题','mode':'builtin','purpose':'study'})
    assert created.status_code in (200,201),created.text
    other={**home,'session_id':created.json()['session_id']}
    second=post(client,other,'只练洛必达法则，安排90分钟。')
    assert second['session_id']!=first['session_id']
    assert client.get(ROOT,params={'session_id':home['session_id']}).json()['task_id']==first['task_id']
    assert client.get(ROOT,params={'session_id':other['session_id']}).json()['task_id']==second['task_id']


def test_cancel_refresh_and_replay_keep_other_topic_and_business_data_unchanged(client,home,session_factory):
    first=post(client,home,'只练线性代数，90分钟')
    other={**home,'session_id':client.post('/api/chat/sessions',json={'title':'另一个话题','mode':'builtin','purpose':'study'}).json()['session_id']}
    second=post(client,other,'只练洛必达法则，安排90分钟。')
    before=counts(session_factory)
    body={'session_id':home['session_id'],'request_key':'cancel-replay-home-0001','action':'cancel','goal':'','expected_version':first['draft_version']}
    cancelled=client.post(ROOT,json=body)
    assert cancelled.status_code==200,cancelled.text
    result=cancelled.json()
    assert result['status']=='cancelled' and result['draft'] is None
    assert '取消' in result['message']
    refreshed=client.get(ROOT,params={'session_id':home['session_id']}).json()
    assert refreshed['task_id']==result['task_id'] and refreshed['status']=='cancelled'
    assert client.post(ROOT,json=body).json()['task_id']==result['task_id']
    assert client.post(f"{ROOT}/{first['task_id']}/confirm",json={'session_id':home['session_id'],'draft_version':first['draft_version']}).status_code==409
    other_restored=client.get(ROOT,params={'session_id':other['session_id']}).json()
    assert other_restored['task_id']==second['task_id'] and other_restored['status']=='ready'
    assert counts(session_factory)==before
    with session_factory() as db:
        assert db.get(LearningTask,UUID(first['task_id'])).status=='cancelled'
        assert db.get(LearningTask,UUID(second['task_id'])).status=='ready'


def test_free_qa_uses_offline_stream_without_creating_learning_work(client,home,session_factory,monkeypatch):
    from scripts.e2e_backend import OfflineProvider
    from backend.api.routes import chat
    from backend.retrieval.embedding import FakeEmbedder
    from backend.retrieval.keyword import KeywordIndex
    from backend.retrieval.rerank import IdentityReranker
    from backend.retrieval.stack import RetrievalStack
    from backend.retrieval.vector_store import InMemoryVectorStore
    monkeypatch.setattr(chat,'provider_from_settings',lambda _:OfflineProvider())
    embedder=FakeEmbedder(dimension=64)
    client.app.state.retrieval_stack=RetrievalStack(embedder=embedder,
        vector_store=InMemoryVectorStore(embedding_model=embedder.model_name),
        keyword_index=KeywordIndex(),reranker=IdentityReranker())
    before=counts(session_factory)
    with session_factory() as db:tasks_before=db.scalar(select(func.count()).select_from(LearningTask))
    answer=client.post(f"/api/chat/sessions/{home['session_id']}/answers:stream",json={'question':'洛必达法则的适用条件是什么？'},params={'purpose':'study'})
    assert answer.status_code==200,answer.text
    assert 'event: done' in answer.text,answer.text
    assert counts(session_factory)==before
    with session_factory() as db:assert db.scalar(select(func.count()).select_from(LearningTask))==tasks_before
    import os
    from pathlib import Path
    if os.environ.get('PHASE45I_CLOSE_OUTPUT'):
        (Path(os.environ['PHASE45I_CLOSE_OUTPUT'])/'free-qa-offline-sse.txt').write_text(answer.text,encoding='utf-8')


def test_home_replaced_preview_is_rejected_even_if_its_ready_projection_survives(client,home,session_factory):
    old=post(client,home,'只练线性代数，90分钟')
    current=post(client,home,'刚才90分钟太长了，改成60分钟。')
    current=post(client,home,action='accept_workload',target_task_id=current['task_id'],expected_version=current['draft_version'])
    # Controlled legacy stale projection, only in the new runner-owned database.
    with session_factory.begin() as db:db.get(LearningTask,UUID(old['task_id'])).status='ready'
    before=counts(session_factory)
    rejected=client.post(f"{ROOT}/{old['task_id']}/confirm",json={'session_id':home['session_id'],'draft_version':old['draft_version']})
    assert rejected.status_code==409,rejected.text
    assert counts(session_factory)==before
    accepted=client.post(f"{ROOT}/{current['task_id']}/confirm",json={'session_id':home['session_id'],'draft_version':current['draft_version']})
    assert accepted.status_code==200,accepted.text
    assert client.get('/api/plans/today').json()['total_count']==len(current['draft']['questions'])


def test_workbench_initial_recommendation_is_real_and_entirely_read_only(client,home,session_factory):
    before=counts(session_factory)
    with session_factory() as db:tasks_before=db.scalar(select(func.count()).select_from(LearningTask))
    response=client.get('/api/plans/today/home-recommendation')
    assert response.status_code==200,response.text
    data=response.json()
    assert data['recommendations'] and data['inventory']['practice_eligible_count']>0
    assert data['initial_paper']['questions']
    assert data['initial_paper']['total_minutes']==sum(q['minutes'] for q in data['initial_paper']['questions'])
    assert counts(session_factory)==before
    with session_factory() as db:assert db.scalar(select(func.count()).select_from(LearningTask))==tasks_before


def test_workbench_keep_system_scope_with_five_question_limit_uses_formal_confirmation(client,home,session_factory):
    initial=post(client,home,action='default',budget_minutes=90)
    assert initial['status']=='ready',initial
    before=counts(session_factory)
    adjusted=post(client,home,'保留系统推荐，但减少到5道题。',expected_version=initial['draft_version'])
    assert adjusted['status']=='ready',adjusted
    assert adjusted['draft']['question_limit']==5
    assert len(adjusted['draft']['questions'])<=5
    assert adjusted['draft']['selected_kp_ids']==initial['draft']['selected_kp_ids']
    assert counts(session_factory)==before
    confirmed=client.post(f"{ROOT}/{adjusted['task_id']}/confirm",json={'session_id':home['session_id'],'draft_version':adjusted['draft_version']})
    assert confirmed.status_code==200,confirmed.text
    actual=client.get('/api/plans/today').json()
    assert [(q['question_id'],q['question_version_id']) for q in actual['items']]==[(q['question_id'],q['question_version_id']) for q in adjusted['draft']['questions']]


def test_simple_home_direct_generation_uses_readonly_recommendation_and_existing_confirmation(client,home,session_factory):
    with session_factory() as db:
        sessions_before=db.scalar(select(func.count()).select_from(ChatSession))
    before=counts(session_factory)
    initial=client.get('/api/plans/today/home-recommendation')
    assert initial.status_code==200,initial.text
    paper=initial.json()['initial_paper']
    assert counts(session_factory)==before
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(ChatSession))==sessions_before
    draft=post(client,home,action='default',budget_minutes=paper['budget_minutes'])
    assert draft['status']=='ready',draft
    assert draft['draft']['questions']==paper['questions']
    assert draft['draft']['total_minutes']==paper['total_minutes']
    assert counts(session_factory)==before
    result=client.post(f"{ROOT}/{draft['task_id']}/confirm",json={'session_id':home['session_id'],'draft_version':draft['draft_version']})
    assert result.status_code==200,result.text
    active=client.get('/api/plans/today').json()
    assert [(q['question_id'],q['question_version_id']) for q in active['items']]==[(q['question_id'],q['question_version_id']) for q in paper['questions']]
    assert active['estimated_minutes']==paper['total_minutes']
    again=client.post(f"{ROOT}/{draft['task_id']}/confirm",json={'session_id':home['session_id'],'draft_version':draft['draft_version']})
    assert again.status_code==200 and again.json()['receipt']==result.json()['receipt']
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(DailyPlan))==1
        assert db.scalar(select(func.count()).select_from(QuestionAttempt))==0


def test_simple_home_count_adjustment_retains_current_specialist_scope(client,home,session_factory):
    initial=post(client,home,'只练线性代数，90分钟')
    before=counts(session_factory)
    updated=post(client,home,'保留推荐范围，减少到2道题',expected_version=initial['draft_version'])
    assert updated['status']=='ready',updated
    assert updated['draft']['selected_kp_ids']==initial['draft']['selected_kp_ids']
    assert updated['draft']['question_limit']==2
    assert len(updated['draft']['questions'])<=2
    assert counts(session_factory)==before
    assert client.post(f"{ROOT}/{initial['task_id']}/confirm",json={'session_id':home['session_id'],'draft_version':initial['draft_version']}).status_code==409


def test_daily_home_explanation_persists_chat_but_creates_no_task_or_paper(client,home,session_factory):
    before=counts(session_factory)
    with session_factory() as db: tasks=db.scalar(select(func.count()).select_from(LearningTask))
    response=post(client,home,'为什么推荐这些知识点？')
    assert response['kind']=='explanation'
    assert response['session_id']==home['session_id']
    assert '初始诊断' in response['message']
    assert counts(session_factory)==before
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(LearningTask))==tasks
    history=client.get(f"/api/chat/sessions/{home['session_id']}/messages",params={'purpose':'study'})
    assert history.status_code==200
    assert '为什么推荐这些知识点' in history.text


def test_home_preview_undo_redo_restore_history_is_versioned_and_does_not_touch_formal_paper(client, home, session_factory):
    before = counts(session_factory)
    first = post(client, home, action='default', selected_kp_ids=[home['linear']], budget_minutes=90)
    second = post(client, home, action='default', selected_kp_ids=[home['lh']], budget_minutes=90,
        expected_version=first['draft_version'])
    assert second['status'] == 'ready', second
    assert second['undo_available'] is True
    assert second['redo_available'] is False

    # Stale clients cannot move the history stack.
    stale = client.post(ROOT, json={'session_id': home['session_id'], 'request_key': uuid4().hex,
        'goal': '', 'action': 'undo', 'expected_version': first['draft_version']})
    assert stale.status_code == 409, stale.text

    undone = post(client, home, action='undo', expected_version=second['draft_version'])
    assert [(q['question_id'], q['question_version_id']) for q in undone['draft']['questions']] == [
        (q['question_id'], q['question_version_id']) for q in first['draft']['questions']]
    assert undone['draft']['selected_kp_ids'] == first['draft']['selected_kp_ids']
    assert undone['undo_available'] is False
    assert undone['redo_available'] is True
    assert 'home_undo_stack' not in undone['context']
    assert 'home_redo_stack' not in undone['context']

    recovered = client.get(ROOT, params={'session_id': home['session_id']})
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()['draft'] == undone['draft']
    redone = post(client, home, action='redo', expected_version=undone['draft_version'])
    assert [(q['question_id'], q['question_version_id']) for q in redone['draft']['questions']] == [
        (q['question_id'], q['question_version_id']) for q in second['draft']['questions']]
    assert redone['draft']['selected_kp_ids'] == second['draft']['selected_kp_ids']
    assert redone['undo_available'] is True
    assert redone['redo_available'] is False
    assert counts(session_factory) == before


def test_home_remove_third_visible_node_and_manual_save_do_not_change_formal_data(client,home,session_factory):
    first=post(client,home,action='default',budget_minutes=90)
    # Match the actual workbench order: allocated topics first, then any
    # selected topics with no allocated question, with duplicates removed.
    selected=first['draft']['selected_kp_ids']
    visible=[kp for kp in dict.fromkeys([q['kp_id'] for q in first['draft']['questions']]+selected) if kp in selected]
    assert len(visible)>=3,first
    before=counts(session_factory)
    updated=post(client,home,'把刚才推荐的第三个知识点去掉',expected_version=first['draft_version'])
    assert updated['status']=='ready',updated
    assert updated['draft']['selected_kp_ids']==visible[:2]+visible[3:]
    assert visible[2] not in [q['kp_id'] for q in updated['draft']['questions']]
    manual=post(client,home,action='default',selected_kp_ids=[home['lh']],budget_minutes=60,expected_version=updated['draft_version'])
    assert manual['status']=='ready',manual
    assert manual['draft']['selected_kp_ids']==[home['lh']]
    assert all(q['kp_id']==home['lh'] for q in manual['draft']['questions'])
    assert counts(session_factory)==before
    assert client.post(f"{ROOT}/{first['task_id']}/confirm",json={'session_id':home['session_id'],'draft_version':first['draft_version']}).status_code==409


def test_materialized_daily_plan_rejects_home_chat_edits_without_changing_paper(client,home,session_factory):
    preview=post(client,home,action='default',selected_kp_ids=[home['linear']])
    confirm_payload={'session_id':home['session_id'],'draft_version':preview['draft_version']}
    first=client.post(f"{ROOT}/{preview['task_id']}/confirm",json=confirm_payload)
    assert first.status_code==200,first.text
    repeated=client.post(f"{ROOT}/{preview['task_id']}/confirm",json=confirm_payload)
    assert repeated.status_code==200 and repeated.json()['receipt']==first.json()['receipt']

    with session_factory() as db:
        plan=db.scalar(select(DailyPlan).order_by(DailyPlan.created_at.desc()).limit(1))
        assert plan is not None
        before=[(str(item.id),str(item.question_id),str(item.question_version_id),
                 str(item.kp_id),item.ordinal)
                for item in db.scalars(select(PracticeItem).where(
                    PracticeItem.plan_id==plan.id).order_by(PracticeItem.ordinal))]
        task_count=db.scalar(select(func.count()).select_from(LearningTask))

    writes=[
        {'action':'adjust','goal':'再加一道洛必达法则题','expected_version':preview['draft_version']},
        {'action':'default','selected_kp_ids':[home['linear']]},
        {'action':'restore','goal':'恢复今日系统推荐','expected_version':preview['draft_version']},
        {'action':'undo','goal':'撤销刚才的调整','expected_version':preview['draft_version']},
        {'action':'redo','goal':'重做刚才的调整','expected_version':preview['draft_version']},
    ]
    for operation in writes:
        response=client.post(ROOT,json={
            'session_id':home['session_id'],
            'request_key':uuid4().hex,
            'goal':operation.get('goal',''),
            'action':operation['action'],
            'selected_kp_ids':operation.get('selected_kp_ids'),
            'expected_version':operation.get('expected_version'),
        })
        assert response.status_code==409, (operation,response.text)
        assert response.json()['error']['code']=='plan_already_generated'

    with session_factory() as db:
        plan=db.scalar(select(DailyPlan).order_by(DailyPlan.created_at.desc()).limit(1))
        after=[(str(item.id),str(item.question_id),str(item.question_version_id),
                str(item.kp_id),item.ordinal)
               for item in db.scalars(select(PracticeItem).where(
                   PracticeItem.plan_id==plan.id).order_by(PracticeItem.ordinal))]
        assert db.scalar(select(func.count()).select_from(LearningTask))==task_count
    assert after==before
    assert client.get('/api/plans/today').json()['items']
