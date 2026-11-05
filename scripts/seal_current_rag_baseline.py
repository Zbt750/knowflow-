"""Seal one completed, authorized synthetic P0 run without making any calls.

The preflight archive and raw report are immutable inputs. Keep every score,
failure and pending human review; never pool historical/current metrics.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import statistics
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.freeze_current_rag_baseline import (
    SAFE_CONFIG, chain_path, collect_current, digest, json_digest, report_record,
)


def latency_stats(values):
    return {"n": len(values), "mean_ms": round(statistics.fmean(values), 1) if values else None,
            "median_ms": round(statistics.median(values), 1) if values else None,
            "max_ms": max(values) if values else None}


def build_measurement(audit: dict, raw: dict, review: dict, current: dict) -> dict:
    if "summary" not in raw or raw.get("status") == "in_progress":
        raise ValueError("cannot seal an incomplete checkpoint")
    manifest = raw["evaluation_configuration"]
    before = audit["current_manifest"]
    expected = [c["id"] for c in before["dataset_cases"]]
    if [c["case_id"] for c in raw["cases"]] != expected:
        raise ValueError("case set/order differs from frozen dataset; no sample filtering allowed")
    if manifest.get("planned_question_requests") != 18 or manifest.get("question_request_limit") != 18:
        raise ValueError("run lacks the authorized 18-request guard")
    for key in SAFE_CONFIG:
        if manifest.get(key) != before.get(key) or manifest.get(key) != current.get(key):
            raise ValueError(f"measured configuration changed: {key}")
    for key in ("endpoint_sha256", "fixture_sha256", "expected_judge_configuration"):
        if current.get(key) != before.get(key):
            raise ValueError(f"preflight configuration changed: {key}")
    for name, expected_hash in before["workspace_file_sha256"].items():
        if chain_path(name) or name.startswith(("eval/dataset/", "eval/fixtures/")) or name in (
            "scripts/run_ragas_chat_eval.py", "scripts/run_isolated_chat_ragas.py", "scripts/rag_baseline_manifest.py"
        ):
            if manifest["workspace_file_sha256"].get(name) != expected_hash or current["workspace_file_sha256"].get(name) != expected_hash:
                raise ValueError(f"measured source changed: {name}")
    if {c["case_id"] for c in review["case_reviews"]} != set(expected) or review.get("human_review_status") != "pending":
        raise ValueError("review must cover every case and preserve independent-human pending status")
    result = report_record("authorized-current-run", raw, current)
    if result["classification"] != "exact_recorded_conditions_match":
        raise ValueError("current measurement cannot be matched to current source/config")
    for source, normalized in zip(raw["cases"], result["cases"]):
        if "metrics" in source and normalized["snapshot_audit"]["status"] != "valid":
            raise ValueError("scored case lacks valid actual evidence; cannot claim integrity")
        precision = source.get("metrics", {}).get("context_precision", {})
        diagnostics = precision.get("diagnostics", [])
        complete = (precision.get("diagnostics_complete") is True
                    and len(diagnostics) == normalized["snapshot_audit"].get("block_count")
                    and all(d.get("verdict") in (0, 1) for d in diagnostics))
        relevant = sum(d["verdict"] for d in diagnostics) if complete else None
        normalized["precision_block_diagnostic"] = {
            "complete": complete, "positive_verdicts": relevant,
            "total_verdicts": len(diagnostics),
            "positive_fraction": round(relevant / len(diagnostics), 4) if complete and diagnostics else None,
            "meaning": "judge-verdict diagnostic, NOT a replacement RAGAS score or human truth",
        }
        snapshot = source.get("actual_evidence") or {}
        labels = {b["label"] for b in snapshot.get("blocks", [])}
        used = set(re.findall(r"\[(C[1-9]\d*)\]", source.get("answer", "")))
        normalized["citation_labels"] = {"used": sorted(used), "unused_evidence_labels": sorted(labels - used),
                                         "invalid_answer_labels": sorted(used - labels),
                                         "limit": "unused does not necessarily mean irrelevant; ID match is not semantic support"}
    generated = [c for c in raw["cases"] if (c.get("generation_trace") or {}).get("calls")]
    observed = sum((c["generation_trace"].get("observed_usage") or {}).get("total_tokens", 0) for c in generated)
    setups = [s for c in raw["cases"] for s in c.get("setup_results", [])]
    setup_observed = sum((s.get("usage") or {}).get("total_tokens", 0) for s in setups)
    metric_statuses = [m.get("status") for c in raw["cases"] for m in c.get("metrics", {}).values()]
    return {
        "version": "current-rag-baseline-measured-v1", "sealed_at": datetime.now(timezone.utc).isoformat(),
        "status": "frozen_current_diagnostic_baseline_with_known_bad_cases",
        "quality_pass_claimed": False, "p1_started": False,
        "measured_workspace_version_sha256": json_digest(manifest["workspace_file_sha256"]),
        "measured_manifest": manifest, "preflight_safe_conditions": before,
        "generation_source_matches_preflight_and_current": True,
        "measurement": result, "content_review": review,
        "current_ragas_metrics": result["recomputed_metrics"],
        "actual_run_judge": {"model": raw.get("judge_model"), "max_tokens": raw.get("judge_max_tokens"),
                             "provenance": raw.get("judge_provenance"),
                             "actual_judge_invoked": any(s in ("scored", "error") for s in metric_statuses),
                             "upstream_revision": "not_observed"},
        "request_and_metric_accounting": {
            "planned_and_guarded_question_requests": 18, "target_results": len(raw["cases"]),
            "successful_setup_results": len(setups), "generated_target_results": len(generated),
            "scored_metric_jobs": metric_statuses.count("scored"), "error_metric_jobs": metric_statuses.count("error"),
            "skipped_metric_jobs": metric_statuses.count("skipped"),
            "upstream_call_count": "not fully observed; question requests are not model-call count",
        },
        "generated_target_latency": {key: latency_stats([c[key] for c in generated if isinstance(c.get(key), (int, float))])
                                     for key in ("first_delta_ms", "first_useful_body_ms", "total_latency_ms")},
        "usage": {"target_observed_total_tokens": observed, "setup_observed_total_tokens": setup_observed,
                  "observed_total_tokens_lower_bound": observed + setup_observed,
                  "scope": "target generation traces + final setup usage only; judge/intent excluded",
                  "setup_all_attempt_usage": "not recorded; no inference about setup retries",
                  "unknown_usage_is_not_zero": True, "monetary_total": None},
        "historical_evidence": audit["reports"], "duplicate_checkpoints": audit["duplicate_checkpoints"],
        "legacy_inventory": audit["legacy_inventory"], "limitations": audit["limitations"][1:],
        "interpretation": ["No pooled cross-version score", "No score adjustments or bad-case exclusions",
                           "Zero errors is not zero bugs", "Human review pending; agent review is not independent expert review",
                           "Precision is rank-sensitive average precision; high score need not mean little irrelevant context",
                           "One run cannot prove latency/cost/quality improvements or universal coverage"],
    }


def seal(audit_dir: Path, live_report: Path, review_file: Path, output_dir: Path) -> dict:
    root = (ROOT / "eval/reports").resolve()
    output_dir = output_dir.resolve()
    if not root.is_relative_to(ROOT.resolve()) or not output_dir.is_relative_to(root) or output_dir == root:
        raise ValueError("output must be a new directory under ignored eval/reports")
    audit_bytes = (audit_dir / "baseline.json").read_bytes()
    audit = json.loads(audit_bytes)
    raw_bytes, review_bytes = live_report.read_bytes(), review_file.read_bytes()
    raw, review = json.loads(raw_bytes), json.loads(review_bytes)
    result = build_measurement(audit, raw, review, collect_current())
    result["measurement"]["report"] = live_report.name
    old_bundle = audit_dir / "reproduction-inputs.zip"
    if digest(old_bundle.read_bytes()) != audit["reproduction_archive_sha256"]:
        raise ValueError("preflight archive checksum mismatch")
    entries = {}
    with zipfile.ZipFile(old_bundle) as old:
        if set(old.namelist()) != set(audit["archive_entry_sha256"]):
            raise ValueError("preflight archive entry set mismatch")
        for name, checksum in audit["archive_entry_sha256"].items():
            body = old.read(name)
            if digest(body) != checksum:
                raise ValueError("preflight archive entry corrupted")
            entries[name] = body
    entries["preflight/baseline.json"] = audit_bytes
    entries["current-run/raw-report.json"] = raw_bytes
    entries["current-run/assisted-review.json"] = review_bytes
    for name in ("scripts/seal_current_rag_baseline.py", "tests/unit/test_seal_current_rag_baseline.py",
                 "docs/current-rag-baseline-measured-2026-10-01.md"):
        entries[f"closure-artifacts/{name}"] = (ROOT / name).read_bytes()
    result["source_artifact_sha256"] = {"preflight_audit": digest(audit_bytes), "raw_live_report": digest(raw_bytes),
                                       "assisted_review": digest(review_bytes)}
    result["archive_entry_sha256"] = {name: digest(body) for name, body in sorted(entries.items())}
    output_dir.mkdir(parents=True, exist_ok=False)
    bundle = output_dir / "reproduction-inputs.zip"
    with zipfile.ZipFile(bundle, "x", compression=zipfile.ZIP_DEFLATED) as new:
        for name, body in sorted(entries.items()):
            new.writestr(name, body)
    result["reproduction_archive_sha256"] = digest(bundle.read_bytes())
    with (output_dir / "baseline.json").open("x", encoding="utf-8") as target:
        json.dump(result, target, ensure_ascii=False, indent=2)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-dir", required=True, type=Path)
    parser.add_argument("--live-report", required=True, type=Path)
    parser.add_argument("--review-file", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    result = seal(args.audit_dir, args.live_report, args.review_file, args.output_dir)
    print(json.dumps({"status": result["status"], "output_dir": str(args.output_dir),
                      "new_model_or_judge_calls": 0, "quality_pass_claimed": False}))


if __name__ == "__main__":
    main()
