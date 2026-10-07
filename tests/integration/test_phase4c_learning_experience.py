"""Phase4C isolated DB/protocol tests, never model quality or production writes."""
from datetime import timedelta
from uuid import UUID,uuid4
from sqlalchemy import select,delete,func
import pytest
from tests.integration.test_learning_assistant import session_factory,clean_database,clean_tasks,conversations,setup,talk,reply,QAProvider,CapturedPlanner,NOW
from backend.models.chat import ChatSession,ChatMessage
from backend.models.learning import DailyPlan,PracticeItem,LearningEvent
from backend.models.learning_task import LearningTask
from backend.models.practice_request import PracticeRequest
from backend.schemas.learning_assistant import AssistantRequest,StudyContext
from backend.schemas.learning_task import ConfirmTask
from backend.services.practice_request_service import send_request,decline_request,plan_request,list_requests,view
from backend.services.learning_task_service import confirm_task
from backend.services.deep_qa_handoff_service import create_deep_qa
from backend.errors import AppError
from scripts.expand_phase3b_inventory import protected_fingerprints

@pytest.fixture(autouse=True)
def requests_cleanup(session_factory):
    with session_factory.begin() as db:db.execute(delete(PracticeRequest))
    yield
    with session_factory.begin() as db:db.execute(delete(PracticeRequest))

def formal(factory):
    sid,ctx,correct=setup(factory)
    with factory.begin() as db:db.get(ChatSession,sid).purpose="qa"
    return sid,ctx,correct
def request(factory):
    sid,ctx,_=formal(factory)
    p=QAProvider();frames=talk(factory,sid,AssistantRequest(question="给我安排1道这种题",study_context=ctx),p)
    data=next(d for e,d in frames if e=="practice_request")
    assert not p.prompts
    return sid,ctx,UUID(data["id"])
def today_session(factory):
    with factory.begin() as db:
        session=ChatSession(purpose="study",mode="builtin",study_date="2026-01-01");db.add(session);db.flush();return session.id

def test_two_confirmations_no_plan_before_second_and_replay_idempotent(session_factory):
    sid,ctx,rid=request(session_factory)
    with session_factory() as db:before=protected_fingerprints(db)
    sent=send_request(session_factory,rid,source_conversation_id=sid,now=NOW)
    assert sent["status"]=="pending"
    assert send_request(session_factory,rid,source_conversation_id=sid,now=NOW)["id"]==str(rid)
    result=plan_request(session_factory,rid,study_session_id=today_session(session_factory),provider=CapturedPlanner(),now=NOW)
    assert result["request"]["status"]=="proposed"
    with session_factory() as db:assert before==protected_fingerprints(db)
    task=result["task"];confirmed=confirm_task(session_factory,UUID(task["task_id"]),ConfirmTask(draft_version=task["draft_version"]),now=NOW)
    repeated=confirm_task(session_factory,confirmed.task_id,ConfirmTask(draft_version=task["draft_version"]),now=NOW)
    assert confirmed.metrics["commit"]==repeated.metrics["commit"]
    with session_factory() as db:
        row=db.get(PracticeRequest,rid);assert row.status=="accepted" and row.request["confirmation_b"]
        assert db.scalar(select(func.count()).select_from(PracticeItem))==2

def test_unsent_request_cannot_plan_and_wrong_source_cannot_send(session_factory):
    sid,ctx,rid=request(session_factory)
    with pytest.raises(AppError):send_request(session_factory,rid,source_conversation_id=uuid4(),now=NOW)
    with pytest.raises(AppError):plan_request(session_factory,rid,study_session_id=today_session(session_factory),provider=CapturedPlanner(),now=NOW)
    assert decline_request(session_factory,rid,now=NOW)["status"]=="declined"
    with pytest.raises(AppError):send_request(session_factory,rid,source_conversation_id=sid,now=NOW)

def test_expired_request_fails_closed(session_factory):
    sid,ctx,rid=request(session_factory)
    with pytest.raises(AppError) as error:send_request(session_factory,rid,source_conversation_id=sid,now=NOW+timedelta(days=8))
    assert error.value.code=="practice_request_expired"

