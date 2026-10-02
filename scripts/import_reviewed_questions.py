"""Import a rights/answer-reviewed JSON pack; default read-only, no historical rewrites."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import get_settings
from backend.db import create_db_engine, create_session_factory
from backend.services.question_pack import QuestionPack, import_pack


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.pack.stat().st_size > 16 * 1024 * 1024:
        parser.error("question pack exceeds 16 MiB")
    pack = QuestionPack.model_validate_json(args.pack.read_text(encoding="utf-8"))
    engine = create_db_engine(str(get_settings().active_database_url))
    try:
        with create_session_factory(engine)() as db:
            result = import_pack(db, pack, apply=args.apply)
            if args.apply:
                db.commit()
            else:
                db.rollback()
            print(result)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
