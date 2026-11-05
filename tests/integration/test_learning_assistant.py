"""Isolated PostgreSQL + protocol providers. These are NOT real-model tests."""
import asyncio
from datetime import datetime,timedelta,timezone
import json
from uuid import UUID,uuid4
import pytest
from sqlalchemy import delete,func,select
from tests.integration.test_learning_loop import session_factory,clean_database,mark_isolated_question_trusted,client,clock
from tests.integration.test_learning_tasks import clean_tasks,PlanningProvider
from backend.models.chat import ChatSession,ChatMessage,MessageCitation
from backend.models.learning import Question,PracticeItem,DailyPlan,QuestionAttempt,LearningEvent,KpState,KnowledgePoint,QuestionVersion
from backend.models.personal_generation import PersonalGenerationBatch
from backend.models.learning_task import LearningTask
from backend.models.practice_request import PracticeRequest
from backend.models.rag import Material,DocumentChunk
from backend.schemas.learning_assistant import StudyContext,AssistantRequest
from backend.schemas.learning_task import ConfirmTask
from backend.schemas.learning_task import CreateTask
from backend.services.study_context_service import validate_study_context
from backend.services.learning_assistant_service import assistant_stream,begin_turn,planner_handoff,prepare_planner
from backend.services.assistant_data_queries import persist_generated_question_refs
from backend.services.assistant_data_queries import classify_read_only_data_query
from backend.services.learning_qa_service import assemble_learning_context
from backend.services.learning_task_service import confirm_task
from backend.services.learning_task_service import create_task
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


def setup_pre_generation(factory, *, purpose="study"):
    """Keep the source paper as history, leaving today's destination uncreated."""
    sid, context, correct = setup(factory)
    with factory.begin() as db:
        db.get(DailyPlan, context.daily_plan_id).study_date = (NOW - timedelta(days=1)).date().isoformat()
        db.get(ChatSession, sid).purpose = purpose
    return sid, context.model_copy(update={"daily_plan_id": None, "practice_item_id": None,
        "conversation_id": sid, "surface": "chat" if purpose == "qa" else "study"}), correct


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


@pytest.mark.parametrize('purpose',['study','qa'])
def test_readonly_bank_instruction_executes_query_not_a_plan(session_factory,purpose):
    sid,ctx,_=setup(session_factory)
    if purpose=='qa':
        with session_factory.begin() as db:
            db.get(ChatSession,sid).purpose='qa'
        ctx=StudyContext()
    provider=QAProvider()
    frames=talk(session_factory,sid,AssistantRequest(question='从题库找两道洛必达法则的题，不要加入今日卷',study_context=ctx),provider)
    routes=[data for name,data in frames if name=='route']
    assert routes and routes[-1]['capability']=='data_query' and routes[-1]['intent']=='find'
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(LearningTask))==0
        assert db.scalar(select(func.count()).select_from(PracticeRequest))==0
        assert db.scalar(select(func.count()).select_from(PersonalGenerationBatch))==0
        assert db.scalar(select(func.count()).select_from(PracticeItem))==1
    assert not provider.prompts


