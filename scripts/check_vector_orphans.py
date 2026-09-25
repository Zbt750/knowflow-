"""向量库一致性检查：向量是否与数据库里的激活版本块一一对应。

为什么需要它：向量库是可重建的派生索引，本该与「ready 且当前激活版本」的块一致。
但**删除资料时向量库的删除与数据库事务不是原子的** —— 如果那一步失败
（索引损坏、进程被强杀），向量就会变成永远召不回的孤儿，白占索引空间。

用法（项目根执行）：
    python scripts\\check_vector_orphans.py            # 只检查并报告
    python scripts\\check_vector_orphans.py --clean    # 检查并清理孤儿向量
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from backend.config import get_settings  # noqa: E402
from backend.db import create_db_engine, create_session_factory  # noqa: E402

PAGE_SIZE = 1000


def load_known_materials() -> dict[str, tuple[str, str | None, int]]:
    """数据库侧：资料 id → (标题, 激活版本, 激活块数)。"""
    settings = get_settings()
    engine = create_db_engine(str(settings.active_database_url))
    try:
        with create_session_factory(engine)() as db:
            rows = db.execute(
                text(
                    "SELECT m.id::text, m.title, m.active_index_version, "
                    "(SELECT count(*) FROM document_chunks dc WHERE dc.material_id = m.id "
                    " AND dc.index_version = m.active_index_version) AS active_chunks "
                    "FROM materials m ORDER BY m.created_at"
                )
            ).all()
    finally:
        engine.dispose()
    return {row[0]: (row[1], row[2], int(row[3])) for row in rows}


def collect_vectors(collection) -> dict[str, list[str]]:
    """向量库侧：material_id → 该资料的向量 id 列表。"""
    total = collection.count()
    by_material: dict[str, list[str]] = {}
    offset = 0
    while offset < max(total, 1):
        page = collection.get(limit=PAGE_SIZE, offset=offset, include=["metadatas"])
        ids = page.get("ids") or []
        if not ids:
            break
        for chunk_id, meta in zip(ids, page.get("metadatas") or []):
            material_id = str((meta or {}).get("material_id", ""))
            by_material.setdefault(material_id, []).append(str(chunk_id))
        offset += len(ids)
    return by_material


def main() -> int:
    parser = argparse.ArgumentParser(description="检查/清理向量库孤儿向量")
    parser.add_argument("--clean", action="store_true", help="清理孤儿向量")
    args = parser.parse_args()

    settings = get_settings()
    import chromadb

    client = chromadb.PersistentClient(path=str(Path(settings.chroma_dir)))
    collection = client.get_or_create_collection(name="kaoyan_chunks")
    print(f"向量库：{settings.chroma_dir}")

    known = load_known_materials()
    print(f"数据库侧资料：{len(known)} 份")
    for material_id, (title, version, chunks) in known.items():
        print(f"  {title} | {version} | 激活块 {chunks} | {material_id}")

    by_material = collect_vectors(collection)
    print(f"向量库向量数：{sum(len(v) for v in by_material.values())}")

    orphan_ids: list[str] = []
    orphan_by_material: dict[str, int] = {}
    for material_id, chunk_ids in by_material.items():
        if material_id not in known:
            orphan_by_material[material_id] = len(chunk_ids)
            orphan_ids.extend(chunk_ids)
            continue
        expected = known[material_id][2]
        # 资料还在，但向量数多于激活块数：说明旧版本或重复写入的向量没被清掉。
        if len(chunk_ids) > expected:
            orphan_by_material[material_id] = len(chunk_ids) - expected
            orphan_ids.extend(chunk_ids[expected:])

    # 反向检查：向量**少于**激活块数（含一条都没有）。
    #
    # 为什么必须补这一段（真实缺陷）：原来只查「向量多于块」的多余向量，
    # 于是当向量库整个为空、数据库里却还有几十个激活块时，脚本照样打印
    # 「一致性正常：没有孤儿向量」，并且**提前 return 0** —— 把最严重的不一致
    # 报成了健康。实测踩过：删掉损坏的向量目录后重建，向量数为 0，
    # 这个脚本却报正常，差点据此认为检索已经恢复。
    missing_by_material: dict[str, int] = {}
    for material_id, (_title, _version, expected) in known.items():
        actual = len(by_material.get(material_id, []))
        if actual < expected:
            missing_by_material[material_id] = expected - actual

    if not orphan_by_material and not missing_by_material:
        print("\n一致性正常：孤儿向量与缺失向量都没有。")
        return 0

    if missing_by_material:
        print("\n发现向量缺失（数据库里是激活块，向量库里没有对应向量）：")
        for material_id, count in sorted(missing_by_material.items(), key=lambda kv: -kv[1]):
            title, version, expected = known[material_id]
            actual = len(by_material.get(material_id, []))
            print(f"  {title} | {version} | 激活块 {expected}，向量 {actual}，缺 {count}")
        print(f"合计缺 {sum(missing_by_material.values())} 条")
        print("→ 向量库是可重建的派生索引：跑 scripts/rebuild_all_indexes.py 补回即可；")
        print("  正文与分块在 PostgreSQL 里没有丢，不要手工改数据库。")

    if not orphan_by_material:
        return 1 if missing_by_material else 0

    print("\n发现孤儿向量（资料已删除，或数量多于激活块数）：")
    for material_id, count in sorted(orphan_by_material.items(), key=lambda kv: -kv[1]):
        title = known.get(material_id, ("<已删除>", None, 0))[0]
        print(f"  {title} | {material_id}: {count} 条")
    print(f"合计 {len(orphan_ids)} 条")

    if not args.clean:
        print("\n（加 --clean 可清理；清理只影响派生索引，正文与分块不受影响）")
        return 1

    print("\n开始清理…")
    for start in range(0, len(orphan_ids), PAGE_SIZE):
        collection.delete(ids=orphan_ids[start : start + PAGE_SIZE])
    print(f"清理完成，剩余向量 {collection.count()} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
