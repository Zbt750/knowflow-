"""Seed explicit TEST_FIXTURE questions in the harness-owned test cluster only."""
import os
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sqlalchemy import text, create_engine
from sqlalchemy.engine import make_url
from backend.config import get_settings
from backend.db import create_db_engine,create_session_factory
from scripts.prepare_e2e_learning import prepare_learning


def main():
    settings=get_settings();url=make_url(str(settings.active_database_url))
    if (settings.app_env!="test" or url.host!="127.0.0.1" or not (url.database or "").endswith("_test")
            or str(url.port)!=os.environ.get("PHASE45E_OWNED_TEST_PORT") or url.port==5433):
        raise ValueError("Browser fixture requires the explicitly owned temporary test instance")
    # Unique browser databases require the full runner ownership proof. The
    # original canonical test database contract remains supported.
    if url.database != "kaoyan_test":
        expected_system=os.environ.get("NAIWA_EXPECTED_SYSTEM_IDENTIFIER")
        expected_cluster=os.environ.get("NAIWA_EXPECTED_CLUSTER_ID")
        marker_path=Path(os.environ.get("NAIWA_OWNER_MARKER", "")).resolve()
        admin=make_url(os.environ.get("NAIWA_ADMIN_TEST_DATABASE_URL", ""))
        if (os.environ.get("NAIWA_FRESH_TEST_DATABASE")!="1"
                or os.environ.get("NAIWA_ISOLATED_DATABASE")!=url.database
                or url.username!="kaoyan_app" or not url.port or url.port<=18000
                or not expected_system or not expected_cluster
                or not marker_path.is_relative_to((ROOT/"tmp/managed-test-clusters").resolve())
                or not marker_path.is_file()
                or admin.host!=url.host or admin.port!=url.port or admin.username!="kaoyan_admin"):
            raise ValueError("Unique browser fixture requires full owned cluster proof")
        owner=json.loads(marker_path.read_text(encoding="utf-8"))
        if owner.get("cluster_id")!=expected_cluster:
            raise ValueError("Browser fixture owner identity mismatch")
        admin_engine=create_engine(admin)
        try:
            with admin_engine.connect() as connection:
                observed=str(connection.scalar(text("SELECT system_identifier FROM pg_control_system()")))
            if observed!=expected_system:
                raise ValueError("Browser fixture system identity mismatch")
        finally:admin_engine.dispose()
    engine=create_db_engine(str(settings.active_database_url))
    try:
        with create_session_factory(engine).begin() as db:
            observed=tuple(db.execute(text("SELECT current_database(),current_user,host(inet_server_addr()),inet_server_port()")).one())
            if observed!=(url.database,"kaoyan_app","127.0.0.1",url.port):
                raise ValueError("Browser fixture live database identity mismatch")
            fixture=prepare_learning(db)
        print("TEST_FIXTURE browser seed ready; original database unchanged; "
              f"formal_questions={fixture['formal_fixture_count']}; "
              f"frozen_nodes={fixture['frozen_node_count']}; "
              f"unsupported={len(fixture['unsupported'])}")
    finally:engine.dispose()


if __name__=="__main__":main()
