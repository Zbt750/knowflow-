"""Real service/PG path, offline provider, new cluster only."""
from uuid import UUID,uuid4
from sqlalchemy import select,func
from backend.models.learning import Question,PracticeItem,DailyPlan
from backend.models.chat import ChatSession
from backend.models.learning_task import LearningTask
from backend.models.personal_generation import PersonalGenerationBatch
from backend.schemas.learning_assistant import StudyContext,AssistantRequest
from tests.integration.test_home_recommendation import client,clock,session_factory,clean_database,home,post,counts,ROOT
from tests.integration.test_learning_assistant import talk,reply,QAProvider
from tests.integration.test_personal_question_bank import bank

PROMPT='给我从我的题库来一道这样类似的题加到我今日卷里'

def setup_paper(client,home,session_factory,matching=True):
    with session_factory.begin() as db:
        questions=list(db.scalars(select(Question).where(Question.kp_id==home['linear']).order_by(Question.estimated_minutes)))
        from backend.models.learning import KnowledgePoint
        for index,q in enumerate(questions):
            q.skill_tags=[db.get(KnowledgePoint,q.kp_id).name] if matching=='generic' else ['链式求导'] if matching else [f'方法{index}']
            # Leave one basic reference and hard alternatives so the explicit
            # "难度提高" journey has a real, eligible candidate in this fixture.
            q.difficulty='basic' if q.estimated_minutes<=20 else 'hard'
    preview=post(client,home,action='default',selected_kp_ids=[home['linear']],budget_minutes=20)
    if (preview.get('context') or {}).get('workload_pending'):
        preview=post(client,home,action='accept_workload',target_task_id=preview['task_id'],
            expected_version=preview['draft_version'])
    r=client.post(ROOT+'/'+preview['task_id']+'/confirm',json={'session_id':home['session_id'],'draft_version':preview['draft_version']})
    assert r.status_code==200,r.text
    sid=uuid4()
    with session_factory.begin() as db:
        item=db.scalar(select(PracticeItem).where(PracticeItem.plan_id==r.json()['receipt']['plan_id']))
        reference=db.get(Question,item.question_id)
        node=db.get(KnowledgePoint,reference.kp_id)
        candidate_tags=[node.name] if matching=='generic' else ['链式求导'] if matching else ['无法匹配的独立方法']
        candidate=Question(kp_id=reference.kp_id,question_type=reference.question_type,
            stem='SYNTHETIC similar-bank alternate: lim(x->0) sin(x)/x.',
            options={'A':'0','B':'1'},correct_answer='B',explanation='极限为1。',
            estimated_minutes=5,grading_mode='auto',grading_config={'verified':True,'method':'single_choice'},
            difficulty='hard',skill_tags=candidate_tags,is_active=True)
        from tests.integration.test_learning_loop import mark_isolated_question_trusted
        mark_isolated_question_trusted(candidate,db=db)
        db.add(candidate)
        db.add(ChatSession(id=sid,mode='builtin',purpose='study',study_date='2026-01-01'))
        ctx=StudyContext(surface='study',question_id=item.question_id,question_version_id=item.question_version_id,practice_item_id=item.id,daily_plan_id=item.plan_id,knowledge_node_ids=[item.kp_id])
    return sid,ctx


