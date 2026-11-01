from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from backend.models.learning import DailyPlan, PracticeItem
from backend.services.practice_service import (
    PlanAlreadyGeneratedError,
    append_questions_to_plan,
    create_initial_plan,
)


def _populated_plan(session: Session) -> DailyPlan:
    plan = DailyPlan(study_date="2040-01-02", status="active")
    session.add(plan)
    session.flush()
    session.add(PracticeItem(
        plan_id=plan.id,
        question_id=None,
        question_version_id=None,
        exam_reference_id=uuid4(),
        kp_id=uuid4(),
        ordinal=1,
    ))
    session.flush()
    return plan


def test_populated_daily_plan_rejects_service_append_and_legacy_extension(monkeypatch):
    """Pure service regression: rejection happens before any paper mutation.

    SQLite here is an in-memory unit-test substrate only. PostgreSQL locking,
    transaction and API behavior are covered by the isolated integration suite.
    """
    engine = create_engine("sqlite:///:memory:")
    DailyPlan.__table__.create(engine)
    PracticeItem.__table__.create(engine)
    try:
        with Session(engine, autoflush=False) as session:
            plan = _populated_plan(session)
            before_plan = (plan.id, plan.study_date, plan.status)
            before_items = list(session.execute(
                select(PracticeItem.id, PracticeItem.question_id,
                       PracticeItem.question_version_id, PracticeItem.kp_id,
                       PracticeItem.ordinal)
                .where(PracticeItem.plan_id == plan.id)
            ))

            # 正式卷生成后允许追加；已存在的题目按幂等跳过，不重复写入。
            existing_question = session.scalar(
                select(PracticeItem.question_id).where(PracticeItem.plan_id == plan.id).limit(1)
            )
            assert append_questions_to_plan(
                session, plan_id=plan.id, question_ids=[existing_question]
            ) == 0

            original_execute = session.execute

            def skip_postgres_advisory_lock(statement, *args, **kwargs):
                if "pg_advisory_xact_lock" in str(statement):
                    return None
                return original_execute(statement, *args, **kwargs)

            monkeypatch.setattr(session, "execute", skip_postgres_advisory_lock)
            with pytest.raises(PlanAlreadyGeneratedError,
                               match="plan_already_generated"):
                create_initial_plan(
                    session,
                    study_date=date(2040, 1, 2),
                    selected_kp_ids=[uuid4()],
                    now=datetime(2040, 1, 2, tzinfo=timezone.utc),
                    extend_existing=True,
                )

            session.expire_all()
            current_plan = session.get(DailyPlan, before_plan[0])
            after_items = list(session.execute(
                select(PracticeItem.id, PracticeItem.question_id,
                       PracticeItem.question_version_id, PracticeItem.kp_id,
                       PracticeItem.ordinal)
                .where(PracticeItem.plan_id == before_plan[0])
            ))
            assert (current_plan.id, current_plan.study_date,
                    current_plan.status) == before_plan
            assert after_items == before_items
            assert session.scalar(select(func.count()).select_from(PracticeItem)) == 1
    finally:
        engine.dispose()
