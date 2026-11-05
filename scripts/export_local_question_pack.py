"""Export an existing unverified local intake pack for guarded answer enrichment."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from backend.config import get_settings
from backend.db import create_db_engine, create_session_factory
from backend.models.learning import Question, KnowledgePoint
from backend.services.question_pack import QuestionPack


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack_id")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / "storage/question-intake"
    if not args.output.resolve().is_relative_to(root) or args.output.exists():
        parser.error("Use a new ignored local intake output")
    engine = create_db_engine(str(get_settings().active_database_url))
    try:
        with create_session_factory(engine)() as db:
            rows = db.execute(select(Question, KnowledgePoint.code).join(KnowledgePoint, Question.kp_id == KnowledgePoint.id)
                              .where(Question.is_active.is_(True))).all()
            questions = []
            for row, code in rows:
                config = row.grading_config or {}
                provenance = config.get("provenance", {})
                key = provenance.get("key", "")
                if not key.startswith(args.pack_id + ":"):
                    continue
                if config.get("verified") or provenance.get("content_status") != "source_transcribed":
                    raise ValueError("Not an unverified transcription")
                fields = ("question_type", "stem", "options", "correct_answer", "explanation", "question_role",
                          "difficulty", "skill_tags", "estimated_minutes", "is_variant")
                questions.append({**{field: getattr(row, field) for field in fields}, "source_id": key[len(args.pack_id)+1:],
                                  "kp_code": code, "source": provenance["source"], "content_status": "source_transcribed"})
            pack = QuestionPack(pack_id=args.pack_id, version="1", questions=questions)
            args.output.write_text(pack.model_dump_json(indent=2), encoding="utf-8")
            print(f"Exported {len(questions)} existing local records; database unchanged")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