def test_original_phrase_finds_real_similar_candidate_and_confirms_once(client,home,session_factory):
    sid,ctx=setup_paper(client,home,session_factory)
    before=counts(session_factory); provider=QAProvider('不得调用模型')
    with session_factory() as db: batches=db.scalar(select(func.count()).select_from(PersonalGenerationBatch))
    key=uuid4(); body=AssistantRequest(question=PROMPT,study_context=ctx,request_key=key)
    frames=talk(session_factory,sid,body,provider); saved=reply(session_factory,sid)
    assert provider.prompts==[]
    assert saved.metadata_['capability_route']['reason']=='explicit_bank_selection',saved.metadata_.get('capability_route')
    assert 'personal_generation' not in saved.metadata_ and 'personal_generation_confirmation' not in saved.metadata_
    with session_factory() as db:
        task=db.get(LearningTask,saved.metadata_['planner_task_id'])
        import os,json
        from pathlib import Path
        if os.environ.get('PHASE45I_CLOSE_OUTPUT'):
            find_step=next((step for step in task.trace if step.get('tool')=='find_questions'),{})
            debug={'study_context':ctx.model_dump(mode='json'),'planner_handoff':(task.context or {}).get('planner_handoff'),
                'task_status':task.status,'task_error_code':task.error_code,'task_message':task.message,
                'find_questions':find_step.get('result')}
            (Path(os.environ['PHASE45I_CLOSE_OUTPUT'])/'similar-bank-reference-debug.json').write_text(
                json.dumps(debug,ensure_ascii=False,default=str,indent=2),encoding='utf-8')
        assert task.status=='ready',{'message':task.message,'trace':task.trace,
            'handoff':(task.context or {}).get('planner_handoff'),'study_context':ctx.model_dump(mode='json')}
        assert any(s['tool']=='find_questions' for s in task.trace)
        assert len(task.draft['questions'])==1
        q=task.draft['questions'][0]; candidate=db.get(Question,q['question_id'])
        assert candidate and str(candidate.current_version_id)==q['question_version']
        assert candidate.id!=ctx.question_id and '链式求导' in candidate.skill_tags
        assert q['match_basis']['shared_skill_tags']==['链式求导'] and q['source_category']
        taskid=str(task.id);version=saved.metadata_['planner_task_id'] and task.draft_version if hasattr(task,'draft_version') else None
        from backend.services.learning_task_service import _draft_version
        version=_draft_version(task)
        assert db.scalar(select(func.count()).select_from(PersonalGenerationBatch))==batches
    assert counts(session_factory)==before
    replay=talk(session_factory,sid,body,provider)
    assert any(n=='meta' and data.get('replayed') for n,data in replay)
    assert counts(session_factory)==before
    a=client.post('/api/learning-tasks/'+taskid+'/confirm',json={'draft_version':version,'session_id':str(sid)}); assert a.status_code==200,a.text
    b=client.post('/api/learning-tasks/'+taskid+'/confirm',json={'draft_version':version,'session_id':str(sid)}); assert b.status_code==200,b.text
    with session_factory() as db:
        items=list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id==ctx.daily_plan_id).order_by(PracticeItem.ordinal)))
        assert len(items)==before['practice_items']+1
        added_item=next(item for item in items if str(item.question_id)==q['question_id'])
        assert str(added_item.question_version_id)==q['question_version']
        assert db.scalar(select(func.count()).select_from(DailyPlan))==before['daily_plans']
        assert db.scalar(select(func.count()).select_from(PersonalGenerationBatch))==batches
    assert any(n=='done' for n,_ in frames)
    import os,json
    from pathlib import Path
    output=os.environ.get('PHASE45I_CLOSE_OUTPUT')
    if output:
        evidence={'input':PROMPT,'route':saved.metadata_['capability_route'],
            'candidate':q,'find_questions_trace':[step for step in task.trace if step['tool']=='find_questions'],
            'task_id':taskid,'draft_version':version,'no_provider_calls':not provider.prompts,
            'batch_count_before_and_after':batches,'counts_before_confirmation':before,
            'plan_id':str(ctx.daily_plan_id),'confirmed_question_id':str(items[1].question_id),
            'confirmed_question_version_id':str(items[1].question_version_id),
            'repeat_request_replayed':True,'repeat_confirmation_ok':True,'sse_events':[name for name,_ in frames]}
        (Path(output)/'similar-bank-flow-evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,default=str,indent=2),encoding='utf-8')


def test_current_question_lookup_and_ellipsis_create_confirmable_append_only(client,home,session_factory):
    """Natural current-question wording is read-only; the next short turn stages the exact candidate."""
    sid,ctx=setup_paper(client,home,session_factory)
    provider=QAProvider('相似题检索不得调用通用问答模型')
    before=counts(session_factory)
    frames=talk(session_factory,sid,AssistantRequest(
        question='题库有类似当前这道隐函数求导的题目吗？',study_context=ctx),provider)
    first=reply(session_factory,sid)
    assert first.metadata_['capability_route']['intent']=='similar',first.metadata_.get('capability_route')
    assert first.metadata_['capability_route']['reason']=='current_question_similar_bank_lookup'
    assert first.metadata_['writes'] is False
    assert '题号' in first.content and '版本' in first.content and '来源' in first.content
    candidates=first.metadata_['similar_items']
    assert candidates and candidates[0]['similar_evidence'] is True
    assert candidates[0]['stem'] in first.content
    assert not any(name in {'planner','personal_generation','practice_request'} for name,_ in frames)
    assert counts(session_factory)==before

    talk(session_factory,sid,AssistantRequest(
        question='帮我找10道相关题，看看哪些可以加入今日卷。',study_context=ctx),provider)
    second=reply(session_factory,sid)
    assert second.metadata_['answer_source']=='similar_questions'
    assert second.metadata_['writes'] is False
    assert '只读检索' in second.content and len(second.metadata_['similar_items']) <= 10
    assert counts(session_factory)==before

    talk(session_factory,sid,AssistantRequest(
        question='只看题目，不要加入今日卷。',study_context=ctx),provider)
    readonly=reply(session_factory,sid)
    assert readonly.metadata_['answer_source']=='similar_questions_clarification'
    assert readonly.metadata_['writes'] is False and '没有加入或修改今日卷' in readonly.content
    assert readonly.metadata_['similar_items']==second.metadata_['similar_items']

    talk(session_factory,sid,AssistantRequest(
        question='这些题目哪些比较难？',study_context=ctx),provider)
    difficulty=reply(session_factory,sid)
    assert '没有可核验的逐题难度评估' in difficulty.content
    assert difficulty.metadata_['similar_items']==second.metadata_['similar_items']
    assert counts(session_factory)==before

    proposal_frames=talk(session_factory,sid,AssistantRequest(
        question='帮我加入一道',study_context=ctx),provider)
    proposal=reply(session_factory,sid)
    assert any(name=='planner' for name,_ in proposal_frames)
    assert proposal.metadata_['capability_route']['reason']=='similar_candidate_append_proposal'
    public_proposal=next(payload for name,payload in proposal_frames if name=='planner')
    assert not public_proposal.get('metrics',{}).get('pre_generation'), public_proposal
    assert len(public_proposal.get('draft',{}).get('questions',[]))==1, public_proposal
    assert public_proposal['draft'].get('kind') not in {'study_plan','activity_schedule'}
    task_id=UUID(proposal.metadata_['planner_task_id'])
    with session_factory() as db:
        task=db.get(LearningTask,task_id)
        assert task.status=='ready',{'message':task.message,'trace':task.trace}
        assert task.context['daily_plan_operation']=='append'
        assert task.context['planner_handoff']['constraints']['similar_requested'] is True
        proposed=dict(task.draft['questions'][0])
        first_addable=next(item for item in candidates if not item['in_today'] and item['similar_evidence'] is True)
        assert proposed['question_id']==first_addable['question_id']
        assert proposed['question_version']==first_addable['version_id']
    assert counts(session_factory)==before, 'proposal must not write to the formal plan'

    confirm_frames=talk(session_factory,sid,AssistantRequest(question='确认',study_context=ctx),provider)
    confirmed=reply(session_factory,sid)
    assert confirmed.metadata_['bank_confirmation_resolution']=='confirmed'
    assert any(name=='planner' for name,_ in confirm_frames)
    with session_factory() as db:
        saved_task=db.get(LearningTask,task_id)
        item=db.scalar(select(PracticeItem).where(PracticeItem.plan_id==ctx.daily_plan_id,
            PracticeItem.question_id==UUID(proposed['question_id'])))
        assert saved_task.metrics['commit']['added_count']==1
        assert item and str(item.question_version_id)==proposed['question_version']
    assert counts(session_factory)['practice_items']==before['practice_items']+1
    assert provider.prompts==[]


def test_similar_append_difficulty_without_evidence_clarifies_and_keeps_candidates(client,home,session_factory):
    sid,ctx=setup_paper(client,home,session_factory)
    provider=QAProvider('相似题查询不得调用通用模型')
    before=counts(session_factory)
    talk(session_factory,sid,AssistantRequest(
        question='找10道当前题目的类似题',study_context=ctx),provider)
    search=reply(session_factory,sid)
    assert search.metadata_['similar_items']
    response=talk(session_factory,sid,AssistantRequest(
        question='帮我加入两道比较难的题目',study_context=ctx),provider)
    clarified=reply(session_factory,sid)
    assert '没有可核验的逐题难度依据' in clarified.content
    assert clarified.metadata_['answer_source']=='similar_questions_clarification'
    assert clarified.metadata_['writes'] is False
    assert clarified.metadata_['similar_items']==search.metadata_['similar_items']
    assert not clarified.metadata_.get('planner_task_id')
    assert not any(name=='planner' for name,_ in response)
    assert counts(session_factory)==before


def test_omitted_similar_candidate_turns_keep_pool_and_select_alternatives(client,home,session_factory):
    """Short follow-ups remain attached to the version-pinned similar-search object."""
    sid,ctx=setup_paper(client,home,session_factory)
    with session_factory.begin() as db:
        reference=db.get(Question,ctx.question_id)
        for index in range(4):
            candidate=Question(kp_id=reference.kp_id,question_type=reference.question_type,
                stem=f'SYNTHETIC similar candidate {index}: 求导并判断结果。',
                options={'A':str(index),'B':str(index+1)},correct_answer='B',
                explanation='独立核验的集成测试候选。',estimated_minutes=5,
                grading_mode='auto',grading_config={'verified':True,'method':'single_choice'},
                difficulty='hard',skill_tags=['链式求导'],is_active=True)
            from tests.integration.test_learning_loop import mark_isolated_question_trusted
            mark_isolated_question_trusted(candidate,db=db);db.add(candidate)
    provider=QAProvider('相似题多轮上下文不得调用通用模型')
    before=counts(session_factory)
    talk(session_factory,sid,AssistantRequest(question='找10道当前题目的类似题',study_context=ctx),provider)
    search=reply(session_factory,sid)
    pool=search.metadata_.get('similar_candidate_pool')
    assert len(pool)>=4
    assert search.metadata_['writes'] is False

    talk(session_factory,sid,AssistantRequest(question='再来两道',study_context=ctx),provider)
    two=reply(session_factory,sid)
    assert two.metadata_['answer_source']=='similar_questions'
    assert len(two.metadata_['similar_items'])==2
    selected_ids={item['question_id'] for item in two.metadata_['similar_items']}
    assert selected_ids <= {item['question_id'] for item in pool}
    assert all(item['similar_evidence'] is True for item in two.metadata_['similar_items'])
    assert '只读筛选' in two.content and counts(session_factory)==before

    talk(session_factory,sid,AssistantRequest(question='换成更难的',study_context=ctx),provider)
    harder=reply(session_factory,sid)
    assert '没有可核验的逐题难度评估' in harder.content
    assert harder.metadata_['similar_items']==two.metadata_['similar_items']
    assert harder.metadata_['similar_candidate_pool']==pool
    assert harder.metadata_['writes'] is False and counts(session_factory)==before

    talk(session_factory,sid,AssistantRequest(question='刚才那两道不要，换另外两道',study_context=ctx),provider)
    alternatives=reply(session_factory,sid)
    assert len(alternatives.metadata_['similar_items'])==2
    alternative_ids={item['question_id'] for item in alternatives.metadata_['similar_items']}
    assert alternative_ids.isdisjoint(selected_ids)
    assert alternative_ids <= {item['question_id'] for item in pool}
    assert all(item['similar_evidence'] is True for item in alternatives.metadata_['similar_items'])
    assert '换出 2 道不同的' in alternatives.content
    assert alternatives.metadata_['writes'] is False and counts(session_factory)==before

    proposal_frames=talk(session_factory,sid,AssistantRequest(question='加入第一道',study_context=ctx),provider)
    proposal=reply(session_factory,sid)
    assert any(name=='planner' for name,_ in proposal_frames)
    task_id=UUID(proposal.metadata_['planner_task_id'])
    with session_factory() as db:
        task=db.get(LearningTask,task_id)
        assert task.status=='ready',task.message
        assert task.draft['questions'][0]['question_id']==alternatives.metadata_['similar_items'][0]['question_id']
        assert counts(session_factory)==before
        from backend.services.learning_task_service import _draft_version
        draft_version=_draft_version(task)
    confirmation=talk(session_factory,sid,AssistantRequest(question='确认',study_context=ctx),provider)
    assert any(name=='planner' for name,_ in confirmation)
    with session_factory() as db:
        added=db.scalar(select(PracticeItem).where(PracticeItem.plan_id==ctx.daily_plan_id,
            PracticeItem.question_id==UUID(alternatives.metadata_['similar_items'][0]['question_id'])))
        assert added is not None
        added_item_id=str(added.id)
        assert str(added.question_version_id)==alternatives.metadata_['similar_items'][0]['version_id']
        assert counts(session_factory)['practice_items']==before['practice_items']+1

    talk(session_factory,sid,AssistantRequest(question='再来一道',study_context=ctx),provider)
    next_candidate=reply(session_factory,sid)
    assert next_candidate.metadata_['answer_source']=='similar_questions'
    assert len(next_candidate.metadata_['similar_items'])==1
    assert next_candidate.metadata_['similar_items'][0]['question_id'] != alternatives.metadata_['similar_items'][0]['question_id']
    with session_factory() as db:
        current_ids={str(value) for value in db.scalars(select(PracticeItem.question_id).where(
            PracticeItem.plan_id==ctx.daily_plan_id))}
    assert next_candidate.metadata_['similar_items'][0]['question_id'] not in current_ids
    assert next_candidate.metadata_['writes'] is False
    assert counts(session_factory)['practice_items']==before['practice_items']+1

    # A later pronoun may refer to the exact candidate just committed. Resolve
    # that object from the committed same-session task and keep removal behind
    # the existing versioned paper-adjustment preview/confirmation boundary.
    removal_frames=talk(session_factory,sid,AssistantRequest(
        question='把刚才加入的那道删除，预算5分钟',study_context=ctx),provider)
    removal=reply(session_factory,sid)
    adjustment=(removal.metadata_ or {}).get('paper_adjustment') or {}
    removal_proposal=adjustment.get('proposal') if isinstance(adjustment,dict) else None
    assert isinstance(removal_proposal,dict) and removal_proposal.get('task_id'), (
        f"content={removal.content!r}; metadata={removal.metadata_!r}")
    assert adjustment['context']['operation']=='remove'
    assert adjustment['context']['item_ids']==[added_item_id]
    assert removal.metadata_['writes'] is False
    workload=removal_proposal.get('workload') or (removal_proposal.get('draft') or {}).get('workload') or {}
    assert workload.get('budget_minutes')==5
    assert workload.get('requires_confirmation') is True
    assert '超出预算' in removal.content and '尚未执行' in removal.content
    assert '回复“确认超预算调整”' in removal.content
    generic_confirmation_frames=talk(session_factory,sid,AssistantRequest(
        question='确认调整',study_context=ctx),provider)
    with session_factory() as db:
        unchanged=db.scalar(select(PracticeItem).where(PracticeItem.id==UUID(added_item_id)))
        assert unchanged is not None and unchanged.removed_at is None
        assert counts(session_factory)['practice_items']==before['practice_items']+1
    assert not any(name=='paper_adjustment' for name,_ in generic_confirmation_frames)
    with session_factory() as db:
        assert counts(session_factory)['practice_items']==before['practice_items']+1
        persisted_added=db.scalar(select(PracticeItem).where(
            PracticeItem.plan_id==ctx.daily_plan_id,
            PracticeItem.question_id==UUID(alternatives.metadata_['similar_items'][0]['question_id'])))
        assert persisted_added is not None and persisted_added.removed_at is None
    confirmation_frames=talk(session_factory,sid,AssistantRequest(
        question='确认超预算调整',study_context=ctx),provider)
    assert any(name=='paper_adjustment' for name,_ in confirmation_frames)
    with session_factory() as db:
        persisted_added=db.scalar(select(PracticeItem).where(
            PracticeItem.plan_id==ctx.daily_plan_id,
            PracticeItem.question_id==UUID(alternatives.metadata_['similar_items'][0]['question_id'])))
        assert persisted_added is not None and persisted_added.removed_at is not None
        assert str(persisted_added.question_version_id)==alternatives.metadata_['similar_items'][0]['version_id']
        assert counts(session_factory)['practice_items']==before['practice_items']+1
        assert db.scalar(select(func.count()).select_from(PracticeItem).where(
            PracticeItem.plan_id==ctx.daily_plan_id,PracticeItem.removed_at.is_(None)))==before['practice_items']
    assert provider.prompts==[]


def test_chat_confirmation_commits_the_same_bank_preview_and_is_idempotent(client, home, session_factory):
    """A plain chat confirmation must reach the official transactional commit path."""
    from backend.services.learning_task_service import _draft_version

    sid, ctx = setup_paper(client, home, session_factory)
    provider = QAProvider('通用回答不应被调用')
    first = talk(session_factory, sid, AssistantRequest(question=PROMPT, study_context=ctx), provider)
    proposed = reply(session_factory, sid)
    with session_factory() as db:
        task = db.get(LearningTask, proposed.metadata_['planner_task_id'])
        assert task.status == 'ready' and task.draft, {'message':task.message,'trace':task.trace,
            'handoff':(task.context or {}).get('planner_handoff'),'study_context':ctx.model_dump(mode='json')}
        candidate = task.draft['questions'][0]
        task_id = task.id
        version = _draft_version(task)
        plan_id = ctx.daily_plan_id
    before = counts(session_factory)

    confirmation = talk(session_factory, sid, AssistantRequest(question='确认', study_context=ctx), provider)
    confirmed = reply(session_factory, sid)
    assert provider.prompts == []
    assert any(event == 'planner' for event, _ in confirmation)
    assert any(event == 'done' and payload.get('status') == 'completed'
               for event, payload in confirmation)
    assert confirmed.metadata_['capability_route']['intent'] == 'confirm'
    with session_factory() as db:
        stored_task = db.get(LearningTask, task_id)
        items = list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id == plan_id)
                                .order_by(PracticeItem.ordinal)))
        added = [item for item in items if str(item.question_id) == candidate['question_id']]
        assert stored_task.metrics['commit']['added_count'] == 1
        assert len(added) == 1
        assert str(added[0].question_version_id) == candidate['question_version']
        assert str(added[0].question_id) == candidate['question_id']
    after_first = counts(session_factory)
    assert after_first['practice_items'] == before['practice_items'] + 1

    duplicate = talk(session_factory, sid, AssistantRequest(question='确认', study_context=ctx), provider)
    assert provider.prompts == []
    assert any(event == 'done' and payload.get('status') == 'completed'
               for event, payload in duplicate)
    assert counts(session_factory) == after_first


