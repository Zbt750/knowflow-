"""Real API and isolated PostgreSQL; deterministic provider, no network calls."""
from uuid import uuid4, UUID
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from backend.models.chat import ChatMessage
from backend.models.learning import Question, QuestionVersion, PracticeItem, DailyPlan
from tests.integration.test_generation_confirmation_recovery import (
    generation_fixture, application, events,
)

SOURCE = r"当 |x|<1 时，求级数 \(\sum_{n=1}^{\infty}nx^n\) 的和。"
GOAL = "帮我生成一道难度更大一点的类似题。"


def post(client, sid, question, **kwargs):
    payload = {"question": question, "request_key": str(uuid4()), **kwargs}
    return payload, events(client.post(f"/api/chat/sessions/{sid}/assistant:stream", json=payload))


def confirm(client, sid, payload, frames, kp):
    card_id = next(data["message_id"] for name, data in frames if name == "meta")
    request = {**payload, "request_key": str(uuid4()),
        "personal_generation_confirmed_kp_id": str(kp),
        "personal_generation_confirmation_message_id": card_id}
    return request, events(client.post(f"/api/chat/sessions/{sid}/assistant:stream", json=request))


def test_missing_original_then_paste_preserves_request_and_source_and_saves_once(generation_fixture):
    factory, _, kp, sid, model = generation_fixture
    with TestClient(application(factory, model)) as client:
        _, first = post(client, sid, GOAL)
        assert any(name == "meta" and data["capability"] == "generation_reference_required" for name, data in first)
        assert not any(name == "personal_generation_confirmation" for name, _ in first)
        assert model.calls == 0
        payload, second = post(client, sid, SOURCE)
        assert any(name == "personal_generation_confirmation" for name, _ in second)
        request, saved = confirm(client, sid, payload, second, kp)
        result = next(data for name, data in saved if name == "personal_generation")
        assert len(result["question_ids"]) == 1, saved
        assert not any(name == "error" for name, _ in saved)
        assert model.calls == 1
        assert model.requests[0]["reference"]["statement"] == SOURCE
        assert model.requests[0]["user_requirement"] == GOAL
        assert model.requests[0]["difficulty"] == "improved"
        repeated = events(client.post(f"/api/chat/sessions/{sid}/assistant:stream", json=request))
        assert any(name == "meta" and data.get("replayed") for name, data in repeated)
        assert model.calls == 1
        history = client.get(f"/api/chat/sessions/{sid}/messages").json()
        assert [row["content"] for row in history if row["role"] == "user"] == [GOAL, SOURCE]
        assert history[-1]["personal_generation"]["question_ids"] == result["question_ids"]
    with factory() as db:
        question = db.get(Question, UUID(result["question_ids"][0]))
        assert question.kp_id == kp and question.bank_scope == "personal"
        assert db.get(QuestionVersion, question.current_version_id).question_id == question.id
        assert db.scalar(select(func.count()).select_from(PracticeItem)) == 0


def test_pasted_source_before_request_and_stale_card_do_not_block_new_goal(generation_fixture):
    factory, _, kp, sid, model = generation_fixture
    with factory.begin() as db:
        db.add(ChatMessage(session_id=sid, role="user", content=SOURCE, status="completed"))
        db.add(ChatMessage(session_id=sid, role="assistant", content="先求导再乘x。", status="completed"))
    with TestClient(application(factory, model)) as client:
        old_payload, old_frames = post(client, sid, GOAL)
        old_id = next(data["message_id"] for name, data in old_frames if name == "meta")
        payload, frames = post(client, sid, "再来一道综合性更强的类似练习题。")
        replay = events(client.post(f"/api/chat/sessions/{sid}/assistant:stream", json=old_payload))
        assert not any(name == "personal_generation_confirmation" for name, _ in replay)
        old = {**old_payload, "personal_generation_confirmed_kp_id": str(kp),
            "personal_generation_confirmation_message_id": old_id, "request_key": str(uuid4())}
        rejected = events(client.post(f"/api/chat/sessions/{sid}/assistant:stream", json=old))
        assert rejected[-1][1]["code"] == "personal_generation_confirmation_invalid"
        new_card = next(data for name, data in frames if name == 'personal_generation_confirmation')
        assert not new_card.get('proposed_targets'), new_card
        request, saved = confirm(client, sid, payload, frames, kp)
        assert any(name == "personal_generation" and len(data["question_ids"]) == 1 for name, data in saved), saved
        assert model.requests[0]["reference"]["statement"] == SOURCE
        assert model.requests[0]["difficulty"] == "comprehensive"
        assert model.calls == 1


