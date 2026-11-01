"""Persistent personal training flow; requires the guarded isolated PostgreSQL fixture."""
from uuid import UUID, uuid4
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.api.deps import get_time_provider
from backend.api.routes.personal_trainings import router as training_router
from backend.errors import register_error_handlers
from backend.models.chat import ChatSession
from backend.models.learning import DailyPlan, KnowledgePoint, KpState, PracticeItem, Question, QuestionAttempt, QuestionVersion
from backend.models.personal_generation import PersonalGenerationBatch
from backend.models.personal_training import PersonalTraining, PersonalTrainingAttempt, PersonalTrainingItem
from tests.integration.test_generation_confirmation_recovery import generation_fixture
from tests.integration.test_learning_loop import mark_isolated_question_trusted

NOW = datetime(2026, 10, 30, 2, tzinfo=timezone.utc)


def _app(factory):
    app = FastAPI()
    app.include_router(training_router, prefix="/api")
    register_error_handlers(app)
    app.state.session_factory = factory
    app.dependency_overrides[get_time_provider] = lambda: lambda: NOW
    return app


@pytest.fixture
def training_bank(generation_fixture):
    factory, _schema, kp_id, _qa_session_id, _model = generation_fixture
    with factory.begin() as db:
        owner = ChatSession(title="TEST_FIXTURE personal training owner", mode="builtin", purpose="study")
        db.add(owner)
        db.flush()
        for index in range(8):
            row = Question(
                kp_id=kp_id,
                stem=f"TEST_FIXTURE: 计算第 {index + 1} 题的正确选项。",
                question_type="single_choice",
                grading_mode="objective",
                grading_config={"verified": True, "method": "single_choice"},
                options={"A": "2", "B": "3", "C": "4", "D": "5"},
                correct_answer="A",
                explanation="TEST_FIXTURE: 根据题设逐步计算得到选项 A。",
                estimated_minutes=5,
                difficulty="basic",
                question_provenance="trusted_practice",
                content_trust="verified",
                source_status="not_applicable",
                answer_provenance="human_verified",
                answer_reliability="verified",
            )
            mark_isolated_question_trusted(row, db=db)
        owner_id = owner.id
    return factory, kp_id, owner_id


