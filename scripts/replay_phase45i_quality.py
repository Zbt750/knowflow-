"""Offline replay of frozen Phase 4.5I provider outputs; never calls a model."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RUN = ROOT / "storage/quality-audits/phase45i-real-20261009/actual-run"
FIXTURE = ROOT / "tests/fixtures/phase45i_generation_targets.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=RUN / "phase45i-fix-replay")
    args = parser.parse_args()
    from backend.models.learning import KnowledgePoint
    from backend.services.question_generation import Output, assess_output, verify_explanation_step
    from backend.services.quality_verifiers import verify_problem

    calls = [json.loads(line) for line in (RUN / "provider-calls.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    nodes = {row["code"]: row for row in fixture["nodes"]}
    summary = json.loads((RUN / "window-0-summary.json").read_text(encoding="utf-8"))
    progress = json.loads((RUN / "progress.json").read_text(encoding="utf-8"))
    # progress.json is the complete per-target ledger; window summaries may
    # omit a row when its preflight failed before the summary was appended.
    original = {row["target_id"]: row for row in progress.get("quality_rows", [])}
    original.update({row["target_id"]: {**original.get(row["target_id"], {}), **row}
                     for row in summary.get("targets_attempted_this_window", [])})
    results = []
    for call in calls:
        target_id = call["target_id"]
        prior = original.get(target_id, {})
        node_code = target_id.split(":", 2)[1]
        target_node = nodes[node_code]
        subject = "408" if target_node["subject"] == "408" else "考研数学"
        node = KnowledgePoint(id=UUID(target_node["id"]), code=node_code, name=target_node["name"],
            subject=subject, is_active=True, is_assessable=True, is_reference_only=True)
        base = {"call_number": call["call_number"], "target_id": target_id,
            "subject": target_node["subject"], "node": target_node["name"],
            "prompt_version": call.get("prompt_version"), "model": call.get("model"),
            "original_quality_status": prior.get("quality_status"),
            "original_service_status": (prior.get("result") or {}).get("status"),
            "original_service_reasons": prior.get("failure_reasons", []),
            "http_status": call.get("http_status"), "finish_reason": call.get("finish_reason"),
            "usage": call.get("usage"), "elapsed_ms": call.get("elapsed_ms"),
            "peak_price_cost_cny_estimate": call.get("peak_price_cost_cny")}
        raw = call.get("response_content")
        if not raw:
            state = "OUTPUT_TRUNCATED" if call.get("finish_reason") == "length" else "BLOCKED"
            results.append({**base, "replay_status": state, "candidate_eligible_for_personal_save": False,
                            "database_saved": False,
                            "raw_response_preserved": True, "reason": call.get("error_category") or call.get("finish_reason")})
            continue
        try:
            output = Output.model_validate(json.loads(raw))
        except Exception as exc:
            results.append({**base, "replay_status": "FORMAT_ERROR", "candidate_eligible_for_personal_save": False,
                            "database_saved": False,
                            "reason": type(exc).__name__})
            continue
        trace = {"model": call.get("model"), "mode": "real_model", "model_calls": 1,
                 "prompt_version": call.get("prompt_version"), "usage": call.get("usage")}
        difficulty = {"basic": "basic", "improved": "medium", "comprehensive": "advanced"}.get(
            prior.get("difficulty", "basic"), "basic")
        assessment = assess_output(output, node, request_id=f"phase45i-frozen-replay:{call['call_number']}",
            mode="original", family=target_node["expected_family"], trace=trace,
            difficulty=difficulty)
        q = assessment["question"]
        independent = verify_problem(q)
        from backend.services.question_quality import audit_question
        audit = audit_question(q, node, source_check={"status":"UNKNOWN", "reason":"offline_replay_source_not_checked"}, candidate=True)
        from backend.services.answer_grading import available_practice_grading_method
        practice_method = available_practice_grading_method(question_type=q.question_type, config=q.grading_config,
            expected=q.correct_answer, options=q.options, answer_provenance=q.answer_provenance,
            content_trust=q.content_trust, answer_reliability=q.answer_reliability)
        steps = [{"expression": step.get("expression"), "value": step.get("value"),
                  "result": verify_explanation_step(step.get("expression"), step.get("value"))}
                 for step in output.steps]
        results.append({**base, "replay_status": assessment["review_status"],
            "legacy_compat_status": assessment["status"], "errors": assessment["errors"],
            "uncertainties": assessment.get("uncertainties", []), "independent_verifier": independent,
            "final_value": output.final_value, "final_value_check": __import__(
                "backend.services.phase45i_quality_verifiers", fromlist=["final_value_matches"]).final_value_matches(q, output.final_value, independent or {}),
            "steps": steps, "quality": assessment["quality"],
            "candidate_eligible_for_personal_save": assessment["status"] == "AUTO_PASS",
            "database_saved": False,
            "audit_stages": audit["stages"],
            "generated_practice_method": q.grading_config.get("generated_practice_method"),
            "generation_record_present": isinstance(q.grading_config.get("generation"), dict),
            "answer_provenance": q.answer_provenance, "answer_reliability": q.answer_reliability,
            "available_practice_method": practice_method,
            "stem": output.stem, "answer": output.correct_answer,
            "explanation": output.explanation, "options": output.options})

    totals = {}
    for subject in ("数学二", "408"):
        rows = [row for row in results if row["subject"] == subject]
        statuses = {state: sum(row["replay_status"] == state for row in rows)
                    for state in ("AUTO_PASS", "CONFIRMED_WRONG", "UNSUPPORTED", "INSUFFICIENT_EVIDENCE", "FORMAT_ERROR", "OUTPUT_TRUNCATED", "BLOCKED")}
        totals[subject] = {"calls": len(rows), "complete_structured": sum("stem" in row for row in rows),
                           "review_status_counts": statuses,
                           "eligible_for_personal_save": sum(bool(row.get("candidate_eligible_for_personal_save")) for row in rows),
                           "database_saved_by_replay": sum(bool(row.get("database_saved")) for row in rows),
                           "observed_prompt_tokens": sum((row.get("usage") or {}).get("prompt_tokens", 0) for row in rows),
                           "observed_completion_tokens": sum((row.get("usage") or {}).get("completion_tokens", 0) for row in rows),
                           "peak_cost_estimate_cny": round(sum(row.get("peak_price_cost_cny_estimate") or 0 for row in rows), 6)}
    payload = {"report_version": "phase45i-fix-offline-replay-v1", "model_calls": 0,
        "source_calls": str(RUN / "provider-calls.jsonl"), "source_call_count": len(calls),
        "verifier_version": __import__("backend.services.quality_verifiers", fromlist=["VERSION"]).VERSION,
        "generation_version": __import__("backend.services.question_generation", fromlist=["GENERATION_VERSION"]).GENERATION_VERSION,
        "prompt_version_for_future_requests": "question-generation-c3-v1", "totals": totals, "results": results}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "replay.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output_dir": str(args.output_dir), "totals": totals}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
