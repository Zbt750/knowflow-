"""One assistant conversation, independent QA and existing Planner executors."""
import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo
from sqlalchemy import select
from backend.errors import AppError
from backend.models.chat import ChatMessage, ChatSession, MessageCitation
from backend.models.learning import KnowledgePoint, Question, DailyPlan, PracticeItem
from backend.models.learning_task import LearningTask
from backend.schemas.learning_assistant import PlannerHandoff, QAHandoff, StudyContext
from backend.schemas.learning_task import CreateTask, TaskInput
from backend.services.study_context_service import validate_study_context
from backend.services.assistant_router import CapabilityRoute,route_message,assistance_action,answer_reliability_question
from backend.services.learning_task_service import create_task,modify_task,run_task,get_task
from backend.services.learning_task_tools import TaskTools
from backend.services.learning_qa_service import record_qa_assistance,safe_hint,final_answer_disclosed,question_relevant,PROMPT_VERSION
from backend.chat.service import answer,stream_answer,encode_sse,citation_payloads


def begin_turn(factory,*,session_id,body,now=None):
    now=now or datetime.now(timezone.utc)
    with factory.begin() as db:
        session=db.scalar(select(ChatSession).where(ChatSession.id==session_id).with_for_update())
        ctx=validate_study_context(db,session_id=session_id,context=body.study_context,now=now)
        if session.purpose=="study" and session.study_date!=now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat():
            raise AppError("study_session_expired",status_code=409)
        if session.mode=="user" and not session.material_scope_ids:raise AppError("private_scope_required",status_code=422)
        fingerprint=sha256(json.dumps({"question":body.question,"action":body.qa_action,"current_work":body.current_work,
            "context":ctx.model_dump(mode="json",exclude={"generated_at"})},sort_keys=True).encode()).hexdigest()
        if body.request_key:
            old=db.scalar(select(ChatMessage).where(ChatMessage.session_id==session_id,ChatMessage.role=="assistant",
                ChatMessage.metadata_["request_key"].as_string()==str(body.request_key)).order_by(ChatMessage.seq.desc()))
            if old:
                if (old.metadata_ or {}).get("input_sha256")!=fingerprint: raise AppError("idempotency_key_conflict",status_code=409)
                if old.status=="generating": raise AppError("assistant_turn_busy",status_code=409)
                if old.status!="completed": raise AppError("assistant_retry_invalid",status_code=409)
                return ctx,old.id,UUID(old.metadata_["source_user_message_id"]),True
        if db.scalar(select(ChatMessage.id).where(ChatMessage.session_id==session_id,ChatMessage.status=="generating")):
            raise AppError("assistant_turn_busy",status_code=409)
        if body.retry_of_message_id:
            failed=db.get(ChatMessage,body.retry_of_message_id)
            if not failed or failed.session_id!=session_id or failed.role!="assistant" or failed.status not in {"failed","cancelled"}: raise AppError("assistant_retry_invalid",status_code=422)
            source=(failed.metadata_ or {}).get("source_user_message_id")
            user=db.get(ChatMessage,UUID(source)) if source else None
            if not user or user.content!=body.question: raise AppError("assistant_retry_invalid",status_code=422)
            original=(failed.metadata_ or {}).get("study_context",{})
            for field in ("question_id","practice_item_id","attempt_id","daily_plan_id","knowledge_node_ids","material_id","chunk_id"):
                if original.get(field)!=ctx.model_dump(mode="json").get(field): raise AppError("assistant_retry_invalid",status_code=422)
            if not ctx.task_id and (failed.metadata_ or {}).get("planner_task_id"):
                ctx.task_id=UUID(failed.metadata_["planner_task_id"])
        else:
            user=ChatMessage(session_id=session_id,role="user",content=body.question,status="completed",metadata_={"study_context":ctx.model_dump(mode="json")})
            db.add(user); db.flush()
        if session.title=="新对话": session.title=body.question.replace("\n"," ")[:24]
        reply=ChatMessage(session_id=session_id,role="assistant",status="generating",content="",
            metadata_={"study_context":ctx.model_dump(mode="json"),"source_user_message_id":str(user.id),
                "request_key":str(body.request_key or uuid4()),"input_sha256":fingerprint,
                "retry_of_message_id":str(body.retry_of_message_id) if body.retry_of_message_id else None})
        db.add(reply); db.flush()
        return ctx,reply.id,user.id,False


