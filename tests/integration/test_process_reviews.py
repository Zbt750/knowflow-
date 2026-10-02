from uuid import UUID

import pytest
from sqlalchemy import delete, func, select

from backend.api.routes import study as study_routes
from backend.errors import AppError
from backend.models.learning import DailyPlan, KpState, LearningEvent, PracticeItem, Question, QuestionAttempt
from backend.services.process_review_service import EVENT_TYPE
from backend.services.process_review_service import _review_admission
from tests.integration.test_learning_loop import client, clock, clean_database, session_factory


class FakeProvider:
    model = "synthetic-review-provider"

    def __init__(self, *, fail: bool = False):
        self.calls = 0
        self.prompts = []
        self.fail = fail

    def complete(self, messages, *, attempt=1):
        self.calls += 1
        self.prompts.append(messages)
        if self.fail:
            raise AppError("generation_failed", retryable=False)
        return "先核对变形所需的条件；你写出的中间式还需要说明分母在邻域内不为零。", {"total_tokens": 25}


@pytest.fixture(autouse=True)
def cleanup_review_records(session_factory, clean_database):
    yield
    with session_factory() as db:
        for model in (QuestionAttempt, LearningEvent, PracticeItem, DailyPlan):
            db.execute(delete(model))
        db.commit()


@pytest.fixture
def calculation_item(session_factory):
    with session_factory() as db:
        question = db.scalar(select(Question).where(Question.stem.like("计算 lim(x->1) (x^2 - 1)%")))
        assert question is not None
        plan = DailyPlan(study_date="2026-01-01", status="active")
        db.add(plan)
        db.flush()
        item = PracticeItem(plan_id=plan.id, question_id=question.id, kp_id=question.kp_id, ordinal=1)
        db.add(item)
        db.commit()
        return str(item.id)


def review(client, item_id, *, key="process-review-key-0001", work="我先对分子分母分别求导，再计算新分式的极限。"):
    return client.post(f"/api/practice-items/{item_id}/process-reviews", json={
        "idempotency_key": key, "work_text": work,
    })


def test_text_review_is_idempotent_and_only_marks_later_answer_as_assisted(
    client, calculation_item, session_factory, monkeypatch,
):
    provider = FakeProvider()
    monkeypatch.setattr(study_routes, "provider_from_settings", lambda _settings: provider)

    latest_url = f"/api/practice-items/{calculation_item}/process-reviews/latest"
    assert client.get(latest_url).json() is None
    first = review(client, calculation_item)
    assert first.status_code == 200, first.text
    payload = first.json()
    assert payload["review_kind"] == "calculation"
    assert payload["changes_mastery"] is False and payload["is_final_grade"] is False
    assert client.get(latest_url).json() == payload
    assert review(client, calculation_item).json()["review_id"] == payload["review_id"]
    assert provider.calls == 1
    conflict = review(client, calculation_item, work="我换一个思路，先将分子因式分解再约分计算。")
    assert conflict.status_code == 409
    assert provider.calls == 1
    with session_factory() as db:
        item = db.get(PracticeItem, UUID(calculation_item))
        assert item.completed_at is None
        assert db.get(KpState, item.kp_id).state == "unseen"
        event = db.scalar(select(LearningEvent).where(LearningEvent.event_type == EVENT_TYPE))
        assert event.source_id == item.id and event.payload["raw_work_stored"] is False
        assert "我先对分子分母" not in str(event.payload)
        assert db.scalar(select(func.count()).select_from(LearningEvent)) == 1

    submitted = client.post(f"/api/practice-items/{calculation_item}/answer-submissions", json={
        "idempotency_key": "answer-after-review-0001", "raw_answer": "2",
    })
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["assisted"] is True
    assert submitted.json()["effective_confirmation_count"] == 0


def test_review_rejects_choice_without_model_call(client, calculation_item, session_factory, monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr(study_routes, "provider_from_settings", lambda _settings: provider)
    with session_factory() as db:
        choice = db.scalar(select(Question).where(Question.question_type == "single_choice"))
        item = db.get(PracticeItem, UUID(calculation_item))
        item.question_id = choice.id
        item.kp_id = choice.kp_id
        db.commit()
    response = review(client, calculation_item)
    assert response.status_code == 409
    assert provider.calls == 0


def test_provider_failure_does_not_record_assistance(client, calculation_item, session_factory, monkeypatch):
    provider = FakeProvider(fail=True)
    monkeypatch.setattr(study_routes, "provider_from_settings", lambda _settings: provider)
    response = review(client, calculation_item)
    assert response.status_code == 503
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(LearningEvent)) == 0


def test_busy_response_is_safe_and_retry_is_available(client, calculation_item, session_factory, monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr(study_routes, "provider_from_settings", lambda _settings: provider)
    with _review_admission(UUID(calculation_item), "other-tab"):
        response = review(client, calculation_item)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "process_review_busy"
        assert provider.calls == 0
        with session_factory() as db:
            assert db.scalar(select(func.count()).select_from(LearningEvent)) == 0
    response = review(client, calculation_item)
    assert response.status_code == 200
    assert provider.calls == 1


@pytest.mark.parametrize("question_type,kind,expected", [("proof", None, "proof"), ("subjective", "algorithm", "algorithm"), ("subjective", "concept", "concept")])
def test_open_question_review_does_not_supply_hidden_solution(client, calculation_item, session_factory, monkeypatch, question_type, kind, expected):
    provider = FakeProvider()
    monkeypatch.setattr(study_routes, "provider_from_settings", lambda _settings: provider)
    with session_factory.begin() as db:
        item = db.get(PracticeItem, UUID(calculation_item))
        item.question.question_type = question_type
    response = client.post(f"/api/practice-items/{calculation_item}/process-reviews", json={
        "idempotency_key": "open-review-test-0001", "work_text": "我先写出需要满足的前提，再检查每一步是否成立。", "subjective_kind": kind,
    })
    assert response.status_code == 200, response.text
    assert response.json()["review_kind"] == expected
    import json
    prompt_data = json.loads(provider.prompts[0][1]["content"])
    assert prompt_data["已查看的参考解析"] is None
