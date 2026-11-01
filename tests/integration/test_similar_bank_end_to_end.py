"""Real service/PG path, offline provider, new cluster only."""
from uuid import uuid4
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
    preview=post(client,home,'线性代数90分钟，只做1道题')
    r=client.post(ROOT+'/'+preview['task_id']+'/confirm',json={'session_id':home['session_id'],'draft_version':preview['draft_version']})
    assert r.status_code==200,r.text
    sid=uuid4()
    with session_factory.begin() as db:
        item=db.scalar(select(PracticeItem).where(PracticeItem.plan_id==r.json()['receipt']['plan_id']))
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
        assert task.status=='ready',(task.message,task.trace)
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
    a=client.post('/api/learning-tasks/'+taskid+'/confirm',json={'draft_version':version}); assert a.status_code==200,a.text
    b=client.post('/api/learning-tasks/'+taskid+'/confirm',json={'draft_version':version}); assert b.status_code==200,b.text
    with session_factory() as db:
        items=list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id==ctx.daily_plan_id).order_by(PracticeItem.ordinal)))
        assert len(items)==2
        assert str(items[1].question_id)==q['question_id'] and str(items[1].question_version_id)==q['question_version']
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


def test_chat_confirmation_commits_the_same_bank_preview_and_is_idempotent(client, home, session_factory):
    """A plain chat confirmation must reach the official transactional commit path."""
    from backend.services.learning_task_service import _draft_version

    sid, ctx = setup_paper(client, home, session_factory)
    provider = QAProvider('通用回答不应被调用')
    first = talk(session_factory, sid, AssistantRequest(question=PROMPT, study_context=ctx), provider)
    proposed = reply(session_factory, sid)
    with session_factory() as db:
        task = db.get(LearningTask, proposed.metadata_['planner_task_id'])
        assert task.status == 'ready' and task.draft
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
        assert task.status=='needs_info' and task.draft is None,(task.message,task.trace)
        assert any(s['tool']=='find_questions' for s in task.trace)
    assert counts(session_factory)==before


def test_missing_reference_asks_and_never_generates(client,home,session_factory):
    from uuid import uuid4
    sid=uuid4()
    with session_factory.begin() as db: db.add(ChatSession(id=sid,mode='builtin',purpose='study',study_date='2026-01-01'))
    provider=QAProvider('不得调用模型'); before=counts(session_factory)
    talk(session_factory,sid,AssistantRequest(question=PROMPT,study_context=StudyContext(surface='study')),provider)
    saved=reply(session_factory,sid)
    assert provider.prompts==[] and 'personal_generation' not in saved.metadata_
    assert '参照' in saved.content or '知识点' in saved.content
    assert counts(session_factory)==before


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
