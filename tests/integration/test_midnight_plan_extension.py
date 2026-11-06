"""Shanghai midnight regression; real APIs and owned PostgreSQL, no model fees."""
from datetime import datetime, timezone
import json
from uuid import UUID
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from backend.api.deps import get_time_provider
from backend.api.routes.study import router as study_router
from backend.api.routes.personal_questions import router as personal_router
from backend.api.routes.chat import router as chat_router
from backend.errors import register_error_handlers
from backend.models.learning import KnowledgePoint, KpState, KpMasteryPolicy, Question, QuestionVersion, PracticeItem, DailyPlan, LearningEvent, QuestionAttempt
from backend.schemas.personal_questions import PersonalGenerationRequest, GenerationTarget
from backend.services.personal_question_service import run_generation
from scripts.run_question_repair_pilot import isolated_factory
from tests.integration.test_learning_loop import mark_isolated_question_trusted
from tests.integration.test_personal_general_generation import GeneralModel

BEFORE = datetime(2026, 10, 18, 15, 59, tzinfo=timezone.utc)
AFTER = datetime(2026, 10, 18, 16, 0, 2, tzinfo=timezone.utc)


@pytest.fixture
def midnight_bank(test_database_url):
    with isolated_factory(test_database_url) as (factory, _):
        with factory.begin() as db:
            node = KnowledgePoint(code="TEST_FIXTURE.midnight.series", name="级数求和（午夜隔离测试）", subject="考研数学", is_active=True, is_assessable=True)
            db.add(node); db.flush(); kp = node.id
            db.add_all([KpState(kp_id=kp), KpMasteryPolicy(kp_id=kp, policy_version=1,
                min_confirmations=1, min_real_questions=1, required_question_types={"single_choice":1}, required_variant_count=0)])
            for index in range(3):
                q = Question(kp_id=kp, stem=f"隔离练习{index}：首项为2、公比为1/2的等比级数求和。", question_type="single_choice",
                    options={"A":"4","B":"3","C":"2","D":"1"}, correct_answer="A", explanation="使用等比级数求和公式：2/(1-1/2)=4。", grading_mode="single_choice", grading_config={"verified":True,"method":"single_choice"}, skill_tags=["级数求和"])
                mark_isolated_question_trusted(q, db=db)
        now = [BEFORE]
        app = FastAPI(); register_error_handlers(app)
        app.include_router(study_router, prefix="/api"); app.include_router(personal_router, prefix="/api")
        app.include_router(chat_router, prefix="/api")
        app.state.session_factory = factory
        from types import SimpleNamespace
        app.state.settings = SimpleNamespace(app_env="test", capture_test_evidence=False)
        app.dependency_overrides[get_time_provider] = lambda: lambda: now[0]
        with TestClient(app) as client:
            yield factory, client, now, kp


def personal(factory, kp, now):
    from uuid import uuid4
    class MidnightModel(GeneralModel):
        def complete(self, messages, *, attempt=1):
            raw,usage=super().complete(messages,attempt=attempt)
            data=json.loads(raw)
            first=2 if now==BEFORE else 3
            data.update(stem=f'SYNTHETIC 午夜测试：等比级数首项为{first}、公比为1/2，求其和。',
                correct_answer=str(first*2),final_value=str(first*2),
                explanation=f'公比绝对值小于1，和为{first}/(1-1/2)={first*2}。')
            return json.dumps(data,ensure_ascii=False),usage
    result = run_generation(factory, PersonalGenerationRequest(request_key=uuid4(), generation_mode="ai_generated",
        targets=[GenerationTarget(kp_id=kp, question_type="calculation", count=1)]), MidnightModel(), now=now)
    assert len(result["question_ids"]) == 1, result
    return result["question_ids"][0]


