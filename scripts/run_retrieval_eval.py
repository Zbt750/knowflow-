"""检索质量评估：用真实 embedding 模型与真实向量库跑数据集。

为什么必须用真实模型：
单元测试里的假 embedding 只能验证「链路接线正确」，它对语义一无所知，
因此**任何检索质量结论都必须用真实模型得出**。

做法（不污染开发索引）：
1. 在临时目录建一个独立 Chroma 持久库与关键词索引；
2. 把 `seed/materials/` 下的内置资料真实摄取进去（真的解析、真的分块、真的编码）；
3. 对数据集里每个问题跑一次混合检索，按标题路径判断是否命中预期主题；
4. 输出 Hit@k / Recall@k / MRR 与逐条结果。

用法（项目根执行，需要后端依赖已就绪）：
    python scripts/run_retrieval_eval.py
    python scripts/run_retrieval_eval.py --k 10 --dataset eval/dataset/retrieval_v1.jsonl
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]

from backend.config import get_settings  # noqa: E402
from backend.db import create_db_engine, create_session_factory  # noqa: E402
from backend.eval.dataset import load_dataset  # noqa: E402
from backend.eval.metrics import CaseResult, EvalReport, format_report  # noqa: E402
from backend.ingestion.file_storage import save_upload_streaming  # noqa: E402
from backend.models.rag import Material  # noqa: E402
from backend.retrieval.embedding import SentenceTransformerEmbedder  # noqa: E402
from backend.retrieval.keyword import KeywordIndex  # noqa: E402
from backend.retrieval.protocols import RetrievalRequest  # noqa: E402
from backend.retrieval.rerank import build_reranker  # noqa: E402
from backend.retrieval.vector_store import ChromaVectorStore  # noqa: E402
from backend.services.ingestion_service import (  # noqa: E402
    activate_version,
    build_index,
    compute_index_version,
    parse_material,
    plan_material,
    rebuild_keyword_index,
)
from backend.services.retrieval_service import search_chunks  # noqa: E402


class FileUpload:
    """最小 UploadFile 替身，用于把仓库里的资料落盘到临时根目录。"""

    def __init__(self, path: Path) -> None:
        self.filename = path.name
        self._data = path.read_bytes()
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


def ingest_materials(session, *, materials_root: Path, embedder, vector_store, keyword_index) -> int:
    """把 seed/materials 下的资料真实摄取进临时索引，返回块总数。"""
    import asyncio

    material_dir = ROOT / "seed" / "materials"
    files = sorted(material_dir.glob("*"))
    total_chunks = 0
    for path in files:
        if path.suffix.lower() not in {".md", ".txt", ".docx", ".pdf"}:
            continue
        material = Material(
            title=path.stem,
            source_type="builtin",
            original_filename=path.name,
            stored_path="pending",
            status="pending",
        )
        session.add(material)
        session.flush()

        stored_path, size, raw_hash = asyncio.run(
            save_upload_streaming(FileUpload(path), material_id=material.id, root=materials_root)
        )
        material.stored_path = stored_path
        material.file_size = size
        material.raw_hash = raw_hash
        session.flush()

        plan = plan_material(material, materials_root=materials_root)
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
        total_chunks += outcome.chunk_count
        print(f"  已摄取 {path.name}：{outcome.chunk_count} 块，版本 {version}")
    # 版本激活之后才重建关键词索引（否则会得到空索引）。
    rebuild_keyword_index(session, keyword_index)
    session.commit()
    return total_chunks


def main() -> int:
    parser = argparse.ArgumentParser(description="检索质量评估")
    parser.add_argument("--dataset", default="eval/dataset/retrieval_v1.jsonl")
    parser.add_argument("--k", type=int, default=6, help="评估的前 k 条结果")
    parser.add_argument("--top-k", type=int, default=10, help="每次检索取回多少条")
    args = parser.parse_args()

    settings = get_settings()
    dataset_path = (ROOT / args.dataset).resolve()
    cases = load_dataset(dataset_path)
    print(f"数据集：{dataset_path.name}，{len(cases)} 条用例")

    # ignore_cleanup_errors：即使某个句柄还没释放，也不该让评估结果丢失。
    with tempfile.TemporaryDirectory(
        prefix="kaoyan-eval-", ignore_cleanup_errors=True
    ) as temp_dir:
        temp_root = Path(temp_dir)
        materials_root = temp_root / "uploads"
        materials_root.mkdir(parents=True, exist_ok=True)

        embedder = SentenceTransformerEmbedder(
            settings.embedding_model, cache_dir=str(settings.model_cache_dir)
        )
        vector_store = ChromaVectorStore(
            persist_directory=temp_root / "chroma",
            embedding_model=settings.embedding_model,
        )
        keyword_index = KeywordIndex()
        reranker = build_reranker(settings.reranker_model, cache_dir=str(settings.model_cache_dir))
        print(f"模型：{settings.embedding_model}；重排：{settings.reranker_model or '未启用'}")

        print("摄取内置资料：")
        engine = create_db_engine(str(settings.active_database_url))
        session_factory = create_session_factory(engine)
        try:
            with session_factory() as session:
                total = ingest_materials(
                    session,
                    materials_root=materials_root,
                    embedder=embedder,
                    vector_store=vector_store,
                    keyword_index=keyword_index,
                )
            print(f"共 {total} 块，向量库计数 {vector_store.count()}\n")

            report = EvalReport(k=args.k)
            with session_factory() as session:
                for case in cases:
                    outcome = search_chunks(
                        session,
                        request=RetrievalRequest(query=case.query, top_k=args.top_k),
                        embedder=embedder,
                        vector_store=vector_store,
                        keyword_index=keyword_index,
                        reranker=reranker,
                    )
                    report.results.append(
                        CaseResult(
                            case_id=case.case_id,
                            query=case.query,
                            difficulty=case.difficulty,
                            expected=case.expected_headings,
                            actual_headings=[tuple(hit.heading_path) for hit in outcome.hits],
                            out_of_scope=case.is_out_of_scope,
                            # 记录最高分数：越界用例要靠它校准上层的拒绝阈值。
                            top_score=outcome.hits[0].score if outcome.hits else None,
                        )
                    )
        finally:
            engine.dispose()
        # 显式释放向量库句柄，否则 Windows 上临时目录删不掉。
        vector_store.close()

    print(format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
