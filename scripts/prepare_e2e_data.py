"""端到端测试的数据准备：把资料灌进**测试库**并建好索引。

为什么需要这个脚本：

e2e 改成隔离模式（打 `APP_ENV=test` 的测试后端、拒绝连 dev/prod）之后，
测试库 `kaoyan_test` 里**一份资料都没有** —— 因为 pytest 的夹具会 TRUNCATE 它，
而 `scripts/seed.py` 只灌知识点与题库、**不含资料**。
于是「资料页删除」「超上限被拒」「问答引用」「归因依据」这些用例没有对象可测，
隔离模式 e2e 稳定挂在 4 条上。

所以隔离改造必须配套这一步：**显式把测试数据准备好**，而不是靠手工上传。
它是幂等的（按标题 upsert + 重建索引），可以随时重跑。

安全边界：
- 只认 `APP_ENV=test` 且库名以 `_test` 结尾（`Settings` 本身已经强制这一点），
  绝不可能写到开发库；
- 向量与上传文件也走测试库专用目录（见 `.env.test` 的 `CHROMA_DIR`），
  不碰开发索引。

用法（项目根执行）：
    python scripts/prepare_e2e_data.py            # 看会做什么
    python scripts/prepare_e2e_data.py --apply    # 真的准备
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]

from sqlalchemy import func, select, text  # noqa: E402

from backend.config import get_settings  # noqa: E402
from backend.db import create_db_engine, create_session_factory  # noqa: E402
from backend.ingestion.file_storage import save_upload_streaming  # noqa: E402
from backend.models.rag import DocumentChunk, Material  # noqa: E402
from backend.retrieval.embedding import SentenceTransformerEmbedder  # noqa: E402
from backend.retrieval.keyword import KeywordIndex  # noqa: E402
from backend.retrieval.vector_store import ChromaVectorStore  # noqa: E402
from backend.services.ingestion_service import (  # noqa: E402
    activate_version,
    build_index,
    compute_index_version,
    parse_material,
    plan_material,
    rebuild_keyword_index,
)

# e2e 需要的两份资料：
# 1. 内置资料 —— 问答页「内置资料」模式的检索范围，聊天用例全靠它；
# 2. 用户资料 —— 「我的资料」模式的范围，模式隔离用例要靠它证明两种范围互不串。
BUILTIN_LECTURE = ROOT / "seed" / "materials" / "gaoshu-lecture-01.md"
BUILTIN_TITLE = "高等数学核心考点讲义"

# 「我的资料」用的讲义：内容刻意与内置讲义**不重叠**，
# 这样模式隔离用例才能断言「在哪个范围里检索、答案就来自哪个范围」。
USER_NOTE_TITLE = "阶段A验收笔记"
USER_NOTE_BODY = """# 阶段A前后端连通性验收笔记

## 后端连通性

后端提供 /api/health，返回 status、database 与 retrieval 三个字段。
PostgreSQL 不可用时它返回 503，页面必须显示明确错误与重试按钮，而不是白屏。

## 前端页面

