"""只读核对实际题库判题覆盖；不把题号来源计为在线题，不自动核验答案。"""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from backend.config import get_settings
from backend.db import create_db_engine, create_session_factory
from backend.models.learning import Question, KnowledgePoint, ExamQuestionReference
from backend.services.answer_grading import available_grading_method


def classify_question(question):
    config = question.grading_config or {}
    method = available_grading_method(question_type=question.question_type, config=config,
                                     expected=question.correct_answer, options=question.options)
    if method:
        return method
    return "invalid_verified_config" if config.get("verified") is True else "manual_or_unverified"


def main():
    engine = create_db_engine(str(get_settings().active_database_url))
    try:
        with create_session_factory(engine)() as db:
            counts = Counter()
            invalid = []
            for question, code in db.execute(select(Question, KnowledgePoint.code).join(KnowledgePoint).where(
                Question.is_active.is_(True), KnowledgePoint.is_active.is_(True), KnowledgePoint.is_assessable.is_(True))):
                status = classify_question(question)
                counts[(code, status)] += 1
                if status == "invalid_verified_config":
                    invalid.append(str(question.id))
            print("Node | method | active assessable questions (NOT exam references)")
            for (code, status), count in sorted(counts.items()):
                print(f"{code} | {status} | {count}")
            references = len(db.scalars(select(ExamQuestionReference.id)).all())
            print(f"Total answerable questions: {sum(counts.values())}; exam references separately: {references}")
            print(f"Invalid verified configs: {len(invalid)}")
            for identifier in invalid:
                print(f"Review question: {identifier}")
            return 1 if invalid else 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