def task_is_current(task, now):
    context=task.context or {}
    study_date=(context.get("current_plan") or {}).get("study_date")
    if not study_date:
        created=task.created_at
        if created.tzinfo is None: created=created.replace(tzinfo=timezone.utc)
        study_date=created.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
    return study_date==now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()


def active_task(factory,ctx,now=None):
    if not ctx.task_id: return None
    with factory() as db:
        task=db.get(LearningTask,ctx.task_id)
        if not task: return None
        return {"status":task.status,"committed":bool((task.metrics or {}).get("commit")) or not task_is_current(task,now or datetime.now(timezone.utc))}


def requested_count(text):
    match=re.search(r"(?:补|安排|练|做|推荐|给我|只要|只做)(?:充)?\s*([一二三四五六七八九]十[一二三四五六七八九]?|十[一二三四五六七八九]?|[一二两三四五六七八九]|[1-9]\d?)\s*(?:道|题)",text)
    if not match: return None
    value=match.group(1)
    return chinese_number(value)


def chinese_number(value):
    if value.isdigit(): return int(value)
    digits={c:i for i,c in enumerate("零一二三四五六七八九")}; digits["两"]=2
    if "十" in value:
        left,right=value.split("十",1); return digits.get(left,1)*10+digits.get(right,0)
    return digits[value]


def explicit_minutes(message):
    values=[]
    for match in re.finditer(r"(\d{1,3}|[一二两三四五六七八九十]{1,3})\s*分钟",message):
        if not re.search(r"刚才|做了|花了|用了",message[max(0,match.start()-8):match.start()]): values.append((match.start(),chinese_number(match.group(1))))
    for match in re.finditer(r"(半|\d|[一二两三四])(?:个)?小时",message):
        if not re.search(r"刚才|做了|花了|用了",message[max(0,match.start()-8):match.start()]): values.append((match.start(),30 if match.group(1)=="半" else chinese_number(match.group(1))*60))
    return max(values)[1] if values else None