def test_source_modification_is_a_new_confirmation_and_quality_failure_never_saves(generation_fixture):
    factory, _, kp, sid, model = generation_fixture
    model.fault = "wrong_step"
    with TestClient(application(factory, model)) as client:
        post(client, sid, GOAL)
        post(client, sid, SOURCE)
        new_source = r"原题：设函数 f(x)=x^2，求 x=1 处的导数。"
        payload, frames = post(client, sid, new_source)
        _, failed = confirm(client, sid, payload, frames, kp)
        assert any(name == "error" and data["code"] == "personal_generation_failed" for name, data in failed), failed
        assert model.requests[0]["reference"]["statement"] == new_source.split("：", 1)[1]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Question)) == 0
        assert db.scalar(select(func.count()).select_from(QuestionVersion)) == 0


def test_practice_reference_uses_bound_old_version_not_mutated_current_question(generation_fixture):
    factory, _, kp, sid, model = generation_fixture
    with factory.begin() as db:
        # The test exercises immutable version binding. An unverified personal
        # AI question is not admitted as a formal variant source, so use a
        # public formal source rather than bypassing that admission rule.
        original = Question(kp_id=kp, stem=SOURCE, question_type="calculation", correct_answer="x/(1-x)^2",
            explanation="在收敛区间内逐项求导并乘以x。", grading_mode="self_assessed", bank_scope="public")
        plan = DailyPlan(study_date="2026-10-18", status="active")
        db.add_all([original, plan]); db.flush()
        version_id = original.current_version_id
        item = PracticeItem(plan_id=plan.id, question_id=original.id, question_version_id=version_id, kp_id=kp, ordinal=1)
        db.add(item); db.flush(); item_id = item.id
    with factory.begin() as db:
        original = db.get(Question, original.id)
        original.stem = "已知 f(x)=x^3，求导数。当前版本不是原练习题。"
        # A previously pasted problem must not override the active PracticeItem.
        db.add(ChatMessage(session_id=sid, role='user', content='原题：设 f(x)=x^9，求导数。', status='completed'))
    with TestClient(application(factory, model)) as client:
        payload, frames = post(client, sid, '帮我生成比这题还难的题', study_context={"surface":"study", "practice_item_id":str(item_id)})
        _, result = confirm(client, sid, payload, frames, kp)
        assert any(name == "personal_generation" for name, _ in result), result
        reference = model.requests[0]["reference"]
        assert reference["statement"] == SOURCE
        assert reference["source"]["question_version_id"] == str(version_id)
        assert reference["source"]["question_id"] == str(original.id)
        assert model.requests[0]['difficulty_requirement']['relative_change'] == 'harder'
        assert model.calls == 1


def test_completed_confirmed_scope_can_be_reused_without_repeating_confirmation(generation_fixture):
    factory, _, kp, sid, model = generation_fixture
    with TestClient(application(factory, model)) as client:
        context = {"surface":"chat", "knowledge_node_ids":[str(kp)]}
        payload, frames = post(client, sid, "给我生成一道等比级数的题", study_context=context)
        _, saved = confirm(client, sid, payload, frames, kp)
        assert any(name == "personal_generation" for name, _ in saved)
        _, followup = post(client, sid, "再来一道难一点的练习题", study_context=context)
        assert not any(name == "personal_generation_confirmation" for name, _ in followup)
        assert any(name == "personal_generation" for name, _ in followup)
        assert model.calls == 2


def test_pending_difficulty_refinement_keeps_source_and_reconfirms_without_duplicate_generation(generation_fixture):
    factory, _, kp, sid, model = generation_fixture
    with TestClient(application(factory, model)) as client:
        post(client, sid, GOAL)
        post(client, sid, SOURCE)
        payload, frames = post(client, sid, "难度再调高一点，改成证明题")
        assert model.calls == 0
        request, result = confirm(client, sid, payload, frames, kp)
        assert any(name == "personal_generation" for name, _ in result), result
        assert model.requests[0]["question_type"] == "proof"
        assert model.requests[0]["reference"]["statement"] == SOURCE
        events(client.post(f"/api/chat/sessions/{sid}/assistant:stream", json=request))
        assert model.calls == 1


def test_two_pasted_originals_require_one_clarification_and_accept_a_numbered_choice(generation_fixture):
    factory, _, kp, sid, model = generation_fixture
    second = "设 f(x)=x^3，求 f'(1)。"
    with TestClient(application(factory, model)) as client:
        post(client, sid, GOAL)
        _, ambiguous = post(client, sid, "1. "+SOURCE+"\n2. "+second)
        assert any(name == "meta" and data["capability"] == "generation_reference_required" for name, data in ambiguous)
        assert model.calls == 0
        payload, frames = post(client, sid, "第二题")
        card = next(data for name, data in frames if name == "personal_generation_confirmation")
        assert card["reference_text"] == second
        _, saved = confirm(client, sid, payload, frames, kp)
        assert any(name == "personal_generation" for name, _ in saved)
        assert model.requests[0]["reference"]["statement"] == second