def test_pre_generation_question_list_is_blinded_in_sse_and_message_history(session_factory,client):
    """The homepage planning phase may return exact counts, never question content."""
    with session_factory.begin() as db:
        question=db.scalar(select(Question).join(KnowledgePoint).where(
            KnowledgePoint.code=="math.calculus.limit.lhopital",
            Question.is_active.is_(True)).order_by(Question.id))
        assert question is not None
        node_id=question.kp_id
        session=ChatSession(mode="builtin",purpose="study",study_date="2026-01-01")
        db.add(session);db.flush();session_id=session.id
        sensitive=[question.stem,question.explanation,str(question.id)]
        if question.current_version_id:sensitive.append(str(question.current_version_id))
        if isinstance(question.options,dict):
            sensitive.extend(value for value in question.options.values() if len(str(value))>=8)
    context=StudyContext(surface="study",conversation_id=session_id,knowledge_node_ids=[node_id])
    response=client.post(f"/api/chat/sessions/{session_id}/assistant:stream?purpose=study",json={
        "question":"列出洛必达法则的练习题题干和选项",
            "request_key":str(uuid4()),
        "study_context":context.model_dump(mode="json"),
    })
    assert response.status_code==200,response.text
    wire_events=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    done=next(event for event in wire_events if event.get("answer") is not None)
    answer=done["answer"]
    serialized=response.text
    assert "今日正式学习卷尚未生成" in answer
    assert "符合正式准入条件的真实题量" in answer
    assert all(value not in serialized and value not in answer for value in sensitive if value)
    stored=reply(session_factory,session_id)
    evidence=stored.metadata_["read_only_data_query"]
    assert evidence["query_status"]=="pre_generation_blindbox"
    assert evidence["preview_questions"]==[] and evidence["returned_preview_count"]==0
    assert evidence["writes"] is False and evidence["model_called"] is False
    history=client.get(f"/api/chat/sessions/{session_id}/messages",params={"purpose":"study"})
    assert history.status_code==200
    history_json=history.json()
    assert all(value not in json.dumps(history_json,ensure_ascii=False) for value in sensitive if value)
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(DailyPlan).where(
            DailyPlan.study_date=="2026-01-01"))==0
        assert db.scalar(select(func.count()).select_from(PracticeItem))==0
        assert db.scalar(select(func.count()).select_from(LearningTask))==0


def test_prohibited_generation_does_not_create_a_generation_card_or_batch(session_factory):
    sid,ctx,_=setup(session_factory)
    frames=talk(session_factory,sid,AssistantRequest(question='不许给我生成两道洛必达法则题',study_context=ctx),QAProvider())
    assert not any(name in {'personal_generation','personal_generation_confirmation'} for name,_ in frames)
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(PersonalGenerationBatch))==0


@pytest.mark.parametrize('purpose',['study','qa'])
def test_original_exam_inventory_notice_does_not_substitute_or_mutate_plan(session_factory,purpose):
    sid,ctx,_=setup(session_factory)
    if purpose=='qa':
        with session_factory.begin() as db:db.get(ChatSession,sid).purpose='qa'
        ctx=StudyContext()
    provider=QAProvider()
    frames=talk(session_factory,sid,AssistantRequest(question='给我找一道原版历年真题',study_context=ctx),provider)
    done=next(data for name,data in frames if name=='done')
    assert '没有原版' in done['answer'] and '是否接受' in done['answer']
    assert not provider.prompts
    assert not any(name in {'planner','personal_generation'} for name,_ in frames)
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(DailyPlan))==1
        assert db.scalar(select(func.count()).select_from(PracticeItem))==1
        assert db.scalar(select(func.count()).select_from(PersonalGenerationBatch))==0


def fresh_exercise(factory, ctx):
    """后续验证使用新练习，保留上一题已锁定的原始记录。"""
    with factory.begin() as db:
        old=db.get(PracticeItem,ctx.practice_item_id)
        day=datetime.fromisoformat(db.get(DailyPlan,old.plan_id).study_date).date()+timedelta(days=1)
        while db.scalar(select(DailyPlan.id).where(DailyPlan.study_date==day.isoformat())):
            day+=timedelta(days=1)
        plan=DailyPlan(study_date=day.isoformat(),status="active");db.add(plan);db.flush()
        item=PracticeItem(plan_id=plan.id,question_id=old.question_id,kp_id=old.kp_id,
            question_version_id=old.question_version_id,ordinal=1)
        db.add(item);db.flush()
        return ctx.model_copy(update={"practice_item_id":item.id,"daily_plan_id":plan.id,"attempt_id":None})