def planner_handoff(factory,*,ctx,user_id,message,route,now):
    explicit=explicit_minutes(message)
    minutes=explicit if explicit is not None else 90
    if explicit is None and ctx.task_id:
        with factory() as db:
            previous=db.get(LearningTask,ctx.task_id)
            if previous and task_is_current(previous,now) and not (previous.metrics or {}).get("commit"): minutes=previous.budget_minutes
    if minutes<5 or minutes>240: raise AppError("planning_budget_out_of_range",status_code=422)
    observed=TaskTools(factory,budget_minutes=minutes,now=now,goal=message)
    # A global inventory query never inherits yesterday's question as a hard scope.
    targets=list(observed.explicit_scope or [])[:8]
    scope_origin="explicit_user_scope" if targets else "unresolved"
    if observed.explicit_scope:
        with factory() as db:
            anchors=[n for n in db.scalars(select(KnowledgePoint).where(KnowledgePoint.id.in_(observed.explicit_scope)).order_by(KnowledgePoint.code)) if n.parent_id not in observed.explicit_scope]
            targets=[n.id for n in anchors[:8]]
    # "Based on today's learning" requests read today's actual plan, not a partial
    # substring match (e.g. 矩阵 inside 伴随矩阵) that silently drops another subject.
    if ctx.daily_plan_id and re.search(r"^根据(?:我)?今天.{0,45}(?:学习|作答|实际)",message) and not re.search(r"只练|只做|仅练|限定范围|改练|换成",message):
        with factory() as db:
            today_plan=db.get(DailyPlan,ctx.daily_plan_id)
            if today_plan and today_plan.study_date==now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat():
                targets=list(db.scalars(select(PracticeItem.kp_id).where(PracticeItem.plan_id==today_plan.id).distinct().order_by(PracticeItem.kp_id)))[:8]
                if targets: scope_origin="today_evidence_scope"
    if not targets and ctx.task_id and re.search(r"少一点|多一点|只做|只要|基础一点|简单一点|再减少",message):
        with factory() as db:
            previous=db.get(LearningTask,ctx.task_id)
            if previous and task_is_current(previous,now) and not (previous.metrics or {}).get("commit"):
                targets=[UUID(k) for k in ((previous.context or {}).get("planner_handoff",{})).get("target_knowledge_node_ids",[])]
                if targets: scope_origin="current_task_draft"
    if not targets and route.intent!="query":
        targets=list(ctx.knowledge_node_ids)
        if targets: scope_origin="current_study_context"
    if not targets and route.intent!="query" and re.search(r"这种|这个|这样|类似|继续|再补",message):
        with factory() as db:
            latest=db.scalar(select(ChatMessage).where(ChatMessage.session_id==ctx.conversation_id,ChatMessage.role=="assistant",ChatMessage.status=="completed").order_by(ChatMessage.seq.desc()))
            ids=((latest.metadata_ or {}).get("learning_trace") or {}).get("knowledge_node_ids_used",[]) if latest else []
            if not ids and latest:ids=((latest.metadata_ or {}).get("learning_trace") or {}).get("resolved_knowledge_node_ids",[])
            if not ids and latest and latest.matched_kp_id: ids=[str(latest.matched_kp_id)]
            parsed=[UUID(k) for k in ids[:8]]
            targets=list(db.scalars(select(KnowledgePoint.id).where(KnowledgePoint.id.in_(parsed),KnowledgePoint.is_active.is_(True))))
            if targets: scope_origin="latest_validated_qa_context"
    exclusions=set(observed.excluded_scope)
    if route.intent=="query" and re.search(r"除.{0,24}(?:当前|正在看|这个).{0,12}(?:知识点|节点)",message): exclusions.update(ctx.knowledge_node_ids)
    target_subject=ctx.subject
    if targets:
        with factory() as db:subjects=set(db.scalars(select(KnowledgePoint.subject).where(KnowledgePoint.id.in_(targets))))
        target_subject=next(iter(subjects)) if len(subjects)==1 else None
    return PlannerHandoff(source_conversation_id=ctx.conversation_id,source_message_id=user_id,
        source_question_id=ctx.question_id,source_attempt_id=ctx.attempt_id,target_knowledge_node_ids=targets,
        subject=target_subject,user_problem=message,request_type=route.intent,
        requested_question_count=requested_count(message),available_minutes=minutes,
        difficulty_preference="basic" if "基础" in message else None,
        constraints={"user_problem_is_self_report":True,"current_plan_id":str(ctx.daily_plan_id) if ctx.daily_plan_id else None,
            "relax_count":bool(re.search(r"少一点|再减少|不用那么多",message)),"time_explicit":explicit is not None,
            "global_inventory":route.intent=="query" and not observed.explicit_scope,
            "context_node_ids":[str(k) for k in ctx.knowledge_node_ids],
            "scope_origin":scope_origin,
            "inventory_subject":"408" if re.search(r"408",message) else "考研数学" if re.search(r"数学二|数二",message) else None},
        exclusions=list(exclusions)[:8],generated_at=now)


def qa_handoff(ctx,task_id,message,*,reason="requested_concept_help",scope=None):
    return QAHandoff(source_task_id=task_id,knowledge_node_ids=scope or ctx.knowledge_node_ids,
        question_id=ctx.question_id,reason=reason,learning_problem=message[:1200],suggested_mode="question" if ctx.question_id else "knowledge")


