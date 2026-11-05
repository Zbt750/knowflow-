"""Enrich existing unverified questions, with optimistic content checks and audit history."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.config import get_settings
from backend.db import create_db_engine, create_session_factory
from backend.services.question_pack import QuestionPack
from backend.services.question_answer_revision import revise_answers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack", type=Path)
    parser.add_argument("revisions", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    pack = QuestionPack.model_validate_json(args.pack.read_text(encoding="utf-8"))
    revisions = json.loads(args.revisions.read_text(encoding="utf-8"))
    engine = create_db_engine(str(get_settings().active_database_url))
    try:
        with create_session_factory(engine)() as db:
            result = revise_answers(db, pack, revisions, apply=args.apply)
            db.commit() if args.apply else db.rollback()
            print(result)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
