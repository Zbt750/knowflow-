"""Local-cache-only pre-rerank fusion probe on fixed synthetic fixtures; no LLM/DB."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.chat.query_context import contextualize_retrieval_query
from backend.ingestion.chunker import build_chunk_drafts
from backend.ingestion.title_tree import source_blocks_from_title_tree
from backend.retrieval.fusion import fuse_ranked_ids
from backend.retrieval.keyword import KeywordIndex
from backend.retrieval.protocols import IndexFilter, VectorRecord
from backend.retrieval.vector_store import InMemoryVectorStore


def synthetic_records():
    records = []
    for title, filename in [("合成数学条件讲义", "baseline_math_v3.md"), ("合成408机制讲义", "baseline_408_v3.md")]:
        body = (ROOT / "eval/fixtures" / filename).read_text(encoding="utf-8")
        drafts = build_chunk_drafts(body, source_blocks_from_title_tree(body))
        for draft in drafts:
            records.append(VectorRecord(chunk_id=uuid5(NAMESPACE_URL, filename + str(draft.ordinal)),
                                        material_id=uuid5(NAMESPACE_URL, filename), index_version="probe-v1",
                                        ordinal=draft.ordinal, content=draft.content, heading_path=draft.heading_path,
                                        source_type="builtin", material_title=title))
    return records


def fusion_probe(query, records, embedder, store, keyword):
    filters = IndexFilter(source_types=("builtin",), index_versions=("probe-v1",))
    vector = store.query(embedder.encode([query])[0], top_k=36, index_filter=filters)
    title = keyword.search_title_tree(query, top_k=36, index_filter=filters)
    body = keyword.search(query, top_k=36, index_filter=filters)
    fused = fuse_ranked_ids({"vector": [h.chunk_id for h in vector], "title": [i for i, _ in title],
                             "keyword": [i for i, _ in body]}, top_k=36)
    by_id = {r.chunk_id: r for r in records}
    cosines = {h.chunk_id: h.score for h in vector}
    return [{"rank": rank, "heading_path": list(by_id[key].heading_path),
             "material_title": by_id[key].material_title, "cosine": cosines.get(key), "rrf": score}
            for rank, (key, score) in enumerate(fused, 1)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Report exists; refuse overwrite")
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    from backend.config import get_settings
    from backend.retrieval.embedding import SentenceTransformerEmbedder
    settings = get_settings()
    embedder = SentenceTransformerEmbedder(settings.embedding_model, cache_dir=str((ROOT / settings.model_cache_dir).resolve()))
    records = synthetic_records()
    store = InMemoryVectorStore(embedding_model=embedder.model_name)
    store.upsert(records, embedder.encode([r.content for r in records]))
    keyword = KeywordIndex()
    keyword.rebuild(records)
    dataset = ROOT / "eval/dataset/chat_baseline_v3_1.jsonl"
    case = next(json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines() if json.loads(line)["id"] == "math-followup")
    rewritten = contextualize_retrieval_query(case["question"], case["setup_questions"])
    report = {"version": "local-followup-fusion-probe-v1", "scope": "pre_rerank_fusion_not_full_chat",
              "external_model_calls": 0, "database_access": False,
              "embedding_model": embedder.model_name, "dataset_sha256": sha256(dataset.read_bytes()).hexdigest(),
              "source_sha256": {name: sha256((ROOT / name).read_bytes()).hexdigest() for name in (
                  "backend/chat/query_context.py", "backend/services/retrieval_service.py", "scripts/probe_followup_retrieval.py",
                  "eval/fixtures/baseline_math_v3.md", "eval/fixtures/baseline_408_v3.md")},
              "case_id": case["id"], "original_query": case["question"], "contextual_query": rewritten.query,
              "query_context": rewritten.diagnostic(), "candidate_k": 36,
              "before": fusion_probe(case["question"], records, embedder, store, keyword),
              "after": fusion_probe(rewritten.query, records, embedder, store, keyword)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"case": case["id"], "before_top3": report["before"][:3], "after_top3": report["after"][:3]}, ensure_ascii=False))
    print("Report:", args.output)


if __name__ == "__main__":
    main()
