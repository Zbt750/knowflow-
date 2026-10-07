"""Deferred human review: synthetic unverified content through real APIs and PG.

The planner is an offline protocol double, not a live-model evaluation.
"""
from copy import deepcopy
from datetime import timedelta
from uuid import UUID
import pytest
from sqlalchemy import select
from backend.models.learning import Question, KpState
from tests.integration.test_p5_adaptive_journey import adaptive, arrange, confirm
from tests.integration.test_learning_loop import session_factory, clean_database, client, clock
from tests.integration.test_learning_tasks import clean_tasks
from tests.integration.test_answer_submissions import cleanup_answer_records
from tests.integration.test_golden_learning_slice import slice_questions


@pytest.mark.parametrize("subject", ["math2", "408"])
@pytest.mark.parametrize("scenario", ["submitted", "solution", "repeated"])
def test_unverified_practice_never_becomes_independent_agent_evidence(
        adaptive, session_factory, client, clock, subject, scenario):
    asset, ids = adaptive
    kept = ["M01", "M03"] if subject == "math2" else ["T01", "T02"]
    topic = next(t for t in asset.topics if t.subject == subject)
    with session_factory.begin() as db:
        kp_id = db.get(Question, UUID(ids[kept[0]])).kp_id
        for question in db.scalars(select(Question).where(Question.kp_id == kp_id)):
            question.is_active = str(question.id) in {ids[k] for k in kept}
            config = deepcopy(question.grading_config)
            config.update(verified=False, method=None)
            config["provenance"]["content_status"] = "source_transcribed"
            config["provenance"]["source"].update(
                source_type="mock", year=2025, question_number=1,
                subject="408" if subject == "408" else "数学二",
                paper_title="隔离合成模拟试题，非真实原卷",
                citation="PRIVATE_REVIEW_SENTINEL")
            config["content_revisions"] = [{"private": "PRIVATE_REVIEW_SENTINEL"}]
            question.grading_config = config
            question.grading_mode = "self_assessed"
    original_question = None
    rounds = 3 if scenario == "repeated" else 2
    old_plans = []
    for index in range(rounds):
        tid, draft = arrange(client, session_factory, topic.name)
        assert draft["status"] == "ready", (
            f"status={draft.get('status')}; message={draft.get('message')}; "
            f"error={draft.get('error_code')}; trace={draft.get('trace')}"
        )
        chosen = draft["draft"]["questions"][0]
        assert chosen["question_source"]["content_status"] == "source_transcribed"
        assert chosen["question_source"]["paper_title"] == "隔离合成模拟试题，非真实原卷"
        assert "PRIVATE_REVIEW_SENTINEL" not in str(draft)
        pool = next(t["result"] for t in draft["trace"] if t["tool"] == "find_questions")
        assert all(q["grading_method"] is None for q in pool["questions"])
        if original_question is None:
            original_question = chosen["question_id"]
        else:
            assert chosen["question_id"] == original_question
            state = next(t["result"]["states"][0] for t in draft["trace"] if t["tool"] == "get_learning_state")
            assert state["recent_attempts"][0]["result"] == "right"
            assert not state["pending_review_question_ids"]
            assert all(d["independent_question_count"] == 0 for d in state["capability_profile"]["dimensions"])
        item = confirm(client, tid, draft)
        if scenario == "solution":
            assert client.post(f"/api/practice-items/{item['id']}/answer-reveal").status_code == 200
        with session_factory() as db:
            question = db.get(Question, UUID(item["question_id"]))
            payload = {"selected_option" if question.options else "raw_answer": question.correct_answer,
                       "idempotency_key": f"unverified-journey-{index}"}
        response = client.post(f"/api/practice-items/{item['id']}/answer-submissions", json=payload)
        assert response.status_code == 200, response.text
        receipt = response.json()
        assert receipt["result"] == "right" and receipt["reason"].startswith("reference_")
        assert receipt["effective_confirmation_count"] == 0
        assert client.post(f"/api/practice-items/{item['id']}/answer-submissions", json=payload).json() == receipt
        with session_factory() as db:
            assert db.get(KpState, kp_id).state != "mastered"
        old_plans.append(client.get("/api/plans/today").json())
        for old in old_plans:
            assert client.get(f"/api/plans/{old['plan_id']}/items").json() == old
        clock.now += timedelta(days=1)
