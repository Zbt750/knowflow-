"""Seed explicit TEST_FIXTURE questions in the harness-owned test cluster only."""
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sqlalchemy import text
from sqlalchemy.engine import make_url
from backend.config import get_settings
from backend.db import create_db_engine,create_session_factory
from scripts.prepare_e2e_learning import prepare_learning


def main():
    settings=get_settings();url=make_url(str(settings.active_database_url))
    if (settings.app_env!="test" or url.host!="127.0.0.1" or url.database!="kaoyan_test"
            or str(url.port)!=os.environ.get("PHASE45E_OWNED_TEST_PORT") or url.port==5433):
        raise ValueError("Browser fixture requires the explicitly owned temporary test instance")
    engine=create_db_engine(str(settings.active_database_url))
    try:
        with create_session_factory(engine).begin() as db:
            assert db.scalar(text("SELECT current_database()"))=="kaoyan_test"
            fixture=prepare_learning(db)
        print("TEST_FIXTURE browser seed ready; original database unchanged; "
              f"formal_questions={fixture['formal_fixture_count']}; "
              f"frozen_nodes={fixture['frozen_node_count']}; "
              f"unsupported={len(fixture['unsupported'])}")
    finally:engine.dispose()


if __name__=="__main__":main()
