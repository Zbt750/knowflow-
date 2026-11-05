"""Summarize answer-generation traces from explicitly named local eval reports.

Only aggregate metadata is printed. Questions, answers, contexts and prompts are
never emitted by this command.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any


def _duration_summary(values: list[float]) -> dict[str, float | int | None]:
    return {
        "n": len(values),
        "median_ms": round(statistics.median(values), 1) if values else None,
        "max_ms": round(max(values), 1) if values else None,
    }


def _trace_for(row: dict[str, Any]) -> dict[str, Any] | None:
    trace = row.get("generation_trace")
    if isinstance(trace, dict):
        return trace
    failure = row.get("failure_diagnostic")
    if isinstance(failure, dict) and isinstance(failure.get("generation_trace"), dict):
        return failure["generation_trace"]
    return None


def summarize_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    traced = [(row, trace) for row in cases if (trace := _trace_for(row)) is not None
              and isinstance(trace.get("calls"), list) and trace["calls"]]
    retry_cases = 0
    length_cases = 0
    failed_attempt_cases = 0
    completed_answer_cases = 0
    failed_answer_cases = 0
    observed_tokens = 0
    complete_usage_cases = 0
    partial_usage_cases = 0
    total_ms: list[float] = []
    first_body_ms: list[float] = []
    for row, trace in traced:
        calls = trace["calls"]
        completed_answer_cases += int("error_type" not in row and calls[-1].get("status") == "completed")
        failed_answer_cases += int("error_type" in row or calls[-1].get("status") == "failed")
        retry_cases += int(len(calls) > 1)
        length_cases += int(any(call.get("finish_reason") == "length" or
                                call.get("error_code") == "answer_truncated"
                                for call in calls))
        failed_attempt_cases += int(any(call.get("status") == "failed" for call in calls))
        usage = trace.get("observed_usage")
        if isinstance(usage, dict) and isinstance(usage.get("total_tokens"), int):
            if trace.get("total_usage_complete") is True:
                observed_tokens += usage["total_tokens"]
                complete_usage_cases += 1
            else:
                partial_usage_cases += 1
        duration = row.get("total_latency_ms")
        if duration is None and isinstance(row.get("failure_diagnostic"), dict):
            duration = row["failure_diagnostic"].get("total_ms")
        if isinstance(duration, (int, float)):
            total_ms.append(float(duration))
        if isinstance(row.get("first_useful_body_ms"), (int, float)):
            first_body_ms.append(float(row["first_useful_body_ms"]))
    return {
        "cases": len(cases),
        "traced_cases": len(traced),
        "untraced_cases": len(cases) - len(traced),
        "retried_cases": retry_cases,
        "completed_answer_cases": completed_answer_cases,
        "failed_answer_cases": failed_answer_cases,
        "output_limit_cases": length_cases,
        "failed_attempt_cases": failed_attempt_cases,
        "total_latency": _duration_summary(total_ms),
        "first_useful_body": _duration_summary(first_body_ms),
        "complete_usage_cases": complete_usage_cases,
        "partial_usage_cases": partial_usage_cases,
        "observed_total_tokens_complete_cases": observed_tokens,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path, help="Explicit local report JSON paths")
    args = parser.parse_args()
    summaries = []
    for path in args.reports:
        report = json.loads(path.read_text(encoding="utf-8"))
        cases = report.get("cases")
        if not isinstance(cases, list):
            parser.error(f"{path.name}: missing cases array")
        summaries.append({"report": path.name, **summarize_cases(cases)})
    print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
