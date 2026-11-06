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


def _personal_training_contract_counts(factory):
    with factory() as db:
        return {
            'trainings':db.scalar(select(func.count()).select_from(PersonalTraining)),
            'items':db.scalar(select(func.count()).select_from(PersonalTrainingItem)),
            'training_attempts':db.scalar(select(func.count()).select_from(PersonalTrainingAttempt)),
            'generation_batches':db.scalar(select(func.count()).select_from(PersonalGenerationBatch)),
            'daily_plans':db.scalar(select(func.count()).select_from(DailyPlan)),
            'practice_items':db.scalar(select(func.count()).select_from(PracticeItem)),
            'question_attempts':db.scalar(select(func.count()).select_from(QuestionAttempt)),
        }


def test_independent_training_create_answer_pause_resume_append_report_and_next_round(training_bank):
    """Legacy lifecycle URL stays disabled and cannot mutate learning or training rows."""
    factory,kp_id,owner_id=training_bank
    before=_personal_training_contract_counts(factory)
    with TestClient(_app(factory)) as client:
        response=client.post("/api/practice-trainings",json={
            "owner_session_id":str(owner_id),"request_key":"TEST_FIXTURE-disabled-lifecycle-0001",
            "title":"TEST_FIXTURE 洛必达专项","knowledge_point_ids":[str(kp_id)],
            "question_count":2,"target_minutes":30,"difficulty":"any",
            "question_type":"single_choice","basis":"selected"})
        assert response.status_code==409,response.text
        assert response.json()['error']['code']=='personal_training_disabled'
        listing=client.get(f"/api/practice-trainings?owner_session_id={owner_id}")
        assert listing.status_code==409 and listing.json()['error']['code']=='personal_training_disabled'
    assert _personal_training_contract_counts(factory)==before


def test_chatpage_qa_session_can_create_and_control_independent_training(training_bank):
    """A disabled ChatPage command cannot create a training from a QA session."""
    import asyncio
    from backend.schemas.learning_assistant import AssistantRequest
    from backend.services.learning_assistant_service import assistant_stream
    from backend.services.personal_training_chat import parse_training_command
    factory,_kp_id,_study_owner_id=training_bank
    with factory.begin() as db:
        owner=ChatSession(title="TEST_FIXTURE ChatPage disabled training owner",mode="builtin",purpose="qa")
        db.add(owner);db.flush();owner_id=owner.id
    question="给我安排五道洛必达法则练习"
    assert parse_training_command(question) is None
    before=_personal_training_contract_counts(factory)
    async def turn(text):
        body=AssistantRequest(question=text,request_key=uuid4())
        frames=[]
        async for frame in assistant_stream(factory,request=None,session_id=owner_id,body=body,
                stack=None,provider=None,now=NOW):
            frames.append(frame)
        return "".join(frame.decode('utf-8') if isinstance(frame,bytes) else frame for frame in frames)
    wire=asyncio.run(turn(question))
    assert 'event: personal_training' not in wire
    assert _personal_training_contract_counts(factory)==before


def test_chat_ai_training_parser_preserves_compound_node_counts_and_types(training_bank):
    """The formerly public compound AI-training parser remains disabled."""
    from backend.services.personal_training_chat import parse_training_command
    command=parse_training_command("给我生成三道洛必达法则单选题、两道隐函数求导填空题")
    assert command is None


def test_ai_training_from_recent_mistakes_uses_real_wrong_scope_not_active_training_scope(training_bank):
    """A real wrong attempt does not make the disabled AI-training chat command callable."""
    from backend.services.personal_training_chat import parse_training_command
    from backend.services.personal_training_service import create_training,submit_training_answer
    factory,kp_id,owner_id=training_bank
    with factory.begin() as db:
        training=create_training(db,owner_session_id=owner_id,request_key="TEST_FIXTURE-real-mistake-setup-01",
            title="TEST_FIXTURE recent-mistake history",kp_ids=[kp_id],question_count=1,
            target_minutes=10,difficulty="any",question_type="single_choice",selection_basis="selected",now=NOW)
        item=training['items'][0]
        result=submit_training_answer(db,training_id=UUID(training['training_id']),item_id=UUID(item['item_id']),
            owner_session_id=owner_id,idempotency_key="TEST_FIXTURE-real-mistake-setup-answer-01",
            expected_version=training['version'],raw_answer=None,selected_option="B",now=NOW)
        assert result['items'][0]['latest_result']=='wrong'
    before=_personal_training_contract_counts(factory)
    assert before['trainings']==1 and before['training_attempts']==1
    assert parse_training_command("根据最近错题生成五道AI练习题") is None
    assert _personal_training_contract_counts(factory)==before


def test_invalid_owner_or_no_real_mistake_evidence_does_not_create_training(training_bank):
    """Disabled create guard rejects both owner scopes and leaves history untouched."""
    factory,kp_id,owner_id=training_bank
    with factory.begin() as db:
        other=ChatSession(title="TEST_FIXTURE other disabled owner",mode="builtin",purpose="study")
        db.add(other);db.flush();other_id=other.id
    before=_personal_training_contract_counts(factory)
    with TestClient(_app(factory)) as client:
        for session_id,key,basis in ((other_id,'TEST_FIXTURE-disabled-foreign-01','selected'),
                (owner_id,'TEST_FIXTURE-disabled-owner-01','recent_mistakes')):
            response=client.post("/api/practice-trainings",json={
                "owner_session_id":str(session_id),"request_key":key,
                "title":"TEST_FIXTURE disabled request","knowledge_point_ids":[str(kp_id)],
                "question_count":1,"target_minutes":10,"difficulty":"any",
                "question_type":"single_choice","basis":basis})
            assert response.status_code==409,response.text
            assert response.json()['error']['code']=='personal_training_disabled'
    assert _personal_training_contract_counts(factory)==before
