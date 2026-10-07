"""Retire only exact original seed exercises, preserving plans and attempts."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.config import get_settings
from backend.db import create_db_engine, create_session_factory
from backend.services.question_pack import retire_demo_questions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    demo = json.loads((Path(__file__).resolve().parents[1] / "seed/questions.json").read_text(encoding="utf-8"))
    engine = create_db_engine(str(get_settings().active_database_url))
    try:
        with create_session_factory(engine)() as db:
            result = retire_demo_questions(db, demo, apply=args.apply)
            if args.apply:
                db.commit()
            else:
                db.rollback()
        content = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            args.output.write_text(content + "\n", encoding="utf-8")
        print(content)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
