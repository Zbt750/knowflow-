"""Import a rights/answer-reviewed JSON pack; default read-only, no historical rewrites."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import get_settings
from backend.db import create_db_engine, create_session_factory
from backend.services.question_pack import QuestionPack, import_pack, replace_demo_questions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--replace-demo", action="store_true", help="仅停用本次已用真题/模拟题替换的节点中的原始演示题；保留历史")
    args = parser.parse_args()
    if args.pack.stat().st_size > 16 * 1024 * 1024:
        parser.error("question pack exceeds 16 MiB")
    pack = QuestionPack.model_validate_json(args.pack.read_text(encoding="utf-8"))
    engine = create_db_engine(str(get_settings().active_database_url))
    try:
        with create_session_factory(engine)() as db:
            if args.replace_demo:
                demo = json.loads((Path(__file__).resolve().parents[1] / "seed/questions.json").read_text(encoding="utf-8"))
                result = replace_demo_questions(db, pack, demo, apply=args.apply)
            else:
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
