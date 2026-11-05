"""追练候选的基准：只认**最新这一条**回答的归因。

为什么单独写这个文件：
`followup_candidates` 此前**没有任何测试覆盖**，于是「往前找最近一条有归因的消息」
这个实现活了下来 —— 用户刚问了一个知识库答不上来的越界问题（按契约不归因），
页面却拿几十条之前的旧归因去出追练题，违反验收文档里
「只有服务端可靠匹配到叶子知识点时才显示追练候选」。

这里用真实 PostgreSQL 直接构造消息行（比驱动真实模型稳定得多），
再打真实路由，验证三件事：
1. 最新回答有归因 → 给出该知识点的候选；
2. 最新回答没有归因（越界问题）→ **必须为空**，即使历史上有过归因；
3. 困惑标记同样只认最新回答，不能记到旧知识点上。
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.models import import_models

import_models()

from backend.models.chat import ChatMessage, ChatSession  # noqa: E402
from backend.models.learning import KnowledgePoint, Question  # noqa: E402

from tests.conftest import TEST_DATABASE_URL  # noqa: E402

CHAT_TABLES = ("message_citations", "chat_messages", "chat_sessions")
LEARNING_TABLES = (
    "learning_events",
    "question_attempts",
    "practice_items",
    "daily_plans",
    "questions",
    "kp_states",
    "chunk_knowledge_points",
    "knowledge_points",
)


@pytest.fixture
def session_factory():
    from backend.db import create_db_engine, create_session_factory

    engine = create_db_engine(TEST_DATABASE_URL)
    try:
        yield create_session_factory(engine)
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def clean_tables(session_factory) -> Iterator[None]:
    with session_factory() as db:
        db.execute(
            text(
                "TRUNCATE TABLE "
                + ", ".join(CHAT_TABLES + LEARNING_TABLES)
                + " RESTART IDENTITY CASCADE"
            )
        )
        db.commit()
    yield


@pytest.fixture
def client(app) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def make_session(session_factory, *, mode: str = "builtin") -> UUID:
    with session_factory.begin() as db:
        row = ChatSession(title="新对话", mode=mode)
        db.add(row)
        db.flush()
        return row.id


def make_kp_with_questions(session_factory, *, code: str) -> UUID:
    """建一个叶子知识点，并给它两道有效题目。"""
    with session_factory.begin() as db:
        kp = KnowledgePoint(
            code=code, subject="math", name=f"知识点 {code}", is_assessable=True
        )
        db.add(kp)
        db.flush()
        kp_id = kp.id
        for index in range(2):
            db.add(
                Question(
                    kp_id=kp_id,
                    stem=f"{code} 的题目 {index}",
                    question_type="calculation",
                    correct_answer="1",
                    explanation="解析",
                    is_variant=False,
                    is_active=True,
                )
            )
    return kp_id


def add_assistant_message(
    session_factory, *, session_id: UUID, matched_kp_id: UUID | None, content: str
) -> UUID:
    with session_factory.begin() as db:
        row = ChatMessage(
            session_id=session_id,
            role="assistant",
            content=content,
            status="completed",
            matched_kp_id=matched_kp_id,
        )
        db.add(row)
        db.flush()
        return row.id


def test_candidates_come_from_the_latest_attributed_answer(session_factory, client) -> None:
    """最新回答有归因 → 给出该知识点的候选。"""
    session_id = make_session(session_factory)
    kp_id = make_kp_with_questions(session_factory, code="math.attributed")
    add_assistant_message(
        session_factory, session_id=session_id, matched_kp_id=kp_id, content="有归因的回答 [C1]。"
    )

    response = client.post(f"/api/chat/sessions/{session_id}/followup-candidates")
    assert response.status_code == 200
    body = response.json()
    assert len(body["candidates"]) == 2
    assert {item["kp_id"] for item in body["candidates"]} == {str(kp_id)}

def test_candidates_are_bound_to_the_answer_selected_in_composer(session_factory, client) -> None:
    """回答切换后，迟到的旧请求不能拿当前回答的归因来推荐题目。"""
    session_id = make_session(session_factory)
    old_kp = make_kp_with_questions(session_factory, code="math.old-answer")
    current_kp = make_kp_with_questions(session_factory, code="math.current-answer")
    old_id = add_assistant_message(
        session_factory, session_id=session_id, matched_kp_id=old_kp, content="旧回答。"
    )
    current_id = add_assistant_message(
        session_factory, session_id=session_id, matched_kp_id=current_kp, content="当前回答。"
    )

    stale = client.post(
        f"/api/chat/sessions/{session_id}/followup-candidates",
        json={"message_id": str(old_id)},
    )
    assert stale.status_code == 200
    assert stale.json()["candidates"] == []

    current = client.post(
        f"/api/chat/sessions/{session_id}/followup-candidates",
        json={"message_id": str(current_id)},
    )
    assert current.status_code == 200
    assert len(current.json()["candidates"]) == 2
    assert {item["kp_id"] for item in current.json()["candidates"]} == {str(current_kp)}


def test_out_of_scope_latest_answer_yields_no_candidates(session_factory, client) -> None:
    """越界问题的回答不归因 → 候选必须为空，**即使历史上曾有过归因**。

    这正是修复前的缺陷：实现会回溯历史，把旧归因的题目端出来。
    """
    session_id = make_session(session_factory)
    kp_id = make_kp_with_questions(session_factory, code="math.old")
    # 先来一条有归因的回答（历史）
    add_assistant_message(
        session_factory, session_id=session_id, matched_kp_id=kp_id, content="旧回答 [C1]。"
    )
    # 再来一条越界回答（当前）：服务端没有归因
    add_assistant_message(
        session_factory,
        session_id=session_id,
        matched_kp_id=None,
        content="当前资料里没有关于这个问题的内容。",
    )

    response = client.post(f"/api/chat/sessions/{session_id}/followup-candidates")
    assert response.status_code == 200
    assert response.json()["candidates"] == [], "当前回答没有归因时不得回溯历史出题"


def test_no_completed_answer_yields_no_candidates(session_factory, client) -> None:
    session_id = make_session(session_factory)
    response = client.post(f"/api/chat/sessions/{session_id}/followup-candidates")
    assert response.status_code == 200
    assert response.json()["candidates"] == []


def test_generating_answer_is_ignored_when_looking_for_the_latest(
    session_factory, client
) -> None:
    """正在生成的占位不算「最新已完成回答」。"""
    session_id = make_session(session_factory)
    kp_id = make_kp_with_questions(session_factory, code="math.generating")
    add_assistant_message(
        session_factory, session_id=session_id, matched_kp_id=kp_id, content="已完成 [C1]。"
    )
    with session_factory.begin() as db:
        db.add(
            ChatMessage(
                session_id=session_id,
                role="assistant",
                content="",
                status="generating",
                matched_kp_id=None,
            )
        )

    response = client.post(f"/api/chat/sessions/{session_id}/followup-candidates")
    assert response.status_code == 200
    # 最新已完成的那条有归因 → 仍然给候选（生成中的占位不该把它盖掉）
    assert len(response.json()["candidates"]) == 2


def test_mark_confused_targets_the_latest_answer_only(session_factory, client) -> None:
    """困惑标记必须记在**当前**回答的知识点上，不能记到旧知识点。"""
    session_id = make_session(session_factory)
    kp_id = make_kp_with_questions(session_factory, code="math.confused")
    add_assistant_message(
        session_factory, session_id=session_id, matched_kp_id=kp_id, content="旧回答 [C1]。"
    )
    add_assistant_message(
        session_factory, session_id=session_id, matched_kp_id=None, content="当前回答没有归因。"
    )

    response = client.post(f"/api/chat/sessions/{session_id}/mark-confused")
    assert response.status_code == 409, "当前回答没有归因时不该能标记困惑"
    assert response.json()["error"]["code"] == "matched_kp_not_found"


def test_mark_confused_records_a_weak_signal_without_touching_mastery(
    session_factory, client
) -> None:
    """有归因时可以标记，但它只是弱信号，绝不改掌握状态。"""
    session_id = make_session(session_factory)
    kp_id = make_kp_with_questions(session_factory, code="math.signal")
    message_id = add_assistant_message(
        session_factory, session_id=session_id, matched_kp_id=kp_id, content="回答 [C1]。"
    )

    response = client.post(f"/api/chat/sessions/{session_id}/mark-confused")
    assert response.status_code == 200
    body = response.json()
    assert body["changes_mastery"] is False
    assert body["kp_id"] == str(kp_id)

    with session_factory() as db:
        row = db.execute(
            text(
                "SELECT event_type, payload FROM learning_events WHERE source_id = :sid"
            ),
            {"sid": str(message_id)},
        ).first()
    assert row is not None
    assert row[0] == "marked_confused"
    assert row[1]["changes_mastery"] is False
    assert row[1]["can_graduate"] is False


def test_unknown_session_is_rejected(session_factory, client) -> None:
    response = client.post(f"/api/chat/sessions/{uuid4()}/followup-candidates")
    assert response.status_code == 404
