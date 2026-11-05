"""Actual retained isolated PG, each unit case inside an outer rollback.

No parent conftest migration/delete fixtures. Existing rows are never edited.
The browser flow is separate and remains persisted for user inspection.
"""
import asyncio,json,socket,sys
from datetime import datetime,timezone
from uuid import UUID
import pytest
from sqlalchemy import create_engine,select,func
from sqlalchemy.orm import sessionmaker
from backend.models.chat import ChatSession,ChatMessage
from backend.models.learning import QuestionVersion,Question,PracticeItem,DailyPlan,QuestionAttempt,LearningEvent
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
    engine=create_engine(url,connect_args={'connect_timeout':5})
    with engine.connect() as c:
        tx=c.begin();f=sessionmaker(bind=c,expire_on_commit=False,join_transaction_mode='create_savepoint')
        try:yield f
        finally:tx.rollback()
    engine.dispose()

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
    frames=talk(factory,sid,text);view=next(d for e,d in frames if e=='practice_request')
    draft=view['details']['preview_draft'];assert len(draft['questions'])==1
    q=draft['questions'][0];assert len(q['options'])==4 and q['stem'] and q['kp_name']=='洛必达法则'
    with factory() as db:
        version=db.get(QuestionVersion,UUID(q['question_version']));assert str(version.question_id)==q['question_id']
    assert view['status']=='draft' and not view['details']['confirmation_a']
    assert counts(factory)==before
    assert [s['tool'] for s in view['details']['preview_trace']]==['read_lesson','get_learning_state','get_question_availability','find_questions','validate_plan']

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
    request=next(d for e,d in frames if e=='practice_request')
    assert request['details']['preview_status']=='ready'
    assert request['details']['preview_draft']['questions'][0]['kp_name']=='洛必达法则'


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
    # Exhaust the real isolated eligible inventory using only the official
    # proposal/confirmation flow, all within this fixture's outer rollback.
    initial=talk(factory,session(factory),'讲讲洛必达法则，再从题库挑一道加入今日卷。')
    view=next(d for e,d in initial if e=='practice_request')
    found=next(v['result']['questions'] for v in view['details']['preview_trace'] if v['tool']=='find_questions')
    eligible=[q for q in found if not q['in_today_plan'] and q.get('question_version')
              and not q.get('source_category','').startswith('personal')]
    assert eligible
    for _ in eligible:
        rid,task=prepare(factory)
        confirm_task(factory,UUID(task['task_id']),ConfirmTask(draft_version=task['draft_version']),now=TEST_NOW)
    before=counts(factory)
    frames=talk(factory,session(factory),'讲讲洛必达法则，再从题库挑一道加入今日卷。')
    view=next(d for e,d in frames if e=='practice_request')
    assert view['details']['preview_draft'] is None and view['details']['preview_status']=='needs_info'
    assert '可新增 0 道' in view['details']['preview_message']
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
    view=next(d for e,d in frames if e=='practice_request')
    assert view['details']['preview_status']=='failed' and view['details']['preview_draft'] is None
    assert '去心邻域' in next(d for e,d in frames if e=='done')['answer']
    assert view['details']['preview_trace'][-1]['status']=='error'
    assert counts(factory)==before


def test_another_qa_session_cannot_inherit_lesson_scope(factory):
    talk(factory,session(factory),'先别加题，只解释洛必达法则。')
    frames=talk(factory,session(factory),'我说的是题库已有的题，不要生成新题。')
    view=next(d for e,d in frames if e=='practice_request')
    assert view['details']['preview_draft'] is None
    assert view['details']['preview_status']=='needs_info'
