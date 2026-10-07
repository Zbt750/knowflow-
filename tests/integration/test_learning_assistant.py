"""Isolated PostgreSQL + protocol providers. These are NOT real-model tests."""
import asyncio
from datetime import datetime,timedelta,timezone
import json
from uuid import UUID,uuid4
import pytest
from sqlalchemy import delete,func,select
from tests.integration.test_learning_loop import session_factory,clean_database,mark_isolated_question_trusted
from tests.integration.test_learning_tasks import clean_tasks,PlanningProvider
from backend.models.chat import ChatSession,ChatMessage,MessageCitation
from backend.models.learning import Question,PracticeItem,DailyPlan,QuestionAttempt,LearningEvent,KpState,KnowledgePoint
from backend.models.learning_task import LearningTask
from backend.models.rag import Material,DocumentChunk
from backend.schemas.learning_assistant import StudyContext,AssistantRequest
from backend.schemas.learning_task import ConfirmTask
from backend.services.study_context_service import validate_study_context
from backend.services.learning_assistant_service import assistant_stream,begin_turn,planner_handoff,prepare_planner
from backend.services.learning_qa_service import assemble_learning_context
from backend.services.learning_task_service import confirm_task
from backend.services.answer_submission_service import submit_answer
from backend.services.assistant_router import route_message
from backend.services.learning_task_tools import TaskTools
from backend.schemas.learning_task import QuestionAvailabilityQuery
from backend.services.question_availability import question_availability
from backend.services.learning_qa_service import record_qa_assistance,qa_assistance_for_item
from backend.errors import AppError

