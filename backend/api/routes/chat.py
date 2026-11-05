from __future__ import annotations
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Request
from fastapi import Depends
from backend.api.deps import get_time_provider
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import delete, exists, select
from zoneinfo import ZoneInfo
from backend.chat.service import answer, basis_payload, provider_from_settings, stream_answer
from backend.services.chat_session_scope import effective_purpose, require_session_purpose, session_list_predicate
from backend.errors import AppError
from backend.services.generation_diagnostics import with_diagnostics
from backend.services.generation_outcomes import with_outcomes
from backend.models.chat import ChatMessage, ChatSession, MessageCitation
from backend.models.learning import DailyPlan, KnowledgePoint
from backend.models.rag import DocumentChunk, Material

router = APIRouter(tags=["chat"])
from backend.schemas.material_search import MaterialSearchScope, MaterialSearchSession


@router.post("/chat/material-search/session", response_model=MaterialSearchSession)
def material_search_session(request: Request):
    from backend.services.material_search_service import daily_session
    return daily_session(request.app.state.session_factory)


@router.patch("/chat/material-search/scope", response_model=MaterialSearchSession)
def material_search_scope(request: Request, body: MaterialSearchScope):
    from backend.services.material_search_service import update_scope
    return update_scope(request.app.state.session_factory, **body.model_dump())
from backend.schemas.learning_assistant import AssistantRequest
from backend.schemas.learning_assistant import StudyContext

class _DeferredProvider:
    """Native scope notices/request drafts do not require a configured model."""
    def __init__(self,settings):self.settings=settings;self.resolved=None
    def __getattr__(self,name):
        if self.resolved is None:self.resolved=provider_from_settings(self.settings)
        return getattr(self.resolved,name)
    def for_answer(self,prepared):
        # 请求级策略必须作用于真正的 Provider，而不能因延迟包装器的类型
        # 判断而被跳过。只在确实准备送模时解析，不影响免费确认/通知分支。
        from backend.chat.service import _provider_for_answer
        if self.resolved is None:self.resolved=provider_from_settings(self.settings)
        return _provider_for_answer(self.resolved,prepared)

class DeepQARequest(BaseModel):
    source_session_id:UUID
    study_context:StudyContext
    learning_problem:str=Field(min_length=1,max_length=1200)
    request_key:UUID

@router.post("/chat/deep-handoffs",status_code=201)
def deep_handoff(request:Request,body:DeepQARequest):
    from backend.services.deep_qa_handoff_service import create_deep_qa
    return create_deep_qa(request.app.state.session_factory,source_session_id=body.source_session_id,context=body.study_context,
        learning_problem=body.learning_problem,request_key=body.request_key)


@router.post("/chat/sessions/{session_id}/assistant:stream")
async def learning_assistant(request: Request,session_id: UUID,body: AssistantRequest,
                             purpose: Literal["qa", "study", "materials", "material_search"] = "qa",
                             clock=Depends(get_time_provider)):
    from backend.services.learning_assistant_service import assistant_stream
    from backend.services.study_context_service import validate_study_context
    now = clock()
    with request.app.state.session_factory() as db:
        require_session_purpose(db, session_id, purpose)
        validate_study_context(db,session_id=session_id,context=body.study_context,now=now)
    return StreamingResponse(assistant_stream(request.app.state.session_factory,request=request,session_id=session_id,body=body,
        stack=getattr(request.app.state,"retrieval_stack",None),provider=_DeferredProvider(request.app.state.settings),now=now,web_search_provider=getattr(request.app.state,"web_search_provider",None)),
        media_type="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str = Field(default="新对话", min_length=1, max_length=200)
    mode: Literal["builtin", "user"] = "builtin"
    purpose: Literal["qa","materials","study"] = "qa"
    material_scope_ids: list[UUID] = Field(default_factory=list,max_length=8)
class AskRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=4000)


