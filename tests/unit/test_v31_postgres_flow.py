"""Actual owned PostgreSQL, fresh marked schema and synthetic seed per case.

No public-schema fallback or retained browser inventory dependency.
"""
import asyncio,json,socket,sys
from datetime import datetime,timezone
from uuid import UUID
import pytest
from sqlalchemy import create_engine,select,func
from sqlalchemy.orm import sessionmaker
from backend.models.chat import ChatSession,ChatMessage
from backend.models.learning import QuestionVersion,Question,PracticeItem,DailyPlan,QuestionAttempt,LearningEvent
from backend.models.learning import KnowledgePoint
from backend.models.practice_request import PracticeRequest
from backend.models.learning_task import LearningTask
from backend.schemas.learning_assistant import AssistantRequest,StudyContext
from backend.schemas.learning_task import ConfirmTask
from backend.services.learning_assistant_service import assistant_stream
from backend.services.practice_request_service import send_request,plan_request
from backend.services.learning_task_service import confirm_task
from backend.errors import AppError

# A fixed, otherwise unused study date makes the rollback cases repeatable after
# a real browser acceptance has legitimately filled the retained today's plan.
# This does not change the host clock or any persisted historical date.
TEST_NOW=datetime(2040,1,2,0,0,tzinfo=timezone.utc)

def no_external(event,args):
    if event=='socket.getaddrinfo' and args[0] not in {'127.0.0.1','localhost','::1'}:raise AssertionError('external DNS forbidden')
    if event=='socket.connect' and not (isinstance(args[1],tuple) and args[1][0] in {'127.0.0.1','::1'}):raise AssertionError('external socket forbidden')
sys.addaudithook(no_external)

class NoProvider:
    async def stream(self,*a,**kw):raise AssertionError('must use lesson/business tools');yield ''
    def complete(self,*a,**kw):raise AssertionError('must not generate/answer by mock')
    def tool_turn(self,*a,**kw):raise AssertionError('must not call model planner')

@pytest.fixture
def factory():
    # R12：不再依赖 63044 硬编码；统一读取 TEST_DATABASE_URL（隔离 _test 集群）。
    import os
    from sqlalchemy.engine import make_url
    url = os.environ.get('TEST_DATABASE_URL') or os.environ.get('DATABASE_URL')
    assert url, 'TEST_DATABASE_URL 必须由隔离测试运行器显式设置'
    u = make_url(url)
    assert (u.database or '').endswith('_test') and u.port != 5433, '测试库必须是非 5433 的 _test 库'
    from scripts.run_question_repair_pilot import isolated_factory
    from scripts.seed import seed_all
    from tests.integration.test_learning_loop import mark_isolated_question_trusted
    with isolated_factory(url) as (f, _schema):
        with f.begin() as db:
            seed_all(db);db.flush()
            for question in db.scalars(select(Question)):
                mark_isolated_question_trusted(question,db=db)
            node=db.scalar(select(KnowledgePoint).where(KnowledgePoint.code=='math.calculus.limit.lhopital'))
            for index in range(2):
                question=Question(kp_id=node.id,question_type='single_choice',
                    stem=f'SYNTHETIC V31 alternate {index}: 求 lim(x->0) sin(x)/x。',
                    options={'A':'1','B':'0','C':'2','D':'3'},correct_answer='A',
                    explanation='合成测试解析：该极限为1。',estimated_minutes=3,
                    grading_mode='auto',grading_config={'verified':True,'method':'single_choice'})
                mark_isolated_question_trusted(question,db=db)
        yield f


def private_details(factory, view):
    assert 'preview_draft' not in view['details']
    assert '"question_id"' not in json.dumps(view)
    with factory() as db:
        return db.get(PracticeRequest,UUID(view['id'])).request

def session(f,purpose='qa'):
    with f.begin() as db:
        s=ChatSession(title='V31 ROLLBACK ONLY',mode='builtin',purpose=purpose,
            study_date=TEST_NOW.date().isoformat() if purpose=='study' else None)
        db.add(s);db.flush();return s.id