def test_independent_training_create_answer_pause_resume_append_report_and_next_round(training_bank):
    factory, kp_id, owner_id = training_bank
    initial_question_attempts = 0
    with TestClient(_app(factory)) as client:
        created_response = client.post("/api/practice-trainings", json={
            "owner_session_id": str(owner_id), "request_key": "TEST_FIXTURE-training-create-0001",
            "title": "TEST_FIXTURE 洛必达专项", "knowledge_point_ids": [str(kp_id)],
            "question_count": 2, "target_minutes": 30, "difficulty": "any",
            "question_type": "single_choice", "basis": "selected",
        })
        assert created_response.status_code == 201, created_response.text
        created = created_response.json()
        assert created["status"] == "active" and created["item_count"] == 2
        original_bindings = [(row["question_id"], row["question_version_id"]) for row in created["items"]]
        assert all(version_id for _, version_id in original_bindings)

        listed = client.get(f"/api/practice-trainings?owner_session_id={owner_id}")
        assert listed.status_code == 200 and [row["training_id"] for row in listed.json()] == [created["training_id"]]
        reloaded = client.get(f"/api/practice-trainings/{created['training_id']}?owner_session_id={owner_id}")
        assert [(row["question_id"], row["question_version_id"]) for row in reloaded.json()["items"]] == original_bindings

        first_item = reloaded.json()["items"][0]
        draft = client.patch(f"/api/practice-trainings/{created['training_id']}/items/{first_item['item_id']}/draft", json={
            "owner_session_id": str(owner_id), "expected_draft_revision": 0,
            "draft_answer": None, "draft_selected_option": "B",
        })
        assert draft.status_code == 200, draft.text
        assert draft.json()["items"][0]["draft_selected_option"] == "B"
        assert draft.json()["items"][0]["draft_revision"] == 1
        draft_refresh = client.get(f"/api/practice-trainings/{created['training_id']}?owner_session_id={owner_id}")
        assert draft_refresh.json()["items"][0]["draft_selected_option"] == "B"
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(PersonalTrainingAttempt)) == 0
            assert db.scalar(select(func.count()).select_from(QuestionAttempt)) == initial_question_attempts

        pause_body = {"owner_session_id": str(owner_id), "request_key": "TEST_FIXTURE-training-pause-0001",
            "expected_version": created["version"]}
        paused = client.post(f"/api/practice-trainings/{created['training_id']}/pause", json=pause_body)
        assert paused.status_code == 200 and paused.json()["status"] == "paused"
        paused_replay = client.post(f"/api/practice-trainings/{created['training_id']}/pause", json=pause_body)
        assert paused_replay.json()["version"] == paused.json()["version"]

        resume_body = {"owner_session_id": str(owner_id), "request_key": "TEST_FIXTURE-training-resume-0001",
            "expected_version": paused.json()["version"]}
        active = client.post(f"/api/practice-trainings/{created['training_id']}/resume", json=resume_body)
        assert active.status_code == 200 and active.json()["status"] == "active"

        appended = client.post(f"/api/practice-trainings/{created['training_id']}/items", json={
            "owner_session_id": str(owner_id), "request_key": "TEST_FIXTURE-training-append-0001",
            "expected_version": active.json()["version"], "question_count": 1,
        })
        assert appended.status_code == 200 and appended.json()["item_count"] == 3
        all_question_ids = [item["question_id"] for item in appended.json()["items"]]
        assert len(all_question_ids) == len(set(all_question_ids)) == 3
        assert [(item["question_id"], item["question_version_id"]) for item in appended.json()["items"][:2]] == original_bindings

        first, second, third = appended.json()["items"]
        blank = client.post(f"/api/practice-trainings/{created['training_id']}/items/{first['item_id']}/answers", json={
            "owner_session_id": str(owner_id), "idempotency_key": "TEST_FIXTURE-training-answer-blank-0001",
            "expected_version": appended.json()["version"], "raw_answer": None, "selected_option": None,
        })
        assert blank.status_code == 422
        assert blank.json()["error"]["code"] == "selected_option_required"
        wrong = client.post(f"/api/practice-trainings/{created['training_id']}/items/{first['item_id']}/answers", json={
            "owner_session_id": str(owner_id), "idempotency_key": "TEST_FIXTURE-training-answer-wrong-0001",
            "expected_version": appended.json()["version"], "raw_answer": None, "selected_option": "B",
        })
        assert wrong.status_code == 200 and wrong.json()["items"][0]["latest_result"] == "wrong"
        assert wrong.json()["items"][0]["draft_selected_option"] is None
        wrong_replay = client.post(f"/api/practice-trainings/{created['training_id']}/items/{first['item_id']}/answers", json={
            "owner_session_id": str(owner_id), "idempotency_key": "TEST_FIXTURE-training-answer-wrong-0001",
            "expected_version": appended.json()["version"], "raw_answer": None, "selected_option": "B",
        })
        assert wrong_replay.status_code == 200

        right = client.post(f"/api/practice-trainings/{created['training_id']}/items/{second['item_id']}/answers", json={
            "owner_session_id": str(owner_id), "idempotency_key": "TEST_FIXTURE-training-answer-right-0001",
            "expected_version": wrong.json()["version"], "raw_answer": None, "selected_option": "A",
        })
        third_wrong = client.post(f"/api/practice-trainings/{created['training_id']}/items/{third['item_id']}/answers", json={
            "owner_session_id": str(owner_id), "idempotency_key": "TEST_FIXTURE-training-answer-wrong-0002",
            "expected_version": right.json()["version"], "raw_answer": None, "selected_option": "D",
        })
        assert third_wrong.status_code == 200
        active_next = client.post(f"/api/practice-trainings/{created['training_id']}/next", json={
            "owner_session_id": str(owner_id), "request_key": "TEST_FIXTURE-training-next-too-early-0001",
            "question_count": 1, "target_minutes": 10,
        })
        assert active_next.status_code == 409

        finished = client.post(f"/api/practice-trainings/{created['training_id']}/finish", json={
            "owner_session_id": str(owner_id), "request_key": "TEST_FIXTURE-training-finish-0001",
            "expected_version": third_wrong.json()["version"],
        })
        assert finished.status_code == 200 and finished.json()["status"] == "completed"
        report = client.get(f"/api/practice-trainings/{created['training_id']}/report?owner_session_id={owner_id}")
        assert report.status_code == 200
        assert (report.json()["submitted_count"], report.json()["wrong_count"], report.json()["right_count"]) == (3, 2, 1)
        assert report.json()["wrong_knowledge_points"][0]["kp_id"] == str(kp_id)

        next_round = client.post(f"/api/practice-trainings/{created['training_id']}/next", json={
            "owner_session_id": str(owner_id), "request_key": "TEST_FIXTURE-training-next-0001",
            "question_count": 2, "target_minutes": 20,
        })
        assert next_round.status_code == 201, next_round.text
        next_payload = next_round.json()
        assert next_payload["adapted_from_training_id"] == created["training_id"]
        assert not (set(all_question_ids) & {item["question_id"] for item in next_payload["items"]})
        second_wrong = client.post(f"/api/practice-trainings/{next_payload['training_id']}/items/{next_payload['items'][0]['item_id']}/answers", json={
            "owner_session_id": str(owner_id), "idempotency_key": "TEST_FIXTURE-training-round2-wrong-0001",
            "expected_version": next_payload["version"], "raw_answer": None, "selected_option": "B",
        })
        assert second_wrong.status_code == 200
        second_finished = client.post(f"/api/practice-trainings/{next_payload['training_id']}/finish", json={
            "owner_session_id": str(owner_id), "request_key": "TEST_FIXTURE-training-round2-finish-0001",
            "expected_version": second_wrong.json()["version"],
        })
        assert second_finished.status_code == 200
        third_round = client.post(f"/api/practice-trainings/{next_payload['training_id']}/next", json={
            "owner_session_id": str(owner_id), "request_key": "TEST_FIXTURE-training-next-round3-0001",
            "question_count": 1, "target_minutes": 15,
        })
        assert third_round.status_code == 201, third_round.text
        third_payload = third_round.json()
        assert third_payload["adapted_from_training_id"] == next_payload["training_id"]
        assert not (set(all_question_ids) | {item["question_id"] for item in next_payload["items"]}) & {
            item["question_id"] for item in third_payload["items"]}
        replayed_third = client.post(f"/api/practice-trainings/{next_payload['training_id']}/next", json={
            "owner_session_id": str(owner_id), "request_key": "TEST_FIXTURE-training-next-round3-0001",
            "question_count": 1, "target_minutes": 15,
        })
        assert replayed_third.status_code == 201
        assert replayed_third.json()["training_id"] == third_payload["training_id"]
        # A second session cannot read or mutate this user's independent training.
        foreign_read = client.get(f"/api/practice-trainings/{created['training_id']}?owner_session_id={uuid4()}")
        assert foreign_read.status_code == 404

    with factory() as db:
        assert db.scalar(select(func.count()).select_from(PersonalTraining)) == 3
        assert db.scalar(select(func.count()).select_from(PersonalTrainingItem)) == 6
        assert db.scalar(select(func.count()).select_from(PersonalTrainingAttempt)) == 4
        assert db.scalar(select(func.count()).select_from(QuestionAttempt)) == initial_question_attempts
        assert db.scalar(select(func.count()).select_from(PersonalGenerationBatch)) == 0
        assert db.scalar(select(func.count()).select_from(DailyPlan)) == 0
        assert db.scalar(select(func.count()).select_from(PracticeItem)) == 0
        ids = [UUID(value) for value in all_question_ids]
        assert all(db.get(QuestionVersion, db.get(Question, value).current_version_id) for value in ids)