def prepare_planner(factory,*,ctx,handoff,now):
    with factory() as db:
        names=list(db.scalars(select(KnowledgePoint.code).where(KnowledgePoint.id.in_(handoff.target_knowledge_node_ids))))
    goal=("学习范围："+"、".join(names)+"\n" if names else "")+handoff.user_problem
    if len(goal)>1200: raise AppError("learning_goal_too_long",status_code=422)
    prior=get_task(factory,ctx.task_id) if ctx.task_id else None
    with factory() as db:
        prior_row=db.get(LearningTask,ctx.task_id) if ctx.task_id else None
        prior_current=bool(prior_row and task_is_current(prior_row,now))
        request_link=(prior_row.context or {}).get("practice_request_id") if prior_row else None
    if prior and prior_current and prior.status in {"created","ready","needs_info","failed"} and not prior.metrics.get("commit") and handoff.request_type=="plan":
        task=modify_task(factory,ctx.task_id,TaskInput(goal=goal,budget_minutes=handoff.available_minutes),now=now)
    else:
        with factory() as db:
            viewed_plan=db.get(DailyPlan,ctx.daily_plan_id) if ctx.daily_plan_id else None
            today_id=ctx.daily_plan_id if viewed_plan and viewed_plan.study_date==now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat() else None
        task=create_task(factory,CreateTask(goal=goal,budget_minutes=handoff.available_minutes,session_id=ctx.conversation_id,current_plan_id=today_id),now=now)
    with factory.begin() as db:
        row=db.get(LearningTask,task.task_id)
        recent=list(db.scalars(select(DailyPlan).where(DailyPlan.study_date<now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()).order_by(DailyPlan.study_date.desc()).limit(2)))
        recent_scope=[]
        for plan in recent:
            ids=list(db.scalars(select(PracticeItem.kp_id).where(PracticeItem.plan_id==plan.id).distinct()))
            recent_scope.append({"plan_id":str(plan.id),"study_date":plan.study_date,"status":plan.status,
                "knowledge_node_ids":[str(i) for i in ids],
                "knowledge_nodes":[{"id":str(n.id),"name":n.name,"code":n.code} for n in db.scalars(select(KnowledgePoint).where(KnowledgePoint.id.in_(ids)))],
                "unfinished_question_ids":[str(i) for i in db.scalars(select(PracticeItem.question_id).where(PracticeItem.plan_id==plan.id,PracticeItem.completed_at.is_(None),PracticeItem.question_id.is_not(None)))]})
        row.context={**(row.context or {}),"planner_handoff":handoff.model_dump(mode="json"),"study_context":ctx.model_dump(mode="json"),
            "recent_learning":recent_scope,"memory_policy":"task-scoped; no QA conversation messages"}
        if prior and prior_current and task.task_id==prior.task_id and request_link:row.context={**row.context,"practice_request_id":request_link}
    return task


def persist_route(factory,message_id,route,extra=None):
    with factory.begin() as db:
        message=db.get(ChatMessage,message_id)
        message.metadata_={**(message.metadata_ or {}),"capability_route":route.public_dict(),**(extra or {})}


def fail_turn(factory,message_id,code):
    with factory.begin() as db:
        message=db.get(ChatMessage,message_id)
        if message and message.status=="generating":
            message.status="failed"; message.metadata_={**(message.metadata_ or {}),"assistant_error_code":code}


