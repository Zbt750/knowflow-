"""Offline P0 evidence freeze. Never constructs a provider, judge or DB engine.

Historical scores stay attached to their original run; they are not current
scores, and checkpoints are not independent samples. Full synthetic evidence
is archived locally under the Git-ignored eval/reports directory only.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.chat.evidence import validate_evidence_snapshot
from scripts.analyze_chat_generation_reports import _trace_for, summarize_cases
from scripts.run_ragas_chat_eval import load_cases, mean_metric

REPORTS = (
    "chat-baseline-v3-20260929.json",
    "chat-baseline-v3_1-20260929.json",
    "chat-file-focus-v4-20260930.json",
    "chat-file-focus-v4-retry-20260930.json",
    "chat-cross-file-budget-4000-20260930.json",
    "chat-cross-file-budget-6000-20260930.json",
    "chat_ragas_four_metrics_20260930_221106.json",
    "chat_ragas_four_metrics_20261001_105823.json",
)
CHECKPOINTS = {
    "chat_ragas_four_metrics_20260930_220702.json": REPORTS[-2],
    "chat_ragas_four_metrics_20261001_105512.json": REPORTS[-1],
}
DATASET = "eval/dataset/chat_baseline_v3_1.jsonl"
FIXTURES = tuple(f"eval/fixtures/baseline_{name}_v3.md" for name in ("math", "408", "user", "compare"))
METRICS = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")
PACKAGES = ("ragas", "openai", "instructor", "sentence-transformers", "chromadb",
            "SQLAlchemy", "pydantic", "httpx", "numpy", "torch")
REVIEW_DOCS = (
    "docs/current-rag-baseline-p0-2026-10-01.md",
    "docs/current-rag-baseline-p0-review-2026-10-01.json",
    "docs/rag-baseline-v3-2026-09-29.md", "docs/rag-baseline-v3_1-2026-09-29.md",
    "docs/rag-file-focus-v4-2026-09-30.md", "docs/rag-file-focus-v4-retry-2026-09-30.md",
    "docs/chat-cross-file-budget-pair-2026-09-30.md", "docs/release-foundations-and-rag-2026-10-01.md",
)
SAFE_CONFIG = ("model", "model_parameters", "embedding_model", "reranker_model",
               "prompt_version", "snapshot_version", "dataset_sha256", "retrieval_configuration")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_digest(value) -> str:
    return digest(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8"))


def source_path(name: str) -> bool:
    """Explicit reproducibility inputs, not .env/storage/Git/model caches."""
    path = Path(name)
    if path.suffix == ".py" and name.startswith(("backend/", "scripts/", "migrations/", "tests/")):
        return True
    return (name in {"pyproject.toml", "alembic.ini", "eval/README.md", DATASET,
                     "eval/dataset/chat_baseline_v3.jsonl", *FIXTURES, *REVIEW_DOCS}
            or (name.startswith("requirements") and path.suffix == ".txt"))


def chain_path(name: str) -> bool:
    return (name.startswith(("backend/chat/", "backend/retrieval/", "backend/ingestion/"))
            or name in {"backend/config.py", "backend/errors.py", "backend/app.py",
                        "backend/api/routes/chat.py", "backend/api/routes/materials.py",
                        "backend/services/retrieval_service.py", "backend/services/material_service.py",
                        "backend/services/model_settings_service.py"})


def case_record(row: dict) -> dict:
    trace = _trace_for(row) or {}
    failure = row.get("failure_diagnostic") or {}
    snapshot = row.get("actual_evidence") or failure.get("actual_evidence")
    audit = {"status": "missing", "request_id_binding": "not_available"}
    if snapshot is not None:
        # If a trace is absent, structural checks can still run, but don't claim
        # an independently observed message-ID binding from its own snapshot ID.
        request_id = trace.get("request_id") or failure.get("message_id")
        try:
            blocks, contexts = validate_evidence_snapshot(snapshot, request_id or snapshot.get("request_id"))
            audit = {"status": "valid", "request_id_binding": "trace_or_message" if request_id else "snapshot_only",
                     "version": snapshot["version"], "evidence_sha256": snapshot["evidence_sha256"],
                     "block_count": len(blocks), "model_called": snapshot.get("model_called"),
                     "context_chars": sum(map(len, contexts))}
        except (ValueError, TypeError, AttributeError) as exc:
            audit = {"status": "invalid", "error_type": type(exc).__name__}
    metrics = row.get("metrics", {})
    flags = []
    if row.get("error_type") or row.get("stream_error") or row.get("sse_parse_error"):
        flags.append("request_or_stream_error")
    if any(v.get("status") == "error" for v in metrics.values()):
        flags.append("judge_error")
    if metrics.get("context_precision", {}).get("value") == 0:
        flags.append("zero_context_precision")
    if any(isinstance(v.get("value"), (int, float)) and v["value"] < 0.8 for v in metrics.values()):
        flags.append("score_below_0_8_review_only_not_acceptance_threshold")
    duration = row.get("total_latency_ms", failure.get("total_ms"))
    if isinstance(duration, (int, float)) and duration > 30000:
        flags.append("over_30_seconds")
    if trace.get("retry_count", 0):
        flags.append("retried")
    if any(c.get("finish_reason") == "length" for c in trace.get("calls", [])):
        flags.append("output_limit_attempt")
    if trace.get("calls") and not trace.get("total_usage_complete"):
        flags.append("incomplete_usage")
    if row.get("behavior_check", {}).get("passed") is False:
        flags.append("behavior_check_failed_requires_content_review")
    return {
        "case_id": row["case_id"], "category": row.get("category"), "mode": row.get("mode"),
        "answerability": row.get("answerability"), "raw_case_sha256": json_digest(row),
        "answer_sha256": digest(row.get("answer", "").encode("utf-8")) if "answer" in row else None,
        "snapshot_audit": audit, "metrics": metrics,
        "manual_review": row.get("manual_review", {"status": "not_recorded"}),
        "citation_audit": row.get("citation_audit"), "behavior_check": row.get("behavior_check"),
        "precision_conflict_review": row.get("precision_conflict_review"),
        "latency": {key: row.get(key) for key in ("search_latency_ms", "first_delta_ms",
                    "first_useful_body_ms", "total_latency_ms", "server_response_duration_ms")},
        "first_body_semantics": "first heuristic visible body; can belong to discarded attempt; final-success TTFT not recorded",
        "failed_request_total_ms": failure.get("total_ms"),
        "generation_trace": trace or None,
        "setup_results": [{"question_sha256": digest(s.get("question", "").encode("utf-8")),
                           **{k: s.get(k) for k in ("total_ms", "usage", "retrieval_mode", "scope_resolved")}}
                          for s in row.get("setup_results", [])],
        # A type/code is safe in this metadata file. Full original diagnostics
        # remain in the local synthetic report archive, never a general log.
        "error_type": row.get("error_type"), "stream_error": row.get("stream_error"),
        "sse_parse_error": row.get("sse_parse_error"), "flags": flags,
    }


def report_record(name: str, data: dict, current: dict) -> dict:
    old = data.get("evaluation_configuration", {})
    before, now = old.get("workspace_file_sha256", {}), current["workspace_file_sha256"]
    changed = [n for n in sorted(set(before) | set(now)) if chain_path(n) and before.get(n) != now.get(n)]
    evaluation_changed = [n for n in ("scripts/run_ragas_chat_eval.py", "scripts/run_isolated_chat_ragas.py",
                                     "scripts/rag_baseline_manifest.py") if before.get(n) != now.get(n)]
    config_changes = {k: {"then": old.get(k), "now": current.get(k)}
                      for k in SAFE_CONFIG if old.get(k) != current.get(k)}
    # Whole module hashes are conservative. A prompt label alone is insufficient;
    # no automatic claim that different source bytes had equivalent behavior.
    compatible = bool(before) and not changed and not config_changes and not evaluation_changed
    rows = [case_record(c) for c in data["cases"]]
    return {
        "report": name, "created_at": data.get("created_at"),
        "classification": "exact_recorded_conditions_match" if compatible else "historical_not_current_measurement",
        "current_compatibility": {"generation_chain_changed_files": changed, "config_changes": config_changes,
                                  "evaluation_changed_files": evaluation_changed,
                                  "historical_environment_or_endpoint_identity": "not_fully_recorded"},
        "run_manifest": old, "judge": {k: data.get(k) for k in ("judge_model", "judge_max_tokens", "judge_provenance")},
        "original_summary": data.get("summary"),
        "recomputed_metrics": {key: mean_metric(data["cases"], key) for key in METRICS},
        "trace_summary": summarize_cases(data["cases"]), "cases": rows,
    }


def build_audit(current: dict, reports: dict[str, dict], checkpoints: dict[str, dict]) -> dict:
    records = [report_record(name, reports[name], current) for name in REPORTS]
    duplicates = []
    for name, canonical in CHECKPOINTS.items():
        checkpoint = checkpoints[name]
        same = (checkpoint.get("cases") == reports[canonical].get("cases")
                and checkpoint.get("evaluation_configuration") == reports[canonical].get("evaluation_configuration"))
        if not same:
            raise ValueError(f"checkpoint changed; cannot deduplicate: {name}")
        duplicates.append({"report": name, "canonical": canonical, "cases_equal": True,
                           "included_as_independent_samples": False})
    return {
        "version": "current-rag-baseline-audit-v1", "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "current_conditions_frozen_live_baseline_pending_authorization",
        "live_calls_performed": 0, "current_manifest": current,
        "reports": records, "duplicate_checkpoints": duplicates,
        "current_metrics": {key: {"status": "not_measured_for_current_frozen_version", "value": None} for key in METRICS},
        "rules": ["no_cross_version_pooled_mean", "retain_all_cases_errors_and_zero_scores",
                  "skipped_and_failed_metrics_are_not_zero", "snapshot_not_retrieval_reconstruction",
                  "manual_review_pending_is_not_human_verified", "budget_is_not_observed_usage"],
        "limitations": ["Only historical synthetic runs; no current full-dataset measurement",
                        "Upstream model alias/revision, historical endpoint fingerprints and full dependency locks absent",
                        "Snapshot records evidence blocks, not full system/history prompt or all retrieval candidates",
                        "Usage scope is answer generation; judge/intent and unreported failed attempts excluded",
                        "Independent human/expert review remains pending; agent review is not a substitute"],
    }


def collect_current() -> dict:
    from backend.config import get_settings
    from backend.services.model_settings_service import load_local_settings
    from scripts.rag_baseline_manifest import build_manifest
    from backend.chat import service
    settings = load_local_settings(get_settings().model_copy(update={"app_env": "dev"}))
    if settings.local_model_settings_error:
        raise ValueError("local model configuration unavailable; cannot freeze silently")
    current = build_manifest(settings, ROOT / DATASET, True)
    current["workspace_version_sha256"] = json_digest(current["workspace_file_sha256"])
    current["generation_chain_sha256"] = json_digest({n: h for n, h in current["workspace_file_sha256"].items() if chain_path(n)})
    current["fixture_sha256"] = {name: digest((ROOT / name).read_bytes()) for name in FIXTURES}
    current["endpoint_sha256"] = digest((settings.llm_base_url or "").encode("utf-8"))
    current["key_configured"] = bool(settings.llm_api_key and settings.llm_api_key.get_secret_value())
    current["generation_request_options"] = (
        {"reasoning_effort": "low"}
        if urlsplit(settings.llm_base_url or "").hostname == "api.deepseek.com"
        and settings.llm_model in {"deepseek-flash", "deepseek-v4-pro"} else {}
    )
    current["expected_judge_configuration"] = {
        "model": os.environ.get("RAGAS_LLM_MODEL") or settings.llm_model,
        "endpoint_sha256": digest((os.environ.get("RAGAS_BASE_URL") or settings.llm_base_url or "").encode("utf-8")),
        "key_source": "RAGAS_API_KEY" if os.environ.get("RAGAS_API_KEY") else "app_settings",
        "model_override_present": bool(os.environ.get("RAGAS_LLM_MODEL")),
        "endpoint_override_present": bool(os.environ.get("RAGAS_BASE_URL")),
        "actual_judge_invoked": False,
    }
    current["context_configuration"] = {"overview_max_chunks": service.OVERVIEW_MAX_CHUNKS,
                                        "overview_max_chars": service.OVERVIEW_MAX_CHARS,
                                        "cross_file_first_budget_policy": "max(configured, min(6000, retry_ceiling))",
                                        "token_estimate": "CJK ~1 char/token; other ~4 chars/token; not measured usage"}
    current["prompt_source_sha256"] = current["chat_source_sha256"]
    current["evaluation_method"] = {
        "source_sha256": current["workspace_file_sha256"].get("scripts/run_ragas_chat_eval.py"),
        "metrics": list(METRICS), "context_source": "actual-model-evidence-v2 only",
        "faithfulness": "grounded section only, excludes explicit general-reference section",
        "answer_relevancy": "3 judge-generated questions + local BGE cosine; not factual correctness",
        "context_precision": "reference-based per-block utility/ranking; original raw scores retained",
        "context_recall": "reference fact coverage over actual evidence, not completeness of answer",
        "not_applicable": "guard: all four skipped; general: only relevancy scored",
        "judge_temperature": 0, "judge_max_tokens_default": 8000,
        "judge_thinking": "disabled; Instructor JSON",
        "judge_retries": "OpenAI SDK max_retries=1; structured judge can make multiple internal calls",
        "historical_judge_identity": "see per-run judge; current judge not invoked",
        "retry_error_handling": "metric errors retained, no automatic full-run retry",
    }
    current["packages_observed_in_audit_environment"] = {}
    for name in PACKAGES:
        try:
            current["packages_observed_in_audit_environment"][name] = version(name)
        except PackageNotFoundError:
            current["packages_observed_in_audit_environment"][name] = None
    cases = load_cases(ROOT / DATASET)
    current["dataset_cases"] = [{"id": c.case_id, "category": c.category, "answerability": c.answerability,
                                 "setup_count": len(c.setup_questions)} for c in cases]
    current["planned_full_dataset_question_requests"] = sum(1 + len(c.setup_questions) for c in cases)
    return current


def freeze(output_dir: Path) -> dict:
    output_dir = output_dir.resolve()
    allowed = (ROOT / "eval/reports").resolve()
    if not allowed.is_relative_to(ROOT.resolve()) or not output_dir.is_relative_to(allowed) or output_dir == allowed:
        raise ValueError("freeze must use a new subdirectory of ignored eval/reports")
    current = collect_current()
    inputs = {name: (ROOT / "eval/reports" / name).read_bytes() for name in (*REPORTS, *CHECKPOINTS)}
    parsed = {name: json.loads(body) for name, body in inputs.items()}
    audit = build_audit(current, {n: parsed[n] for n in REPORTS}, {n: parsed[n] for n in CHECKPOINTS})
    # Metadata-only legacy inventory. Never import/score their reconstructed contexts.
    audit["legacy_inventory"] = [{"report": p.name, "sha256": digest(p.read_bytes()),
                                  "classification": "legacy_context_reconstruction_not_current_snapshot_baseline"}
                                 for p in sorted((ROOT / "eval/reports").glob("chat*20260926*.json"))]
    archive = dict((f"historical-reports/{n}", body) for n, body in inputs.items())
    for name, expected in current["workspace_file_sha256"].items():
        if source_path(name):
            source = (ROOT / name).resolve()
            if not source.is_relative_to(ROOT.resolve()):
                raise ValueError(f"source escapes workspace: {name}")
            body = source.read_bytes()
            if digest(body) != expected:
                raise ValueError(f"workspace changed during freeze: {name}")
            archive[f"workspace/{name}"] = body
    audit["archive_entry_sha256"] = {n: digest(body) for n, body in sorted(archive.items())}
    audit["source_artifact_sha256"] = {n: digest(body) for n, body in inputs.items()}
    # mkdir and exclusive writes refuse any previous freeze. No raw originals are modified.
    output_dir.mkdir(parents=True, exist_ok=False)
    bundle = output_dir / "reproduction-inputs.zip"
    with zipfile.ZipFile(bundle, "x", compression=zipfile.ZIP_DEFLATED) as target:
        for name, body in sorted(archive.items()):
            target.writestr(name, body)
    audit["reproduction_archive_sha256"] = digest(bundle.read_bytes())
    with (output_dir / "baseline.json").open("x", encoding="utf-8") as target:
        json.dump(audit, target, ensure_ascii=False, indent=2)
    return audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    audit = freeze(args.output_dir)
    print(json.dumps({"status": audit["status"], "output_dir": str(args.output_dir),
                      "historical_runs": len(audit["reports"]), "live_calls": 0,
                      "workspace_version_sha256": audit["current_manifest"]["workspace_version_sha256"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