def test_deep_handoff_explicit_idempotent_preserves_position_and_assistance(session_factory):
    sid,ctx,_=setup(session_factory)
    talk(session_factory,sid,AssistantRequest(question="给我提示",study_context=ctx,qa_action="hint_1"),QAProvider())
    with session_factory() as db:before=protected_fingerprints(db)
    key=uuid4();first=create_deep_qa(session_factory,source_session_id=sid,context=ctx,learning_problem="请详细解释这个条件",request_key=key,now=NOW)
    second=create_deep_qa(session_factory,source_session_id=sid,context=ctx,learning_problem="请详细解释这个条件",request_key=key,now=NOW)
    assert first["session_id"]==second["session_id"] and first["handoff"]["assistance_already_given"]=="hint_1"
    assert first["study_context"]["question_id"]==str(ctx.question_id)
    assert first["study_context"]["task_id"] is None
    with session_factory() as db:
        assert before==protected_fingerprints(db)
        assert db.get(ChatSession,sid).purpose=="study"
        target=db.get(ChatSession,UUID(first["session_id"]));assert target.purpose=="qa"
        assert db.scalar(select(func.count()).select_from(ChatMessage).where(ChatMessage.session_id==target.id))==1

def test_general_qa_bypasses_even_broken_retrieval_and_leaves_state_unchanged(session_factory):
    sid,ctx,_=formal(session_factory)
    with session_factory() as db:before=protected_fingerprints(db)
    p=QAProvider("通用知识参考：async使程序在等待IO时让出执行机会。")
    talk(session_factory,sid,AssistantRequest(question="Python async/await为什么存在？",study_context=ctx),p)
    assert p.prompts and "question_id" not in p.prompts[0][1]["content"]
    assert reply(session_factory,sid).metadata_["qa_information_route"]=="general"
    assert "未检索系统资料" in reply(session_factory,sid).content
    assert "知识库中没有找到" not in reply(session_factory,sid).content
    with session_factory() as db:
        assert before==protected_fingerprints(db)
        assert db.scalar(select(func.count()).select_from(PracticeRequest))==0

def test_web_unavailable_and_private_scope_request_never_calls_model(session_factory):
    sid,ctx,_=formal(session_factory);p=QAProvider()
    talk(session_factory,sid,AssistantRequest(question="2027年408大纲有什么最新变化？",study_context=ctx),p)
    assert not p.prompts and "未配置联网搜索" in reply(session_factory,sid).content
    talk(session_factory,sid,AssistantRequest(question="我上传的PDF怎么解释？",study_context=ctx),p)
    assert not p.prompts and "资料库" in reply(session_factory,sid).content

def test_day_scoped_session_is_not_reused_on_next_day(session_factory):
    from backend.services.learning_assistant_service import begin_turn
    sid,ctx,_=setup(session_factory)
    with pytest.raises(AppError) as error:begin_turn(session_factory,session_id=sid,body=AssistantRequest(question="今天学什么",study_context=ctx),now=NOW+timedelta(days=1))
    assert error.value.code=="study_session_expired"

def test_proposed_request_reuses_task_without_model_and_decline_prevents_confirm(session_factory):
    sid,ctx,rid=request(session_factory);send_request(session_factory,rid,source_conversation_id=sid,now=NOW)
    study=today_session(session_factory);first=plan_request(session_factory,rid,study_session_id=study,provider=CapturedPlanner(),now=NOW)
    p=CapturedPlanner();second=plan_request(session_factory,rid,study_session_id=study,provider=p,now=NOW)
    assert first["task"]["task_id"]==second["task"]["task_id"] and p.calls==0
    decline_request(session_factory,rid,now=NOW)
    with pytest.raises(AppError):confirm_task(session_factory,UUID(first["task"]["task_id"]),ConfirmTask(draft_version=first["task"]["draft_version"]),now=NOW)

def test_insufficient_inventory_no_generated_question_or_daily_plan_write(session_factory):
    from backend.models.learning import Question
    sid,ctx,_=formal(session_factory)
    with session_factory() as db:before=protected_fingerprints(db);qcount=db.scalar(select(func.count()).select_from(Question))
    frames=talk(session_factory,sid,AssistantRequest(question="给我补2道这种题",study_context=ctx),QAProvider())
    data=next(d for e,d in frames if e=="practice_request");rid=UUID(data["id"])
    send_request(session_factory,rid,source_conversation_id=sid,now=NOW)
    result=plan_request(session_factory,rid,study_session_id=today_session(session_factory),provider=CapturedPlanner(),now=NOW)
    assert result["request"]["status"]=="failed" and result["task"]["draft"] is None
    with session_factory() as db:
        assert before==protected_fingerprints(db)
        assert qcount==db.scalar(select(func.count()).select_from(Question))