NOW=datetime(2026,1,1,2,tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def conversations(session_factory,clean_tasks):
    with session_factory.begin() as db:
        db.execute(delete(MessageCitation)); db.execute(delete(ChatMessage)); db.execute(delete(ChatSession))
    yield


def setup(factory,*,mode="builtin"):
    with factory.begin() as db:
        q=db.scalar(select(Question).join(KnowledgePoint).where(Question.question_type=="single_choice",KnowledgePoint.code=="math.calculus.limit.lhopital").order_by(Question.id))
        plan=DailyPlan(study_date="2026-01-01",status="active"); session=ChatSession(mode=mode,purpose="study" if mode=="builtin" else "qa",study_date="2026-01-01" if mode=="builtin" else None)
        db.add_all([plan,session]); db.flush()
        item=PracticeItem(plan_id=plan.id,question_id=q.id,kp_id=q.kp_id,ordinal=1); db.add(item); db.flush()
        return session.id,StudyContext(surface="study",question_id=q.id,practice_item_id=item.id,daily_plan_id=plan.id,knowledge_node_ids=[q.kp_id]),q.correct_answer


class Alive:
    async def is_disconnected(self): return False


class QAProvider:
    def __init__(self,text="先检查未定式类型与使用条件。",fail=False): self.text=text; self.fail=fail; self.prompts=[]
    def complete(self,messages,*,attempt=1):
        self.prompts.append(messages)
        if self.fail: raise AppError("generation_failed",retryable=False)
        return self.text,{"total_tokens":10}
    async def stream(self,messages,*,attempt=1):
        self.prompts.append(messages)
        if self.fail: raise AppError("generation_failed",retryable=False)
        yield self.text


def talk(factory,sid,body,provider):
    async def collect():
        frames=[]
        async for raw in assistant_stream(factory,request=Alive(),session_id=sid,body=body,stack=None,provider=provider,now=NOW):
            lines=raw.decode().splitlines(); frames.append((lines[0].removeprefix("event: "),json.loads(lines[1].removeprefix("data: "))))
        return frames
    return asyncio.run(collect())


def reply(factory,sid):
    with factory() as db: return db.scalar(select(ChatMessage).where(ChatMessage.session_id==sid,ChatMessage.role=="assistant").order_by(ChatMessage.seq.desc()))


@pytest.mark.parametrize("mutation",["question","plan","node","attempt","subject","conversation"])
def test_context_rejects_wrong_entities_and_relationships(session_factory,mutation):
    sid,ctx,_=setup(session_factory)
    values={"question":"question_id","plan":"daily_plan_id","attempt":"attempt_id","conversation":"conversation_id"}
    if mutation in values: setattr(ctx,values[mutation],uuid4())
    elif mutation=="node": ctx.knowledge_node_ids=[uuid4()]
    else: ctx.subject="408" if ctx.subject!="408" else "考研数学"
    with session_factory() as db:
        with pytest.raises(AppError): validate_study_context(db,session_id=sid,context=ctx)


def test_user_material_session_cannot_import_learning_scope(session_factory):
    sid,ctx,_=setup(session_factory,mode="user")
    with session_factory() as db:
        with pytest.raises(AppError) as exc: validate_study_context(db,session_id=sid,context=ctx)
    assert exc.value.code=="forbidden"


def test_conversation_continues_but_question_location_changes(session_factory):
    sid,ctx,_=setup(session_factory)
    talk(session_factory,sid,AssistantRequest(question="这题考什么？",study_context=ctx),QAProvider())
    with session_factory() as db:
        other=db.scalar(select(Question).where(Question.id!=ctx.question_id).order_by(Question.id))
        changed=StudyContext(surface="chat",question_id=other.id,knowledge_node_ids=[other.kp_id])
    p=QAProvider(); talk(session_factory,sid,AssistantRequest(question="这题考什么？",study_context=changed),p)
    assert str(changed.question_id) in p.prompts[0][1]["content"]
    assert reply(session_factory,sid).metadata_["study_context"]["question_id"]==str(changed.question_id)
    with session_factory() as db: assert db.scalar(select(func.count()).select_from(ChatMessage).where(ChatMessage.session_id==sid))==4


def test_hints_follow_attempt_sequence_and_solution_is_nonindependent(session_factory):
    sid,ctx,correct=setup(session_factory)
    talk(session_factory,sid,AssistantRequest(question="给一点提示",study_context=ctx,qa_action="hint_1"),QAProvider())
    with session_factory.begin() as db:
        q=db.get(Question,ctx.question_id); wrong=next(k for k in q.options if k!=correct)
        a=submit_answer(db,item_id=ctx.practice_item_id,raw_answer=None,selected_option=wrong,idempotency_key="phase4-wrong",now=NOW)
    assert a.assistance_level=="hint_1" and a.result=="wrong"
    ctx.attempt_id=a.attempt_id
    talk(session_factory,sid,AssistantRequest(question="提示下一步",study_context=ctx,qa_action="hint_2"),QAProvider())
    with session_factory.begin() as db:
        b=submit_answer(db,item_id=ctx.practice_item_id,raw_answer=None,selected_option=wrong,idempotency_key="phase4-wrong2",now=NOW,expected_previous_attempt_id=a.attempt_id)
    assert b.assistance_level=="hint_2" and b.previous_attempt_id==a.attempt_id
    ctx.attempt_id=b.attempt_id
    talk(session_factory,sid,AssistantRequest(question="查看完整解答",study_context=ctx,qa_action="solution"),QAProvider("这是参考解答，不代表所有来源都经权威核验。"))
    with session_factory.begin() as db:
        c=submit_answer(db,item_id=ctx.practice_item_id,raw_answer=None,selected_option=correct,idempotency_key="phase4-right",now=NOW,expected_previous_attempt_id=b.attempt_id)
        assert db.scalar(select(func.count()).select_from(QuestionAttempt))==3
    assert c.assistance_level=="solution" and c.sequence_category=="solution_assisted_correct" and c.effective_confirmation_count==0


def test_ordinary_knowledge_qa_does_not_record_hint_or_use_current_question(session_factory):
    sid,ctx,_=setup(session_factory); p=QAProvider()
    talk(session_factory,sid,AssistantRequest(question="解释洛必达法则的使用条件",study_context=ctx),p)
    assert reply(session_factory,sid).metadata_["learning_trace"]["model_knowledge_only"]
    assert all("question_id" not in message["content"] for message in p.prompts[0])
    with session_factory() as db: assert db.scalar(select(func.count()).select_from(LearningEvent).where(LearningEvent.event_type=="qa_assistance_used"))==0


def test_hint_is_buffered_and_answer_leak_replaced(session_factory):
    sid,ctx,correct=setup(session_factory); p=QAProvider(f"正确答案为 {correct}。")
    frames=talk(session_factory,sid,AssistantRequest(question="一点提示",study_context=ctx,qa_action="hint_1"),p)
    assert not any(f"答案为 {correct}" in data.get("text","") for _,data in frames)
    payload=json.loads(p.prompts[0][1]["content"].split("\n",1)[1])
    assert "reference_answer" not in payload["question"] and "reference_explanation" not in payload["question"]
    assert reply(session_factory,sid).metadata_["hint_guard_blocked"] is True


def test_provider_failure_preserves_source_message_and_retry_does_not_duplicate_user(session_factory):
    sid,ctx,_=setup(session_factory)
    talk(session_factory,sid,AssistantRequest(question="为什么这题错了？",study_context=ctx),QAProvider(fail=True))
    failed=reply(session_factory,sid); assert failed.status=="failed"
    frames=talk(session_factory,sid,AssistantRequest(question="为什么这题错了？",study_context=ctx,retry_of_message_id=failed.id),QAProvider())
    assert frames[-1][0]=="done"
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(ChatMessage).where(ChatMessage.session_id==sid,ChatMessage.role=="user"))==1