@router.post("/chat/sessions/{session_id}/generation-confirmations/{message_id}/cancel")
def cancel_generation_card(request: Request, session_id: UUID, message_id: UUID,
                           purpose: Literal["qa", "study", "materials", "material_search"] = "qa"):
    from backend.services.learning_assistant_service import cancel_generation_confirmation
    with request.app.state.session_factory() as db:
        require_session_purpose(db, session_id, purpose)
    return cancel_generation_confirmation(request.app.state.session_factory,
        session_id=session_id, message_id=message_id)

class FollowupCandidatesRequest(BaseModel):
    message_id: UUID | None = None

class RenameSessionRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
def _cards(db, messages: list[ChatMessage]) -> dict[UUID, list[dict[str, object]]]:
    """消息恢复与 SSE 使用同一套可定位引用字段。"""
    out = {message.id: [] for message in messages}
    if not out:
        return out
    rows = db.execute(
        select(MessageCitation, DocumentChunk, Material)
        .join(DocumentChunk, DocumentChunk.id == MessageCitation.chunk_id)
        .join(Material, Material.id == DocumentChunk.material_id)
        .where(MessageCitation.message_id.in_(out))
        .order_by(MessageCitation.message_id, MessageCitation.ordinal)
    ).all()
    for citation, chunk, material in rows:
        out[citation.message_id].append(
            {
                "label": citation.label,
                "chunk_id": str(chunk.id),
                "material_id": str(material.id),
                "material_title": material.title,
                "heading_path": list(chunk.heading_path or []),
                "ordinal": chunk.ordinal,
                "preview": chunk.content[:180],
            }
        )
    return out


def _kp_names(db, messages: list[ChatMessage]) -> dict[UUID, str]:
    """批量取名，避免 N+1 查询。"""
    ids = {row.matched_kp_id for row in messages if row.matched_kp_id is not None}
    if not ids:
        return {}
    rows = db.execute(select(KnowledgePoint.id, KnowledgePoint.name).where(KnowledgePoint.id.in_(ids))).all()
    return {row[0]: row[1] for row in rows}


def _matched_kp_view(row: ChatMessage, cards: list[dict[str, object]], name: str | None) -> dict[str, object] | None:
    if row.matched_kp_id is None:
        return None
    label_by_chunk = {str(card["chunk_id"]): str(card["label"]) for card in cards}
    return basis_payload(
        dict(row.matched_kp_basis or {}),
        label_by_chunk,
        kp_name=name,
        kp_id=row.matched_kp_id,
    )

@router.post("/chat/sessions", status_code=201)
def create_session(request: Request, body: CreateSessionRequest, clock=Depends(get_time_provider)):
    with request.app.state.session_factory.begin() as db:
        from datetime import datetime,timezone
        from zoneinfo import ZoneInfo
        today=clock().astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
        if body.purpose=="study" and body.mode!="builtin":raise AppError("forbidden",status_code=403)
        if body.purpose=="materials" or body.material_scope_ids:
            if body.mode!="user" or not body.material_scope_ids:raise AppError("private_scope_required",status_code=422)
            for mid in body.material_scope_ids:
                material=db.get(Material,mid)
                if not material or material.source_type!="user":raise AppError("forbidden",status_code=403)
                if material.status!="ready":raise AppError("material_not_ready",status_code=409)
        session=ChatSession(title=body.title.strip(),mode=body.mode,purpose=body.purpose,
            study_date=today if body.purpose=="study" else None,material_scope_ids=[str(k) for k in body.material_scope_ids])
        db.add(session);db.flush()
        return {"session_id":str(session.id),"title":session.title,"mode":session.mode,"purpose":session.purpose,"study_date":session.study_date,"material_scope_ids":session.material_scope_ids}