def counts(f):
    with f() as db:return [db.scalar(select(func.count()).select_from(t)) for t in (Question,QuestionVersion,DailyPlan,PracticeItem,QuestionAttempt,LearningEvent)]

def talk(f,sid,text,context=None):
    async def collect():
        return [raw async for raw in assistant_stream(f,request=None,session_id=sid,
            body=AssistantRequest(question=text,study_context=context or StudyContext(surface='chat')),
            stack=None,provider=NoProvider(),now=TEST_NOW)]
    frames=[]
    for raw in asyncio.run(collect()):
        lines=raw.decode().splitlines();frames.append((lines[0][7:],json.loads(lines[1][6:])))
    assert not any(e=='error' for e,d in frames),frames
    return frames

@pytest.mark.parametrize('text',[
 '洛必达法则是怎么样的，帮我从题库里面拿出一道放进今日卷。',
 '讲讲洛必达法则，再从题库挑一道加入今日卷。',
 '洛必达法则是什么？先给我讲清楚，题目可以先选好但不要加入。',
 '帮我找一道洛必达的题，先给我看看。',
 '给我安排一道洛必达题。',
])
def test_real_preview_has_version_no_plan_write(factory,text):
    sid=session(factory);before=counts(factory)
    frames=talk(factory,sid,text)
    if text=='洛必达法则是什么？先给我讲清楚，题目可以先选好但不要加入。':
        assert not any(e in {'practice_request','planner'} for e,d in frames)
        assert '去心邻域' in next(d['answer'] for e,d in frames if e=='done')
        assert counts(factory)==before
        return
    if text=='帮我找一道洛必达的题，先给我看看。':
        assert not any(e in {'practice_request','planner'} for e,d in frames)
        with factory() as db:
            saved=db.scalar(select(ChatMessage).where(ChatMessage.session_id==sid,
                ChatMessage.role=='assistant').order_by(ChatMessage.seq.desc()))
            refs=saved.metadata_['read_only_data_query']['preview_questions']
            assert len(refs)==1
            version=db.get(QuestionVersion,UUID(refs[0]['question_version']))
            assert str(version.question_id)==refs[0]['question_id'] and version.stem
        assert counts(factory)==before
        return
    view=next(d for e,d in frames if e=='practice_request')
    draft=private_details(factory,view)['preview_draft'];assert len(draft['questions'])==1
    q=draft['questions'][0];assert len(q['options'])==4 and q['stem'] and q['kp_name']=='洛必达法则'
    with factory() as db:
        version=db.get(QuestionVersion,UUID(q['question_version']));assert str(version.question_id)==q['question_id']
    assert view['status']=='draft' and not view['details'].get('confirmation_a',False)
    with factory() as db:
        pending=db.get(PracticeRequest,UUID(view['id']))
        assert pending.planner_task_id is None and pending.daily_plan_id is None
        assert pending.handled_at is None and not pending.request.get('confirmation_a',False)
    assert counts(factory)==before
    expected_tools=['get_learning_state','get_question_availability','find_questions','validate_plan']
    if text!='给我安排一道洛必达题。':
        expected_tools.insert(0,'read_lesson')
    assert [s['tool'] for s in private_details(factory,view)['preview_trace']]==expected_tools

def test_explain_only_and_elliptical_followup_never_select(factory):
    sid=session(factory);before=counts(factory)
    for message in ('先别加题，只解释洛必达法则。','没有合格题也没关系，你先讲解。','先讲知识点，再问我是否要安排题目。'):
        frames=talk(factory,sid,message)
        done=next(d for e,d in frames if e=='done')
        assert '去心邻域' in done['answer'] and '题库选题与待确认方案' not in done['answer'],message
        assert not any(e in {'practice_request','planner'} for e,d in frames)
    assert counts(factory)==before