def test_idempotent_completed_message_replay_has_no_model_or_assistance_repeat(session_factory):
    sid,ctx,_=setup(session_factory); body=AssistantRequest(question="给提示",study_context=ctx,qa_action="hint_1",request_key=uuid4()); p=QAProvider()
    talk(session_factory,sid,body,p); calls=len(p.prompts)
    frames=talk(session_factory,sid,body,p)
    assert frames[0][1]["replayed"] and len(p.prompts)==calls
    with session_factory() as db: assert db.scalar(select(func.count()).select_from(LearningEvent).where(LearningEvent.event_type=="qa_assistance_used"))==1


class CapturedPlanner(PlanningProvider):
    def tool_turn(self,messages,tools,*,timeout):
        if not self.calls: self.initial=messages[1]["content"]
        return super().tool_turn(messages,tools,timeout=timeout)


def test_structured_handoff_uses_inventory_requires_confirm_and_excludes_qa_history(session_factory):
    sid,ctx,_=setup(session_factory)
    with session_factory.begin() as db: db.add(ChatMessage(session_id=sid,role="user",content="QA_RAW_HISTORY_SENTINEL",status="completed"))
    p=CapturedPlanner(); frames=talk(session_factory,sid,AssistantRequest(question="给我安排1道这种题",study_context=ctx),p)
    task_data=next(data for event,data in frames if event=="planner")
    assert task_data["status"]=="ready",task_data
    prompt=json.loads(p.initial); assert "structured_handoff" in prompt and "QA_RAW_HISTORY_SENTINEL" not in p.initial
    assert prompt["structured_handoff"]["source_question_id"]==str(ctx.question_id)
    with session_factory() as db: assert db.scalar(select(func.count()).select_from(PracticeItem))==1
    result=confirm_task(session_factory,UUID(task_data["task_id"]),ConfirmTask(draft_version=task_data["draft_version"]),now=NOW)
    assert result.metrics["commit"]["added_count"]==1 and result.metrics["memory_lifecycle"]=="closed"
    assert confirm_task(session_factory,result.task_id,ConfirmTask(draft_version=task_data["draft_version"]),now=NOW).metrics["commit"]==result.metrics["commit"]
    row=reply(session_factory,sid); assert row.metadata_["memory_lifecycle"]=="closed"
    ctx.task_id=result.task_id
    talk(session_factory,sid,AssistantRequest(question="请先解释这个知识点",study_context=ctx),QAProvider())
    assert reply(session_factory,sid).metadata_["qa_handoff"]["source_task_id"]==str(result.task_id)


def test_modify_is_explicitly_unsupported_and_has_no_model_or_plan_write(session_factory):
    sid,ctx,_=setup(session_factory); p=CapturedPlanner()
    frames=talk(session_factory,sid,AssistantRequest(question="把剩下的换简单一点",study_context=ctx),p)
    result=next(data for event,data in frames if event=="planner")
    assert result["error_code"]=="unsupported_operation" and p.calls==0
    with session_factory() as db: assert db.scalar(select(func.count()).select_from(PracticeItem))==1