def test_chatpage_qa_session_can_create_and_control_independent_training(training_bank):
    """Real assistant stream commands execute the same session-owned training service."""
    import asyncio
    from backend.schemas.learning_assistant import AssistantRequest
    from backend.services.learning_assistant_service import assistant_stream

    factory, kp_id, _study_owner_id = training_bank
    with factory.begin() as db:
        node = db.get(__import__("backend.models.learning", fromlist=["KnowledgePoint"]).KnowledgePoint, kp_id)
        node.name = "TEST_FIXTURE 洛必达法则"
        owner = ChatSession(title="TEST_FIXTURE ChatPage training owner", mode="builtin", purpose="qa")
        db.add(owner); db.flush(); owner_id = owner.id

    async def turn(question: str):
        body = AssistantRequest(question=question, request_key=uuid4())
        frames = []
        async for frame in assistant_stream(factory, request=None, session_id=owner_id, body=body,
                stack=None, provider=None, now=NOW):
            frames.append(frame)
        return "".join(frames)

    create_frames = asyncio.run(turn("给我安排五道洛必达法则练习"))
    assert "event: personal_training" in create_frames
    assert "实际分配 5 道真实题库题" in create_frames
    with factory() as db:
        training = db.scalar(select(PersonalTraining).where(PersonalTraining.owner_session_id == owner_id))
        assert training is not None and training.status == "active"
        assert len(training.items) == 5
        training_id = training.id
        assert db.scalar(select(func.count()).select_from(DailyPlan)) == 0
    pause_frames = asyncio.run(turn("暂停当前专项"))
    assert "已暂停" in pause_frames
    with factory() as db:
        training = db.get(PersonalTraining, training_id)
        assert training.status == "paused"
    resume_frames = asyncio.run(turn("继续上次没做完的专项"))
    assert "已继续" in resume_frames
    query_frames = asyncio.run(turn("我现在有哪些专项"))
    assert "event: personal_training" in query_frames and str(training_id) in query_frames