@router.get("/chat/sessions")
def list_sessions(request: Request, mode: Literal["builtin", "user"] | None = None,
                  purpose: Literal['qa', 'study', 'materials', 'material_search'] | None = None):
    """列出「未归档」且「已经有消息」的会话。

    两条筛选都是有意的：

    - `mode`（可选）：篇 01「两种问答模式严格隔离」规定，两种模式的检索范围、
      matched_kp、追练推荐与学习事件**完全不同**。混在同一个列表里用户分不清
      哪条属于哪个范围，所以允许按模式取。
    - **空会话不返回**：没有任何消息的会话只是「点了一下新建」留下的残留。
      真实会话在发第一条问题时就会随事务写入 user 消息，因此这不会漏掉任何会话，
      只会让列表里剩下的每一条都能点开看。

    契约：响应字段与原来完全一致；`mode` 是可选参数，不传即原来的行为。
    """
    with request.app.state.session_factory() as db:
        statement = (
            select(ChatSession)
            .where(ChatSession.archived_at.is_(None))
            .where(session_list_predicate(purpose))
            .where(
                exists(
                    select(ChatMessage.id).where(ChatMessage.session_id == ChatSession.id)
                )
            )
            .order_by(ChatSession.updated_at.desc())
        )
        if mode is not None:
            statement = statement.where(ChatSession.mode == mode)
        rows = db.scalars(statement).all()
        return [{"session_id":str(row.id),"title":row.title,"mode":row.mode,"purpose":effective_purpose(db,row),
                 "study_date":row.study_date,"material_scope_ids":row.material_scope_ids} for row in rows]

@router.patch("/chat/sessions/{session_id}")
def rename_session(request: Request, session_id: UUID, body: RenameSessionRequest,
                   purpose: Literal["qa", "study", "materials", "material_search"] = "qa"):
    """会话标题仅供历史导航；不会改写消息、引用或学习事实。"""
    with request.app.state.session_factory.begin() as db:
        session = require_session_purpose(db, session_id, purpose)
        session.title = body.title.strip()
        return {"session_id": str(session.id), "title": session.title, "mode": session.mode}

@router.delete("/chat/sessions/{session_id}", status_code=204)
def delete_session(request: Request, session_id: UUID,
                   purpose: Literal["qa", "study", "materials", "material_search"] = "qa"):
    """**物理删除**会话，连同它的消息与引用一起从库里移除。

    2026-09-20 之前这里是**归档**（只置 `archived_at`），理由是「问答与引用要可追溯」。
    产品方明确要求列表里的 × 真的删掉记录，因此改成物理删除；
    该决策与取舍记在 `docs/reference-build-changes.md` 的 D-31。

    按依赖顺序逐条删（引用 → 消息 → 会话），而不是只删会话行、靠数据库级联：
    模式里虽然声明了 `ON DELETE CASCADE`，但显式删除不依赖那份约束是否真的建成，
    换库或重建约束时也不会静默留下孤儿行。

    注意：`learning_events.source_id` **故意没有外键**（见 `backend/models/learning.py`），
    所以这里不会、也不应该连带删除学习事件 —— 掌握度与弱信号是学习事实，
    不该因为用户清理了一轮对话就抹掉；代价是那几条事件的 `source_id` 会变成悬空 id。
    """
    with request.app.state.session_factory.begin() as db:
        session = require_session_purpose(db, session_id, purpose)
        db.execute(
            delete(MessageCitation).where(
                MessageCitation.message_id.in_(
                    select(ChatMessage.id).where(ChatMessage.session_id == session.id)
                )
            )
        )
        db.execute(delete(ChatMessage).where(ChatMessage.session_id == session.id))
        db.delete(session)

