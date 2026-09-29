from __future__ import annotations
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import delete, exists, select
from backend.chat.service import answer, basis_payload, provider_from_settings, require_active_session, stream_answer
from backend.errors import AppError
from backend.models.chat import ChatMessage, ChatSession, MessageCitation
from backend.models.learning import KnowledgePoint
from backend.models.rag import DocumentChunk, Material

router = APIRouter(tags=["chat"])

class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str = Field(default="新对话", min_length=1, max_length=200)
    mode: Literal["builtin", "user"] = "builtin"
class AskRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=4000)

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
def create_session(request: Request, body: CreateSessionRequest):
    with request.app.state.session_factory.begin() as db:
        session = ChatSession(title=body.title.strip(), mode=body.mode); db.add(session); db.flush()
        return {"session_id": str(session.id), "title": session.title, "mode": session.mode}

@router.get("/chat/sessions")
def list_sessions(request: Request, mode: Literal["builtin", "user"] | None = None):
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
        return [{"session_id": str(row.id), "title": row.title, "mode": row.mode} for row in rows]

@router.patch("/chat/sessions/{session_id}")
def rename_session(request: Request, session_id: UUID, body: RenameSessionRequest):
    """会话标题仅供历史导航；不会改写消息、引用或学习事实。"""
    with request.app.state.session_factory.begin() as db:
        session = require_active_session(db, session_id)
        session.title = body.title.strip()
        return {"session_id": str(session.id), "title": session.title, "mode": session.mode}

@router.delete("/chat/sessions/{session_id}", status_code=204)
def delete_session(request: Request, session_id: UUID):
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
        session = require_active_session(db, session_id)
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
def list_messages(request: Request, session_id: UUID):
    with request.app.state.session_factory() as db:
        require_active_session(db, session_id)
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
        return [
            {
                "message_id": str(row.id),
                "role": row.role,
                "content": row.content,
                "status": row.status,
                "response_duration_ms": row.metadata_.get("response_duration_ms"),
                "answer_source": row.metadata_.get("answer_source"),
                "matched_kp_id": str(row.matched_kp_id) if row.matched_kp_id else None,
                # 归因依据：前端据此告诉用户「凭什么归到这个知识点，
                # 依据是正文里的哪一个来源编号」。
                "matched_kp": _matched_kp_view(
                    row, cards[row.id], names.get(row.matched_kp_id) if row.matched_kp_id else None
                ),
                "citations": cards[row.id],
            }
            for row in rows
        ]

@router.post("/chat/sessions/{session_id}/answers", status_code=201)
def ask(request: Request, session_id: UUID, body: AskRequest):
    stack = getattr(request.app.state, "retrieval_stack", None)
    if stack is None: raise AppError("retrieval_unavailable")
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
async def ask_stream(request: Request, session_id: UUID, body: AskRequest):
    stack = getattr(request.app.state, "retrieval_stack", None)
    if stack is None: raise AppError("retrieval_unavailable")
    provider = provider_from_settings(request.app.state.settings)
    with request.app.state.session_factory() as db: require_active_session(db, session_id)
    return StreamingResponse(stream_answer(request.app.state.session_factory, request=request, session_id=session_id, question=body.question.strip(), stack=stack, provider=provider), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@router.post("/chat/sessions/{session_id}/followup-candidates")
def followup_candidates(request: Request, session_id: UUID, body: FollowupCandidatesRequest | None = None):
    """只从服务端已归因叶子的既有题库读取候选；绝不在问答层造题或改掌握状态。"""
    from datetime import datetime, timezone
    from backend.models.learning import KpState, Question, QuestionAttempt

    with request.app.state.session_factory() as db:
        require_active_session(db, session_id)
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
def mark_confused(request: Request, session_id: UUID):
    """把困惑写成弱信号；它绝不伪造成作答、更不清空毕业证据。"""
    from datetime import datetime, timezone
    from backend.models.learning import LearningEvent

    with request.app.state.session_factory.begin() as db:
        require_active_session(db, session_id)
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