def test_explicit_same_preview_candidate_confirmation_commits_without_asking_again(client, home, session_factory):
    """A specific selection from the same chat should resume its owned bank proposal."""
    from backend.services.learning_task_service import _draft_version
    sid, ctx = setup_paper(client, home, session_factory)
    provider = QAProvider('不应进入通用问答')
    talk(session_factory, sid, AssistantRequest(question=PROMPT, study_context=ctx), provider)
    proposed = reply(session_factory, sid)
    with session_factory() as db:
        task = db.get(LearningTask, proposed.metadata_['planner_task_id'])
        candidate = dict(task.draft['questions'][0])
        task_id = task.id
        version = _draft_version(task)
        plan_id = ctx.daily_plan_id
    before = counts(session_factory)

    frames = talk(session_factory, sid, AssistantRequest(
        question='就这题吧给我放在今日卷', study_context=ctx), provider)
    committed = reply(session_factory, sid)
    assert provider.prompts == []
    assert committed.metadata_['bank_confirmation_resolution'] == 'confirmed'
    assert '已加入今日卷' in committed.content
    assert any(event == 'planner' for event, _ in frames)
    with session_factory() as db:
        stored = db.get(LearningTask, task_id)
        items = list(db.scalars(select(PracticeItem).where(
            PracticeItem.plan_id == plan_id, PracticeItem.question_id == candidate['question_id'])))
        assert stored.metrics['commit']['added_count'] == 1
        assert len(items) == 1
        assert str(items[0].question_version_id) == candidate['question_version']
    assert counts(session_factory)['practice_items'] == before['practice_items'] + 1

    repeat = talk(session_factory, sid, AssistantRequest(
        question='把预览中刚才那道题加入今日卷', study_context=ctx), provider)
    repeated = reply(session_factory, sid)
    assert provider.prompts == []
    assert repeated.metadata_['bank_confirmation_resolution'] == 'confirmed'
    assert '重复确认没有新增题目' in repeated.content
    assert any(event == 'done' and payload.get('status') == 'completed' for event, payload in repeat)
    assert counts(session_factory)['practice_items'] == before['practice_items'] + 1
    assert task_id and version