def test_next_day_planner_has_structured_plan_history_not_previous_qa_memory(session_factory):
    sid,ctx,_=setup(session_factory)
    with session_factory.begin() as db: db.add(ChatMessage(session_id=sid,role="user",content="OLD_RAW_QA_SENTINEL",status="completed"))
    with session_factory.begin() as db:
        next_session=ChatSession(mode="builtin",purpose="study",study_date="2026-01-02");db.add(next_session);db.flush();sid=next_session.id
    next_ctx=StudyContext(surface="study",conversation_id=sid)
    request=AssistantRequest(question="今天练洛必达",study_context=next_ctx)
    next_time=NOW+timedelta(days=1)
    ctx2,mid,uid,_=begin_turn(session_factory,session_id=sid,body=request,now=next_time)
    handoff=planner_handoff(session_factory,ctx=ctx2,user_id=uid,message=request.question,route=route_message(request.question,ctx2),now=next_time)
    task=prepare_planner(session_factory,ctx=ctx2,handoff=handoff,now=next_time)
    with session_factory() as db:
        stored=db.get(LearningTask,task.task_id).context
        assert stored["recent_learning"][0]["plan_id"]==str(ctx.daily_plan_id)
        assert stored["recent_learning"][0]["knowledge_nodes"] and "OLD_RAW_QA_SENTINEL" not in json.dumps(stored)


def test_unconfirmed_draft_does_not_carry_budget_to_next_day(session_factory):
    sid,ctx,_=setup(session_factory)
    ctx.conversation_id=sid
    route=route_message("安排一道洛必达题",ctx)
    handoff=planner_handoff(session_factory,ctx=ctx,user_id=uuid4(),message="安排一道洛必达题，30分钟",route=route,now=NOW)
    first=prepare_planner(session_factory,ctx=ctx,handoff=handoff,now=NOW)
    ctx.task_id=first.task_id
    next_time=NOW+timedelta(days=1)
    second_handoff=planner_handoff(session_factory,ctx=ctx,user_id=uuid4(),message="安排一道洛必达题",route=route,now=next_time)
    assert second_handoff.available_minutes==90
    second=prepare_planner(session_factory,ctx=ctx,handoff=second_handoff,now=next_time)
    assert second.task_id!=first.task_id


def test_planner_to_qa_resolves_structured_scope_without_repeating_node(session_factory):
    sid,ctx,_=setup(session_factory)
    frames=talk(session_factory,sid,AssistantRequest(question="给我安排1道这种题",study_context=ctx),CapturedPlanner())
    task=next(data for event,data in frames if event=="planner")
    p=QAProvider()
    follow=StudyContext(surface="study",conversation_id=sid,task_id=UUID(task["task_id"]))
    talk(session_factory,sid,AssistantRequest(question="请先解释相关知识",study_context=follow),p)
    assert reply(session_factory,sid).metadata_["study_context"]["knowledge_node_ids"]==[str(ctx.knowledge_node_ids[0])]
    payload=json.loads(p.prompts[0][1]["content"].split("\n",1)[1])
    assert payload["builtin_lessons"]


def test_inventory_counts_are_complete_and_preview_is_not_subject_total(session_factory):
    sid,ctx,_=setup(session_factory)
    tools=TaskTools(session_factory,budget_minutes=90,now=NOW,goal="有哪些节点有可练题",handoff={
        "request_type":"query","constraints":{"global_inventory":True,"context_node_ids":[str(ctx.knowledge_node_ids[0])]}})
    with session_factory() as db:
        result=tools.get_question_availability(db,QuestionAvailabilityQuery(subject="考研数学"))
        complete=question_availability(db,now=NOW,limit=0)
        maths=question_availability(db,now=NOW,subject="考研数学",limit=0)
    counts=result["inventory_counts"]
    assert counts["question_count_total"]==complete["practice_eligible_count"]
    assert counts["node_count_total"]==complete["eligible_node_count"]
    assert counts["question_count_in_list_scope"]==maths["practice_eligible_count"]
    assert counts["node_count_in_list_scope"]==maths["eligible_node_count"]
    assert counts["returned_node_count"]==len(result["eligible_nodes"])
    assert counts["node_list_is_truncated"]==(maths["eligible_node_count"]>24)
    assert sum(s["question_count"] for s in counts["subject_totals"])==counts["question_count_total"]
    assert result["current_context_nodes"][0]["name"]