def test_agent_handoff_inherits_frozen_case_budget_from_task_context(session_factory):
    sid,ctx,_=setup(session_factory)
    task=create_task(session_factory,CreateTask(goal="复验练习",budget_minutes=20,session_id=sid,
        current_plan_id=ctx.daily_plan_id),now=NOW,read_only=True)
    ctx=StudyContext(surface="study",conversation_id=sid,task_id=task.task_id,
        daily_plan_id=ctx.daily_plan_id,knowledge_node_ids=ctx.knowledge_node_ids)
    handoff=planner_handoff(session_factory,ctx=ctx,user_id=uuid4(),
        message="请查看最近三次错误，推荐复验练习方案，并区分尝试次数和不同题数。",
        route=route_message("请查看最近三次错误，推荐复验练习方案，并区分尝试次数和不同题数。",ctx),now=NOW)
    assert handoff.available_minutes==20
    assert handoff.constraints["time_explicit"] is False


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
    ctx=fresh_exercise(session_factory,ctx)
    talk(session_factory,sid,AssistantRequest(question="提示下一步",study_context=ctx,qa_action="hint_2"),QAProvider())
    with session_factory.begin() as db:
        b=submit_answer(db,item_id=ctx.practice_item_id,raw_answer=None,selected_option=wrong,idempotency_key="phase4-wrong2",now=NOW+timedelta(minutes=1))
    assert b.assistance_level=="hint_2" and b.previous_attempt_id is None
    ctx=fresh_exercise(session_factory,ctx)
    talk(session_factory,sid,AssistantRequest(question="查看完整解答",study_context=ctx,qa_action="solution"),QAProvider("这是参考解答，不代表所有来源都经权威核验。"))
    with session_factory.begin() as db:
        c=submit_answer(db,item_id=ctx.practice_item_id,raw_answer=None,selected_option=correct,idempotency_key="phase4-right",now=NOW+timedelta(minutes=2))
        assert db.scalar(select(func.count()).select_from(QuestionAttempt))==3
    assert c.assistance_level=="solution" and c.sequence_category=="solution_assisted_correct" and c.effective_confirmation_count==0


def test_ordinary_knowledge_qa_does_not_record_hint_or_use_current_question(session_factory):
    sid,ctx,_=setup(session_factory); p=QAProvider()
    talk(session_factory,sid,AssistantRequest(question="解释洛必达法则的使用条件",study_context=ctx),p)
    assert reply(session_factory,sid).metadata_["learning_trace"]["model_knowledge_only"]
    assert all("question_id" not in message["content"] for message in p.prompts[0])
    with session_factory() as db: assert db.scalar(select(func.count()).select_from(LearningEvent).where(LearningEvent.event_type=="qa_assistance_used"))==0


