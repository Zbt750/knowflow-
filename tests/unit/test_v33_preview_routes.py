import importlib.util
from pathlib import Path
from uuid import UUID
import pytest
from sqlalchemy import select
from backend.schemas.learning_assistant import StudyContext
from backend.services.assistant_router import route_message
from backend.models.chat import ChatMessage
from backend.models.practice_request import PracticeRequest

spec=importlib.util.spec_from_file_location('v33_support',Path(__file__).with_name('test_v31_postgres_flow.py'))
support=importlib.util.module_from_spec(spec);spec.loader.exec_module(support)
factory=support.factory

@pytest.mark.parametrize('text,intent',[
 ('把刚才那道题加入今日卷','plan'),('换一道同知识点的','plan'),
 ('取消刚才的题，换一道洛必达的','plan'),
 ('讲清楚洛必达法则，如果没有符合资格的洛必达题，就只讲解，不要生成新题。','plan'),
 ('我只想看看题库里有哪些洛必达法则的题，不要创建计划。','find'),
 ('这次只想看题库，不要创建计划。','find')])
def test_original_routes(text,intent):
    assert route_message(text,StudyContext(surface='chat')).intent==intent

def last_evidence(factory,sid):
    with factory() as db:
        return db.scalar(select(ChatMessage).where(ChatMessage.session_id==sid,ChatMessage.role=='assistant').order_by(ChatMessage.seq.desc())).metadata_['read_only_data_query']

def request(frames):
    return next(d for e,d in frames if e=='practice_request')

def test_last_preview_exact_version(factory):
    sid=support.session(factory);before=support.counts(factory)
    support.talk(factory,sid,'有没有洛必达法则的题目？')
    ref=last_evidence(factory,sid)['preview_questions'][0]
    result=request(support.talk(factory,sid,'把刚才那道题加入今日卷'))
    chosen=result['details']['preview_draft']['questions'][0]
    assert (chosen['question_id'],chosen['question_version'])==(ref['question_id'],ref['question_version'])
    assert support.counts(factory)==before

@pytest.mark.parametrize('text',['换一道同知识点的','取消刚才的题，换一道洛必达的'])
def test_replacement_excludes_and_retires_old_draft(factory,text):
    sid=support.session(factory);before=support.counts(factory)
    first=request(support.talk(factory,sid,'先选一道洛必达让我看看，不要加入。'))
    second=request(support.talk(factory,sid,text))
    a=first['details']['preview_draft']['questions'][0];b=second['details']['preview_draft']['questions'][0]
    assert a['question_id']!=b['question_id'] and a['kp_id']==b['kp_id']
    with factory() as db:assert db.get(PracticeRequest,UUID(first['id'])).status=='declined'
    assert support.counts(factory)==before

def test_read_only_list_and_numbered_reference(factory):
    sid=support.session(factory);before=support.counts(factory)
    frames=support.talk(factory,sid,'我只想看看题库里有哪些洛必达法则的题，不要创建计划。')
    assert not any(e in {'practice_request','planner'} for e,d in frames)
    refs=last_evidence(factory,sid)['preview_questions'];assert len(refs)>1
    ambiguous=support.talk(factory,sid,'把刚才那道题加入今日卷')
    assert not any(e=='practice_request' for e,d in ambiguous)
    chosen=request(support.talk(factory,sid,'把第2道加入今日卷'))['details']['preview_draft']['questions'][0]
    assert chosen['question_id']==refs[1]['question_id'] and chosen['question_version']==refs[1]['question_version']
    assert support.counts(factory)==before

def test_old_preview_cannot_be_used_after_expiry(factory):
    from datetime import timedelta
    from backend.services.practice_preview_reference import latest_preview
    sid=support.session(factory);support.talk(factory,sid,'有没有洛必达法则的题目？')
    ref,error=latest_preview(factory,sid,'把刚才那道加入',support.TEST_NOW+timedelta(minutes=31))
    assert ref is None and '过期' in error

def test_other_session_cannot_borrow_preview(factory):
    sid=support.session(factory);support.talk(factory,sid,'有没有洛必达法则的题目？')
    other=support.session(factory);frames=support.talk(factory,other,'把刚才那道题加入今日卷')
    assert not any(e=='practice_request' for e,d in frames)

def test_conditional_zero_inventory_has_lesson_but_no_draft(factory):
    from sqlalchemy import update,func
    from backend.models.learning import Question
    sid=support.session(factory)
    with factory.begin() as db:
        db.execute(update(Question).where(Question.kp_id==UUID('32a29e1e-8ae3-41fc-9322-43f727596819')).values(is_active=False))
    before=support.counts(factory)
    frames=support.talk(factory,sid,'讲清楚洛必达法则，如果没有符合资格的洛必达题，就只讲解，不要生成新题。')
    assert not any(e in {'practice_request','planner'} for e,d in frames)
    answer=next(d['answer'] for e,d in frames if e=='done')
    assert '系统节点讲解' in answer and '可新增 0 道' in answer
    with factory() as db:assert db.scalar(select(func.count()).select_from(PracticeRequest).where(PracticeRequest.source_conversation_id==sid))==0
    assert support.counts(factory)==before

def test_query_failure_not_reported_as_zero(factory,monkeypatch):
    from backend.services.learning_task_tools import TaskTools
    original=TaskTools.find_questions
    def fail(*args,**kwargs):raise RuntimeError('injected read dependency failure')
    monkeypatch.setattr(TaskTools,'find_questions',fail)
    sid=support.session(factory);before=support.counts(factory)
    frames=support.talk(factory,sid,'讲清楚洛必达法则，如果没有符合资格的洛必达题，就只讲解，不要生成新题。')
    assert not any(e=='practice_request' for e,d in frames)
    answer=next(d['answer'] for e,d in frames if e=='done')
    assert '系统节点讲解' in answer and '查询或方案校验未完成' in answer and '可新增 0 道' not in answer
    assert support.counts(factory)==before
