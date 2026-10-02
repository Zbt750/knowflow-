"""阶段 B 学习闭环的 API 集成测试。

这些测试都打真实 PostgreSQL（`kaoyan_test`），不使用 mock 数据库：
- 每个用例开始前清空业务表并重新灌入种子数据，用例之间互不污染。
- 时间通过覆盖 `get_time_provider` 注入，因此跨天毕业不需要改系统时间。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from backend.api.deps import get_time_provider
from backend.app import create_app
from backend.models.learning import (
    DailyPlan,
    ExamQuestionReference,
    KnowledgePoint,
    KpState,
    LearningEvent,
    PracticeItem,
    Question,
    QuestionAttempt,
)
from scripts.seed import seed_all
from backend.services.exam_reference_service import sync_exam_reference_index

from tests.conftest import TEST_DATABASE_URL

# 上海 10:00 == UTC 02:00；学习日以上海为准。
DAY1 = datetime(2026, 1, 1, 2, tzinfo=timezone.utc)
DAY2 = datetime(2026, 1, 2, 2, tzinfo=timezone.utc)
DAY3 = datetime(2026, 1, 3, 2, tzinfo=timezone.utc)

BUSINESS_TABLES = (
    "exam_question_references",
    "question_attempts",
    "learning_events",
    "practice_items",
    "daily_plans",
    "questions",
    "kp_states",
    "knowledge_points",
)


class FakeClock:
    """可变时钟：同一请求内取值一致，测试可在请求之间推进它。"""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(DAY1)


@pytest.fixture
def session_factory():
    """独立会话工厂：用于准备/断言数据库状态，与会话内路由的会话互不干扰。"""
    from backend.db import create_db_engine, create_session_factory

    engine = create_db_engine(TEST_DATABASE_URL)
    try:
        yield create_session_factory(engine)
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def clean_database(session_factory) -> Iterator[None]:
    """每个用例前清空业务表并灌入种子；清空顺序遵循外键依赖。"""
    with session_factory() as db:
        db.execute(text("TRUNCATE TABLE " + ", ".join(BUSINESS_TABLES) + " RESTART IDENTITY CASCADE"))
        seed_all(db)
        db.commit()
    yield


@pytest.fixture
def client(clock: FakeClock) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_time_provider] = lambda: clock
    # 必须用 with：否则 lifespan 不执行，测试会变成假绿灯。
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# 辅助
# --------------------------------------------------------------------------- #


def test_knowledge_lesson_reads_seed_file_and_breadcrumbs(client: TestClient) -> None:
    response = client.get("/api/knowledge/lessons/math.calculus.limit.lhopital")
    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == "math.calculus.limit.lhopital"
    assert payload["is_assessable"] is True
    assert payload["question_count"] >= 1
    assert "例题" in payload["markdown"]
    assert [item["code"] for item in payload["breadcrumbs"]] == [
        "math.calculus",
        "math.calculus.limit",
        "math.calculus.limit.lhopital",
    ]

    parent = client.get("/api/knowledge/lessons/math.calculus.limit")
    assert parent.status_code == 200
    assert parent.json()["is_assessable"] is False
    assert parent.json()["question_count"] == 0

    missing = client.get("/api/knowledge/lessons/no.such.node")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "knowledge_point_not_found"


def leaf_codes(session_factory) -> dict[str, UUID]:
    with session_factory() as db:
        rows = db.execute(
            select(KnowledgePoint.code, KnowledgePoint.id).where(
                KnowledgePoint.is_assessable.is_(True)
            )
        ).all()
    return {code: kp_id for code, kp_id in rows}


def restart_plan_items(session_factory) -> None:
    """把今天卷里的题恢复为“未完成”，模拟第二天重新做同一批题。"""
    with session_factory() as db:
        for item in db.scalars(select(PracticeItem)).all():
            item.completed_at = None
            item.latest_self_grade = None
        db.commit()


def set_plan_active(session_factory) -> None:
    with session_factory() as db:
        for plan in db.scalars(select(DailyPlan)).all():
            plan.status = "active"
        db.commit()


def generate_plan(client: TestClient, kp_ids: list[UUID]):
    return client.post(
        "/api/plans/today/generate", json={"selected_kp_ids": [str(kp) for kp in kp_ids]}
    )


def items_by_ordinal(plan: dict) -> dict[int, dict]:
    return {item["ordinal"]: item for item in plan["items"]}


def assess(
    client: TestClient,
    item_id: str,
    grade: str,
    key: str,
    raw_answer: str | None = None,
    selected_option: str | None = None,
):
    body: dict[str, object] = {"self_grade": grade, "idempotency_key": key}
    if raw_answer is not None:
        body["raw_answer"] = raw_answer
    if selected_option is not None:
        body["selected_option"] = selected_option
    return client.post(f"/api/practice-items/{item_id}/self-assessments", json=body)


# --------------------------------------------------------------------------- #
# 知识树
# --------------------------------------------------------------------------- #


def test_knowledge_tree_marks_only_leaves_assessable_and_leaves_parent_state_empty(
    client: TestClient, session_factory
) -> None:
    response = client.get("/api/knowledge/tree")
    assert response.status_code == 200
    roots = response.json()["nodes"]
    assert [node["code"] for node in roots] == ["math.calculus", "math.linear-algebra"]

    def walk(node: dict):
        yield node
        for child in node["children"]:
            yield from walk(child)

    nodes = [node for root in roots for node in walk(root)]
    assert len(nodes) == 11
    leaves = [node for node in nodes if node["is_assessable"]]
    assert len(leaves) == 5
    # 父节点不得暴露状态与自评入口所需的字段值。
    for node in nodes:
        if not node["is_assessable"]:
            assert node["state"] is None
            assert node["children"], "父节点必须是汇总节点"
        else:
            assert node["state"] == "unseen"
            assert node["children"] == []


def test_annual_exam_question_is_bound_to_assessable_source_reference_node(
    client: TestClient, session_factory
) -> None:
    with session_factory() as db:
        first = sync_exam_reference_index(db)
        db.commit()
        reference = db.scalar(
            select(ExamQuestionReference).where(
                ExamQuestionReference.subject == "408",
                ExamQuestionReference.year == 2010,
                ExamQuestionReference.question_number == 1,
            )
        )
        assert reference is not None
        kp_id = reference.knowledge_point_id
        second = sync_exam_reference_index(db)
        db.commit()

    assert first["references_created"] >= 1400
    assert second["references_created"] == 0
    detail_response = client.get(f"/api/knowledge/{kp_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["node"]["is_reference_only"] is True
    assert detail["node"]["is_assessable"] is True
    assert detail["questions"] == []
    assert detail["lesson_available"] is True
    assert any(
        row["year"] == 2010
        and row["question_number"] == 1
        and row["question_source_url"].endswith("/2010/01")
        for row in detail["exam_references"]
    )

    tree_codes = {node["code"] for node in client.get("/api/knowledge/tree").json()["nodes"]}
    assert "cs408" in tree_codes
    today = client.get("/api/plans/today").json()
    assert str(kp_id) not in {item["kp_id"] for item in today.get("recommendations", [])}


def test_external_exam_reference_can_be_scheduled_and_reported_without_graduation(
    client: TestClient, session_factory
) -> None:
    with session_factory() as db:
        sync_exam_reference_index(db)
        db.commit()
        single_reference_kps = (
            select(ExamQuestionReference.knowledge_point_id)
            .group_by(ExamQuestionReference.knowledge_point_id)
            .having(func.count(ExamQuestionReference.id) == 1)
        )
        reference_id, kp_id = db.execute(
            select(ExamQuestionReference.id, ExamQuestionReference.knowledge_point_id)
            .where(ExamQuestionReference.knowledge_point_id.in_(single_reference_kps))
            .order_by(ExamQuestionReference.year, ExamQuestionReference.question_number)
        ).first()
        before_question_count = db.scalar(select(func.count(Question.id)))

    added = client.post(
        "/api/plans/today/exam-references", json={"reference_ids": [str(reference_id)]}
    )
    assert added.status_code == 200, added.text
    plan = added.json()
    assert plan["status"] == "active"
    assert plan["total_count"] == 1
    item = plan["items"][0]
    assert item["kp_id"] == str(kp_id)
    assert item["question_id"] is None
    assert item["question_type"] == "external_exam"
    assert item["stem"] is None
    assert item["exam_reference"]["id"] == str(reference_id)
    assert item["is_external_reference"] is True

    no_answer = client.get(f"/api/practice-items/{item['id']}/answer")
    assert no_answer.status_code == 409
    assert no_answer.json()["error"]["code"] == "external_exam_has_no_embedded_answer"

    skipped = client.post(
        f"/api/practice-items/{item['id']}/self-assessments",
        json={"self_grade": "skip", "idempotency_key": "exam-skip-0001"},
    )
    assert skipped.status_code == 200, skipped.text
    assert skipped.json()["reason_code"] == "skipped"

    assessed = client.post(
        f"/api/practice-items/{item['id']}/self-assessments",
        json={"self_grade": "mastered", "idempotency_key": "exam-mastered-01"},
    )
    assert assessed.status_code == 200, assessed.text
    assert assessed.json()["state"] == "unseen"
    assert assessed.json()["reason_code"] == "self_feedback_only"
    detail = client.get(f"/api/knowledge/{kp_id}").json()
    assert detail["node"]["state"] == "unseen"
    assert detail["node"]["effective_confirmation_count"] == 0
    assert len(detail["attempts"]) == 1
    assert detail["attempts"][0]["question_id"] is None
    assert detail["attempts"][0]["exam_reference_id"] == str(reference_id)
    with session_factory() as db:
        attempt = db.scalar(
            select(QuestionAttempt).where(QuestionAttempt.practice_item_id == UUID(item["id"]))
        )
        assert attempt is not None
        assert attempt.question_id is None
        assert attempt.exam_reference_id == reference_id
        assert db.scalar(select(func.count(Question.id))) == before_question_count


def test_reference_only_node_can_generate_an_external_task_from_scope(
    client: TestClient, session_factory
) -> None:
    with session_factory() as db:
        sync_exam_reference_index(db)
        db.commit()
        reference = db.scalar(select(ExamQuestionReference).order_by(ExamQuestionReference.id))
        assert reference is not None
        kp_id = reference.knowledge_point_id

    response = client.post(
        "/api/plans/today/generate",
        json={"selected_kp_ids": [str(kp_id)], "budget": "standard"},
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["total_count"] >= 1
    assert all(item["is_external_reference"] for item in payload["items"])
    assert all(item["question_id"] is None and item["stem"] is None for item in payload["items"])


def test_cross_day_external_self_reports_never_become_confirmations(
    client: TestClient, session_factory, clock: FakeClock
) -> None:
    with session_factory() as db:
        sync_exam_reference_index(db)
        db.commit()
        kp_id, reference_ids = db.execute(
            select(ExamQuestionReference.knowledge_point_id, func.array_agg(ExamQuestionReference.id))
            .group_by(ExamQuestionReference.knowledge_point_id)
            .having(func.count(ExamQuestionReference.id) >= 3)
            .order_by(func.count(ExamQuestionReference.id).desc())
            .limit(1)
        ).one()
        reference_ids = list(reference_ids[:3])

    final_assessment = None
    for index, (reference_id, now) in enumerate(zip(reference_ids, (DAY1, DAY2, DAY3)), start=1):
        clock.now = now
        added = client.post(
            "/api/plans/today/exam-references", json={"reference_ids": [str(reference_id)]}
        )
        assert added.status_code == 200, added.text
        item = added.json()["items"][0]
        final_assessment = client.post(
            f"/api/practice-items/{item['id']}/self-assessments",
            json={"self_grade": "mastered", "idempotency_key": f"exam-cross-day-{index}"},
        )
        assert final_assessment.status_code == 200, final_assessment.text
        if index < 3:
            assert final_assessment.json()["state"] != "mastered"

    assert final_assessment is not None
    assert final_assessment.json()["state"] == "unseen"
    assert final_assessment.json()["reason_code"] == "self_feedback_only"
    detail = client.get(f"/api/knowledge/{kp_id}").json()
    assert detail["node"]["day_span"] is None
    assert detail["node"]["effective_confirmation_count"] == 0


def test_bound_exam_reference_can_be_added_from_an_existing_assessable_node(
    client: TestClient, session_factory
) -> None:
    with session_factory() as db:
        sync_exam_reference_index(db)
        db.commit()
        reference = db.scalar(
            select(ExamQuestionReference)
            .join(KnowledgePoint, KnowledgePoint.id == ExamQuestionReference.knowledge_point_id)
            .where(
                KnowledgePoint.code == "math.calculus.limit.infinitesimal",
                KnowledgePoint.is_reference_only.is_(False),
            )
            .order_by(ExamQuestionReference.year, ExamQuestionReference.question_number)
        )
        assert reference is not None
        reference_id = reference.id
        kp_id = reference.knowledge_point_id

    added = client.post(
        "/api/plans/today/exam-references", json={"reference_ids": [str(reference_id)]}
    )
    assert added.status_code == 200, added.text
    item = added.json()["items"][0]
    assert item["kp_id"] == str(kp_id)
    assert item["exam_reference"]["id"] == str(reference_id)
    assert item["is_external_reference"] is True


def test_topic_family_aggregates_distinct_years_and_can_be_practiced(
    client: TestClient, session_factory
) -> None:
    with session_factory() as db:
        sync_exam_reference_index(db)
        db.commit()
        family = db.scalar(
            select(KnowledgePoint).where(
                KnowledgePoint.code == "math.family.calculus-multivariable"
            )
        )
        assert family is not None
        reference = db.scalar(
            select(ExamQuestionReference).where(
                ExamQuestionReference.knowledge_point_id == family.id,
                ExamQuestionReference.year == 2026,
                ExamQuestionReference.question_number == 17,
            )
        )
        assert reference is not None
        ref_count = db.scalar(
            select(func.count(ExamQuestionReference.id)).where(
                ExamQuestionReference.knowledge_point_id == family.id
            )
        )
        assert ref_count == 65
        family_id = family.id
        reference_id = reference.id

    detail = client.get(f"/api/knowledge/{family_id}").json()
    assert detail["node"]["summary"] and "跨年份专题汇总" in detail["node"]["summary"]
    assert detail["lesson_available"] is True
    assert len(detail["exam_references"]) == 65
    assert all("专题汇总映射" in row["source_note"] for row in detail["exam_references"])

    added = client.post(
        "/api/plans/today/exam-references", json={"reference_ids": [str(reference_id)]}
    )
    assert added.status_code == 200, added.text
    item = added.json()["items"][0]
    assert item["kp_id"] == str(family_id)
    assert item["is_external_reference"] is True


def test_parent_node_cannot_be_assessed(client: TestClient, session_factory) -> None:
    parent = leaf_codes(session_factory)
    with session_factory() as db:
        parent_id = db.scalar(
            select(KnowledgePoint.id).where(KnowledgePoint.is_assessable.is_(False))
        )
    response = client.post(
        f"/api/knowledge/{parent_id}/self-assessment",
        json={"self_grade": "mastered", "idempotency_key": "node-parent-1"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "node_not_assessable"
    assert parent  # 保证夹具真的取到了叶子


# --------------------------------------------------------------------------- #
# 准备页与生成
# --------------------------------------------------------------------------- #


def test_today_returns_setup_with_recommendations_before_generation(client: TestClient) -> None:
    response = client.get("/api/plans/today")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "setup"
    assert body["study_date"] == "2026-01-01"
    # 未学习的叶子理由是 preview；页面据此展示“先看看”。
    assert body["recommendations"]
    assert {item["reason"] for item in body["recommendations"]} == {"preview"}
    assert len(body["recommendations"]) <= 6


def test_generate_plan_creates_two_basic_and_one_variant_per_leaf(
    client: TestClient, session_factory
) -> None:
    leaves = leaf_codes(session_factory)
    kp_id = leaves["math.calculus.limit.lhopital"]
    response = generate_plan(client, [kp_id])
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "active"
    assert body["study_date"] == "2026-01-01"
    # 题量由该叶子的毕业缺口与时间预算决定，不再固定 3 道。
    assert body["completed_count"] == 0
    assert body["total_count"] == len(body["items"])
    # ordinal 从 1 开始连续递增。
    assert [item["ordinal"] for item in body["items"]] == list(
        range(1, body["total_count"] + 1)
    )
    # 洛必达法则的策略要求：选择 1、填空 1、计算 2，且至少 1 道真实变式题。
    assert body["type_summary"].get("single_choice", 0) >= 1
    assert body["type_summary"].get("fill_blank", 0) >= 1
    assert body["type_summary"].get("calculation", 0) >= 2
    assert sum(1 for item in body["items"] if item["is_variant"]) >= 1
    assert "proof" not in body["type_summary"]
    assert body["estimated_minutes"] > 0
    assert body["focus_item_id"] == body["items"][0]["id"]
    # 不显示题目来源标签。
    assert "source" not in body["items"][0]


def test_plan_response_never_leaks_answer_or_explanation(client: TestClient, session_factory) -> None:
    leaves = leaf_codes(session_factory)
    body = generate_plan(client, [leaves["math.calculus.limit.lhopital"]]).json()
    for item in body["items"]:
        assert "correct_answer" not in item
        assert "explanation" not in item


def test_same_day_cannot_generate_twice(client: TestClient, session_factory) -> None:
    leaves = leaf_codes(session_factory)
    kp_id = leaves["math.calculus.limit.lhopital"]
    assert generate_plan(client, [kp_id]).status_code == 201
    second = generate_plan(client, [kp_id])
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "plan_already_generated"


def test_empty_selection_is_rejected(client: TestClient) -> None:
    response = client.post("/api/plans/today/generate", json={"selected_kp_ids": []})
    # Pydantic 的 min_length=1 先拦下空数组。
    assert response.status_code == 422


def test_incomplete_question_pool_is_rejected(client: TestClient, session_factory) -> None:
    """把某个叶子的变式题停用后，整体生成必须失败且不留半张卷。"""
    leaves = leaf_codes(session_factory)
    kp_id = leaves["math.calculus.limit.lhopital"]
    with session_factory() as db:
        # 该叶子策略要求 2 道计算题；把计算题停用后题库就不足以满足策略了。
        rows = db.scalars(
            select(Question).where(
                Question.kp_id == kp_id, Question.question_type == "calculation"
            )
        ).all()
        assert rows, "种子数据里必须有计算题"
        # 策略要求 2 道计算题，所以要把计算题全部停用才算题库不足。
        for row in rows:
            row.is_active = False
        db.commit()

    response = generate_plan(client, [kp_id])
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "question_pool_incomplete"
    with session_factory() as db:
        assert db.scalar(select(DailyPlan)) is None


# --------------------------------------------------------------------------- #
# 答案：纯读取
# --------------------------------------------------------------------------- #


def test_answer_endpoint_is_pure_read_and_does_not_touch_learning_data(
    client: TestClient, session_factory
) -> None:
    leaves = leaf_codes(session_factory)
    kp_id = leaves["math.calculus.limit.lhopital"]
    body = generate_plan(client, [kp_id]).json()
    first = body["items"][0]

    # 做题前也能查看答案。
    answer = client.get(f"/api/practice-items/{first['id']}/answer")
    assert answer.status_code == 200
    payload = answer.json()
    assert payload["correct_answer"]
    assert payload["explanation"]

    # 查看答案不写 attempt、不改状态、不改完成情况。
    with session_factory() as db:
        assert db.scalar(select(QuestionAttempt)) is None
        assert db.scalar(select(LearningEvent)) is None
        state = db.get(KpState, kp_id)
        assert state is not None and state.state == "unseen"
        assert state.evidence_window == []
        item = db.get(PracticeItem, UUID(first["id"]))
        assert item is not None and item.completed_at is None

    # 查看答案后自评仍然可用。
    assert assess(client, first["id"], "mastered", "answer-then-assess").status_code == 200


def test_answer_for_missing_item_returns_stable_code(client: TestClient) -> None:
    response = client.get("/api/practice-items/00000000-0000-0000-0000-000000000000/answer")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "practice_item_not_found"


def redo_item(client: TestClient, session_factory, position: int) -> str:
    """把当天卷内第 position 道题恢复为未完成，模拟「第二天再做一遍」并返回它的 id。

    注意用「卷内位置」而不是 ordinal：后追加或新一天生成的卷，
    ordinal 会继续往上涨，不再从 1 开始。
    """
    today = client.get("/api/plans/today").json()
    items = today["items"]
    assert items, "当天应当已经有练习卷"
    assert 1 <= position <= len(items), f"卷内只有 {len(items)} 道题"
    target = items[position - 1]
    with session_factory() as db:
        item = db.get(PracticeItem, UUID(target["id"]))
        assert item is not None
        item.completed_at = None
        item.latest_self_grade = None
        # 卷里又出现了未完成的题，计划回到进行中。
        item.plan.status = "active"
        db.commit()
    return target["id"]


# --------------------------------------------------------------------------- #
# 四种自评
# --------------------------------------------------------------------------- #


def test_skip_writes_no_attempt_and_changes_nothing(client: TestClient, session_factory) -> None:
    leaves = leaf_codes(session_factory)
    kp_id = leaves["math.calculus.limit.lhopital"]
    body = generate_plan(client, [kp_id]).json()
    item_id = body["items"][0]["id"]

    response = assess(client, item_id, "skip", "skip-key-0001")
    assert response.status_code == 200
    assert response.json()["reason_code"] == "skipped"

    with session_factory() as db:
        assert db.scalar(select(QuestionAttempt)) is None
        item = db.get(PracticeItem, UUID(item_id))
        assert item is not None
        # skip 不标记完成、不写自评结果。
        assert item.completed_at is None
        assert item.latest_self_grade is None
        state = db.get(KpState, kp_id)
        assert state is not None and state.state == "unseen"


def test_partial_keeps_history_but_does_not_enter_window(
    client: TestClient, session_factory
) -> None:
    leaves = leaf_codes(session_factory)
    kp_id = leaves["math.calculus.limit.lhopital"]
    body = generate_plan(client, [kp_id]).json()
    first = body["items"][0]

    response = assess(client, first["id"], "partial", "partial-key-01", raw_answer="我的思路")
    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "unseen"
    assert payload["reason_code"] == "self_feedback_only"
    assert payload["effective_confirmation_count"] == 0

    with session_factory() as db:
        attempt = db.scalar(select(QuestionAttempt))
        assert attempt is not None
        assert attempt.self_grade == "partial"
        assert attempt.raw_answer == "我的思路"
        # objective_result 只是复盘参考，不覆盖 self_grade。
        assert attempt.objective_result == "unknown"
        state = db.get(KpState, kp_id)
        assert state is not None and state.evidence_window == []


def test_not_mastered_clears_window_but_keeps_history(
    client: TestClient, session_factory
) -> None:
    leaves = leaf_codes(session_factory)
    kp_id = leaves["math.calculus.limit.lhopital"]
    body = generate_plan(client, [kp_id]).json()
    ordered = items_by_ordinal(body)

    # 先积累一条已掌握确认。
    first = assess(client, ordered[1]["id"], "mastered", "nm-key-0001")
    assert first.status_code == 200
    assert first.json()["effective_confirmation_count"] == 0

    # 明确未掌握：清空窗口、状态转 stuck、历史保留。
    second = assess(client, ordered[2]["id"], "not_mastered", "nm-key-0002")
    assert second.status_code == 200
    assert second.json()["state"] == "unseen"
    assert second.json()["reason_code"] == "self_feedback_only"
    assert second.json()["effective_confirmation_count"] == 0

    with session_factory() as db:
        attempts = db.scalars(select(QuestionAttempt)).all()
        assert len(attempts) == 2  # 两条历史都在
        assert {attempt.self_grade for attempt in attempts} == {"mastered", "not_mastered"}
        state = db.get(KpState, kp_id)
        assert state is not None
        assert state.state == "unseen"
        assert state.evidence_window == []


def test_self_assessment_is_idempotent_by_key(client: TestClient, session_factory) -> None:
    leaves = leaf_codes(session_factory)
    kp_id = leaves["math.calculus.limit.lhopital"]
    body = generate_plan(client, [kp_id]).json()
    item_id = body["items"][0]["id"]

    first = assess(client, item_id, "mastered", "idem-key-0001")
    second = assess(client, item_id, "mastered", "idem-key-0001")
    assert first.status_code == 200
    assert second.status_code == 200
    # 同一 key 重放：原因码与有效确认数完全一致，不重复累计。
    assert first.json()["reason_code"] == second.json()["reason_code"]
    assert first.json()["effective_confirmation_count"] == second.json()["effective_confirmation_count"] == 0

    with session_factory() as db:
        assert len(db.scalars(select(QuestionAttempt)).all()) == 1
        assert len(db.scalars(select(LearningEvent)).all()) == 1


def test_reassessing_same_item_with_new_key_is_rejected(
    client: TestClient, session_factory
) -> None:
    leaves = leaf_codes(session_factory)
    kp_id = leaves["math.calculus.limit.lhopital"]
    body = generate_plan(client, [kp_id]).json()
    item_id = body["items"][0]["id"]

    assert assess(client, item_id, "mastered", "dup-key-0001").status_code == 200
    second = assess(client, item_id, "mastered", "dup-key-0002")
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "practice_item_already_assessed"


def test_short_idempotency_key_is_rejected(client: TestClient, session_factory) -> None:
    leaves = leaf_codes(session_factory)
    body = generate_plan(client, [leaves["math.calculus.limit.lhopital"]]).json()
    response = assess(client, body["items"][0]["id"], "mastered", "short")
    assert response.status_code == 422


def test_plan_becomes_completed_when_all_items_assessed(
    client: TestClient, session_factory
) -> None:
    leaves = leaf_codes(session_factory)
    body = generate_plan(client, [leaves["math.calculus.limit.lhopital"]]).json()
    ordered = items_by_ordinal(body)

    # 做完这张卷的全部题目。
    for index, item in enumerate(ordered.values(), start=1):
        assert assess(client, item["id"], "mastered", f"done-key-{index:04d}").status_code == 200

    today = client.get("/api/plans/today").json()
    assert today["status"] == "completed"
    assert today["completed_count"] == today["total_count"] == body["total_count"]
    # 全部完成后没有待做项，专注模式指针为空。
    assert today["focus_item_id"] is None
    # 今日知识点摘要反映实际涉及的知识点与完成数量。
    assert len(today["summary_kps"]) == 1
    assert today["summary_kps"][0]["completed_count"] == body["total_count"]


def test_assessed_item_remains_in_full_paper_and_history(
    client: TestClient, session_factory
) -> None:
    leaves = leaf_codes(session_factory)
    kp_id = leaves["math.calculus.limit.lhopital"]
    body = generate_plan(client, [kp_id]).json()
    ordered = items_by_ordinal(body)
    assert assess(client, ordered[1]["id"], "mastered", "keep-key-0001").status_code == 200

    today = client.get("/api/plans/today").json()
    # 全卷仍包含已完成题，且带自评结果。
    assert len(today["items"]) == body["total_count"]
    completed = [item for item in today["items"] if item["completed"]]
    assert len(completed) == 1
    assert completed[0]["latest_self_grade"] == "mastered"
    # 专注模式跳过已完成题。
    assert today["focus_item_id"] == ordered[2]["id"]

    detail = client.get(f"/api/knowledge/{kp_id}").json()
    assert len(detail["attempts"]) == 1
    assert detail["attempts"][0]["self_grade"] == "mastered"


# --------------------------------------------------------------------------- #
# 追加题目
# --------------------------------------------------------------------------- #


def test_plan_row_status_becomes_completed_in_database(
    client: TestClient, session_factory
) -> None:
    """API 的 status 是算出来的；这里直接断言数据库里的计划行也被切换为 completed。"""
    leaves = leaf_codes(session_factory)
    body = generate_plan(client, [leaves["math.calculus.limit.lhopital"]]).json()
    plan_id = body["plan_id"]
    for index, item in enumerate(items_by_ordinal(body).values(), start=1):
        assert assess(client, item["id"], "mastered", f"row-key-{index:04d}").status_code == 200

    with session_factory() as db:
        plan = db.get(DailyPlan, UUID(plan_id))
        assert plan is not None
        assert plan.status == "completed"


def test_append_questions_adds_to_tail_and_deduplicates(
    client: TestClient, session_factory
) -> None:
    leaves = leaf_codes(session_factory)
    kp_id = leaves["math.calculus.limit.lhopital"]
    body = generate_plan(client, [kp_id]).json()
    plan_id = body["plan_id"]

    in_paper = {item["question_id"] for item in body["items"]}
    with session_factory() as db:
        # 从另一个叶子的题库取一道题追加：模拟用户从知识树补充练习。
        other_leaf = leaves["math.calculus.series.geometric"]
        candidate_id = str(
            db.scalar(select(Question.id).where(Question.kp_id == other_leaf))
        )
        duplicate_id = next(iter(in_paper))

    appended = client.post(
        f"/api/plans/{plan_id}/questions",
        json={"question_ids": [candidate_id, candidate_id, duplicate_id]},
    )
    assert appended.status_code == 200
    after = appended.json()
    # 只新增一道：候选题自身的重复被忽略，卷内已存在的题也被忽略。
    expected_total = body["total_count"] + 1
    assert after["total_count"] == expected_total
    assert [item["ordinal"] for item in after["items"]] == list(
        range(1, expected_total + 1)
    )
    assert after["items"][-1]["question_id"] == candidate_id

    with session_factory() as db:
        rows = db.scalars(
            select(PracticeItem).where(PracticeItem.plan_id == UUID(plan_id))
        ).all()
        # 同一张卷内没有重复题。
        assert len({row.question_id for row in rows}) == len(rows) == expected_total


def test_append_to_completed_plan_reactivates_it(client: TestClient, session_factory) -> None:
    """做完今日全部题后仍可继续练习：追加会把已完成的卷改回进行中。

    产品规则要求「追加到 max(ordinal)+1 的卷尾」，并没有说“做完了就不许再练”。
    之前的实现在这里返回 409 plan_not_active，导致用户完成当天任务后无法追加题目。
    """
    leaves = leaf_codes(session_factory)
    kp_id = leaves["math.calculus.limit.lhopital"]
    body = generate_plan(client, [kp_id]).json()
    plan_id = body["plan_id"]
    for index, item in enumerate(items_by_ordinal(body).values(), start=1):
        assert assess(client, item["id"], "mastered", f"ap-key-{index:04d}").status_code == 200

    # 先确认这张卷确实已完成。
    assert client.get("/api/plans/today").json()["status"] == "completed"

    # 从另一个叶子的题库追加一道题。
    with session_factory() as db:
        other_leaf = leaves["math.calculus.series.geometric"]
        candidate = db.scalar(select(Question.id).where(Question.kp_id == other_leaf))

    appended = client.post(
        f"/api/plans/{plan_id}/questions", json={"question_ids": [str(candidate)]}
    )
    assert appended.status_code == 200
    after = appended.json()
    # 计划回到进行中，新题在卷尾。
    assert after["status"] == "active"
    assert after["total_count"] == body["total_count"] + 1
    assert after["completed_count"] == body["total_count"]
    assert after["items"][-1]["question_id"] == str(candidate)
    assert after["focus_item_id"] == after["items"][-1]["id"]

    with session_factory() as db:
        plan = db.get(DailyPlan, UUID(plan_id))
        assert plan is not None
        # 数据库状态与接口返回一致，不再出现“库说 completed、接口说 active”。
        assert plan.status == "active"


# --------------------------------------------------------------------------- #
# 自述记录边界：跨天、变式题和节点自述均不产生确认
# --------------------------------------------------------------------------- #


def test_completing_all_items_by_self_report_does_not_confirm_mastery(
    client: TestClient, session_factory, clock
) -> None:
    """自述完成可以记录练习进度，但不是可靠独立作答证据。"""
    leaves = leaf_codes(session_factory)
    kp_id = leaves["math.calculus.limit.lhopital"]
    body = generate_plan(client, [kp_id]).json()
    ordered = items_by_ordinal(body)

    # 同一天内做完卷内全部题目。
    last = None
    for index, item in enumerate(ordered.values(), start=1):
        last = assess(client, item["id"], "mastered", f"span-key-{index:04d}")
        assert last.status_code == 200
    assert last is not None
    payload = last.json()
    assert payload["state"] == "unseen"
    assert payload["reason_code"] == "self_feedback_only"

    with session_factory() as db:
        state = db.get(KpState, kp_id)
        assert state is not None and state.state == "unseen"


def test_self_reports_across_three_days_do_not_graduate(
    client: TestClient, session_factory, clock
) -> None:
    """连续三天自行对照仍不形成客观确认、跨天证据或复测日期。"""
    leaves = leaf_codes(session_factory)
    kp_id = leaves["math.calculus.limit.lhopital"]
    body = generate_plan(client, [kp_id]).json()
    ordered = items_by_ordinal(body)

    # 第一天自述完成变式题和其他题，避免依赖组卷顺序。
    variant_id = next(item["id"] for item in body["items"] if item["is_variant"])
    others = [item["id"] for item in body["items"] if item["id"] != variant_id]
    first_day_ids = [variant_id, *others[:2]]
    for index, item_id in enumerate(first_day_ids, start=1):
        assert assess(client, item_id, "mastered", f"grad-key-{index:04d}").status_code == 200

    # 第二天继续自述完成，不产生确认。
    clock.now = DAY2
    generate_plan(client, [kp_id])
    second_day_item = redo_item(client, session_factory, position=1)
    still = assess(client, second_day_item, "mastered", "grad-key-9001")
    assert still.status_code == 200
    assert still.json()["state"] == "unseen"
    # 跨日期不会提升自述记录的证据强度。
    assert still.json()["reason_code"] == "self_feedback_only"

    # 第三天继续自述；仍不毕业。
    clock.now = DAY3
    generate_plan(client, [kp_id])
    third_day_item = redo_item(client, session_factory, position=1)
    final = assess(client, third_day_item, "mastered", "grad-key-9002")
    assert final.status_code == 200
    payload = final.json()
    assert payload["state"] == "unseen"
    assert payload["reason_code"] == "self_feedback_only"

    with session_factory() as db:
        state = db.get(KpState, kp_id)
        assert state is not None
        assert state.state == "unseen"
        assert state.mastered_at is None
        assert state.next_review_at is None

    # 知识树详情反映同一结果。
    detail = client.get(f"/api/knowledge/{kp_id}").json()["node"]
    assert detail["state"] == "unseen"
    assert detail["has_real_variant"] is False
    assert detail["day_span"] is None


def test_node_self_report_adds_no_base_credits(
    client: TestClient, session_factory
) -> None:
    leaves = leaf_codes(session_factory)
    kp_id = leaves["math.calculus.limit.lhopital"]

    response = client.post(
        f"/api/knowledge/{kp_id}/self-assessment",
        json={"self_grade": "mastered", "idempotency_key": "node-key-0001"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["manual_credit_count"] == 0
    assert payload["effective_confirmation_count"] == 0
    # 节点自述只更新辅助反馈，不进入毕业计数。
    assert payload["reason_code"] == "self_feedback_only"
    assert payload["state"] == "unseen"

    with session_factory() as db:
        # 绝不伪造 QuestionAttempt。
        assert db.scalar(select(QuestionAttempt)) is None
        state = db.get(KpState, kp_id)
        assert state is not None
        assert state.manual_credit_count == 0
        assert state.node_self_grade == "mastered"
        assert state.evidence_window == []
        # 审计事件只有一条，且没有 evidence_level（基础证据不进窗口）。
        events = db.scalars(select(LearningEvent)).all()
        assert len(events) == 1
        assert events[0].event_type == "node_self_reported"
        assert events[0].source_id is None
        assert events[0].evidence_level is None


def test_node_self_assessment_route_still_needs_real_questions(
    client: TestClient, session_factory, clock
) -> None:
    """节点与练习自述都不能替代可靠的独立正确作答。"""
    leaves = leaf_codes(session_factory)
    kp_id = leaves["math.calculus.limit.lhopital"]

    # 第一天节点整体自述熟悉，不写基础确认。
    first = client.post(
        f"/api/knowledge/{kp_id}/self-assessment",
        json={"self_grade": "mastered", "idempotency_key": "node-grad-0001"},
    )
    assert first.status_code == 200
    assert first.json()["manual_credit_count"] == 0
    assert first.json()["effective_confirmation_count"] == 0

    # 第三天生成练习卷；一道变式题远远不够（策略要求 4 个确认 + 4 道真实题 + 题型覆盖）。
    clock.now = DAY3
    body = generate_plan(client, [kp_id]).json()
    variant_item = next(item for item in body["items"] if item["is_variant"])
    partial = assess(client, variant_item["id"], "mastered", "node-grad-0002")
    assert partial.status_code == 200
    # 只做一道真实变式题时不能毕业。
    assert partial.json()["state"] == "unseen"
    assert partial.json()["manual_credit_count"] == 0

    # 自述完成其余题也不改变证据性质。
    last = partial
    remaining = [item for item in body["items"] if item["id"] != variant_item["id"]]
    for index, item in enumerate(remaining, start=10):
        last = assess(client, item["id"], "mastered", f"node-grad-{index:04d}")
        assert last.status_code == 200
    assert last.json()["state"] == "unseen"
    assert last.json()["reason_code"] == "self_feedback_only"
    assert last.json()["manual_credit_count"] == 0


def test_self_reports_do_not_create_confirmation_dates_or_day_span(
    client: TestClient, session_factory, clock
) -> None:
    """自述时间不能伪装成有效确认日期。"""
    leaves = leaf_codes(session_factory)
    kp_id = leaves["math.calculus.limit.lhopital"]

    # 第一天记录节点自述。
    assert client.post(
        f"/api/knowledge/{kp_id}/self-assessment",
        json={"self_grade": "mastered", "idempotency_key": "span-cal-0001"},
    ).status_code == 200

    # 第三天自述完成卷内题目。
    clock.now = DAY3
    body = generate_plan(client, [kp_id]).json()
    for index, item in enumerate(items_by_ordinal(body).values(), start=1):
        assert assess(client, item["id"], "mastered", f"span-cal-{index:04d}").status_code == 200

    node = client.get(f"/api/knowledge/{kp_id}").json()["node"]
    assert node["state"] == "unseen"
    # 两天跨度不是客观作答证据，因此确认日期仍为空。
    assert node["first_confirmed_on"] is None
    assert node["last_confirmed_on"] is None
    assert node["day_span"] is None
    assert node["manual_credit_count"] == 0


def test_node_partial_feedback_preserves_practice_history(
    client: TestClient, session_factory, clock
) -> None:
    leaves = leaf_codes(session_factory)
    kp_id = leaves["math.calculus.limit.lhopital"]

    assert client.post(
        f"/api/knowledge/{kp_id}/self-assessment",
        json={"self_grade": "mastered", "idempotency_key": "node-part-0001"},
    ).status_code == 200

    body = generate_plan(client, [kp_id]).json()
    ordered = items_by_ordinal(body)
    assert assess(client, ordered[1]["id"], "mastered", "node-part-0002").status_code == 200

    partial = client.post(
        f"/api/knowledge/{kp_id}/self-assessment",
        json={"self_grade": "partial", "idempotency_key": "node-part-0003"},
    )
    assert partial.status_code == 200
    payload = partial.json()
    assert payload["manual_credit_count"] == 0
    # 练习自述记录不进入确认窗口。
    assert payload["effective_confirmation_count"] == 0
    assert payload["state"] == "unseen"

    with session_factory() as db:
        state = db.get(KpState, kp_id)
        assert state is not None
        assert state.manual_credit_count == 0
        assert state.manual_confirmed_at is None
        assert len(state.evidence_window) == 0
        # 其余练习历史不受影响。
        assert len(db.scalars(select(QuestionAttempt)).all()) == 1


def test_node_not_mastered_feedback_does_not_reset_mastery(
    client: TestClient, session_factory
) -> None:
    leaves = leaf_codes(session_factory)
    kp_id = leaves["math.calculus.limit.lhopital"]

    assert client.post(
        f"/api/knowledge/{kp_id}/self-assessment",
        json={"self_grade": "mastered", "idempotency_key": "node-stuck-0001"},
    ).status_code == 200
    body = generate_plan(client, [kp_id]).json()
    ordered = items_by_ordinal(body)
    assert assess(client, ordered[1]["id"], "mastered", "node-stuck-0002").status_code == 200

    stuck = client.post(
        f"/api/knowledge/{kp_id}/self-assessment",
        json={"self_grade": "not_mastered", "idempotency_key": "node-stuck-0003"},
    )
    assert stuck.status_code == 200
    payload = stuck.json()
    assert payload["state"] == "unseen"
    assert payload["reason_code"] == "self_feedback_only"
    assert payload["manual_credit_count"] == 0
    assert payload["effective_confirmation_count"] == 0

    with session_factory() as db:
        state = db.get(KpState, kp_id)
        assert state is not None
        assert state.state == "unseen"
        assert state.evidence_window == []
        # 既往练习历史保留。
        assert len(db.scalars(select(QuestionAttempt)).all()) == 1


def test_node_self_assessment_is_idempotent_by_key(
    client: TestClient, session_factory
) -> None:
    leaves = leaf_codes(session_factory)
    kp_id = leaves["math.calculus.limit.lhopital"]
    payload = {"self_grade": "mastered", "idempotency_key": "node-idem-0001"}

    first = client.post(f"/api/knowledge/{kp_id}/self-assessment", json=payload)
    second = client.post(f"/api/knowledge/{kp_id}/self-assessment", json=payload)
    assert first.status_code == second.status_code == 200
    # 重放不增加自述事件或基础确认。
    assert second.json()["manual_credit_count"] == 0

    with session_factory() as db:
        assert len(db.scalars(select(LearningEvent)).all()) == 1


def test_recommendation_reason_becomes_stuck_after_not_mastered(
    client: TestClient, session_factory, clock
) -> None:
    """未掌握的叶子在第二天的准备页里以 not_mastered 理由高优先级出现。"""
    leaves = leaf_codes(session_factory)
    kp_id = leaves["math.calculus.limit.lhopital"]
    body = generate_plan(client, [kp_id]).json()
    assert assess(client, items_by_ordinal(body)[1]["id"], "not_mastered", "rec-key-0001").status_code == 200

    clock.now = DAY2
    today = client.get("/api/plans/today").json()
    assert today["status"] == "setup"
    target = next(item for item in today["recommendations"] if item["kp_id"] == str(kp_id))
    assert target["reason"] == "not_mastered"
    assert target["state"] == "unseen"
    # 明确未掌握的优先级高于纯未学习。
    assert today["recommendations"][0]["reason"] in {"not_mastered", "overdue_review"}


# --------------------------------------------------------------------------- #
# 旧自评入口不得冒充经过核验的机器判分
# --------------------------------------------------------------------------- #


def test_self_report_endpoint_does_not_grade_selected_options(
    client: TestClient, session_factory, clock
) -> None:
    """旧入口即使附带选项也只记录自述；可靠判题走答案提交服务。"""
    leaves = leaf_codes(session_factory)
    kp_id = leaves["math.calculus.limit.lhopital"]
    body = generate_plan(client, [kp_id]).json()
    ordered = items_by_ordinal(body)

    choice = next(item for item in ordered.values() if item["options"])
    correct = client.get(f"/api/practice-items/{choice['id']}/answer").json()["correct_answer"]
    assert correct, "种子数据的选择题必须有标准答案"

    # 故意选一个与正确答案不同的选项，仍自评「已掌握」。
    wrong_option = next(key for key in choice["options"] if key != correct)
    response = assess(client, choice["id"], "mastered", "obj-key-0001", selected_option=wrong_option)
    assert response.status_code == 200
    # 自述不会产生客观确认，也不会凭选项改掌握状态。
    assert response.json()["effective_confirmation_count"] == 0

    with session_factory() as db:
        attempt = db.scalar(select(QuestionAttempt))
        assert attempt is not None
        assert attempt.objective_result == "unknown"
        assert attempt.self_grade == "mastered"

    # 换一天选对也仍为 unknown，不能绕过可靠判题入口。
    clock.now = DAY2
    other_kp = leaves["math.linear-algebra.determinant.properties"]
    other_body = generate_plan(client, [other_kp]).json()
    other_choice = next(
        item for item in items_by_ordinal(other_body).values() if item["options"]
    )
    other_correct = client.get(
        f"/api/practice-items/{other_choice['id']}/answer"
    ).json()["correct_answer"]
    assert assess(
        client, other_choice["id"], "partial", "obj-key-0002", selected_option=other_correct
    ).status_code == 200

    with session_factory() as db:
        results = {
            attempt.question_id: attempt.objective_result
            for attempt in db.scalars(select(QuestionAttempt)).all()
        }
    assert sorted(results.values()) == ["unknown", "unknown"]


def test_non_choice_question_keeps_objective_result_unknown(
    client: TestClient, session_factory
) -> None:
    """填空题等无法可靠机器判分的题型必须保持 unknown，不能用猜测冒充判分。"""
    leaves = leaf_codes(session_factory)
    kp_id = leaves["math.calculus.limit.lhopital"]
    body = generate_plan(client, [kp_id]).json()
    fill_blank = next(
        item for item in items_by_ordinal(body).values() if item["options"] is None
    )
    # 即使把标准答案原样填进 raw_answer，也不做机器判分。
    correct = client.get(f"/api/practice-items/{fill_blank['id']}/answer").json()["correct_answer"]
    response = assess(
        client, fill_blank["id"], "mastered", "obj-key-0003", raw_answer=correct
    )
    assert response.status_code == 200

    with session_factory() as db:
        attempt = db.scalar(select(QuestionAttempt))
        assert attempt is not None
        assert attempt.objective_result == "unknown"
        assert attempt.raw_answer == correct