def test_capability_question_examples_do_not_execute_business_queries_or_plans(session_factory):
    sid,ctx,_=setup(session_factory)
    text="你能帮我做什么？比如你能查看我的题库有多少道数学二题，能不能查我做过的错题？"
    # This is the regression trigger: a lower-level classifier recognizes the
    # example phrase, but the user's actual turn is asking about capability.
    assert classify_read_only_data_query(text)=="history"
    protected=(DailyPlan,PracticeItem,QuestionAttempt,LearningEvent,LearningTask,PracticeRequest)
    with session_factory() as db:
        before={model:db.scalar(select(func.count()).select_from(model)) for model in protected}
    provider=QAProvider("我能讲解数学二和408知识，也能查询题库和学习记录；需要写入今日卷或创建计划时会先按流程确认。")
    frames=talk(session_factory,sid,AssistantRequest(question=text,study_context=ctx),provider)
    assert next(data for event,data in frames if event=="route")["reason"]=="assistant_capability_inquiry"
    assert not any(event in {"data_query","planner","practice_request"} for event,_ in frames)
    assert len(provider.prompts)==1
    with session_factory() as db:
        answer=db.scalar(select(ChatMessage).where(ChatMessage.session_id==sid,
            ChatMessage.role=="assistant").order_by(ChatMessage.seq.desc()))
        assert answer.status=="completed"
        assert answer.content.endswith(provider.text) and answer.content.count(provider.text)==1
        assert answer.content.count("## 通用知识参考")==1
        assert next(data["answer"] for event,data in frames if event=="done")==answer.content
        assert "".join(data["text"] for event,data in frames if event=="delta")==answer.content
        after={model:db.scalar(select(func.count()).select_from(model)) for model in protected}
        assert after==before


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
    sid,ctx,_=setup_pre_generation(session_factory)
    with session_factory.begin() as db: db.add(ChatMessage(session_id=sid,role="user",content="QA_RAW_HISTORY_SENTINEL",status="completed"))
    p=CapturedPlanner(); frames=talk(session_factory,sid,AssistantRequest(question="给我安排1道这种题",study_context=ctx),p)
    task_data=next(data for event,data in frames if event=="planner")
    assert task_data["status"]=="ready",task_data
    prompt=json.loads(p.initial); assert "structured_handoff" in prompt and "QA_RAW_HISTORY_SENTINEL" not in p.initial
    assert prompt["structured_handoff"]["source_question_id"]==str(ctx.question_id)
    with session_factory() as db: assert db.scalar(select(func.count()).select_from(PracticeItem))==1
    confirmation = ConfirmTask(draft_version=task_data["draft_version"])
    result=confirm_task(session_factory,UUID(task_data["task_id"]),confirmation,now=NOW)
    repeated=confirm_task(session_factory,UUID(task_data["task_id"]),confirmation,now=NOW)
    assert repeated.task_id==result.task_id
    with session_factory() as db:
        # One retained historical item plus one explicitly confirmed new item.
        assert db.scalar(select(func.count()).select_from(PracticeItem)) == 2
        assert db.scalar(select(func.count()).select_from(DailyPlan)) == 2
        assert db.get(LearningTask, UUID(task_data["task_id"])).metrics.get("commit")
    ctx.task_id=UUID(task_data["task_id"])
    talk(session_factory,sid,AssistantRequest(question="请先解释这个知识点",study_context=ctx),QAProvider())
    assert reply(session_factory,sid).metadata_["qa_handoff"]["source_task_id"]==str(result.task_id)


def test_materialized_today_paper_refuses_generic_rebuild_without_model_or_history_writes(session_factory):
    from scripts.expand_phase3b_inventory import protected_fingerprints
    sid,context,_=setup(session_factory)
    with session_factory() as db:
        before=protected_fingerprints(db)
    provider=CapturedPlanner()
    frames=talk(session_factory,sid,AssistantRequest(question="给我安排1道这种题",study_context=context),provider)
    assert provider.calls==0
    assert not any(event in {"planner","practice_request"} for event,_ in frames)
    assert "冻结" in reply(session_factory,sid).content
    with session_factory() as db:
        assert protected_fingerprints(db)==before


def test_modify_is_explicitly_unsupported_and_has_no_model_or_plan_write(session_factory):
    from scripts.expand_phase3b_inventory import protected_fingerprints
    sid,ctx,_=setup(session_factory); p=CapturedPlanner()
    with session_factory() as db:
        before=protected_fingerprints(db)
    frames=talk(session_factory,sid,AssistantRequest(question="把剩下的换简单一点",study_context=ctx),p)
    assert not any(event in {"planner","practice_request"} for event,_ in frames)
    assert p.calls==0 and "冻结" in reply(session_factory,sid).content
    assert reply(session_factory,sid).metadata_["writes"] is False
    with session_factory() as db:
        assert protected_fingerprints(db)==before
        assert db.scalar(select(func.count()).select_from(PracticeItem))==1


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
    # This regression covers an unconfirmed pre-generation draft, not the
    # fixture's already materialized sample paper.
    with session_factory.begin() as db:
        db.get(PracticeItem,ctx.practice_item_id).removed_at=NOW
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
    sid,ctx,_=setup_pre_generation(session_factory)
    frames=talk(session_factory,sid,AssistantRequest(question="给我安排1道这种题",study_context=ctx),CapturedPlanner())
    task=next(data for event,data in frames if event=="planner")
    p=QAProvider()
    follow=StudyContext(surface="study",conversation_id=sid,task_id=UUID(task["task_id"]))
    talk(session_factory,sid,AssistantRequest(question="请先解释相关知识",study_context=follow),p)
    lesson_reply=reply(session_factory,sid)
    assert lesson_reply.metadata_["study_context"]["knowledge_node_ids"]==[str(ctx.knowledge_node_ids[0])]
    assert lesson_reply.metadata_["qa_handoff"]["source_task_id"]==task["task_id"]
    assert lesson_reply.metadata_["answer_source"] in {"system_lesson", "general"}
    if lesson_reply.metadata_["answer_source"] == "system_lesson":
        assert lesson_reply.metadata_["learning_trace"]["resolved_knowledge_node_ids"]==[str(ctx.knowledge_node_ids[0])]
        assert p.prompts==[]
    else:
        assert p.prompts


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