def test_plain_confirmation_without_same_session_proposal_never_writes_or_asks_model(session_factory):
    sid = uuid4()
    with session_factory.begin() as db:
        db.add(ChatSession(id=sid, mode='builtin', purpose='study', study_date='2026-01-01'))
    provider = QAProvider('模型回答不应接管业务确认')
    before = counts(session_factory)
    frames = talk(session_factory, sid, AssistantRequest(question='确认'), provider)
    saved = reply(session_factory, sid)
    assert provider.prompts == []
    assert saved.metadata_['capability_route']['reason'] == 'confirmation_without_proposal'
    assert '没有可确认' in saved.content
    assert any(event == 'done' and payload.get('status') == 'completed'
               for event, payload in frames)
    assert counts(session_factory) == before


def test_no_shared_method_does_not_generate_or_invent_similar_candidate(client,home,session_factory):
    sid,ctx=setup_paper(client,home,session_factory,matching=False)
    before=counts(session_factory); provider=QAProvider('不得调用模型')
    talk(session_factory,sid,AssistantRequest(question=PROMPT,study_context=ctx),provider)
    saved=reply(session_factory,sid)
    assert provider.prompts==[] and 'personal_generation' not in saved.metadata_
    with session_factory() as db:
        task=db.get(LearningTask,saved.metadata_['planner_task_id'])
        assert task.status=='needs_info' and task.draft is None,{'message':task.message,'trace':task.trace,
            'handoff':(task.context or {}).get('planner_handoff'),'study_context':ctx.model_dump(mode='json')}
        assert any(s['tool']=='find_questions' for s in task.trace)
    assert counts(session_factory)==before