def test_generate_2359_keeps_yesterday_and_freezes_today_after_materialization(midnight_bank):
    factory, client, now, kp = midnight_bank
    yesterday = client.post('/api/plans/today/generate', json={"selected_kp_ids":[str(kp)]})
    assert yesterday.status_code == 201, yesterday.text
    old = yesterday.json()
    question_id = personal(factory, kp, BEFORE)
    now[0] = AFTER
    assert client.get('/api/plans/today').json()["status"] == "setup"
    rejected = client.post('/api/personal-questions/append', json={"question_ids":[question_id],"plan_id":old["plan_id"]})
    assert rejected.status_code == 409 and rejected.json()["error"]["code"] == "plan_not_today"
    added = client.post('/api/personal-questions/append', json={"question_ids":[question_id]})
    assert added.status_code == 200, added.text
    current = client.get('/api/plans/today').json()
    assert current["study_date"] == "2026-10-19" and current["total_count"] == 1
    assert current["plan_id"] != old["plan_id"]
    original = current["items"][0]
    recommendations = client.get('/api/plans/today/recommendations')
    assert recommendations.status_code == 200 and any(row["kp_id"] == str(kp) for row in recommendations.json()["recommendations"])
    second_question_id = personal(factory, kp, AFTER)
    # An explicit append is supported after materialization; ordinary daily
    # generation still cannot rebuild the frozen paper. Read the new receipt.
    appended = client.post('/api/personal-questions/append', json={
        "question_ids":[second_question_id],"plan_id":current["plan_id"]})
    assert appended.status_code == 200 and appended.json()['added']==1,appended.text
    assert appended.json()['plan_id']==current['plan_id']
    added_receipt=appended.json()['append_result']
    assert added_receipt['added_count']==1
    assert added_receipt['items'][0]['question_id']==second_question_id
    assert added_receipt['items'][0]['question_version_id'] and added_receipt['items'][0]['stem']
    payload = {"selected_kp_ids":[str(kp)],"extend_existing":True}
    extended = client.post('/api/plans/today/generate', json=payload)
    assert extended.status_code == 409 and extended.json()["error"]["code"] == "plan_already_generated"
    repeated_append = client.post('/api/personal-questions/append', json={"question_ids":[question_id],"plan_id":current["plan_id"]})
    assert repeated_append.status_code == 200 and repeated_append.json()["added"] == 0
    frozen = client.get('/api/plans/today').json()
    assert frozen["plan_id"] == current["plan_id"] and frozen["total_count"] == 2
    assert {item['question_id'] for item in frozen['items']}=={question_id,second_question_id}
    kept=next(item for item in frozen['items'] if item['question_id']==question_id)
    assert kept['id']==original['id'] and kept['question_version_id']==original['question_version_id']
    assert client.get('/api/plans/'+old["plan_id"]+'/items').json()["items"] == old["items"]
    with factory() as db:
        item = db.get(PracticeItem, UUID(original["id"]))
        assert db.get(QuestionVersion, item.question_version_id).question_id == UUID(question_id)
        assert db.scalar(select(func.count()).select_from(DailyPlan)) == 2
        assert db.scalar(select(func.count()).select_from(LearningEvent)) == 0
        assert db.scalar(select(func.count()).select_from(QuestionAttempt)) == 0


def test_midnight_first_personal_does_not_close_recommendation_selection(midnight_bank):
    factory, client, now, kp = midnight_bank
    now[0] = AFTER
    question_id = personal(factory, kp, AFTER)
    client.post('/api/personal-questions/append', json={"question_ids":[question_id]})
    for _ in range(2):
        assert client.get('/api/plans/today').json()["total_count"] == 1
        assert client.get('/api/plans/today/recommendations').json()["recommendations"]
    # Ordinary generation retains its one-paper guard; extension is explicit.
    rejected = client.post('/api/plans/today/generate', json={"selected_kp_ids":[str(kp)]})
    assert rejected.status_code == 409


def test_midnight_study_session_clock_and_expired_card_history(midnight_bank):
    from uuid import uuid4
    from tests.integration.test_generation_confirmation_recovery import events
    factory, client, now, kp = midnight_bank
    session = client.post('/api/chat/sessions', json={"title":"TEST_FIXTURE midnight","mode":"builtin","purpose":"study"}).json()
    assert session["study_date"] == "2026-10-18"
    sid = session["session_id"]
    payload = {"question":"给我生成一道级数求和的练习题","request_key":str(uuid4()),
        "study_context":{"surface":"study","knowledge_node_ids":[str(kp)]}}
    frames = events(client.post(f'/api/chat/sessions/{sid}/assistant:stream',params={'purpose':'study'},json=payload))
    ident = next(data["message_id"] for name,data in frames if name == 'meta')
    now[0] = AFTER
    failed = events(client.post(f'/api/chat/sessions/{sid}/assistant:stream',params={'purpose':'study'},json={**payload,
        "request_key":str(uuid4()),"personal_generation_confirmed_kp_id":str(kp),"personal_generation_confirmation_message_id":ident}))
    assert failed[-1][1]["code"] == "study_session_expired"
    history = client.get(f'/api/chat/sessions/{sid}/messages',params={'purpose':'study'}).json()
    assert history[-1]["personal_generation_confirmation_status"] == "expired"
    assert history[-1]["personal_generation_confirmation"] is None
    fresh = client.post('/api/chat/sessions',json={"title":"TEST_FIXTURE today","mode":"builtin","purpose":"study"}).json()
    assert fresh["study_date"] == "2026-10-19" and fresh["session_id"] != sid
    frames = events(client.post(f'/api/chat/sessions/{fresh["session_id"]}/assistant:stream',params={'purpose':'study'},json={**payload,"request_key":str(uuid4())}))
    assert any(name == 'personal_generation_confirmation' for name,_ in frames)
