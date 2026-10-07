"""仅同步讲解检索副本，不运行 seed，不修改题库或学习证据。"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from backend.config import get_settings
from backend.db import create_db_engine, create_session_factory
from backend.models.learning import KnowledgePoint
from backend.models.rag import Material
from backend.services.lesson_service import lesson_file, sync_builtin_lessons


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="同步文件并提交后台索引任务，默认只检查")
    parser.add_argument("--root-code", help="仅同步该根节点及其后代，不跨科目更新")
    parser.add_argument("--include-guides", action="store_true", help="在指定根节点批次中包括章节导读")
    args = parser.parse_args()
    settings = get_settings()
    engine = create_db_engine(str(settings.active_database_url))
    try:
        with create_session_factory(engine)() as db:
            codes = None
            if args.include_guides and not args.root_code:
                parser.error("--include-guides 必须指定 --root-code")
            if args.root_code:
                all_nodes = db.scalars(select(KnowledgePoint).where(KnowledgePoint.is_active.is_(True))).all()
                root_node = next((node for node in all_nodes if node.code == args.root_code), None)
                if root_node is None:
                    raise SystemExit("根节点不存在或已停用，拒绝同步")
                selected_ids = {root_node.id}
                while True:
                    expanded = selected_ids | {node.id for node in all_nodes if node.parent_id in selected_ids}
                    if expanded == selected_ids:
                        break
                    selected_ids = expanded
                codes = {node.code for node in all_nodes if node.id in selected_ids and '.family.' not in node.code and (args.include_guides or node.is_assessable)}
            if args.apply:
                result = asyncio.run(sync_builtin_lessons(db, materials_root=settings.upload_dir, codes=codes))
                db.commit()
                print(result)
                print("检索副本已同步，索引由既有后台任务处理；不代表索引已完成。")
            else:
                changed = missing = 0
                query = select(KnowledgePoint).where(KnowledgePoint.is_active.is_(True))
                query = query.where(KnowledgePoint.is_assessable.is_(True)) if codes is None else query.where(KnowledgePoint.code.in_(codes))
                nodes = db.scalars(query).all()
                for node in nodes:
                    path = lesson_file(node.code)
                    if path is None or not path.is_file():
                        missing += 1
                        continue
                    material = db.scalar(select(Material).where(
                        Material.source_type == "builtin", Material.original_filename == path.name,
                    ))
                    if material is None or material.raw_hash != hashlib.sha256(path.read_bytes()).hexdigest():
                        changed += 1
                print({"nodes_in_scope": len(nodes), "changed_or_missing_copy": changed, "missing_file": missing})
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