def test_missing_reference_asks_and_never_generates(client,home,session_factory):
    from uuid import uuid4
    from backend.models.practice_request import PracticeRequest
    sid=uuid4()
    with session_factory.begin() as db: db.add(ChatSession(id=sid,mode='builtin',purpose='study',study_date='2026-01-01'))
    provider=QAProvider('不得调用模型'); before=counts(session_factory)
    with session_factory() as db:
        task_count_before=db.scalar(select(func.count()).select_from(LearningTask))
        request_count_before=db.scalar(select(func.count()).select_from(PracticeRequest))
    talk(session_factory,sid,AssistantRequest(question=PROMPT,study_context=StudyContext(surface='study')),provider)
    saved=reply(session_factory,sid)
    assert provider.prompts==[] and 'personal_generation' not in saved.metadata_
    assert '参照' in saved.content or '知识点' in saved.content
    assert saved.metadata_['capability_route']['reason']=='similar_reference_required'
    assert saved.metadata_['notice_code']=='similar_reference_required'
    assert saved.metadata_['model_called'] is False and saved.metadata_['writes'] is False
    assert not saved.metadata_.get('planner_task_id') and not saved.metadata_.get('practice_request_id')
    assert counts(session_factory)==before
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(LearningTask))==task_count_before
        assert db.scalar(select(func.count()).select_from(PracticeRequest))==request_count_before


