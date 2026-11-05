"""Purpose-aware chat session ownership checks and legacy home classification."""
from __future__ import annotations

from sqlalchemy import String, cast, exists, select

from backend.errors import AppError
from backend.models.chat import ChatMessage, ChatSession
from backend.models.learning_task import LearningTask


CHAT_PURPOSES = {"qa", "study", "materials", "material_search"}


def _home_evidence_predicate():
    home_message = exists(select(ChatMessage.id).where(
        ChatMessage.session_id == ChatSession.id,
        ChatMessage.metadata_["home_recommendation"].as_boolean().is_(True),
    ))
    home_task = exists(select(LearningTask.id).where(
        LearningTask.session_id == ChatSession.id,
        LearningTask.context["home_recommendation"].as_boolean().is_(True),
    ))
    return home_message | home_task


def _ambiguous_home_assistant_predicate():
    """A legacy QA row with both home evidence and unrelated assistant turns is unclassified.

    Direct home preview turns carry an explicit marker. Older learning-task replies
    can be tied back to their home task by planner_task_id. Any other assistant turn
    means session-level ownership cannot be inferred safely.
    """
    task_owned_turn = exists(select(LearningTask.id).where(
        LearningTask.session_id == ChatMessage.session_id,
        cast(LearningTask.id, String) == ChatMessage.metadata_["planner_task_id"].as_string(),
        LearningTask.context["home_recommendation"].as_boolean().is_(True),
    ).correlate(ChatMessage))
    owned_home_turn = ChatMessage.metadata_["home_recommendation"].as_boolean().is_(True) | task_owned_turn
    return exists(select(ChatMessage.id).where(
        ChatMessage.session_id == ChatSession.id,
        ChatMessage.role == "assistant",
        owned_home_turn.is_not(True),
    ))


def is_legacy_home_session(db, session: ChatSession) -> bool:
    """Only positively tagged, non-mixed old home sessions are re-scoped."""
    if session.purpose != "qa":
        return False
    has_home_evidence = _home_evidence_predicate()
    ambiguous = _ambiguous_home_assistant_predicate()
    return bool(db.scalar(select(has_home_evidence & ~ambiguous).where(ChatSession.id == session.id)))


def _has_legacy_home_evidence(db, session: ChatSession) -> bool:
    if session.purpose != "qa":
        return False
    return bool(db.scalar(select(_home_evidence_predicate()).where(ChatSession.id == session.id)))


def require_session_purpose(db, session_id, purpose: str) -> ChatSession:
    if purpose not in CHAT_PURPOSES:
        raise AppError("chat_session_not_found", status_code=404)
    session = db.get(ChatSession, session_id)
    if session is None or session.archived_at is not None:
        raise AppError("chat_session_not_found", status_code=404)
    if session.purpose == "qa" and _has_legacy_home_evidence(db, session):
        if purpose == "study" and is_legacy_home_session(db, session):
            return session
        # Tagged but mixed/ambiguous history is left unassigned and inaccessible
        # through both module scopes until an explicit data review resolves it.
        raise AppError("chat_session_not_found", status_code=404)
    if session.purpose == purpose:
        return session
    # The same response for missing and foreign-purpose ids avoids confirming
    # whether another surface owns a conversation.
    raise AppError("chat_session_not_found", status_code=404)


def session_list_predicate(purpose: str | None):
    home_evidence = _home_evidence_predicate()
    ambiguous = _ambiguous_home_assistant_predicate()
    if purpose == "study":
        return (ChatSession.purpose == "study") | ((ChatSession.purpose == "qa") & home_evidence & ~ambiguous)
    if purpose == "qa":
        return (ChatSession.purpose == "qa") & ~home_evidence
    if purpose in {"materials", "material_search"}:
        return ChatSession.purpose == purpose
    # Backward-compatible unscoped listing means ordinary Q&A and materials;
    # study records (including tagged legacy homepage records) stay out.
    return ChatSession.purpose.in_(("qa", "materials")) & ~home_evidence


def effective_purpose(db, session: ChatSession) -> str:
    if session.purpose == "qa" and is_legacy_home_session(db, session):
        return "study"
    return session.purpose