def test_same_session_followup_queries_real_inventory_without_model_or_writes(session_factory):
    sid,ctx,_=setup(session_factory)
    chat=StudyContext(surface="chat",conversation_id=sid)
    first_provider=QAProvider("洛必达法则用于满足条件的未定式极限。")
    talk(session_factory,sid,AssistantRequest(question="洛必达法则是什么？",study_context=chat),first_provider)
    first_reply=reply(session_factory,sid)
    assert first_reply.metadata_["answer_source"]=="system_lesson"
    assert first_reply.metadata_["learning_trace"]["resolved_knowledge_node_ids"]==[str(ctx.knowledge_node_ids[0])]
    with session_factory() as db:
        node=db.scalar(select(KnowledgePoint).where(KnowledgePoint.code=="math.calculus.limit.lhopital"))
        expected=question_availability(db,now=NOW,kp_ids=[node.id],limit=0)["practice_eligible_count"]
        before={model.__name__:db.scalar(select(func.count()).select_from(model)) for model in
            (Question,QuestionVersion,PracticeItem,QuestionAttempt)}
    query_provider=QAProvider()
    frames=talk(session_factory,sid,AssistantRequest(question="那你看看我库里面有多少道这样的题。",study_context=chat),query_provider)
    assert query_provider.prompts==[]
    assert frames[-1][0]=="done"
    answer=frames[-1][1]["answer"]
    assert f"{expected} 道符合当前可练资格" in answer
    with session_factory() as db:
        row=reply(session_factory,sid)
        trace=row.metadata_["read_only_data_query"]
        after={model.__name__:db.scalar(select(func.count()).select_from(model)) for model in
            (Question,QuestionVersion,PracticeItem,QuestionAttempt)}
    assert trace["scope_source"]=="same_session_conversation_context"
    assert trace["scope_node_ids"]==[str(node.id)]
    assert trace["model_called"] is False and trace["writes"] is False
    assert after==before


