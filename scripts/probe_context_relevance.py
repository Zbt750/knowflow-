"""Offline synthetic calibration, real cached embedding, no DB/LLM or production edits.

Uses the existing chunker, three retrieval routes, fusion and MMR. It does not
exercise file overview, DB version validation, CrossEncoder or final prompt.
Human/agent labels are evaluation inputs only, never selection inputs.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.chat.query_context import contextualize_retrieval_query
from backend.chat.service import build_chat_retrieval_plan
from backend.retrieval.fusion import fuse_ranked_ids
from backend.retrieval.keyword import KeywordIndex
from backend.retrieval.protocols import IndexFilter, RetrievalHit
from backend.retrieval.vector_store import InMemoryVectorStore
from backend.services.retrieval_service import mmr_select_hits
from scripts.probe_followup_retrieval import synthetic_records

LABEL_PATH = ROOT / "eval/dataset/context_relevance_p6_v1.json"
BASELINE_PATH = ROOT / "eval/dataset/chat_baseline_v3_1.jsonl"
STRATEGIES = ("baseline", "cosine_0.50", "cosine_0.60", "cosine_0.70", "relative_0.85")


def load_cases():
    labels = json.loads(LABEL_PATH.read_text(encoding="utf-8"))
    baseline = {c["id"]: c for c in (
        json.loads(line) for line in BASELINE_PATH.read_text(encoding="utf-8").splitlines()
    )}
    cases = []
    for case_id, headings in labels["baseline_labels"].items():
        source = baseline[case_id]
        cases.append({"id": case_id, "question": source["question"],
                      "setup_questions": source.get("setup_questions", []),
                      "required_headings": headings})
    cases.extend(labels["additional_cases"])
    if len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Duplicate case IDs")
    return labels, cases


def select_experiment(hits, strategy):
    """Exploratory cut only, not a safe production policy. Unknown score retained."""
    if strategy == "baseline":
        return list(hits)
    if strategy not in STRATEGIES:
        raise ValueError("Unknown strategy")
    known = [h.vector_score for h in hits if h.vector_score is not None and math.isfinite(h.vector_score)]
    if not known:
        return list(hits)
    threshold = max(known) * 0.85 if strategy == "relative_0.85" else float(strategy.removeprefix("cosine_"))
    return [h for h in hits if h.vector_score is None or not math.isfinite(h.vector_score)
            or h.vector_score >= threshold]


def measure(hits, required):
    expected = set(required)
    found = {heading for h in hits for heading in h.heading_path} & expected
    useful = sum(bool(set(h.heading_path) & expected) for h in hits)
    return {"selected_count": len(hits), "useful_count": useful,
            "irrelevant_count": len(hits) - useful,
            "relevant_fraction": useful / len(hits) if hits else None,
            "required_heading_recall": len(found) / len(expected) if expected else None,
            "missing_headings": sorted(expected - found),
            "all_required_present": expected <= found,
            "absent_topic_false_evidence": bool(hits) if not expected else None}


def retrieve(query, plan, records, embedder, store, keyword):
    filters = IndexFilter(source_types=("builtin",), index_versions=("probe-v1",))
    vector = store.query(embedder.encode([query])[0], top_k=plan.candidate_k, index_filter=filters)
    title = keyword.search_title_tree(query, top_k=plan.candidate_k, index_filter=filters)
    body = keyword.search(query, top_k=plan.candidate_k, index_filter=filters)
    fused = fuse_ranked_ids({"vector": [h.chunk_id for h in vector],
                            "title": [i for i, _ in title], "keyword": [i for i, _ in body]},
                           top_k=plan.candidate_k)
    by_id = {r.chunk_id: r for r in records}
    scores = {h.chunk_id: h.score for h in vector}
    hits = []
    for key, score in fused:
        r = by_id[key]
        hits.append(RetrievalHit(chunk_id=key, material_id=r.material_id, material_title=r.material_title,
                                 source_type=r.source_type, index_version=r.index_version,
                                 ordinal=r.ordinal, content=r.content, heading_path=r.heading_path,
                                 kp_ids=(), score=score, fused_score=score, vector_score=scores.get(key)))
    return mmr_select_hits(hits, top_k=plan.top_k, embedder=embedder) if plan.diversify else hits[:plan.top_k]


def run_probe(embedder):
    labels, cases = load_cases()
    records = synthetic_records()
    available = {heading for r in records for heading in r.heading_path}
    for c in cases:
        if not set(c["required_headings"]) <= available:
            raise ValueError(f"Stale label: {c['id']}")
    started = time.perf_counter()
    store = InMemoryVectorStore(embedding_model=embedder.model_name)
    store.upsert(records, embedder.encode([r.content for r in records]))
    keyword = KeywordIndex()
    keyword.rebuild(records)
    index_ms = round((time.perf_counter() - started) * 1000, 3)
    rows = []
    for c in cases:
        query = contextualize_retrieval_query(c["question"], c.get("setup_questions", []))
        plan = build_chat_retrieval_plan(c["question"], provider=None)
        started = time.perf_counter()
        hits = retrieve(query.query, plan, records, embedder, store, keyword)
        retrieval_ms = round((time.perf_counter() - started) * 1000, 3)
        selections = {strategy: select_experiment(hits, strategy) for strategy in STRATEGIES}
        rows.append({**c, "retrieval_query": query.query, "query_context": query.diagnostic(),
                     "plan": asdict(plan), "retrieval_ms": retrieval_ms,
                     "candidates": [{"chunk_id": str(h.chunk_id), "heading_path": list(h.heading_path),
                                     "cosine": h.vector_score, "rrf": h.fused_score} for h in hits],
                     "strategies": {s: {**measure(selected, c["required_headings"]),
                                         "chunk_ids": [str(h.chunk_id) for h in selected]}
                                    for s, selected in selections.items()}})
    summaries = {}
    for s in STRATEGIES:
        answerable = [r for r in rows if r["required_headings"]]
        metrics = [r["strategies"][s] for r in rows]
        summaries[s] = {"answerable_cases": len(answerable),
                        "fully_covered_cases": sum(r["strategies"][s]["all_required_present"] for r in answerable),
                        "coverage_regressions_vs_baseline": [r["id"] for r in answerable
                            if r["strategies"][s]["required_heading_recall"] < r["strategies"]["baseline"]["required_heading_recall"]],
                        "selected_chunks": sum(m["selected_count"] for m in metrics),
                        "irrelevant_chunks": sum(m["irrelevant_count"] for m in metrics),
                        "absent_topic_false_evidence_cases": sum(m["absent_topic_false_evidence"] is True for m in metrics)}
    return {"version": "offline-context-relevance-p6-v1", "label_version": labels["version"],
            "label_review_status": labels["review_status"], "embedding_model": embedder.model_name,
            "scope": "synthetic_three_route_fusion_identity_rerank_and_mmr_not_full_chat",
            "external_model_calls": 0, "database_access": False, "production_policy_changed": False,
            "ragas_metrics": None, "observed_generation_usage": None, "index_load_ms": index_ms,
            "source_sha256": {p: sha256((ROOT / p).read_bytes()).hexdigest() for p in (
                "eval/dataset/context_relevance_p6_v1.json", "eval/dataset/chat_baseline_v3_1.jsonl",
                "eval/fixtures/baseline_math_v3.md", "eval/fixtures/baseline_408_v3.md",
                "backend/chat/service.py", "backend/chat/query_context.py", "backend/services/retrieval_service.py",
                "scripts/probe_followup_retrieval.py", "scripts/probe_context_relevance.py")},
            "summary": summaries, "cases": rows,
            "limitations": ["Agent-reviewed labels, not independent human truth",
                            "Tiny synthetic corpus; not a held-out validation set",
                            "No final generation/DB validation/CrossEncoder/file-overview path",
                            "Heading coverage is not factual correctness or RAGAS recall",
                            "Warm local retrieval latency is not service or generation latency",
                            "Thresholds are exploratory, not approved production configuration"]}


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
    report = run_probe(SentenceTransformerEmbedder(settings.embedding_model,
                        cache_dir=str((ROOT / settings.model_cache_dir).resolve())))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print("Report:", args.output)


if __name__ == "__main__":
    main()
