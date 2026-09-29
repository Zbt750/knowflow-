from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from tests.conftest import PROJECT_ROOT, TEST_DATABASE_URL

# 第一批（学习闭环）必须存在的表。
BATCH_A_TABLES = {
    "knowledge_points",
    "kp_states",
    "learning_events",
    "questions",
    "daily_plans",
    "practice_items",
    "question_attempts",
}

# 第二批（资料与索引）：materials / document_chunks / chunk_knowledge_points / document_jobs。
BATCH_B_TABLES = {
    "materials",
    "document_chunks",
    "chunk_knowledge_points",
    "document_jobs",
}

# 第三批：只保存年份/题号/来源的历年真题关联，不复制题干。
BATCH_C_TABLES = {"exam_question_references"}

# 旧稿表名不得复活。
FORBIDDEN_TABLES = {"daily_plan_items", "practice_sessions"}


def _alembic_config() -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    return config


def test_alembic_upgrade_head_creates_learning_tables_from_empty_database() -> None:
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    try:
        # 从空库开始：先降到 base，验证 upgrade head 真的能重建全部表。
        command.downgrade(_alembic_config(), "base")
        with engine.connect() as connection:
            remaining = set(inspect(connection).get_table_names()) - {"alembic_version"}
        assert remaining == set(), f"downgrade base 后仍有残留表: {sorted(remaining)}"

        command.upgrade(_alembic_config(), "head")

        with engine.connect() as connection:
            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            assert BATCH_A_TABLES <= tables, f"缺少表: {sorted(BATCH_A_TABLES - tables)}"
            assert BATCH_B_TABLES <= tables, f"缺少表: {sorted(BATCH_B_TABLES - tables)}"
            assert BATCH_C_TABLES <= tables, f"缺少表: {sorted(BATCH_C_TABLES - tables)}"
            assert not (FORBIDDEN_TABLES & tables), "旧稿表名不应存在"
            # UUID 主键、外键与唯一约束都要真的落到数据库。
            kp_columns = {c["name"] for c in inspector.get_columns("knowledge_points")}
            assert {"id", "code", "subject", "name", "is_assessable", "is_reference_only"} <= kp_columns
            kp_uniques = inspector.get_unique_constraints("knowledge_points")
            assert any(set(u["column_names"]) == {"code"} for u in kp_uniques)
            fk_targets = {
                fk["referred_table"]
                for fk in inspector.get_foreign_keys("practice_items")
            }
            assert {"daily_plans", "questions", "knowledge_points"} <= fk_targets
            reference_columns = {
                c["name"] for c in inspector.get_columns("exam_question_references")
            }
            assert {
                "subject",
                "year",
                "question_number",
                "knowledge_point_id",
                "question_source_url",
                "topic_source_url",
                "local_folder",
            } <= reference_columns
            practice_columns = {
                c["name"]: c for c in inspector.get_columns("practice_items")
            }
            assert practice_columns["question_id"]["nullable"] is True
            assert practice_columns["exam_reference_id"]["nullable"] is True
            attempt_columns = {
                c["name"]: c for c in inspector.get_columns("question_attempts")
            }
            assert attempt_columns["question_id"]["nullable"] is True
            assert attempt_columns["exam_reference_id"]["nullable"] is True
            attempt_fks = {
                fk["referred_table"] for fk in inspector.get_foreign_keys("question_attempts")
            }
            assert {"questions", "exam_question_references"} <= attempt_fks
            practice_checks = {
                check["name"] for check in inspector.get_check_constraints("practice_items")
            }
            attempt_checks = {
                check["name"] for check in inspector.get_check_constraints("question_attempts")
            }
            assert "ck_practice_items_practice_item_exactly_one_source" in practice_checks
            assert "ck_question_attempts_question_attempt_exactly_one_source" in attempt_checks
    finally:
        engine.dispose()


def test_alembic_check_reports_no_pending_model_changes() -> None:
    """ORM metadata 与迁移必须完全一致，否则后续阶段会悄悄漏表。"""
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    try:
        command.upgrade(_alembic_config(), "head")
        # alembic check 在没有差异时正常返回；有差异会抛异常。
        command.check(_alembic_config())
    finally:
        engine.dispose()


def test_document_jobs_has_status_and_attempt_check_constraints() -> None:
    """document_jobs 必须由数据库锁死 job_type / status 取值与 attempts 范围。"""
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            names = {c["name"] for c in inspector.get_check_constraints("document_jobs")}
            # 约束名来自模型的显式 name=；命名约定会加 ck_document_jobs_ 前缀。
            assert any("job_type_valid" in name for name in names)
            assert any("job_status_valid" in name for name in names)
            assert any("job_attempt_range" in name for name in names)

            columns = {c["name"] for c in inspector.get_columns("document_jobs")}
            assert {
                "worker_id",
                "lease_until",
                "next_run_at",
                "error_code",
                "result_index_version",
            } <= columns
    finally:
        engine.dispose()


def test_chunk_offsets_are_constrained_to_their_material_version() -> None:
    """document_chunks 的 (material_id, index_version, ordinal) 唯一，且块随资料级联删除。"""
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            uniques = inspector.get_unique_constraints("document_chunks")
            assert any(
                set(u["column_names"]) == {"material_id", "index_version", "ordinal"}
                for u in uniques
            ), f"缺少版本内序号唯一约束: {uniques}"

            # 删除资料时块必须级联删除，避免留下孤儿正文。
            cascades = {
                (fk["referred_table"], fk.get("options", {}).get("ondelete"))
                for fk in inspector.get_foreign_keys("document_chunks")
            }
            assert ("materials", "CASCADE") in cascades, cascades

            chunk_kp_fks = {
                (fk["referred_table"], fk.get("options", {}).get("ondelete"))
                for fk in inspector.get_foreign_keys("chunk_knowledge_points")
            }
            assert ("document_chunks", "CASCADE") in chunk_kp_fks, chunk_kp_fks
            assert ("knowledge_points", "CASCADE") in chunk_kp_fks, chunk_kp_fks
    finally:
        engine.dispose()


def test_study_date_column_is_string_ten_chars() -> None:
    """study_date 是上海日期字符串，长度固定 10。"""
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            length = connection.execute(
                text(
                    "SELECT character_maximum_length FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'daily_plans' "
                    "AND column_name = 'study_date'"
                )
            ).scalar_one()
        assert length == 10
    finally:
        engine.dispose()