@router.get("/chat/sessions/{session_id}/messages")
def list_messages(request: Request, session_id: UUID,
                  purpose: Literal["qa", "study", "materials", "material_search"] = "qa",
                  time_provider=Depends(get_time_provider)):
    with request.app.state.session_factory() as db:
        session=require_session_purpose(db, session_id, purpose)
        today=time_provider().astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
        pre_generation_study=session.purpose=='study' and db.scalar(
            select(DailyPlan.id).where(DailyPlan.study_date==today).limit(1)) is None
        # 排序必须带 id 兜底：user 与 assistant 是在**同一个事务**里提交的，
        # created_at（server_default=now()）在事务内完全相同，
        # 只按时间排序时两者先后成了数据库的偶然结果 ——
        # 表现为刷新页面后「回答出现在问题前面」，而且时有时无。
        rows = db.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.seq)
        ).all()
        cards = _cards(db, rows)
        names = _kp_names(db, rows)
        redacted_ids=set()
        safe_content={}
        safe_planner_ids={}
        safe_practice_request_ids={}
        for row in rows:
            metadata=row.metadata_ or {}
            if row.role=='assistant' and metadata.get('planner_task_id'):
                from backend.models.learning_task import LearningTask
                from backend.services.learning_task_service import get_task
                from backend.services.planning_public_view import public_task
                try:
                    task_id=UUID(str(metadata['planner_task_id']))
                    linked=db.get(LearningTask,task_id)
                except (ValueError,TypeError):
                    linked=None
                if linked is None or linked.session_id!=session_id:
                    redacted_ids.add(row.id)
                    safe_content[row.id]='这份历史学习方案目前无法重新核验；请重新规划后再确认。没有据此生成今日卷。'
                    continue
                if linked is not None and linked.session_id==session_id:
                    try:
                        projected=public_task(request.app.state.session_factory,
                            get_task(request.app.state.session_factory,task_id),now=time_provider())
                    except (AppError,ValueError,TypeError):
                        projected=None
                    if projected is not None and projected.metrics.get('pre_generation'):
                        redacted_ids.add(row.id)
                        safe_content[row.id]=projected.message
                        safe_planner_ids[row.id]=str(task_id)
                        continue
                    if projected is None:
                        redacted_ids.add(row.id)
                        safe_content[row.id]='这份历史学习方案目前无法重新核验；请重新规划后再确认。没有据此生成今日卷。'
                        continue
            if row.role=='assistant' and metadata.get('practice_request_id') is not None:
                from backend.models.practice_request import PracticeRequest
                from backend.services.practice_request_service import view as request_view
                try:request_id=UUID(str(metadata['practice_request_id']))
                except (ValueError,TypeError):request_id=None
                practice_row=db.get(PracticeRequest,request_id) if request_id else None
                if practice_row is None or practice_row.source_conversation_id!=session_id:
                    redacted_ids.add(row.id)
                    safe_content[row.id]='这份历史练习方案目前无法重新核验；请重新规划后再确认。没有据此生成今日卷。'
                    continue
                try:
                    projected=request_view(practice_row,time_provider(),db=db)
                except (AppError,ValueError,TypeError):
                    projected=None
                details=(projected or {}).get('details') or {}
                if projected is None:
                    redacted_ids.add(row.id)
                    safe_content[row.id]='这份历史练习方案目前无法重新核验；请重新规划后再确认。没有据此生成今日卷。'
                    continue
                if details.get('pre_generation'):
                    from backend.services.planning_public_view import summary_message
                    redacted_ids.add(row.id)
                    safe_content[row.id]=summary_message(details['plan_summary'],
                        ready=projected['status'] in {'proposed','accepted'})+"\n\n发送练习需求不会修改今日卷。"
                    safe_practice_request_ids[row.id]=str(request_id)
                    continue
            query=metadata.get('read_only_data_query') or {}
            if not (pre_generation_study and row.role=='assistant' and (
                    query.get('preview_questions') or query.get('query_type') in {'find','inventory','source','history'})):
                continue
            redacted_ids.add(row.id)
            from backend.services.pre_generation_query_view import inventory_answer
            safe_content[row.id]=inventory_answer(query)
            if metadata.get('explanation_source') in {'system_lesson','unavailable'}:
                # Rebuild only published node lessons; never reuse arbitrary
                # historical prose or question-preview fields as safe content.
                from backend.services.lesson_service import read_lesson
                allowed={str(node.get('kp_id')) for node in query.get('scope_node_counts',[]) if isinstance(node,dict)}
                sections=[]
                for trace in (metadata.get('lesson_trace') or [])[:8]:
                    key=str(trace.get('kp_id'))
                    if key not in allowed:continue
                    try:node=db.get(KnowledgePoint,UUID(key))
                    except (ValueError,TypeError):continue
                    markdown=read_lesson(node.code) if node is not None else None
                    if markdown:sections.append('系统节点讲解 · '+node.name+'\n\n'+markdown[:4000])
                prefix='\n\n'.join(sections) or '本次未取得该知识点的系统讲义，不能声称已读取讲解。'
                safe_content[row.id]=prefix+'\n\n## 题库只读预览\n\n'+safe_content[row.id]
        return [
            {
                "message_id": str(row.id),
                "role": row.role,
                "content": safe_content.get(row.id,row.content),
                "status": row.status,
                "response_duration_ms": row.metadata_.get("response_duration_ms"),
                "answer_source": row.metadata_.get("answer_source"),
                "matched_kp_id": str(row.matched_kp_id) if row.matched_kp_id else None,
                # 归因依据：前端据此告诉用户「凭什么归到这个知识点，
                # 依据是正文里的哪一个来源编号」。
                "matched_kp": None if row.id in redacted_ids else _matched_kp_view(
                    row, cards[row.id], names.get(row.matched_kp_id) if row.matched_kp_id else None
                ),
                "citations": [] if row.id in redacted_ids else cards[row.id],
                "study_context":None if row.id in redacted_ids else row.metadata_.get("study_context"),
                "capability_route":None if row.id in redacted_ids else row.metadata_.get("capability_route"),
                "planner_task_id":safe_planner_ids.get(row.id) if row.id in redacted_ids else row.metadata_.get("planner_task_id"),
                "qa_handoff":None if row.id in redacted_ids else row.metadata_.get("qa_handoff"),
                "assistance_level":row.metadata_.get("assistance_level"),
                "qa_action":row.metadata_.get("qa_action"),
                "practice_request_id":safe_practice_request_ids.get(row.id) if row.id in redacted_ids
                    else row.metadata_.get("practice_request_id"),
                "personal_generation":(None if row.id in redacted_ids else with_outcomes(with_diagnostics(row.metadata_["personal_generation"])) if row.metadata_.get('personal_generation') else None),
                "personal_training": None if row.id in redacted_ids else row.metadata_.get("personal_training"),
                "personal_generation_confirmation": (None if row.id in redacted_ids or row.metadata_.get("personal_generation_confirmation_status") in {"cancelled", "superseded", "expired"}
                    else row.metadata_.get("personal_generation_confirmation")),
                "personal_generation_confirmation_status": None if row.id in redacted_ids else row.metadata_.get("personal_generation_confirmation_status"),
                "personal_generation_confirmation_message_id": None if row.id in redacted_ids else row.metadata_.get("personal_generation_confirmation_message_id"),
                "personal_generation_confirmed_kp_id": None if row.id in redacted_ids else row.metadata_.get("personal_generation_confirmed_kp_id"),
                "personal_generation_confirmed_targets": None if row.id in redacted_ids else row.metadata_.get("personal_generation_confirmed_targets"),
                "personal_generation_mode": None if row.id in redacted_ids else row.metadata_.get("personal_generation_mode"),
                "current_work": None if row.id in redacted_ids else row.metadata_.get("current_work"),
                "assistant_error_code": row.metadata_.get("assistant_error_code") or row.metadata_.get("error_code"),
                "request_key": row.metadata_.get("request_key"),
                "retryable": row.metadata_.get("assistant_retryable", row.status in {"failed", "cancelled"}),
                "web_sources":[] if row.id in redacted_ids else row.metadata_.get("web_sources",[]),
                "qa_information_route":None if row.id in redacted_ids else row.metadata_.get("qa_information_route"),
                **({"evaluation_evidence": None if row.id in redacted_ids else row.metadata_.get("evaluation_evidence"),
                    "generation_trace": None if row.id in redacted_ids else row.metadata_.get("generation_trace")}
                   if request.app.state.settings.app_env == "test"
                   and request.app.state.settings.capture_test_evidence else {}),
            }
            for row in rows
        ]