def test_chat_ai_training_parser_preserves_compound_node_counts_and_types(training_bank):
    from backend.services.personal_training_chat import _make_ai_request, parse_training_command

    factory, _kp_id, owner_id = training_bank
    text = "给我生成三道洛必达法则单选题、两道隐函数求导填空题"
    command = parse_training_command(text)
    assert command is not None and command.action == "ai_create"
    with factory.begin() as db:
        lhopital = KnowledgePoint(code="TEST_FIXTURE.training_chat.lhopital", name="洛必达法则",
            subject="考研数学", is_active=True, is_assessable=True, is_reference_only=False)
        implicit = KnowledgePoint(code="TEST_FIXTURE.training_chat.implicit", name="隐函数求导",
            subject="考研数学", is_active=True, is_assessable=True, is_reference_only=False)
        db.add_all([lhopital, implicit]); db.flush()
        db.add_all([KpState(kp_id=lhopital.id), KpState(kp_id=implicit.id)])
        request = _make_ai_request(db, text=text, owner_session_id=owner_id, current=None,
            context=SimpleNamespace(question_id=None), request_key=uuid4(), command=command)
        assert [(str(target.kp_id), target.count, target.question_type) for target in request.targets] == [
            (str(lhopital.id), 3, "single_choice"),
            (str(implicit.id), 2, "fill_blank"),
        ]
        assert sum(target.count for target in request.targets) == 5
        assert request.append_to_today is False and request.plan_id is None