def test_bank_failure_is_not_inventory_shortage_or_generation(client,home,session_factory,monkeypatch):
    from backend.services.learning_task_tools import TaskTools
    sid,ctx=setup_paper(client,home,session_factory)
    before=counts(session_factory); provider=QAProvider('不得调用模型')
    def fail(*args,**kwargs):raise RuntimeError('SYNTHETIC bank tool failure')
    monkeypatch.setattr(TaskTools,'find_questions',fail)
    talk(session_factory,sid,AssistantRequest(question=PROMPT,study_context=ctx),provider)
    saved=reply(session_factory,sid)
    assert provider.prompts==[] and 'personal_generation' not in saved.metadata_
    with session_factory() as db:
        task=db.get(LearningTask,saved.metadata_['planner_task_id'])
        assert task.status=='failed' and task.error_code=='business_tool_failed'
        assert task.draft is None and '未完成' in task.message
    assert counts(session_factory)==before


def test_explicit_new_question_uses_generation_confirmation_not_bank(client,home,session_factory):
    sid,ctx=setup_paper(client,home,session_factory)
    provider=QAProvider('不得调用真实模型'); before=counts(session_factory)
    frames=talk(session_factory,sid,AssistantRequest(question='根据这个知识点新编一道题，不用查我的题库。',study_context=ctx),provider)
    saved=reply(session_factory,sid)
    assert provider.prompts==[]
    assert any(n=='personal_generation_confirmation' for n,_ in frames)
    assert not saved.metadata_.get('planner_task_id') and counts(session_factory)==before