@router.post("/chat/sessions/{session_id}/answers", status_code=201)
def ask(request: Request, session_id: UUID, body: AskRequest,
        purpose: Literal["qa", "study", "materials", "material_search"] = "qa"):
    stack = getattr(request.app.state, "retrieval_stack", None)
    if stack is None: raise AppError("retrieval_unavailable")
    with request.app.state.session_factory() as db:
        require_session_purpose(db, session_id, purpose)
    message, citations, mode = answer(request.app.state.session_factory, session_id=session_id, question=body.question.strip(), stack=stack, provider=provider_from_settings(request.app.state.settings))
    label_by_chunk = {str(chunk_id): label for label, chunk_id in citations}
    # 带上知识点名称：只给 uuid 的话，用户看到「归到 3f2a…」等于没解释。
    kp_name = None
    if message.matched_kp_id is not None:
        with request.app.state.session_factory() as db:
            kp = db.get(KnowledgePoint, message.matched_kp_id)
            kp_name = kp.name if kp is not None else None
    return {"message_id": str(message.id), "answer": message.content, "status": message.status, "response_duration_ms": message.metadata_.get("response_duration_ms"), "matched_kp_id": str(message.matched_kp_id) if message.matched_kp_id else None, "matched_kp": basis_payload(dict(message.matched_kp_basis or {}), label_by_chunk, kp_name=kp_name, kp_id=message.matched_kp_id), "citations": [{"label": label, "chunk_id": str(chunk_id)} for label, chunk_id in citations], "retrieval_mode": mode, "answer_source": message.metadata_.get("answer_source")}