def test_real_handoff_target_and_repeat_confirm(factory):
    sid=session(factory);target=session(factory,'study');wrong=session(factory,'study')
    frames=talk(factory,sid,'讲讲洛必达法则，再从题库挑一道加入今日卷。')
    rid=UUID(next(d for e,d in frames if e=='practice_request')['id'])
    send_request(factory,rid,source_conversation_id=sid,target_study_session_id=target,now=TEST_NOW)
    with pytest.raises(AppError):plan_request(factory,rid,study_session_id=wrong,provider=NoProvider(),now=TEST_NOW)
    result=plan_request(factory,rid,study_session_id=target,provider=NoProvider(),now=TEST_NOW);task=result['task']
    assert result['request']['status']=='proposed' and task['metrics']['model_calls']==0
    confirmed=confirm_task(factory,UUID(task['task_id']),ConfirmTask(draft_version=task['draft_version']),now=TEST_NOW)
    before=counts(factory)
    repeated=confirm_task(factory,UUID(task['task_id']),ConfirmTask(draft_version=task['draft_version']),now=TEST_NOW)
    assert counts(factory)==before and repeated.append_result==confirmed.append_result
    assert confirmed.append_result and len(confirmed.append_result['items'])==1

def test_source_correction_keeps_latest_same_session_lesson(factory):
    sid=session(factory)
    talk(factory,sid,'先别加题，只解释洛必达法则。')
    frames=talk(factory,sid,'我说的是题库已有的题，不要生成新题。')
    assert not any(e in {'practice_request','planner'} for e,d in frames)
    with factory() as db:
        saved=db.scalar(select(ChatMessage).where(ChatMessage.session_id==sid,
            ChatMessage.role=='assistant').order_by(ChatMessage.seq.desc()))
        node=db.scalar(select(KnowledgePoint).where(KnowledgePoint.code=='math.calculus.limit.lhopital'))
        assert saved.metadata_['source_policy']=='existing_bank_only'
        assert saved.metadata_['learning_trace']['resolved_knowledge_node_ids']==[str(node.id)]
        assert saved.metadata_['writes'] is False


def prepare(factory):
    sid=session(factory);target=session(factory,'study')
    frames=talk(factory,sid,'讲讲洛必达法则，再从题库挑一道加入今日卷。')
    rid=UUID(next(d for e,d in frames if e=='practice_request')['id'])
    send_request(factory,rid,source_conversation_id=sid,target_study_session_id=target,now=TEST_NOW)
    result=plan_request(factory,rid,study_session_id=target,provider=NoProvider(),now=TEST_NOW)
    return rid,result['task']


def test_append_database_failure_rolls_back_receipt_and_item(factory):
    from sqlalchemy import event
    rid,task=prepare(factory);before=counts(factory);bind=factory.kw['bind']
    def fail_insert(conn,cursor,statement,parameters,context,executemany):
        if statement.lstrip().lower().startswith('insert into practice_items'):
            raise RuntimeError('V31 controlled DB fault before item insert')
    event.listen(bind,'before_cursor_execute',fail_insert)
    try:
        with pytest.raises(RuntimeError,match='controlled DB fault'):
            confirm_task(factory,UUID(task['task_id']),ConfirmTask(draft_version=task['draft_version']),now=TEST_NOW)
    finally:event.remove(bind,'before_cursor_execute',fail_insert)
    assert counts(factory)==before
    with factory() as db:
        row=db.get(LearningTask,UUID(task['task_id']))
        assert not row.metrics.get('commit') and row.status=='ready'
        assert db.get(PracticeRequest,rid).status=='proposed'