def test_unprompted_markdown_final_answer_is_recorded_as_solution(session_factory):
    sid,ctx,correct=setup(session_factory)
    talk(session_factory,sid,AssistantRequest(question="帮我看看这个。",study_context=ctx),QAProvider(f"结论：选 **{correct}**。"))
    with session_factory() as db:
        events=list(db.scalars(select(LearningEvent).where(LearningEvent.event_type=="qa_assistance_used")))
        assert events and db.get(PracticeItem,ctx.practice_item_id).answer_revealed_at is not None


def test_evidence_observations_do_not_invent_feedback_from_assessment_basis(session_factory):
    sid,ctx,_=setup(session_factory)
    with session_factory.begin() as db:
        db.get(KpState,ctx.knowledge_node_ids[0]).assessment_basis="legacy_self_reported"
    with session_factory() as db:
        _,payload,_=assemble_learning_context(db,session_factory,session_id=sid,context=ctx,
            message="为什么这个知识点还没毕业？")
    facts=json.loads(payload)["factual_observations"][0]
    assert facts["historical_assessment_basis"]=="legacy_self_reported"
    assert facts["node_feedback_observed"] is False
    assert facts["attempt_feedback_observed_count"]==0


def test_graduation_explanation_keeps_sequence_without_new_assistance_or_old_chat(session_factory):
    sid,ctx,correct=setup(session_factory)
    with session_factory.begin() as db:
        q=db.get(Question,ctx.question_id); wrong=next(k for k in q.options if k!=correct)
        first=submit_answer(db,item_id=ctx.practice_item_id,raw_answer=None,selected_option=wrong,
            idempotency_key="repair-round2-wrong",now=NOW)
        db.add(ChatMessage(session_id=sid,role="user",content="OLD_LONG_CHAT_SENTINEL",status="completed"))
    ctx.attempt_id=first.attempt_id
    talk(session_factory,sid,AssistantRequest(question="给我一点提示",study_context=ctx),QAProvider())
    with session_factory.begin() as db:
        second=submit_answer(db,item_id=ctx.practice_item_id,raw_answer=None,selected_option=correct,
            idempotency_key="repair-round2-right",now=NOW,expected_previous_attempt_id=first.attempt_id)
        before=db.scalar(select(func.count()).select_from(LearningEvent))
    ctx.attempt_id=second.attempt_id
    provider=QAProvider("提示后答对属于辅助作答；还需要新的独立验证记录。")
    talk(session_factory,sid,AssistantRequest(question="结合系统内置讲解和今天作答记录，看提示后改对为什么还没毕业？",study_context=ctx),provider)
    row=reply(session_factory,sid)
    assert row.metadata_["qa_action"]=="auto"
    assert row.metadata_["qa_information_route"]=="evidence"
    assert "assistance_event_id" not in row.metadata_
    prompt=provider.prompts[0]
    assert "OLD_LONG_CHAT_SENTINEL" not in json.dumps(prompt)
    data=json.loads(prompt[1]["content"].split("\n",1)[1])
    assert [a["result"] for a in data["attempts"]]==["wrong","right"]
    assert data["attempts"][-1]["assistance_level"]=="hint_1"
    assert "builtin_lessons" not in data
    assert "stem" not in data["question"] and "reference_answer" not in data["question"]
    assert data["learning_state"]["states"][0]["gaps"]
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(LearningEvent))==before


def test_today_evidence_handoff_covers_actual_plan_nodes_not_partial_name_match(session_factory):
    sid,ctx,_=setup(session_factory)
    ctx.conversation_id=sid
    with session_factory.begin() as db:
        other=db.scalar(select(Question).where(Question.kp_id!=ctx.knowledge_node_ids[0]).order_by(Question.id))
        db.add(PracticeItem(plan_id=ctx.daily_plan_id,question_id=other.id,kp_id=other.kp_id,ordinal=2))
        expected={ctx.knowledge_node_ids[0],other.kp_id}
    message="根据我今天实际学习记录，接下来应该练什么？"
    route=route_message(message,ctx)
    handoff=planner_handoff(session_factory,ctx=ctx,user_id=uuid4(),message=message,route=route,now=NOW)
    assert set(handoff.target_knowledge_node_ids)==expected
    assert handoff.constraints["scope_origin"]=="today_evidence_scope"
    tools=TaskTools(session_factory,budget_minutes=90,now=NOW,goal=message,handoff=handoff.model_dump(mode="json"))
    assert tools.explicit_scope==expected

