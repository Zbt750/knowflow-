"""Migrate an owned desktop database, backing up upgrades; seed once only."""
import asyncio
import json

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from desktop.postgres import APP_USER, DATABASE, atomic_json


def prepare_schema(manager):
    from backend.db import create_db_engine, create_session_factory

    resources = manager.paths.resources
    config = Config(str(resources / "alembic.ini"))
    config.set_main_option("script_location", str(resources / "migrations").replace("%", "%%"))
    script = ScriptDirectory.from_config(config)
    head = script.get_current_head()
    receipt_path = manager.paths.data / "config" / "bootstrap.json"
    initialized = False
    if receipt_path.exists():
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            initialized = (receipt["format"] == 1 and receipt["initialized"] is True
                           and receipt["cluster_id"] == manager.owner["cluster_id"])
            if not initialized:
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise ValueError("desktop_bootstrap_receipt_invalid") from None
    engine = create_db_engine(manager.database_url)
    backup = None
    try:
        with engine.connect() as connection:
            if connection.execute(text("SELECT current_database(), current_user")).one() != (DATABASE, APP_USER):
                raise ValueError("desktop_bootstrap_database_mismatch")
            tables = set(inspect(connection).get_table_names())
            revisions = list(connection.execute(text("SELECT version_num FROM alembic_version")).scalars()) if "alembic_version" in tables else []
        if len(revisions) > 1 or (tables - {"alembic_version"} and not revisions):
            raise ValueError("desktop_bootstrap_unknown_schema")
        current = revisions[0] if revisions else None
        if initialized and current is None:
            raise ValueError("desktop_bootstrap_initialized_schema_missing")
        if current is not None:
            try:
                script.get_revision(current)
            except Exception:
                raise ValueError("desktop_bootstrap_schema_incompatible") from None
        if current != head:
            if current is not None:
                backup = manager.backup()  # Failure here prevents migration.
            command.upgrade(config, "head")
        if not initialized:
            from scripts.seed import seed_all
            from backend.services.lesson_service import sync_builtin_lessons
            from backend.services.builtin_material_service import sync_builtin_reference_materials
            with create_session_factory(engine)() as db:
                seed_all(db, include_exam_references=True)
                asyncio.run(sync_builtin_lessons(db, materials_root=manager.paths.data / "uploads"))
                asyncio.run(sync_builtin_reference_materials(db, materials_root=manager.paths.data / "uploads"))
                db.commit()
            atomic_json(receipt_path, {"format": 1, "initialized": True, "cluster_id": manager.owner["cluster_id"], "seed_version": "builtin-v1"})
        return {"schema": head, "seeded": not initialized, "backup_created": backup is not None}
    finally:
        engine.dispose()
