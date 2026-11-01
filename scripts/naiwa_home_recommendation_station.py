"""Fresh homepage-review fixture atop the existing isolated UI supervisor.

No auth/network guard overrides. Never resume an old station or seed Attempts.
Use a new NAIWA_UI_TEST_STATION_ID starting with 'home' and unused test ports.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def seed_home_fixture(factory, *, database: str, port: int):
    from sqlalchemy import select, func
    from backend.models.learning import KnowledgePoint, Question
    engine = factory.kw["bind"]
    url = engine.url
    if (os.environ.get("APP_ENV") != "test" or url.host != "127.0.0.1"
            or url.port != port or port <= 18000 or port == 5433
            or url.database != database or not database.endswith("_test")):
        raise RuntimeError("home_fixture_requires_exact_owned_test_database")
    with factory() as db:
        if db.scalar(select(func.count()).select_from(KnowledgePoint)):
            raise RuntimeError("home_fixture_requires_empty_new_database")
    # The same guarded, deterministic fixture used by the integration suite.
    # Values stay in this child process; no DSN/credential is printed or saved.
    os.environ["TEST_DATABASE_URL"] = url.render_as_string(hide_password=False)
    os.environ["KAOYAN_OWNED_TEST_PORT"] = str(port)
    from scripts.seed import seed_all
    from tests.integration.test_home_recommendation import home
    from tests.integration.test_learning_loop import mark_isolated_question_trusted
    with factory.begin() as db:
        seed_all(db)
        db.flush()
        for question in db.scalars(select(Question)):
            question.stem = "【SYNTHETIC 首页推荐验收】" + question.stem
            mark_isolated_question_trusted(question, db=db)
    fixture = home.__wrapped__(None, factory)
    with factory.begin() as db:
        for node in db.scalars(select(KnowledgePoint)):
            if "SYNTHETIC" not in node.name:
                node.name += "（SYNTHETIC）"
    return {"fixture_label": "SYNTHETIC_ONLY_NOT_REAL_EXAM", "home": fixture,
        "real_model_requests": 0, "attempts_seeded": 0,
        "note": "线代80分钟合成库存；洛必达专项更短；所有作答由独立Agent通过页面提交。"}


def main():
    if not os.environ.get("NAIWA_UI_TEST_STATION_ID", "").startswith("home"):
        raise RuntimeError("home_station_requires_new_home_prefixed_epoch")
    os.environ["NAIWA_UI_TEST_FIXTURE_PROFILE"] = "answer_handoff_v1"
    from scripts import naiwa_student_ui_acceptance_20261024 as station
    station._seed_synthetic_data = lambda factory: seed_home_fixture(factory,
        database=station.DB_NAME, port=station.PG_PORT)
    station.main()


if __name__ == "__main__":
    main()