def test_ai_training_from_recent_mistakes_uses_real_wrong_scope_not_active_training_scope(training_bank):
    from types import SimpleNamespace
    from backend.services.personal_training_chat import _make_ai_request, parse_training_command
    from backend.services.personal_training_service import create_training, submit_training_answer

    factory, current_kp_id, owner_id = training_bank
    with factory.begin() as db:
        active = create_training(db, owner_session_id=owner_id, request_key="TEST_FIXTURE-active-topic-0001",
            title="TEST_FIXTURE active unrelated topic", kp_ids=[current_kp_id], question_count=1,
            target_minutes=10, difficulty="any", question_type="single_choice",
            selection_basis="selected", now=NOW)

        weak_kp = KnowledgePoint(code="TEST_FIXTURE.training_recent_mistake.implicit",
            name="TEST_FIXTURE 隐函数求导", subject="考研数学", is_active=True,
            is_assessable=True, is_reference_only=False)
        db.add(weak_kp)
        db.flush()
        question = Question(kp_id=weak_kp.id,
            stem="TEST_FIXTURE: 根据隐函数关系求导。", question_type="single_choice",
            grading_mode="objective", grading_config={"verified": True, "method": "single_choice"},
            options={"A": "2", "B": "3", "C": "4", "D": "5"}, correct_answer="A",
            explanation="TEST_FIXTURE: 通过隐式求导得到选项 A。", estimated_minutes=5,
            difficulty="basic", question_provenance="trusted_practice", content_trust="verified",
            source_status="not_applicable", answer_provenance="human_verified", answer_reliability="verified")
        mark_isolated_question_trusted(question, db=db)
        mistake_training = create_training(db, owner_session_id=owner_id,
            request_key="TEST_FIXTURE-real-mistake-topic-0001", title="TEST_FIXTURE actual weak topic",
            kp_ids=[weak_kp.id], question_count=1, target_minutes=10, difficulty="any",
            question_type="single_choice", selection_basis="selected", now=NOW)
        item_id = UUID(mistake_training["items"][0]["item_id"])
        wrong_result = submit_training_answer(db, training_id=UUID(mistake_training["training_id"]),
            item_id=item_id, owner_session_id=owner_id,
            idempotency_key="TEST_FIXTURE-real-mistake-answer-0001",
            expected_version=mistake_training["version"], raw_answer=None, selected_option="B", now=NOW)
        assert wrong_result["items"][0]["latest_result"] == "wrong"

        current = db.get(PersonalTraining, UUID(active["training_id"]))
        command = parse_training_command("根据最近错题生成五道AI练习题")
        assert command is not None and command.action == "ai_create" and command.recent_mistakes
        request = _make_ai_request(db, text="根据最近错题生成五道AI练习题",
            owner_session_id=owner_id, current=current,
            context=SimpleNamespace(question_id=None), request_key=uuid4(), command=command)
        assert sum(target.count for target in request.targets) == 5
        assert {target.kp_id for target in request.targets} == {weak_kp.id}
        assert request.append_to_today is False and request.plan_id is None


def test_invalid_owner_or_no_real_mistake_evidence_does_not_create_training(training_bank):
    factory, kp_id, owner_id = training_bank
    with TestClient(_app(factory)) as client:
        with factory.begin() as db:
            other_owner = ChatSession(title="TEST_FIXTURE other training owner", mode="builtin", purpose="study")
            db.add(other_owner)
            db.flush()
            other_owner_id = other_owner.id
        other = client.post("/api/practice-trainings", json={
            "owner_session_id": str(other_owner_id), "request_key": "TEST_FIXTURE-other-owner-create-0001",
            "title": "TEST_FIXTURE other user's training", "knowledge_point_ids": [str(kp_id)],
            "question_count": 1, "target_minutes": 10, "difficulty": "any",
            "question_type": "single_choice", "basis": "selected",
        })
        assert other.status_code == 201, other.text
        other_item = other.json()["items"][0]
        other_wrong = client.post(f"/api/practice-trainings/{other.json()['training_id']}/items/{other_item['item_id']}/answers", json={
            "owner_session_id": str(other_owner_id), "idempotency_key": "TEST_FIXTURE-other-owner-wrong-0001",
            "expected_version": other.json()["version"], "raw_answer": None, "selected_option": "B",
        })
        assert other_wrong.status_code == 200

        response = client.post("/api/practice-trainings", json={
            "owner_session_id": str(owner_id), "request_key": "TEST_FIXTURE-training-no-errors-0001",
            "title": "TEST_FIXTURE recent errors", "knowledge_point_ids": [str(kp_id)],
            "question_count": 1, "target_minutes": 15, "difficulty": "any",
            "question_type": "single_choice", "basis": "recent_mistakes",
        })
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "personal_training_recent_mistakes_unavailable"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(PersonalTraining)) == 1
        saved = db.scalar(select(PersonalTraining))
        assert saved is not None and saved.owner_session_id != owner_id
        assert db.scalar(select(func.count()).select_from(PersonalTrainingAttempt)) == 1