def test_missing_system_lesson_falls_through_to_general_qa(session_factory,monkeypatch):
    sid,ctx,_=setup(session_factory)
    chat=StudyContext(surface="chat",conversation_id=sid,knowledge_node_ids=ctx.knowledge_node_ids)
    business_models=(Question,QuestionVersion,DailyPlan,PracticeItem,QuestionAttempt,LearningEvent,
        LearningTask,PracticeRequest,PersonalGenerationBatch)
    with session_factory() as db:
        before_counts={model.__name__:db.scalar(select(func.count()).select_from(model)) for model in business_models}
    original_execute=TaskTools.execute

    def no_lesson(self,name,args):
        if name=="read_lesson":
            return {"available":False,"name":"二分查找","kp_id":args.get("kp_id")}
        return original_execute(self,name,args)

    monkeypatch.setattr(TaskTools,"execute",no_lesson)
    provider=QAProvider("二分查找需要有序数据。数组支持 O(1) 随机访问，可用中点不断缩小区间；链表虽然有序，但找到中点需线性遍历，因此不能保持 O(log n) 的总时间。")
    question="二分查找为什么通常用有序数组？有序链表能不能二分，时间复杂度还是 O(log n) 吗？只讲解，不安排题目。"
    frames=talk(session_factory,sid,AssistantRequest(question=question,study_context=chat),provider)

    assert provider.prompts, frames
    assert frames[-1][0]=="done" and "链表虽然有序" in frames[-1][1]["answer"]
    assert not any(event=="planner" for event,_ in frames)
    with session_factory() as db:
        saved=reply(session_factory,sid)
        assert saved.status=="completed"
        assert saved.metadata_["system_lesson_lookup"]["status"]=="no_system_lesson_available"
        assert saved.metadata_["system_lesson_lookup"]["trace"]
        assert saved.metadata_["answer_source"]=="general"
        assert saved.metadata_["learning_trace"]["model_knowledge_only"] is True
        assert saved.metadata_["generation_trace"]["calls"]
        after_counts={model.__name__:db.scalar(select(func.count()).select_from(model)) for model in business_models}
    assert after_counts==before_counts


def test_materials_entry_can_query_question_inventory_without_leaking_material_scope(session_factory):
    """Business inventory lookup is available from the materials assistant too.

    The user-selected material still validates the session, but a question-bank
    count is sourced from the learning database, not guessed from document text
    or sent to the model as if it were a citation-backed material answer.
    """
    with session_factory.begin() as db:
        material = Material(title="隔离资料范围", source_type="user",
            stored_path="assistant-test/material.md",
            normalized_text="洛必达法则的测试资料正文 MATERIAL_BODY_MUST_NOT_LEAK。",
            status="ready", active_index_version="assistant-test-v1")
        db.add(material); db.flush()
        session = ChatSession(mode="user", purpose="materials",
            material_scope_ids=[str(material.id)])
        db.add(session); db.flush()
        sid, material_id = session.id, material.id
        expected = question_availability(db, now=NOW, limit=0)["practice_eligible_count"]

    context = StudyContext(surface="materials", origin="material",
        conversation_id=sid, material_id=material_id)
    provider = QAProvider()
    frames = talk(session_factory, sid, AssistantRequest(
        question="我题库一共有多少道可练题？", study_context=context), provider)

    assert provider.prompts == []
    assert frames[-1][0] == "done"
    answer_text = frames[-1][1]["answer"]
    assert f"全部科目范围内有 {expected} 道符合当前可练资格" in answer_text
    assert "MATERIAL_BODY_MUST_NOT_LEAK" not in answer_text
    assert frames[-1][1]["citations"] == []
    with session_factory() as db:
        row = reply(session_factory, sid)
        assert row.metadata_["read_only_data_query"]["query_type"] == "inventory"
        assert row.metadata_["read_only_data_query"]["model_called"] is False
        assert row.metadata_["read_only_data_query"]["writes"] is False
        saved_session = db.get(ChatSession, sid)
        assert saved_session.purpose == "materials" and str(material_id) in saved_session.material_scope_ids


def test_history_query_maps_real_attempt_results_and_exact_question_version(session_factory):
    sid,ctx,correct=setup(session_factory)
    with session_factory.begin() as db:
        attempt=submit_answer(db,item_id=ctx.practice_item_id,raw_answer=None,selected_option=correct,
            idempotency_key="assistant-history-query-right",now=NOW)
        version_id=attempt.question_version_id
    provider=QAProvider()
    frames=talk(session_factory,sid,AssistantRequest(question="我做过洛必达法则的题吗？",study_context=ctx),provider)
    assert provider.prompts==[]
    assert frames[-1][0]=="done" and "提交过 1 次作答" in frames[-1][1]["answer"]
    with session_factory() as db:
        row=reply(session_factory,sid); trace=row.metadata_["read_only_data_query"]
        assert trace["attempt_count"]==1 and trace["distinct_question_count"]==1
        assert trace["objective_results"]=={"correct":1}
        assert trace["learning_event_count"]==1
        assert trace["version_binding"]==[{
            "attempt_id":str(attempt.attempt_id),"question_id":str(ctx.question_id),
            "question_version_id":str(version_id),"kp_id":str(ctx.knowledge_node_ids[0]),"binding_valid":True}]
        assert row.metadata_["model_called"] is False and row.metadata_["writes"] is False