@router.post("/chat/sessions/{session_id}/answers:stream")
async def ask_stream(request: Request, session_id: UUID, body: AskRequest,
                     purpose: Literal["qa", "study", "materials", "material_search"] = "qa"):
    stack = getattr(request.app.state, "retrieval_stack", None)
    with request.app.state.session_factory() as db:
        session = require_session_purpose(db, session_id, purpose)
        if session.purpose not in {purpose, "qa"}:
            raise AppError("chat_session_not_found", status_code=404)
        material_search = session.purpose == "material_search"
        if material_search:
            from backend.services.material_search_service import ready_scope
            _, notice = ready_scope(db, session)
        else:
            notice = None
    if stack is None and not notice: raise AppError("retrieval_unavailable")
    if material_search:
        provider = _DeferredProvider(request.app.state.settings)
        # CallTrace can inspect this without resolving credentials for an empty
        # corpus; only the eventual model method resolves the provider.
        provider.model = request.app.state.settings.llm_model
    else:
        provider = provider_from_settings(request.app.state.settings)
    return StreamingResponse(stream_answer(request.app.state.session_factory, request=request, session_id=session_id, question=body.question.strip(), stack=stack, provider=provider), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@router.post("/chat/sessions/{session_id}/followup-candidates")
def followup_candidates(request: Request, session_id: UUID, body: FollowupCandidatesRequest | None = None,
                        purpose: Literal["qa", "study", "materials", "material_search"] = "qa",
                        clock=Depends(get_time_provider)):
    """只从服务端已归因叶子的既有题库读取候选；绝不在问答层造题或改掌握状态。"""
    from datetime import datetime, timezone
    from backend.models.learning import KpState, Question, QuestionAttempt

    with request.app.state.session_factory() as db:
        session = require_session_purpose(db, session_id, purpose)
        today=clock().astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
        if (session.purpose=='study' and db.scalar(
                select(DailyPlan.id).where(DailyPlan.study_date==today).limit(1)) is None):
            # The homework-planning phase is a blindbox: inventory counts are
            # available from the homepage recommendation API, but this older
            # follow-up endpoint must not reveal question identity or content.
            return {"candidates": []}
        # 只认**最新这一条** assistant 回答的归因。
        #
        # 为什么不能「往前找最近一条有归因的消息」：
        # 那样一来，用户刚问了一个知识库答不上来的问题（越界问题，按契约不归因），
        # 页面却会拿几十条之前的旧归因去出追练题 —— 用户会觉得系统在自说自话。
        # 契约要求「只有服务端可靠匹配到叶子知识点时才显示追练候选」，
        # 所以基准必须是**当前这次回答**，它没归因就给空。
        latest_message = db.scalar(
            select(ChatMessage)
            .where(
                ChatMessage.session_id == session_id,
                ChatMessage.role == "assistant",
                ChatMessage.status == "completed",
            )
            .order_by(ChatMessage.seq.desc())
            .limit(1)
        )
        # 输入区的建议动作绑定触发它的回答；若在请求途中又产生了新回答，
        # 不得把旧回答的题目误当成当前回答的推荐。
        if latest_message is None or (body and body.message_id and body.message_id != latest_message.id) or latest_message.matched_kp_id is None:
            return {"candidates": []}
        message = latest_message
        questions = db.scalars(select(Question).where(Question.kp_id == message.matched_kp_id, Question.is_active.is_(True))).all()
        if not questions:
            return {"candidates": []}
        attempts = db.scalars(select(QuestionAttempt).where(QuestionAttempt.question_id.in_([row.id for row in questions])).order_by(QuestionAttempt.question_id, QuestionAttempt.submitted_at.desc())).all()
        latest: dict[UUID, str] = {}
        for attempt in attempts:
            latest.setdefault(attempt.question_id, attempt.self_grade)
        state = db.get(KpState, message.matched_kp_id)
        due = bool(state and state.next_review_at and state.next_review_at <= datetime.now(timezone.utc))
        def status(row: Question) -> str:
            grade = latest.get(row.id)
            if grade is None: return "unseen"
            if grade == "partial": return "partial"
            if grade == "not_mastered": return "not_mastered"
            return "due" if due else "mastered"
        priority = {"unseen": 0, "partial": 1, "not_mastered": 2, "due": 3, "mastered": 4}
        rows = sorted(questions, key=lambda row: (priority[status(row)], row.is_variant, str(row.id)))[:5]
        return {"candidates": [{"question_id": str(row.id), "kp_id": str(row.kp_id), "stem": row.stem, "is_variant": row.is_variant, "practice_status": status(row)} for row in rows]}

@router.post("/chat/sessions/{session_id}/mark-confused")
def mark_confused(request: Request, session_id: UUID,
                  purpose: Literal["qa", "study", "materials", "material_search"] = "qa"):
    """把困惑写成弱信号；它绝不伪造成作答、更不清空毕业证据。"""
    from datetime import datetime, timezone
    from backend.models.learning import LearningEvent

    with request.app.state.session_factory.begin() as db:
        require_session_purpose(db, session_id, purpose)
        # 与 followup_candidates 同一基准：只认**最新这一条**回答的归因。
        # 否则用户在一个越界问题后点「我不理解」，会被记到几十条之前那个知识点上 ——
        # 学习信号记错对象比不记更糟。
        message = db.scalar(select(ChatMessage).where(ChatMessage.session_id == session_id, ChatMessage.role == "assistant", ChatMessage.status == "completed").order_by(ChatMessage.seq.desc()).limit(1).with_for_update())
        if message is None or message.matched_kp_id is None:
            raise AppError("matched_kp_not_found")
        key = f"chat-confused:{message.id}"
        existing = db.scalar(select(LearningEvent).where(LearningEvent.idempotency_key == key))
        if existing is None:
            db.add(LearningEvent(kp_id=message.matched_kp_id, source_id=message.id, event_type="marked_confused", evidence_level=None, payload={"source": "chat", "can_graduate": False, "changes_mastery": False}, occurred_at=datetime.now(timezone.utc), idempotency_key=key))
        return {"kp_id": str(message.matched_kp_id), "reason_code": "marked_confused", "changes_mastery": False}