def test_own_bank_includes_eligible_personal_question_and_keeps_its_identity(bank):
    from tests.integration.test_personal_question_bank import body
    from tests.integration.test_learning_assistant import NOW
    from backend.services.personal_question_service import run_generation
    from backend.schemas.learning_task import ConfirmTask
    from backend.services.learning_task_service import confirm_task,_draft_version
    from backend.services.question_eligibility import question_eligibility
    from backend.models.learning import KnowledgePoint
    factory,kp=bank
    class ForbiddenProvider:
        def complete(self,*args,**kwargs):raise AssertionError('no model calls')
    # Produce a legitimately bound personal practice item through the existing
    # offline service before the request; do not forge generation evidence.
    generated=run_generation(factory,body(kp,1,surface='chat',generation_mode='deterministic_fast'),ForbiddenProvider(),now=NOW)
    assert len(generated['question_ids'])==1 and generated['model_calls']==0,generated
    qid=generated['question_ids'][0];sid=uuid4()
    with factory.begin() as db:
        q=db.get(Question,qid)
        assert question_eligibility(q,db.get(KnowledgePoint,kp)).practice_eligible
        version=str(q.current_version_id)
        db.add(ChatSession(id=sid,mode='builtin',purpose='study',study_date='2026-01-01'))
    with factory() as db:batches=db.scalar(select(func.count()).select_from(PersonalGenerationBatch))
    provider=QAProvider('不得调用模型')
    ctx=StudyContext(surface='study',knowledge_node_ids=[kp])
    frames=talk(factory,sid,AssistantRequest(question='从我的题库找一道题加入今日卷',study_context=ctx),provider)
    saved=reply(factory,sid)
    with factory() as db:
        task=db.get(LearningTask,saved.metadata_['planner_task_id']);assert task.status=='ready',(task.message,task.trace)
        candidate=task.draft['questions'][0];q=db.get(Question,candidate['question_id'])
        assert q.bank_scope=='personal' and candidate['source_category'].startswith('personal')
        assert str(q.id)==qid and str(q.current_version_id)==candidate['question_version']==version
        assert db.scalar(select(func.count()).select_from(PersonalGenerationBatch))==batches
        taskid=task.id;draft_version=_draft_version(task)
    assert provider.prompts==[] and any(n=='done' for n,_ in frames)
    confirm_task(factory,taskid,ConfirmTask(draft_version=draft_version),now=NOW)
    with factory() as db:
        item=db.scalar(select(PracticeItem).where(PracticeItem.question_id==qid))
        assert item and str(item.question_version_id)==version
        assert db.scalar(select(func.count()).select_from(PersonalGenerationBatch))==batches


