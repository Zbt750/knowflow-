"""The preview notice uses the same current type ordering as today's paper."""
from contextlib import nullcontext
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

from backend.models.learning import DailyPlan, KnowledgePoint, PracticeItem, Question, QuestionAttempt, QuestionVersion
from backend.services import practice_preview_reference as module


def test_already_added_preview_uses_current_display_number_and_preserves_ordinal(monkeypatch):
    qid, vid, kp, plan_id = [UUID(int=n) for n in (1, 2, 3, 4)]
    question = SimpleNamespace(id=qid, kp_id=kp)
    plan = SimpleNamespace(id=plan_id, study_date="2026-10-26")
    target = SimpleNamespace(id=UUID(int=5), plan_id=plan_id, question_id=qid,
                             question_version_id=vid, ordinal=2, completed_at=None)
    calculation = SimpleNamespace(id=UUID(int=6), plan_id=plan_id, question_id=UUID(int=7),
                                  question_version_id=UUID(int=8), ordinal=1)

    class Records:
        def get(self, entity, ident):
            return {Question: question, QuestionVersion: SimpleNamespace(question_id=qid),
                    KnowledgePoint: SimpleNamespace(name="洛必达法则"), DailyPlan: plan}[entity]

        def scalars(self, statement):
            entity = statement.column_descriptions[0]["entity"]
            if entity is QuestionAttempt:
                return []
            assert entity is PracticeItem
            params = statement.compile().params
            return [target] if "question_id_1" in params else [calculation, target]

    monkeypatch.setattr(module, "question_version_reference", lambda q: str(vid))
    monkeypatch.setattr(module, "question_eligibility", lambda *args: SimpleNamespace(practice_eligible=True))
    monkeypatch.setattr("backend.services.question_versions.question_for_practice_item",
                        lambda db, item: SimpleNamespace(question_type="single_choice" if item is target else "calculation"))
    result = module.preview_question_state(lambda: nullcontext(Records()),
        {"question_id": str(qid), "question_version": str(vid)},
        SimpleNamespace(daily_plan_id=plan_id), datetime(2026, 10, 26, tzinfo=timezone.utc))
    assert "第 1 题" in result["message"]
    assert result["display_number"] == 1
    assert result["ordinal"] == 2
    assert result["question_version_id"] == str(vid)
