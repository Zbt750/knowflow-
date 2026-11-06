"""Deferred human review: synthetic unverified content through real APIs and PG.

The planner is an offline protocol double, not a live-model evaluation.
"""
from copy import deepcopy
from uuid import UUID
import pytest
from sqlalchemy import select
from backend.models.learning import Question, KpState, QuestionAttempt
from backend.models.learning_task import LearningTask
from tests.integration.test_p5_adaptive_journey import adaptive, arrange, confirm
from tests.integration.test_learning_loop import session_factory, clean_database, client, clock
from tests.integration.test_learning_tasks import clean_tasks
from tests.integration.test_answer_submissions import cleanup_answer_records
from tests.integration.test_golden_learning_slice import slice_questions


@pytest.mark.parametrize("subject", ["math2", "408"])
def test_unreviewed_public_inventory_is_not_offered_by_learning_agent(
        adaptive, session_factory, client, subject):
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
    tid, draft = arrange(client, session_factory, topic.name)
    assert draft["status"] == "needs_info"
    assert "题量不足" in draft["message"]
    assert "PRIVATE_REVIEW_SENTINEL" not in str(draft)
    assert draft['trace'] == []
    with session_factory() as db:
        private_trace = db.get(LearningTask, UUID(tid)).trace
    pool = next(t["result"] for t in private_trace if t["tool"] == "find_questions")
    assert pool["practice_eligible_count"] == 0
    assert pool["blocking_reasons"] == {"public_formal_review_required": len(kept)}
    assert pool["questions"] == []
    state = next(t["result"]["states"][0] for t in private_trace if t["tool"] == "get_learning_state")
    assert state["effective_confirmation_count"] == 0
    assert all(d["independent_question_count"] == 0 for d in state["capability_profile"]["dimensions"])
    assert not draft.get("draft")
    with session_factory() as db:
        assert db.get(KpState, kp_id).state != "mastered"
        assert not list(db.scalars(select(QuestionAttempt).where(QuestionAttempt.kp_id == kp_id)))