def test_existing_generation_context_does_not_hijack_new_bank_request(client,home,session_factory):
    from backend.models.chat import ChatMessage
    sid,ctx=setup_paper(client,home,session_factory)
    with session_factory.begin() as db:
        db.add(ChatMessage(session_id=sid,role='assistant',status='completed',content='旧的生成确认',metadata_={'generation_context':{'instruction':'新编一道题','waiting_reference':True},'personal_generation_confirmation':{'nodes':[]}}))
    provider=QAProvider('不得调用模型');before=counts(session_factory)
    talk(session_factory,sid,AssistantRequest(question=PROMPT+'，难度提高。',study_context=ctx),provider)
    saved=reply(session_factory,sid)
    assert provider.prompts==[] and saved.metadata_['capability_route']['reason']=='explicit_bank_selection'
    assert 'personal_generation' not in saved.metadata_ and 'personal_generation_confirmation' not in saved.metadata_
    assert saved.metadata_.get('generation_context') is None
    with session_factory() as db:
        task=db.get(LearningTask,saved.metadata_['planner_task_id']);assert task.status=='ready',(task.message,task.trace)
        assert any(step['tool']=='find_questions' for step in task.trace)
    assert counts(session_factory)==before


def test_shared_broad_node_name_is_not_claimed_as_method_similarity(client,home,session_factory):
    sid,ctx=setup_paper(client,home,session_factory,matching='generic')
    provider=QAProvider('不得调用模型');before=counts(session_factory)
    talk(session_factory,sid,AssistantRequest(question=PROMPT,study_context=ctx),provider)
    saved=reply(session_factory,sid)
    assert provider.prompts==[] and 'personal_generation' not in saved.metadata_
    with session_factory() as db:
        task=db.get(LearningTask,saved.metadata_['planner_task_id']);assert task.status=='needs_info' and task.draft is None
        assert task.error_code=='similar_evidence_missing'
    assert counts(session_factory)==before


def test_named_scope_conflicting_with_reference_is_clarified(client,home,session_factory):
    sid,ctx=setup_paper(client,home,session_factory)
    before=counts(session_factory);provider=QAProvider('不得调用模型')
    talk(session_factory,sid,AssistantRequest(question='从我的题库找一道洛必达法则的类似题加入今日卷',study_context=ctx),provider)
    saved=reply(session_factory,sid)
    with session_factory() as db:
        task=db.get(LearningTask,saved.metadata_['planner_task_id'])
        assert task.status=='needs_info' and task.draft is None
        assert '不一致' in task.message
    assert provider.prompts==[] and counts(session_factory)==before


def test_version_change_between_search_and_validation_rejects_candidate(client,home,session_factory,monkeypatch):
    from backend.services.learning_task_tools import TaskTools
    sid,ctx=setup_paper(client,home,session_factory);before=counts(session_factory)
    original=TaskTools.validate_plan
    def changed(self,db,args):
        candidate=db.get(Question,args.question_ids[0]);candidate.skill_tags=['改变后的方法'];db.flush()
        return original(self,db,args)
    monkeypatch.setattr(TaskTools,'validate_plan',changed)
    provider=QAProvider('不得调用模型')
    talk(session_factory,sid,AssistantRequest(question=PROMPT,study_context=ctx),provider)
    saved=reply(session_factory,sid)
    with session_factory() as db:
        task=db.get(LearningTask,saved.metadata_['planner_task_id'])
        assert task.status=='needs_info' and task.draft is None
        assert task.error_code=='candidate_version_changed'
    assert provider.prompts==[] and counts(session_factory)==before


def test_ambiguous_come_or_make_question_asks_source_instead_of_generating(client,home,session_factory):
    sid,ctx=setup_paper(client,home,session_factory);before=counts(session_factory)
    provider=QAProvider('不得调用模型')
    frames=talk(session_factory,sid,AssistantRequest(question='请给我出一道题',study_context=ctx),provider)
    saved=reply(session_factory,sid)
    assert provider.prompts==[] and saved.metadata_['capability_route']['reason']=='question_source_clarification'
    assert '现有题库' in saved.content and '新编' in saved.content
    assert not saved.metadata_.get('personal_generation_confirmation') and not saved.metadata_.get('planner_task_id')
    assert any(name=='done' for name,_ in frames) and counts(session_factory)==before


def test_wrong_historic_bank_generation_does_not_authorize_followup(client,home,session_factory):
    from backend.models.chat import ChatMessage
    sid,ctx=setup_paper(client,home,session_factory)
    with session_factory.begin() as db:
        db.add(ChatMessage(session_id=sid,role='assistant',status='completed',content='旧误路由',metadata_={'generation_context':{'instruction':PROMPT},'personal_generation':{'question_ids':[]}}))
    provider=QAProvider('不得调用模型');before=counts(session_factory)
    talk(session_factory,sid,AssistantRequest(question='再来一道类似的题',study_context=ctx),provider)
    saved=reply(session_factory,sid)
    assert provider.prompts==[] and saved.metadata_['capability_route']['reason']=='question_source_clarification'
    assert not saved.metadata_.get('generation_followup_authorized') and counts(session_factory)==before