def present_planner_message(text, task, ctx):
    """Remove identifiers from user presentation, never from factual tool traces."""
    ids={str(ctx.question_id),str(ctx.task_id)}-{"None"}
    for step in task.trace:
        for question in (step.get("result") or {}).get("questions",[]):
            if question.get("question_id"): ids.add(str(question["question_id"]))
    for value in ids:
        for size in range(len(value),7,-1):
            text=re.sub(re.escape(value[:size])+r"(?:…|\.\.\.)", "该题", text)
    return re.sub(r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b","该题",text)


async def assistant_stream(factory,*,request,session_id,body,stack,provider,now=None,web_search_provider=None):
    now=now or datetime.now(timezone.utc)
    try:
        ctx,message_id,user_id,replay=begin_turn(factory,session_id=session_id,body=body,now=now)
    except AppError as exc:
        yield encode_sse("error",{"code":exc.code,"message":exc.message,"retryable":True}); return
    if replay:
        with factory() as db:
            saved=db.get(ChatMessage,message_id); text=saved.content; meta=dict(saved.metadata_ or {})
            pairs=[(c.label,c.chunk_id) for c in db.scalars(select(MessageCitation).where(MessageCitation.message_id==message_id).order_by(MessageCitation.ordinal))]
        cards=citation_payloads(factory,pairs)
        yield encode_sse("meta",{"message_id":str(message_id),"replayed":True})
        yield encode_sse("delta",{"seq":1,"text":text})
        if meta.get("planner_task_id"): yield encode_sse("planner",get_task(factory,UUID(meta["planner_task_id"])).model_dump(mode="json"))
        yield encode_sse("citations",{"citations":cards})
        yield encode_sse("done",{"message_id":str(message_id),"answer":text,"citations":cards,"status":"completed"})
        return
    with factory() as db:
        session=db.get(ChatSession,session_id);mode=session.mode;purpose=session.purpose
    task_summary=active_task(factory,ctx,now)
    route=route_message(body.question,ctx,action=body.qa_action,task=task_summary)
    if mode=="user": route=CapabilityRoute("qa","qa",1,"user_material_qa_scope")
    if purpose=='qa' and mode=='builtin' and re.search(r'^(?:我)?(?:不想|不要|不用|不需要|别)[^，,；;。]{0,12}(?:练习|练题|补题|安排|找题)',body.question) and not re.search(r'[，,；;].*(?:先练|想练|补.{0,4}道|安排.{0,6}道)',body.question):
        route=CapabilityRoute('qa','qa',1,'user_declined_practice')
    unsupported_formal=purpose=="qa" and mode=="builtin" and route.capability=="planner" and route.intent=="modify"
    practice_draft=purpose=="qa" and mode=="builtin" and route.capability=="planner" and route.intent in {"plan","recommend"}
    formal_inventory=purpose=="qa" and mode=="builtin" and route.capability=="planner" and route.intent=="query"
    if practice_draft:route=CapabilityRoute("qa","practice_request",1,"explicit_user_practice_request")
    elif formal_inventory:route=CapabilityRoute("qa","inventory",1,"read_only_inventory_qa")
    elif unsupported_formal:route=CapabilityRoute("qa","qa",1,"unsupported_existing_plan_operation")
    persist_route(factory,message_id,route)
    yield encode_sse("route",route.public_dict())
    try:
        if unsupported_formal:
            text="当前只支持由奶蛙提出追加练习方案，再经你确认加入今日学习；不支持删除或替换原卷题目。没有修改已有试卷。"
            with factory.begin() as db:
                row=db.get(ChatMessage,message_id);row.content=text;row.status="completed";row.metadata_={**row.metadata_,"answer_source":"notice"}
            yield encode_sse("meta",{"message_id":str(message_id)});yield encode_sse("delta",{"seq":1,"text":text});yield encode_sse("citations",{"citations":[]});yield encode_sse("done",{"message_id":str(message_id),"answer":text,"citations":[]});return
        if practice_draft:
            from backend.services.practice_request_service import draft_request
            drafted=draft_request(factory,ctx=ctx,user_id=user_id,assistant_id=message_id,message=body.question,now=now)
            text="可以把这个练习需求交给今日学习里的奶蛙，让它结合学习记录和真实题库提出方案。发送需求不会修改今日练习卷。" if drafted["details"].get("target_knowledge_node_ids") else "请补充具体知识点，我才能把明确的练习需求交给奶蛙。"
            with factory.begin() as db:
                row=db.get(ChatMessage,message_id);row.content=text;row.status="completed";row.metadata_={**row.metadata_,"answer_source":"notice"}
            yield encode_sse("meta",{"message_id":str(message_id)});yield encode_sse("delta",{"seq":1,"text":text})
            yield encode_sse("practice_request",drafted);yield encode_sse("citations",{"citations":[]})
            yield encode_sse("done",{"message_id":str(message_id),"answer":text,"citations":[],"status":"completed"});return
        if formal_inventory:
            from backend.schemas.learning_task import QuestionAvailabilityQuery
            handoff=planner_handoff(factory,ctx=ctx,user_id=user_id,message=body.question,route=CapabilityRoute("planner","query",1,"inventory"),now=now)
            tools=TaskTools(factory,budget_minutes=90,now=now,goal=body.question,handoff=handoff.model_dump(mode="json"))
            with factory() as db:stock=tools.get_question_availability(db,QuestionAvailabilityQuery())
            counts=stock.get("inventory_counts")
            text=(f"当前范围有 {stock['practice_eligible_count']} 道可练题。" if not counts else
                f"按当前排除条件，两科合计 {counts['question_count_total']} 道可练题、{counts['node_count_total']} 个有题节点。"+"；".join(f"{r['subject']}：{r['question_count']} 道题、{r['node_count']} 个节点" for r in counts['subject_totals'])+
                f"。返回 {counts['returned_node_count']} 条节点预览，"+("并非完整列表。" if counts['node_list_is_truncated'] else "未截断。"))
            if stock.get('eligible_nodes'):
                text+='\n\n有题节点预览：\n'+'\n'.join(f"- {n['name']}：{n['practice_eligible_count']} 道" for n in stock['eligible_nodes'])
            with factory.begin() as db:
                row=db.get(ChatMessage,message_id);row.content=text;row.status="completed";row.metadata_={**row.metadata_,"answer_source":"notice","qa_information_route":"inventory"}
            yield encode_sse("meta",{"message_id":str(message_id)});yield encode_sse("delta",{"seq":1,"text":text});yield encode_sse("citations",{"citations":[]});yield encode_sse("done",{"message_id":str(message_id),"answer":text,"citations":[]});return
        if route.capability=="planner":
            handoff=planner_handoff(factory,ctx=ctx,user_id=user_id,message=body.question,route=route,now=now)
            persist_route(factory,message_id,route,{"planner_handoff":handoff.model_dump(mode="json")})
            task=prepare_planner(factory,ctx=ctx,handoff=handoff,now=now)
            persist_route(factory,message_id,route,{"planner_task_id":str(task.task_id)})
            yield encode_sse("meta",{"message_id":str(message_id),"capability":"planner","task_id":str(task.task_id)})
            pending=asyncio.create_task(asyncio.to_thread(run_task,factory,task.task_id,provider,now=now))
            while not pending.done():
                await asyncio.wait({pending},timeout=.5)
                if not pending.done(): yield encode_sse("status",{"message":"正在查看学习记录与题库…"})
            result=await pending
            with factory.begin() as db:
                stored_task=db.get(LearningTask,result.task_id)
                request_link=(stored_task.context or {}).get("practice_request_id")
                if request_link:
                    from backend.models.practice_request import PracticeRequest
                    linked=db.get(PracticeRequest,UUID(request_link),with_for_update=True)
                    if linked and linked.status not in {"accepted","declined","expired"}:
                        linked.status="proposed" if result.status=="ready" and result.draft and result.draft.get('questions') else "failed"
                        linked.error_code=None if linked.status=="proposed" else result.error_code or "insufficient_practice_inventory"
                        linked.handled_at=now
            original=result.message
            visible=present_planner_message(original,result,ctx)
            if visible!=original:
                with factory.begin() as db:
                    row=db.get(LearningTask,task.task_id);row.message=visible
                    row.metrics={**row.metrics,"presentation_ids_removed":True,"raw_message_sha256":sha256(original.encode()).hexdigest()}
                result=get_task(factory,task.task_id)
            qh=qa_handoff(ctx,task.task_id,"先解释相关知识点",reason="optional_review_after_planning",scope=handoff.target_knowledge_node_ids)
            persist_route(factory,message_id,route,{"qa_handoff":qh.model_dump(mode="json")})
            with factory.begin() as db:
                reply=db.get(ChatMessage,message_id); reply.content=result.message; reply.status="failed" if result.status=="failed" else "completed"
            yield encode_sse("delta",{"seq":1,"text":result.message})
            yield encode_sse("planner",{**result.model_dump(mode="json"),"qa_handoff":qh.model_dump(mode="json")})
            yield encode_sse("citations",{"citations":[]})
            yield encode_sse("done",{"message_id":str(message_id),"answer":result.message,"status":"failed" if result.status=="failed" else "completed","citations":[]})
            return
        if ctx.task_id:
            if not ctx.knowledge_node_ids and not ctx.question_id:
                with factory() as db:
                    task=db.get(LearningTask,ctx.task_id)
                    ids=((task.context or {}).get("planner_handoff") or {}).get("target_knowledge_node_ids",[])
                    if ids:
                        ctx=validate_study_context(db,session_id=session_id,context=ctx.model_copy(update={"knowledge_node_ids":[UUID(k) for k in ids[:8]],"daily_plan_id":None,"practice_item_id":None}),now=now)
                persist_route(factory,message_id,route,{"study_context":ctx.model_dump(mode="json")})
            persist_route(factory,message_id,route,{"qa_handoff":qa_handoff(ctx,ctx.task_id,body.question).model_dump(mode="json")})
        action=assistance_action(body.question,explicit=body.qa_action,question_present=bool(ctx.question_id))
        persist_route(factory,message_id,route,{"qa_action":action or "auto"})
        learning={"study_context":ctx.model_dump(mode="json"),"action":action,"current_work":body.current_work,"server_time":now.isoformat()}
        from backend.services.qa_information_router import information_route
        info=information_route(body.question,ctx,private=mode=="user")
        if action and ctx.question_id and info=='general':info='current_question'
        learning["information_route"]=info
        persist_route(factory,message_id,route,{"qa_information_route":info})
        yield encode_sse("information_source",{"source":info})
        notice=None
        if info=="private_scope_required":notice="请到资料库打开对应的私人资料，再针对所选资料提问。这里不会自动搜索你上传的文件。"
        if info=="web":
            from backend.services.web_search_service import search_web
            web=search_web(body.question,provider=web_search_provider)
            if not web.available:notice="当前未配置联网搜索，不能核验最新政策或声称已上网查到。请提供官方来源，或在具备联网能力后再核查。"
            else:
                learning["web_sources"]=web.sources;persist_route(factory,message_id,route,{"web_sources":web.sources})
                yield encode_sse("web_sources",{"sources":web.sources})
        if not ctx.question_id and not ctx.knowledge_node_ids and not ctx.material_id and re.fullmatch(r"(?:帮我)?看看?这个[。？?]?",body.question.strip()):
            notice="可以，先告诉我想看哪道题、哪个知识点或哪份资料。"
        if ctx.question_id and body.qa_action=="auto" and answer_reliability_question(body.question):
            with factory() as db:
                q=db.get(Question,ctx.question_id)
                if q.answer_provenance=="ai_generated": notice="这道题的参考答案由 AI 生成；多次核对一致也不等于官方或人工核验，不能保证一定正确。可以结合当前题面继续检查思路与适用条件。"
                else: notice="应以这道题实际的来源与核验记录为准；题库核验不等于官方发布，也不能保证每一步推导绝对正确。可以继续检查具体步骤。"
        if notice:
            with factory.begin() as db:
                row=db.get(ChatMessage,message_id);row.content=notice;row.status="completed"
                row.metadata_={**row.metadata_,"answer_source":"notice","learning_trace":{"prompt_version":PROMPT_VERSION,"study_context":ctx.model_dump(mode="json"),"model_called":False,"direct_notice":True},"generation_trace":{"request_id":str(message_id),"calls":[],"model_called":False}}
            yield encode_sse("meta",{"message_id":str(message_id),"capability":"qa"})
            yield encode_sse("delta",{"seq":1,"text":notice});yield encode_sse("citations",{"citations":[]})
            yield encode_sse("done",{"message_id":str(message_id),"answer":notice,"answer_source":"notice","citations":[]});return
        if stack is None and (mode=="user" or ctx.material_id): raise AppError("retrieval_unavailable")
        if action in {"hint_1","hint_2"}:
            with factory() as db: q=db.get(Question,ctx.question_id)
            guarded={"blocked":False}
            def filter_hint(text):
                filtered,blocked=safe_hint(text,q,action); guarded["blocked"]=blocked
                with factory.begin() as db: record_qa_assistance(db,context=ctx,message_id=message_id,level=action,now=now)
                return filtered
            yield encode_sse("meta",{"message_id":str(message_id),"capability":"qa","buffered_hint":True})
            result,citations,_=await asyncio.to_thread(answer,factory,session_id=session_id,question=body.question,stack=stack,provider=provider,
                pending_assistant_id=message_id,learning_context=learning,response_filter=filter_hint)
            with factory.begin() as db:
                if result.metadata_.get("retrieval_mode") not in {"scope_notice","overview_notice"}: record_qa_assistance(db,context=ctx,message_id=message_id,level=action,now=now)
                row=db.get(ChatMessage,message_id); row.metadata_={**row.metadata_,"hint_guard_blocked":guarded["blocked"]}
            cards=citation_payloads(factory,citations)
            yield encode_sse("delta",{"seq":1,"text":result.content})
            yield encode_sse("citations",{"citations":cards})
            yield encode_sse("done",{"message_id":str(message_id),"answer":result.content,"citations":cards,"response_duration_ms":result.metadata_.get("response_duration_ms")})
            return
        delivered=False; assist_allowed=True; accumulated=""
        async for frame in stream_answer(factory,request=request,session_id=session_id,question=body.question,stack=stack,provider=provider,
            pending_assistant_id=message_id,learning_context=learning):
            decoded=frame.decode(); event=re.search(r"event: (.+)",decoded); payload=re.search(r"data: (.+)",decoded)
            if event and payload:
                data=json.loads(payload.group(1))
                if event.group(1)=="meta": assist_allowed=data.get("retrieval_mode") not in {"scope_notice","overview_notice"}
                if event.group(1)=="delta":
                    accumulated=str(data.get("text","")) if data.get("replace") else accumulated+str(data.get("text",""))
                    if action!="solution" and ctx.question_id and question_relevant(body.question,action) and final_answer_disclosed(accumulated):
                        action="solution";delivered=False
                if event.group(1)=="delta" and data.get("text") and action and not delivered and assist_allowed:
                    with factory.begin() as db: record_qa_assistance(db,context=ctx,message_id=message_id,level=action,now=now)
                    delivered=True
            yield frame
    except asyncio.CancelledError:
        fail_turn(factory,message_id,"cancelled"); raise
    except Exception as exc:
        code=exc.code if isinstance(exc,AppError) else "internal_error"
        fail_turn(factory,message_id,code)
        err=exc if isinstance(exc,AppError) else AppError("internal_error")
        yield encode_sse("error",{"code":code,"message":err.message,"retryable":True,"message_id":str(message_id)})
