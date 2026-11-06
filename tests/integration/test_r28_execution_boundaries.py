"""R28 actual SQL/SSE boundaries. Providers are explicit protocol fixtures."""
from uuid import UUID, uuid4
import pytest
from sqlalchemy import select, func, event
from backend.models.chat import ChatMessage
from backend.models.learning import DailyPlan, PracticeItem, QuestionAttempt, KpState, LearningEvent
from backend.models.learning_task import LearningTask
from backend.models.practice_request import PracticeRequest
from backend.schemas.learning_assistant import AssistantRequest
from tests.integration.test_learning_assistant import (
    session_factory, clean_database, conversations, setup, talk, QAProvider, NOW,
)
from tests.integration.test_learning_tasks import clean_tasks
from tests.integration.test_complex_intent_current import (
    extra_lhopital_questions, qa_session, ask, request_view, protected_rows,
)


@pytest.mark.parametrize("text", [
    "要不要把刚才生成的题加入今日学习？", "可以把刚才生成的题加入今日学习吗？",
    "先看看刚才生成的题，不要加入今日学习。", "我考虑一下是否加入今日学习。",
    "不要把刚才生成的题加入今日学习。", "暂时不要加入今日学习。", "以后再加入今日学习。",
])
def test_no_consent_never_writes_learning_objects_through_real_sse(session_factory, text):
    sid, ctx, _ = setup(session_factory)
    before = protected_rows(session_factory)
    frames = talk(session_factory, sid, AssistantRequest(question=text, study_context=ctx), QAProvider())
    assert frames and frames[-1][0] == "done", frames
    assert protected_rows(session_factory) == before
    assert not any(e in {"personal_generation", "planner"} for e, _ in frames)


def test_failed_replacement_keeps_owned_draft_and_paper(session_factory, extra_lhopital_questions, monkeypatch):
    from backend.services import composite_bank_plan as composite
    sid = qa_session(session_factory)
    first = request_view(ask(session_factory, sid, "先给我安排一道洛必达法则的待确认方案，不要生成今日卷。"))
    before = protected_rows(session_factory)
    # Deliberate downstream failure, never a fake successful selection.
    monkeypatch.setattr(composite, "build_explained_plan", lambda *a, **kw: {
        "status": "failed", "draft": None, "message": "隔离测试故障：候选读取失败",
        "trace": [], "error_code": "business_tool_failed"})
    frames = ask(session_factory, sid, "换一道同知识点的")
    assert "题库准入检查未完成" in frames[-1][1]["answer"]
    assert "今日卷没有改变" in frames[-1][1]["answer"]
    assert protected_rows(session_factory) == before
    with session_factory() as db:
        assert db.get(PracticeRequest, UUID(first["id"])).status == "draft"


def test_replacement_insert_failure_rolls_back_old_draft_status(session_factory, extra_lhopital_questions):
    from backend.services.practice_request_service import draft_request
    from backend.services.assistant_router import CapabilityRoute
    from backend.schemas.learning_assistant import StudyContext
    from sqlalchemy.orm import Session
    sid = qa_session(session_factory)
    first = request_view(ask(session_factory, sid, "先给我安排一道洛必达法则的待确认方案，不要生成今日卷。"))
    before = protected_rows(session_factory)
    def fail_flush(db, context, instances):
        if any(isinstance(row, PracticeRequest) and row.source_conversation_id == sid for row in db.new):
            raise RuntimeError("R28 injected insert failure")
    with session_factory.begin() as db:
        source = ChatMessage(session_id=sid, role="user", content="换一道同知识点的", status="completed")
        db.add(source)
        db.flush()
        source_id = source.id
    event.listen(Session, "before_flush", fail_flush)
    try:
        with pytest.raises(RuntimeError, match="R28 injected insert failure"):
            draft_request(session_factory, ctx=StudyContext(conversation_id=sid), user_id=source_id,
                assistant_id=uuid4(), message="换一道同知识点的", now=NOW,
                route=CapabilityRoute("planner", "plan", 1, "replace_preview"))
    finally:
        event.remove(Session, "before_flush", fail_flush)
    assert protected_rows(session_factory) == before
    with session_factory() as db:
        assert db.get(PracticeRequest, UUID(first["id"])).status == "draft"
