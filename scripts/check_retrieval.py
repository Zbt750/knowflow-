"""检查向量库当前状态：集合名、元数据、向量数与 embedding 模型一致性。

用法（项目根执行）：
    python scripts/check_retrieval.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import get_settings  # noqa: E402


def main() -> int:
    settings = get_settings()
    chroma_dir = Path(settings.chroma_dir)
    print(f"向量目录：{chroma_dir}")
    print(f"配置的 embedding 模型：{settings.embedding_model}")

    if not (chroma_dir / "chroma.sqlite3").exists():
        print("结论：向量库还没初始化（首次构建索引时会自动创建）。")
        return 0

    import chromadb

    client = chromadb.PersistentClient(path=str(chroma_dir))
    collections = client.list_collections()
    if not collections:
        print("结论：向量库里还没有任何集合。")
        return 0

    for collection in collections:
        metadata = dict(collection.metadata or {})
        stored_model = metadata.get("embedding_model")
        count = collection.count()
        print(f"\n集合：{collection.name}")
        print(f"  向量数：{count}")
        print(f"  空间：{metadata.get('hnsw:space')}")
        print(f"  写入时的模型：{stored_model}")
        if stored_model is not None and str(stored_model) != settings.embedding_model:
            print("  ** 模型与当前配置不一致：数据必须重建索引，否则分数无意义。")
        # 抽样看一条元数据，确认过滤字段齐全。
        sample = collection.get(limit=1, include=["metadatas"])
        ids = sample.get("ids") or []
        if ids:
            print(f"  样例元数据键：{sorted((sample['metadatas'] or [{}])[0].keys())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