def test_saved_generated_question_followup_uses_its_exact_version_and_qa_not_generation(session_factory):
    sid,ctx,_=setup(session_factory)
    with session_factory.begin() as db:
        batch=PersonalGenerationBatch(request_key=str(uuid4()),input_sha256="a"*64,
            status="completed",study_date="2026-01-01",reserved_calls=1,request={},result={})
        db.add(batch); db.flush()
        question=db.get(Question,ctx.question_id)
        question.bank_scope="personal"; question.generation_batch_id=batch.id
        question.question_provenance="ai_generated_practice"
        question.stem="隔离测试生成题：求极限 (x^2-1)/(x-1)，其中 x 趋于 1。"
        question.explanation="因式分解后约去 x-1，得到 x+1，故极限为 2。"
        question.correct_answer="2"
        db.flush()
        exact_version_id=question.current_version_id
        saved_question_id=question.id
        generated_message=ChatMessage(session_id=sid,role="assistant",status="completed",
            content="已经保存1道练习题。",metadata_={"personal_generation":{"batch_id":str(batch.id),
                "question_ids":[str(question.id)]}})
        db.add(generated_message); db.flush(); generated_message_id=generated_message.id
        batch_id=batch.id
    refs=persist_generated_question_refs(session_factory,message_id=generated_message_id,
        generation={"batch_id":str(batch_id),"question_ids":[str(saved_question_id)]})
    assert refs==[{"question_id":str(saved_question_id),"question_version_id":str(exact_version_id),
        "kp_id":str(ctx.knowledge_node_ids[0]),"generation_batch_id":str(batch_id)}]

    chat=StudyContext(surface="chat",conversation_id=sid)
    provider=QAProvider("先把分子分母因式分解，再约去共同因子；代入 x=1，结果为 2。")
    frames=talk(session_factory,sid,AssistantRequest(
        question="那上面你生成的题怎么做？讲解一下。",study_context=chat),provider)
    assert provider.prompts
    prompt="\n".join(str(message.get("content", "")) for message in provider.prompts[0])
    assert "隔离测试生成题" in prompt and "question_version_id" in prompt
    assert "question_id" in prompt and "reference_answer" in prompt
    assert len(provider.prompts)==1
    with session_factory() as db:
        row=reply(session_factory,sid)
        assert row.metadata_["capability_route"]["capability"]=="qa"
        assert row.metadata_["qa_action"]=="solution"
        assert row.metadata_["question_reference"]["question_version_id"]==str(exact_version_id)
        assert "personal_generation" not in row.metadata_
        assert db.scalar(select(func.count()).select_from(PracticeItem))==1


def test_ambiguous_inventory_followup_asks_once_without_global_guess(session_factory):
    sid,_,_=setup(session_factory)
    chat=StudyContext(surface="chat",conversation_id=sid)
    provider=QAProvider()
    frames=talk(session_factory,sid,AssistantRequest(
        question="那你库里面有多少道这样的题？",study_context=chat),provider)
    assert provider.prompts==[]
    assert "没法可靠判断" in frames[-1][1]["answer"]
    with session_factory() as db:
        row=reply(session_factory,sid)
        assert row.metadata_["read_only_data_query"]["scope_source"]=="ambiguous_or_missing_antecedent"


