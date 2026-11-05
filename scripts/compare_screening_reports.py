"""Offline comparison of the two bounded P6 reports; never rescore or rewrite them."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.chat.evidence import validate_evidence_snapshot
from scripts.run_ragas_chat_eval import validate_screening_snapshot

CASE_IDS = {"math-followup", "408-page"}


def compare(off, filtered):
    for field in ("dataset_sha256", "model", "model_parameters", "embedding_model", "reranker_model",
                  "prompt_version", "snapshot_version", "retrieval_configuration"):
        if field not in off["evaluation_configuration"] or off["evaluation_configuration"][field] != filtered["evaluation_configuration"].get(field):
            raise ValueError(f"Incompatible comparison: {field}")
    source = off["evaluation_configuration"]["workspace_file_sha256"]
    other = filtered["evaluation_configuration"]["workspace_file_sha256"]
    relevant = {k for k in source.keys() | other.keys() if k.startswith(("backend/", "scripts/"))}
    if any(source.get(k) != other.get(k) for k in relevant):
        raise ValueError("Generation/evaluation source changed between arms")
    rows = []
    total_usage = {}
    for mode, report in (("off", off), ("filter", filtered)):
        manifest = report["evaluation_configuration"]
        if manifest["context_screening_configuration"]["mode"] != mode:
            raise ValueError("Manifest arm mismatch")
        if (manifest.get("planned_question_requests") != 3 or manifest.get("question_request_limit") != 3
                or set(manifest.get("selected_case_ids", [])) != CASE_IDS):
            raise ValueError("Bounded question scope mismatch")
        cases = report["cases"]
        if len(cases) != 2 or {c["case_id"] for c in cases} != CASE_IDS:
            raise ValueError("Case set mismatch; do not silently omit a failed case")
        usage_sum = 0
        usage_complete = True
        for case in cases:
            trace = case.get("generation_trace", {})
            snapshot = case.get("actual_evidence")
            validate_evidence_snapshot(snapshot, trace.get("request_id"))
            validate_screening_snapshot(snapshot, mode)
            usage = trace.get("observed_usage", {}).get("total_tokens")
            usage_sum += usage or 0
            usage_complete &= isinstance(usage, int)
            for setup in case.get("setup_results", []):
                setup_usage = (setup.get("usage") or {}).get("total_tokens")
                usage_sum += setup_usage or 0
                usage_complete &= isinstance(setup_usage, int)
        total_usage[mode] = {"observed_generation_tokens_including_setup": usage_sum,
                             "all_turn_usage_available_in_this_arm": usage_complete,
                             "excludes_judges_and_unobserved_intent_calls": True,
                             "setup_retry_trace_available": False}
    for case_id in sorted(CASE_IDS):
        pair = {}
        for mode, report in (("off", off), ("filter", filtered)):
            c = next(c for c in report["cases"] if c["case_id"] == case_id)
            trace = c["generation_trace"]
            precision = c["metrics"]["context_precision"]
            useful = sum(d.get("verdict") == 1 for d in precision.get("diagnostics", []))
            pair[mode] = {"metrics": c["metrics"], "behavior": c.get("behavior"),
                          "context_count": len(c["actual_evidence"]["contexts"]),
                          "judge_positive_contexts": useful,
                          "precision_diagnostics_complete": precision.get("diagnostics_complete"),
                          "screening": c["actual_evidence"]["context_screening"],
                          "total_latency_ms": c.get("total_latency_ms"), "first_delta_ms": c.get("first_delta_ms"),
                          "observed_usage": trace.get("observed_usage"), "retry_count": trace.get("retry_count"),
                          "finish_reasons": [x.get("finish_reason") for x in trace.get("calls", [])]}
        rows.append({"case_id": case_id, "arms": pair})
    return {"version": "p6-screening-paired-review-v1", "additional_model_calls": 0,
            "question_requests": 6, "target_answers": 4, "metric_jobs": 16,
            "generation_usage": total_usage, "cases": rows,
            "decision": "keep_default_off_pending_quality_repairs_and_broader_validation",
            "limitations": ["Two cases, one stochastic run each, not significance or overall accuracy",
                            "Same model alias, no immutable upstream model identity",
                            "Faithfulness and Precision may miss raw wording issues or count meta-statements",
                            "Setup retry/finish trace and total judge cost are not observed",
                            "Human domain review remains pending"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--off", type=Path, required=True)
    parser.add_argument("--filter", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; refuse overwrite")
    paths = {"off": args.off, "filter": args.filter}
    blobs = {k: p.read_bytes() for k, p in paths.items()}
    report = compare(*(json.loads(blobs[k]) for k in ("off", "filter")))
    report["source_reports"] = {k: {"path": str(p), "sha256": sha256(blobs[k]).hexdigest()} for k, p in paths.items()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print("Comparison saved; no generation, judging, database access or source report changes.")


if __name__ == "__main__":
    main()
