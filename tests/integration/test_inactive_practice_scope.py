from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select, func

from backend.models.learning import KnowledgePoint, Question, DailyPlan, PracticeItem
from backend.services.practice_service import create_initial_plan, append_questions_to_plan
from tests.integration.test_learning_loop import session_factory, clean_database


@pytest.mark.parametrize("operation", ["generate", "append"])
def test_inactive_node_cannot_enter_practice(session_factory, clean_database, operation):
    with session_factory() as db:
        node = db.scalar(select(KnowledgePoint).where(KnowledgePoint.code == "math.calculus.limit.lhopital"))
        question = db.scalar(select(Question).where(Question.kp_id == node.id, Question.is_active.is_(True)))
        node.is_active = False
        plan = DailyPlan(study_date="2026-01-01", status="active")
        db.add(plan)
        db.flush()
        before = db.scalar(select(func.count()).select_from(PracticeItem))
        with pytest.raises(ValueError, match="knowledge_point_not_found"):
            if operation == "generate":
                create_initial_plan(db, study_date=date(2026, 1, 2), selected_kp_ids=[node.id],
                                    now=datetime(2026, 1, 2, tzinfo=timezone.utc))
            else:
                append_questions_to_plan(db, plan_id=plan.id, question_ids=[question.id])
        assert db.scalar(select(func.count()).select_from(PracticeItem)) == before
        db.rollback()


@pytest.mark.parametrize("change", ["question", "node"])
def test_append_reloads_cached_eligibility(session_factory, clean_database, change):
    with session_factory() as stale:
        node = stale.scalar(select(KnowledgePoint).where(KnowledgePoint.code == "math.calculus.limit.lhopital"))
        question = stale.scalar(select(Question).where(Question.kp_id == node.id, Question.is_active.is_(True)))
        plan = DailyPlan(study_date="2026-01-01", status="active")
        stale.add(plan)
        stale.commit()
        with session_factory.begin() as other:
            other.get(Question if change == "question" else KnowledgePoint,
                      question.id if change == "question" else node.id).is_active = False
        with pytest.raises(ValueError, match="question_not_found" if change == "question" else "knowledge_point_not_found"):
            append_questions_to_plan(stale, plan_id=plan.id, question_ids=[question.id])
        assert stale.scalar(select(func.count()).select_from(PracticeItem)) == 0
        stale.rollback()