def test_explanation_mentioning_unverified_answer_still_calls_qa_provider(session_factory):
    sid,ctx,_=setup(session_factory);p=QAProvider("这里先解释所需条件，再核对关键推导。")
    talk(session_factory,sid,AssistantRequest(question="请讲解当前题的关键思路与适用条件。参考答案尚未人工核验，请明确区分可靠结论和参考推导。",study_context=ctx),p)
    assert p.prompts
    assert reply(session_factory,sid).metadata_["qa_information_route"]=="current_question"


def test_assistance_upgrade_appends_facts_and_submission_uses_solution(session_factory):
    sid,ctx,correct=setup(session_factory)
    class TwoChunks(QAProvider):
        async def stream(self,messages,*,attempt=1):
            yield "先检查适用条件。"
            yield f"正确答案为 **{correct}**。"
    talk(session_factory,sid,AssistantRequest(question="为什么这题错了？",study_context=ctx,qa_action="process_review"),TwoChunks())
    with session_factory.begin() as db:
        events=list(db.scalars(select(LearningEvent).where(LearningEvent.event_type=="qa_assistance_used")))
        assert {e.payload["assistance_level"] for e in events}=={"process_review","solution"}
        assert qa_assistance_for_item(db,db.get(PracticeItem,ctx.practice_item_id),NOW)=="solution"
        result=submit_answer(db,item_id=ctx.practice_item_id,raw_answer=None,selected_option=correct,
            idempotency_key="phase4-promoted-solution",now=NOW)
        assert result.assistance_level=="solution" and result.effective_confirmation_count==0


def test_question_reading_solution_is_same_day_only(session_factory):
    sid,ctx,_=setup(session_factory)
    read=StudyContext(question_id=ctx.question_id,conversation_id=sid)
    talk(session_factory,sid,AssistantRequest(question="请讲解答案",study_context=read,qa_action="solution"),QAProvider())
    with session_factory.begin() as db:
        assert qa_assistance_for_item(db,db.get(PracticeItem,ctx.practice_item_id),NOW)=="solution"
        plan=DailyPlan(study_date="2026-01-02",status="active");db.add(plan);db.flush()
        item=PracticeItem(plan_id=plan.id,question_id=ctx.question_id,kp_id=ctx.knowledge_node_ids[0],ordinal=1);db.add(item);db.flush()
        assert qa_assistance_for_item(db,item,NOW+timedelta(days=1))=="none"


def test_previous_day_unconfirmed_draft_cannot_be_confirmed_for_new_day(session_factory):
    sid,ctx,_=setup(session_factory)
    frames=talk(session_factory,sid,AssistantRequest(question="给我安排1道这种题",study_context=ctx),CapturedPlanner())
    task=next(data for event,data in frames if event=="planner")
    with pytest.raises(AppError) as error:
        confirm_task(session_factory,UUID(task["task_id"]),ConfirmTask(draft_version=task["draft_version"]),now=NOW+timedelta(days=1))
    assert error.value.code=="learning_task_stale_draft"
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(DailyPlan))==1
        assert db.scalar(select(func.count()).select_from(PracticeItem))==1


def test_latest_qa_context_handoff_without_current_question(session_factory):
    sid,ctx,_=setup(session_factory)
    plain=StudyContext(surface="chat",conversation_id=sid)
    talk(session_factory,sid,AssistantRequest(question="解释洛必达法则的使用条件",study_context=plain),QAProvider())
    request=AssistantRequest(question="安排一道这种题",study_context=plain)
    validated,mid,uid,_=begin_turn(session_factory,session_id=sid,body=request,now=NOW)
    handoff=planner_handoff(session_factory,ctx=validated,user_id=uid,message=request.question,
        route=route_message(request.question,validated),now=NOW)
    assert ctx.knowledge_node_ids[0] in handoff.target_knowledge_node_ids
    assert handoff.constraints["scope_origin"]=="latest_validated_qa_context"