def test_actual_inventory_exhaustion_keeps_lesson_no_extra_append(factory):
    # Materialize once, then use the formal-paper boundary for every append.
    from backend.services.paper_adjustment_service import propose_adjustment,confirm_adjustment
    from backend.schemas.paper_adjustment import PaperAdjustmentRequest,PaperAdjustmentConfirmation,ReplacementReference
    from backend.services.question_eligibility import question_eligibility
    from backend.services.question_versions import question_version_reference
    rid,task=prepare(factory)
    confirmed=confirm_task(factory,UUID(task['task_id']),ConfirmTask(draft_version=task['draft_version']),now=TEST_NOW)
    plan_id=UUID(confirmed.metrics['commit']['plan_id'])
    with factory() as db:
        target=UUID(db.get(PracticeRequest,rid).request['target_study_session_id'])
        node=db.scalar(select(KnowledgePoint).where(KnowledgePoint.code=='math.calculus.limit.lhopital'))
        node_id=node.id
        present=set(db.scalars(select(PracticeItem.question_id).where(PracticeItem.plan_id==plan_id)))
        eligible=[ReplacementReference(question_id=q.id,question_version_id=UUID(question_version_reference(q)))
            for q in db.scalars(select(Question).where(Question.kp_id==node_id,Question.bank_scope=='public'))
            if q.id not in present and question_eligibility(q,node).practice_eligible]
    assert eligible
    for ref in eligible:
        proposal=propose_adjustment(factory,PaperAdjustmentRequest(session_id=target,plan_id=plan_id,
            replacements=[ref],budget_minutes=90),now=TEST_NOW)
        confirm_adjustment(factory,UUID(proposal['task_id']),PaperAdjustmentConfirmation(
            session_id=target,draft_version=proposal['draft_version']),now=TEST_NOW)
    before=counts(factory)
    ctx=StudyContext(surface='study',daily_plan_id=plan_id,knowledge_node_ids=[node_id])
    frames=talk(factory,target,'增加一道洛必达法则题目。',ctx)
    with factory() as db:
        saved=db.scalar(select(ChatMessage).where(ChatMessage.session_id==target,
            ChatMessage.role=='assistant').order_by(ChatMessage.seq.desc()))
        assert not saved.metadata_['paper_adjustment'].get('proposal')
        assert '不足' in saved.content or '没有' in saved.content
    assert counts(factory)==before
    frames=talk(factory,session(factory),'讲讲洛必达法则，再从题库挑一道加入今日卷。')
    assert not any(e in {'practice_request','planner'} for e,d in frames)
    assert '去心邻域' in next(d for e,d in frames if e=='done')['answer']
    assert counts(factory)==before


def test_tool_error_preserves_completed_lesson_without_plan(factory,monkeypatch):
    from backend.services.learning_task_tools import TaskTools
    original=TaskTools.execute
    def fail_find(self,name,args):
        if name=='find_questions':raise RuntimeError('V31 controlled tool failure')
        return original(self,name,args)
    monkeypatch.setattr(TaskTools,'execute',fail_find)
    before=counts(factory)
    frames=talk(factory,session(factory),'讲讲洛必达法则，再从题库挑一道加入今日卷。')
    assert not any(e in {'practice_request','planner'} for e,d in frames)
    assert '去心邻域' in next(d for e,d in frames if e=='done')['answer']
    with factory() as db:
        saved=db.scalar(select(ChatMessage).where(ChatMessage.role=='assistant')
            .order_by(ChatMessage.seq.desc()))
        assert saved.metadata_['selection_error_code']=='business_tool_failed'
        assert any(step['status']=='error' for step in saved.metadata_['selection_trace'])
    assert counts(factory)==before


def test_another_qa_session_cannot_inherit_lesson_scope(factory):
    talk(factory,session(factory),'先别加题，只解释洛必达法则。')
    frames=talk(factory,session(factory),'我说的是题库已有的题，不要生成新题。')
    assert not any(e in {'practice_request','planner'} for e,d in frames)
    with factory() as db:
        saved=db.scalar(select(ChatMessage).where(ChatMessage.role=='assistant')
            .order_by(ChatMessage.seq.desc()))
        assert saved.metadata_['learning_trace']['resolved_knowledge_node_ids']==[]
        assert saved.metadata_['writes'] is False
