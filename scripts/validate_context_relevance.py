"""Fixed-policy validation on new synthetic wording and multi-chunk evidence.

No LLM, DB, downloads or production policy writes. Calibration strategies are
imported unchanged; new results must not be used to claim independent subject QA.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import time
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.chat.query_context import contextualize_retrieval_query
from backend.chat.service import build_chat_retrieval_plan
from backend.ingestion.chunker import build_chunk_drafts
from backend.ingestion.title_tree import source_blocks_from_title_tree
from backend.retrieval.keyword import KeywordIndex
from backend.retrieval.protocols import VectorRecord
from backend.retrieval.vector_store import InMemoryVectorStore
from scripts.probe_context_relevance import STRATEGIES, measure, retrieve, select_experiment
from scripts.probe_followup_retrieval import synthetic_records

DATASET = ROOT / "eval/dataset/context_relevance_validation_p6_v1.json"
LONG_FIXTURE = ROOT / "eval/fixtures/context_validation_long_p6.md"


def validation_records():
    records = synthetic_records()
    text = LONG_FIXTURE.read_text(encoding="utf-8")
    filename = LONG_FIXTURE.name
    for draft in build_chunk_drafts(text, source_blocks_from_title_tree(text)):
        records.append(VectorRecord(chunk_id=uuid5(NAMESPACE_URL, filename + str(draft.ordinal)),
                                    material_id=uuid5(NAMESPACE_URL, filename), index_version="probe-v1",
                                    ordinal=draft.ordinal, content=draft.content, heading_path=draft.heading_path,
                                    source_type="builtin", material_title="合成长段落验证讲义"))
    return records


def evidence_measure(hits, case):
    metrics = measure(hits, case["required_headings"])
    fragments = case.get("required_fragments", [])
    relevant = [h for h in hits if set(h.heading_path) & set(case["required_headings"])]
    missing = [text for text in fragments if not any(text in h.content for h in relevant)]
    return {**metrics, "all_required_present": metrics["all_required_present"] if case["required_headings"] else None,
            "required_fragment_count": len(fragments), "missing_fragments": missing,
            "all_required_evidence_present": metrics["all_required_present"] and not missing
                if case["required_headings"] else None}


def validate_cases(dataset, records):
    cases = dataset["cases"]
    if len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Duplicate validation case IDs")
    headings = {h for r in records for h in r.heading_path}
    for c in cases:
        if not set(c["required_headings"]) <= headings:
            raise ValueError(f"Stale heading label: {c['id']}")
        relevant = [r for r in records if set(r.heading_path) & set(c["required_headings"])]
        if any(not any(fragment in r.content for r in relevant) for fragment in c.get("required_fragments", [])):
            raise ValueError(f"Unlocatable fragment label: {c['id']}")


def run_validation(embedder):
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    records = validation_records()
    validate_cases(dataset, records)
    source_paths = ["scripts/validate_context_relevance.py", "scripts/probe_context_relevance.py",
                    "scripts/probe_followup_retrieval.py", "eval/dataset/context_relevance_validation_p6_v1.json",
                    "eval/fixtures/context_validation_long_p6.md", "eval/fixtures/baseline_math_v3.md",
                    "eval/fixtures/baseline_408_v3.md", "backend/chat/service.py", "backend/chat/query_context.py",
                    "backend/services/retrieval_service.py", "backend/retrieval/keyword.py",
                    "backend/retrieval/fusion.py", "backend/ingestion/chunker.py", "backend/ingestion/title_tree.py",
                    "backend/retrieval/embedding.py"]
    hashes = {p: sha256((ROOT / p).read_bytes()).hexdigest() for p in source_paths}
    started = time.perf_counter()
    store = InMemoryVectorStore(embedding_model=embedder.model_name)
    store.upsert(records, embedder.encode([r.content for r in records]))
    keyword = KeywordIndex()
    keyword.rebuild(records)
    index_ms = round((time.perf_counter() - started) * 1000, 3)
    rows = []
    for case in dataset["cases"]:
        query = contextualize_retrieval_query(case["question"], case.get("setup_questions", []))
        plan = build_chat_retrieval_plan(case["question"], provider=None)
        started = time.perf_counter()
        hits = retrieve(query.query, plan, records, embedder, store, keyword)
        ms = round((time.perf_counter() - started) * 1000, 3)
        results = {}
        for strategy in STRATEGIES:
            selected = select_experiment(hits, strategy)
            results[strategy] = {**evidence_measure(selected, case), "chunk_ids": [str(h.chunk_id) for h in selected]}
        rows.append({**case, "retrieval_query": query.query, "query_context": query.diagnostic(),
                     "retrieval_ms": ms, "intent": plan.intent, "top_k": plan.top_k,
                     "candidate_k": plan.candidate_k, "diversify": plan.diversify,
                     "candidates": [{"chunk_id": str(h.chunk_id), "material_title": h.material_title,
                                     "heading_path": list(h.heading_path), "cosine": h.vector_score,
                                     "rrf": h.fused_score, "content_sha256": sha256(h.content.encode()).hexdigest(),
                                     "matched_fragments": [f for f in case.get("required_fragments", []) if f in h.content]}
                                    for h in hits], "strategies": results})
    summary = {}
    answerable = [c for c in rows if c["required_headings"]]
    for s in STRATEGIES:
        summary[s] = {"answerable_cases": len(answerable),
                      "fully_covered_heading_cases": sum(c["strategies"][s]["all_required_present"] for c in answerable),
                      "fully_covered_evidence_cases": sum(c["strategies"][s]["all_required_evidence_present"] for c in answerable),
                      "missing_evidence_cases": [c["id"] for c in answerable if not c["strategies"][s]["all_required_evidence_present"]],
                      "new_failure_vs_baseline": [c["id"] for c in answerable
                          if c["strategies"]["baseline"]["all_required_evidence_present"]
                          and not c["strategies"][s]["all_required_evidence_present"]],
                      "selected_chunks": sum(c["strategies"][s]["selected_count"] for c in rows),
                      "non_required_heading_chunks": sum(c["strategies"][s]["irrelevant_count"] for c in rows),
                      "absent_topic_false_evidence_cases": sum(c["strategies"][s]["absent_topic_false_evidence"] is True for c in rows)}
    if hashes != {p: sha256((ROOT / p).read_bytes()).hexdigest() for p in source_paths}:
        raise RuntimeError("Source changed during validation")
    return {"version": "offline-context-validation-p6-v1", "dataset_version": dataset["version"],
            "label_review_status": dataset["review_status"], "policy": dataset["selection_policy"],
            "embedding_model": embedder.model_name, "external_model_calls": 0, "database_access": False,
            "production_policy_changed": False, "ragas_metrics": None, "observed_usage": None,
            "source_sha256": hashes, "index_load_ms": index_ms, "corpus_chunks": len(records),
            "summary": summary, "cases": rows,
            "limitations": ["New wording but same author, synthetic corpus, not independent subject review",
                            "Sections can be covered while necessary fragments are missing",
                            "Identity rerank; no final prompt, DB active-version checks or generation",
                            "No file-overview pipeline coverage or private data",
                            "Exact fragment match is an evidence coverage proxy, not semantic grading",
                            "No production threshold may be justified from this small sample alone"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Report exists; refuse overwrite")
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    from backend.config import get_settings
    from backend.retrieval.embedding import SentenceTransformerEmbedder
    settings = get_settings()
    report = run_validation(SentenceTransformerEmbedder(settings.embedding_model,
                            cache_dir=str((ROOT / settings.model_cache_dir).resolve())))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print("Report:", args.output)


if __name__ == "__main__":
    main()