def test_request_plan_modification_preserves_request_link_and_revalidates(session_factory):
    sid,ctx,rid=request(session_factory);send_request(session_factory,rid,source_conversation_id=sid,now=NOW)
    study=today_session(session_factory);first=plan_request(session_factory,rid,study_session_id=study,provider=CapturedPlanner(),now=NOW)
    follow=StudyContext(surface="study",task_id=UUID(first["task"]["task_id"]))
    frames=talk(session_factory,study,AssistantRequest(question="少一点",study_context=follow),CapturedPlanner())
    updated=next(d for e,d in frames if e=="planner")
    assert updated["status"]=="ready"
    with session_factory() as db:assert db.get(LearningTask,UUID(updated["task_id"])).context["practice_request_id"]==str(rid)
    confirm_task(session_factory,UUID(updated["task_id"]),ConfirmTask(draft_version=updated["draft_version"]),now=NOW)
    with session_factory() as db:assert db.get(PracticeRequest,rid).status=="accepted"

def test_interrupted_request_is_read_only_recovered_without_model_call(session_factory):
    sid,ctx,rid=request(session_factory);send_request(session_factory,rid,source_conversation_id=sid,now=NOW)
    with session_factory.begin() as db:
        row=db.get(PracticeRequest,rid);row.status="planning";row.request={**row.request,"planning_started_at":NOW.isoformat()}
    listed=list_requests(session_factory,now=NOW+timedelta(minutes=7))
    assert listed[0]["status"]=="failed" and listed[0]["error_code"]=="planning_interrupted"

def test_formal_unsupported_remove_or_replace_is_not_disguised_as_append_request(session_factory):
    sid,ctx,_=formal(session_factory);p=QAProvider()
    frames=talk(session_factory,sid,AssistantRequest(question="把剩下的题换简单一点",study_context=ctx),p)
    assert not p.prompts and not any(e=='practice_request' for e,_ in frames)
    assert "不支持删除或替换" in reply(session_factory,sid).content

def test_implicit_current_question_followup_keeps_question_for_second_hint(session_factory):
    import json
    sid,ctx,_=setup(session_factory);p=QAProvider('检查关键条件。')
    talk(session_factory,sid,AssistantRequest(question='我还是不懂',study_context=ctx),p)
    assert reply(session_factory,sid).metadata_['assistance_level']=='hint_2'
    assert any('question_id' in m['content'] for m in p.prompts[0])

def test_cross_day_proposed_request_is_expired_not_reused(session_factory):
    sid,ctx,rid=request(session_factory);send_request(session_factory,rid,source_conversation_id=sid,now=NOW)
    plan_request(session_factory,rid,study_session_id=today_session(session_factory),provider=CapturedPlanner(),now=NOW)
    rows=list_requests(session_factory,now=NOW+timedelta(days=1))
    assert rows[0]['status']=='expired'

def test_deep_qa_keeps_solution_viewed_from_existing_answer_reveal(session_factory):
    from backend.services.answer_submission_service import record_answer_reveal
    sid,ctx,_=setup(session_factory)
    with session_factory.begin() as db:record_answer_reveal(db,item_id=ctx.practice_item_id,now=NOW)
    result=create_deep_qa(session_factory,source_session_id=sid,context=ctx,learning_problem='请详细讲解',request_key=uuid4(),now=NOW)
    assert result['handoff']['assistance_already_given']=='solution'

def test_task_only_deep_qa_resolves_nodes_before_daily_paper_exists(session_factory):
    sid,ctx,_=setup(session_factory)
    frames=talk(session_factory,sid,AssistantRequest(question='安排1道这种题',study_context=ctx),CapturedPlanner())
    task=next(d for e,d in frames if e=='planner')
    result=create_deep_qa(session_factory,source_session_id=sid,context=StudyContext(surface='study',task_id=UUID(task['task_id'])),
        learning_problem='请详细讲解方案知识',request_key=uuid4(),now=NOW)
    assert result['study_context']['knowledge_node_ids']==[str(ctx.knowledge_node_ids[0])]

def test_lightweight_why_plan_reads_actual_validated_draft_not_only_task_uuid(session_factory):
    import json
    sid,ctx,_=setup(session_factory)
    frames=talk(session_factory,sid,AssistantRequest(question='安排1道这种题',study_context=ctx),CapturedPlanner())
    task=next(d for e,d in frames if e=='planner');p=QAProvider('这个方案仍需你确认。')
    talk(session_factory,sid,AssistantRequest(question='为什么这个方案只安排一道题？',study_context=StudyContext(surface='study',task_id=UUID(task['task_id']))),p)
    payload=json.loads(p.prompts[0][1]['content'].split('\n',1)[1])
    assert payload['planner_task_facts']['question_count']==1
    assert payload['planner_task_facts']['has_written_daily_plan'] is False

def test_explicit_no_practice_does_not_offer_unwanted_request(session_factory):
    sid,ctx,_=formal(session_factory)
    frames=talk(session_factory,sid,AssistantRequest(question='不要给我安排新题，只讲解定理',study_context=ctx),QAProvider())
    assert not any(e=='practice_request' for e,_ in frames)