四个页面通过 vue-router 提供：今日学习、知识树、资料库与问答。
问答页的话题与阶段A的连通性有关，与洛必达法则无关。
"""


class FileUpload:
    """最小 UploadFile 替身：把一段正文当作一次上传读完。"""

    def __init__(self, *, filename: str, data: bytes) -> None:
        self.filename = filename
        self._data = data
        self._offset = 0

    async def read(self, size: int = -1) -> bytes:
        if size < 0:
            chunk = self._data[self._offset :]
            self._offset = len(self._data)
            return chunk
        chunk = self._data[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk

    async def close(self) -> None:
        return None


def ingest_bytes(
    session,
    *,
    title: str,
    filename: str,
    data: bytes,
    source_type: str,
    root: Path,
    embedder,
    vector_store,
) -> int:
    """把一份内存里的正文真实摄取成可检索资料，返回块数。

    走的是与生产完全相同的管道（落盘 → 解析 → 分块 → 建向量 → 激活版本），
    不直接写数据库 —— 否则向量索引与分块会与真实路径不一致。
    """
    material = Material(
        title=title,
        source_type=source_type,
        original_filename=filename,
        stored_path="pending",
        status="pending",
    )
    session.add(material)
    session.flush()

    stored_path, size, raw_hash = asyncio.run(
        save_upload_streaming(
            FileUpload(filename=filename, data=data), material_id=material.id, root=root
        )
    )
    material.stored_path = stored_path
    material.file_size = size
    material.raw_hash = raw_hash
    session.flush()

    plan = plan_material(material, materials_root=root)
    version = compute_index_version(plan.content_hash, embedder.model_name)
    parse_material(session, material, plan=plan, index_version=version)
    outcome = build_index(
        session,
        material,
        index_version=version,
        embedder=embedder,
        vector_store=vector_store,
    )
    activate_version(session, material, version)
    return outcome.chunk_count


def main() -> int:
    parser = argparse.ArgumentParser(description="准备 e2e 所需的测试数据")
    parser.add_argument("--apply", action="store_true", help="真的写入（默认只预演）")
    args = parser.parse_args()

    # 强制测试环境：这一步比什么都重要 —— 它决定会不会写到开发库。
    os.environ["APP_ENV"] = "test"
    if not os.environ.get("TEST_DATABASE_URL"):
        print("缺少 TEST_DATABASE_URL；请先设置（见 .env.test.example）", file=sys.stderr)
        return 2
    get_settings.cache_clear()
    settings = get_settings()
    if settings.app_env != "test":
        print(f"拒绝执行：APP_ENV={settings.app_env}，本脚本只允许在 test 环境运行", file=sys.stderr)
        return 2
    database_name = str(settings.active_database_url).rstrip("/").rsplit("/", 1)[-1]
    if not database_name.endswith("_test"):
        print(f"拒绝执行：目标库 {database_name} 不以 _test 结尾", file=sys.stderr)
        return 2

    print(f"目标库：{database_name}")
    print(f"上传目录：{settings.upload_dir}")
    print(f"向量目录：{settings.chroma_dir}")

    engine = create_db_engine(str(settings.active_database_url))
    session_factory = create_session_factory(engine)
    vector_store = None
    try:
        with session_factory() as db:
            existing = {
                row.title: row
                for row in db.scalars(select(Material)).all()
            }
            plan_lines = [
                f"内置资料：{BUILTIN_TITLE}（文件 {BUILTIN_LECTURE.name}）",
                f"用户资料：{USER_NOTE_TITLE}（{len(USER_NOTE_BODY)} 字正文）",
            ]
            for line in plan_lines:
                print("  将准备 " + line)

            if not args.apply:
                print("\n这是预演。加 --apply 才会真的写入。")
                return 0

            embedder = SentenceTransformerEmbedder(
                settings.embedding_model, cache_dir=str(settings.model_cache_dir)
            )
            # 向量库是**可重建的派生索引**（正文与分块始终以 PostgreSQL 为准）。
            # 如果它的 HNSW 段损坏，打开就会抛 InternalError（实测踩过：
            # `Error creating hnsw segment reader: Error loading hnsw index`），
            # 症状是后端所有检索 500、而数据库看起来完全正常。
            # 这里直接删掉整个测试向量目录重建 —— 它是测试专用的，
            # 而「删掉再重建」比人肉找损坏文件可靠得多。
            try:
                vector_store = ChromaVectorStore(
                    persist_directory=settings.chroma_dir,
                    embedding_model=settings.embedding_model,
                )
            except Exception as error:  # noqa: BLE001 - 派生索引损坏不该需要人肉介入
                print(
                    f"  测试向量库不可用（{type(error).__name__}），"
                    f"删除 {settings.chroma_dir} 后重建"
                )
                shutil.rmtree(settings.chroma_dir, ignore_errors=True)
                vector_store = ChromaVectorStore(
                    persist_directory=settings.chroma_dir,
                    embedding_model=settings.embedding_model,
                )
            root = settings.upload_dir
            root.mkdir(parents=True, exist_ok=True)

            # 先把测试库的资料**全部**清掉，再从零准备。
            #
            # 为什么不是只删同名的两份：e2e 会自己创建与删除测试资料，
            # 一次失败的运行可能留下半截状态（甚至卡在 indexing）。
            # 只有「从确定的干净状态开始」，e2e 的计数类断言（资料条数、统计数字）
            # 才是可复现的；否则上一轮的残留会让这一轮莫名其妙地失败。
            #
            # 顺序不能乱：`message_citations.chunk_id` 指向 `document_chunks`，
            # 直接删资料会被外键挡住（真实踩过：IntegrityError fk_message_citations_...）。
            # 而聊天记录引用的是**已经删掉的那批块**，留着它们没有意义，
            # 所以按依赖顺序先清聊天，再清资料 —— 与项目里「删资料」同一条原则。
            db.execute(text("DELETE FROM message_citations"))
            db.execute(text("DELETE FROM chat_messages"))
            db.execute(text("DELETE FROM chat_sessions"))
            for row in existing.values():
                db.delete(row)
            if existing:
                db.flush()
                print(f"  已清空测试库原有资料 {len(existing)} 份（连带聊天记录）")
            db.commit()

            # 向量库**整体清空**，而不是按数据库里那几个 material_id 逐个删。
            #
            # 为什么必须这样：本脚本每轮都用**新 UUID** 建资料，于是上一轮那批
            # 资料的向量再也无人认领 —— 实测累积到 85 条（正常应为 17）。
            # 残留本身不会让检索失效，但会让「这一轮到底干净不干净」无法判断，
            # 排查时看到的数据也不再可信。
            #
            # `clear()` 只删集合里的**内容行**、不删集合本身：重建集合会让已经
            # 持有旧句柄的后端进程失效（实测表现为所有检索 500）。也因此本脚本
            # 必须**在后端启动之前**跑，见 scripts/test.cmd 第 4 步的顺序说明。
            removed = vector_store.clear()
            print(f"  已清空测试向量库 {removed} 条（避免孤儿向量累积）")

            builtin_chunks = ingest_bytes(
                db,
                title=BUILTIN_TITLE,
                filename=BUILTIN_LECTURE.name,
                data=BUILTIN_LECTURE.read_bytes(),
                source_type="builtin",
                root=root,
                embedder=embedder,
                vector_store=vector_store,
            )
            print(f"  已摄取「{BUILTIN_TITLE}」：{builtin_chunks} 块")
            user_chunks = ingest_bytes(
                db,
                title=USER_NOTE_TITLE,
                filename="阶段A验收笔记.md",
                data=USER_NOTE_BODY.encode(),
                source_type="user",
                root=root,
                embedder=embedder,
                vector_store=vector_store,
            )
            print(f"  已摄取「{USER_NOTE_TITLE}」：{user_chunks} 块")

            keyword_index = KeywordIndex()
            rebuild_keyword_index(db, keyword_index)
            db.commit()

            ready = db.scalars(
                select(Material).where(Material.status == "ready")
            ).all()
            chunk_count = db.scalar(
                select(func.count()).select_from(DocumentChunk)
            )
            vector_count = vector_store.count()
            print(f"\n完成：ready 资料 {len(ready)} 份，分块 {chunk_count} 个，向量库 {vector_count} 条")
            if not chunk_count:
                print("警告：没有任何分块，检索会失败", file=sys.stderr)
                return 1
            # 自检：清空之后向量数应当**恰好**等于分块数。
            # 对不上就说明又出现了孤儿向量（或漏灌），必须当场说出来 ——
            # 这个数字曾经悄悄涨到 85，直接让后续 e2e 的表现无法解释。
            if vector_count != chunk_count:
                print(
                    f"警告：向量库条数 {vector_count} 与分块数 {chunk_count} 不一致，"
                    "可能存在孤儿向量或漏灌",
                    file=sys.stderr,
                )
                return 1
    finally:
        if vector_store is not None:
            vector_store.close()
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
