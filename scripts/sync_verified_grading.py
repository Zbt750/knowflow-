"""精确匹配后同步核验配置及明确勘误，不重灌题库或改动作答历史。"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from backend.config import get_settings
from backend.db import create_db_engine, create_session_factory
from backend.models.learning import Question, KnowledgePoint

TANGENT_STEM = "已知曲线 y^2 = x^3 - 3x + 1，求它在点 (0, 1) 处的切线方程，并说明为什么不能直接把 y 当成自变量求导。"
OLD_TANGENT_EXPLANATION = "两边对 x 求导得 2y·y' = 3x^2 - 3，在 (0,1) 处 y' = -3/2·... 逐步代入得 y' = -3，切线为 y = -3x + 1。若把 y 当自变量求导会得到 dx/dy，方向正好相反，必须先明确对谁求导。"


def sync_question(question, seed):
    """返回 changed / unchanged / conflict；人工改动不被种子配置覆盖。"""
    if seed["stem"] == TANGENT_STEM:
        if question.correct_answer == seed["correct_answer"] and question.explanation == seed["explanation"]:
            return "unchanged"
        if (question.question_type != seed["question_type"] or question.options != seed["options"]
                or question.correct_answer != "y = -3x + 1" or question.explanation != OLD_TANGENT_EXPLANATION
                or question.grading_config):
            return "conflict"
        question.correct_answer = seed["correct_answer"]
        question.explanation = seed["explanation"]
        return "changed"
    if (question.correct_answer != seed["correct_answer"] or question.question_type != seed["question_type"]
            or question.options != seed["options"] or question.explanation != seed["explanation"]):
        return "conflict"
    if question.grading_config == seed["grading_config"]:
        return "unchanged"
    if question.grading_config:
        return "conflict"
    question.grading_config = seed["grading_config"]
    return "changed"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    seeds = json.loads((Path(__file__).resolve().parents[1] / "seed/questions.json").read_text(encoding="utf-8"))["questions"]
    engine = create_db_engine(str(get_settings().active_database_url))
    try:
        with create_session_factory(engine)() as db:
            changed = 0
            conflicts = 0
            missing = 0
            for seed in seeds:
                if not seed.get("grading_config") and seed["stem"] != TANGENT_STEM:
                    continue
                question = db.scalar(select(Question).join(KnowledgePoint).where(
                    KnowledgePoint.code == seed["kp_code"], Question.stem == seed["stem"],
                ))
                if question is None:
                    missing += 1
                    continue
                outcome = sync_question(question, seed)
                changed += outcome == "changed"
                conflicts += outcome == "conflict"
            if args.apply:
                db.commit()
            else:
                db.rollback()
            print(f"{'Applied' if args.apply else 'Dry run'}: changes={changed}, conflicts skipped={conflicts}, missing={missing}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