def test_unprompted_markdown_final_answer_is_recorded_as_solution(session_factory):
    sid,ctx,correct=setup(session_factory)
    provider=QAProvider(f"结论：选 **{correct}**。")
    frames=talk(session_factory,sid,AssistantRequest(question="帮我看看这个。",study_context=ctx),provider)
    with session_factory() as db:
        events=list(db.scalars(select(LearningEvent).where(LearningEvent.event_type=="qa_assistance_used")))
        item=db.get(PracticeItem,ctx.practice_item_id)
        assistant=reply(session_factory,sid)
        meta=[data for event,data in frames if event=="meta"]
        done=next((data for event,data in frames if event=="done"),{})
        assert events and item.answer_revealed_at is not None, (
            f"provider={bool(provider.prompts)} meta={meta} answer={done.get('answer')!r} "
            f"route={(assistant.metadata_ or {}).get('capability_route')} "
            f"action={(assistant.metadata_ or {}).get('qa_action')} "
            f"info={(assistant.metadata_ or {}).get('qa_information_route')} "
            f"retrieval={(assistant.metadata_ or {}).get('retrieval_mode')} events={len(events)}")


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
    ctx=fresh_exercise(session_factory,ctx)
    talk(session_factory,sid,AssistantRequest(question="给我一点提示",study_context=ctx),QAProvider())
    with session_factory.begin() as db:
        second=submit_answer(db,item_id=ctx.practice_item_id,raw_answer=None,selected_option=correct,
            idempotency_key="repair-round2-right",now=NOW+timedelta(seconds=1))
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
    # 当前练习只保存一次提交；之前练习的错误仍由已有学习状态工具读取。
    assert [a["result"] for a in data["attempts"]]==["right"]
    assert data["attempts"][-1]["assistance_level"]=="hint_1"
    assert {a["result"] for a in data["learning_state"]["states"][0]["recent_attempts"]}>={"wrong","right"}
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


def test_matrix_followup_stays_in_qa_and_next_turn_keeps_conversation_context(session_factory):
    sid,ctx,_=setup(session_factory)
    ctx.conversation_id=sid
    first_question="设 A 为前面定义的矩阵，先说明计算特征值时应检查什么。"
    first=QAProvider("先根据矩阵本身求特征多项式，再求根并计算特征空间。")
    talk(session_factory,sid,AssistantRequest(question=first_question,study_context=ctx),first)

    q14="接着上题，这个A的行列式、特征值，以及特征空间维数分别是多少？"
    second=QAProvider("沿用刚才的 A，先求行列式和特征多项式，再分别计算特征空间。")
    talk(session_factory,sid,AssistantRequest(question=q14,study_context=ctx),second)
    with session_factory() as db:
        q14_row=db.scalar(select(ChatMessage).where(ChatMessage.session_id==sid,
            ChatMessage.role=="assistant").order_by(ChatMessage.seq.desc()))
    assert q14_row.metadata_["capability_route"]["capability"]=="qa"
    q14_prompt="\n".join(item.get("content","") or "" for item in second.prompts[-1])
    assert first_question in q14_prompt and "先根据矩阵本身求特征多项式" in q14_prompt

    q15="继续：为什么它不能对角化，而单位矩阵可以？请利用前面已经得到的结论，避免把重根本身说成充分理由。"
    third=QAProvider("是否可对角化取决于特征空间维数与代数重数，不由重根单独决定。")
    talk(session_factory,sid,AssistantRequest(question=q15,study_context=ctx),third)
    with session_factory() as db:
        q15_row=db.scalar(select(ChatMessage).where(ChatMessage.session_id==sid,
            ChatMessage.role=="assistant").order_by(ChatMessage.seq.desc()))
    assert q15_row.metadata_["capability_route"]["capability"]=="qa"
    q15_prompt="\n".join(item.get("content","") or "" for item in third.prompts[-1])
    assert q14 in q15_prompt and "沿用刚才的 A" in q15_prompt


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
    sid,ctx,_=setup_pre_generation(session_factory)
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
