"""Dry-run-first, resumable independent-answer check for eligible AI references.

No model calls occur unless --execute is supplied. A single invocation is
bounded to at most four questions and two provider calls per question.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from backend.config import get_settings
from backend.db import create_db_engine, create_session_factory
from backend.models.learning import KnowledgePoint, Question, QuestionAnswerConsistencyRun, QuestionAttempt
from backend.services.answer_consistency import (
    ANSWER_CONSISTENCY_PROMPT_VERSION,
    MAX_RUNS_PER_CHECK,
    apply_consistency_reliability,
    build_run,
    build_solver_messages,
    consistency_check_key,
    consistency_input_hash,
    consistency_method,
    consistency_outcome,
    normalize_consistency_answer,
    parse_solver_output,
)
from backend.services.question_eligibility import question_eligibility


def _report_path(path: Path | None) -> Path:
    target = path or ROOT / "tmp" / "answer-consistency" / f"phase3_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    resolved = target.resolve()
    if not any(resolved.is_relative_to(ROOT / folder) for folder in ("tmp", "eval/reports")):
        raise ValueError("consistency reports must stay under tmp/ or eval/reports/")
    if resolved.exists():
        raise ValueError("refuse to overwrite an existing report")
    return resolved


def _eligible_questions(db):
    questions = list(db.scalars(select(Question).where(Question.is_active.is_(True)).order_by(Question.id)))
    nodes = {node.id: node for node in db.scalars(select(KnowledgePoint).where(KnowledgePoint.is_active.is_(True)))}
    result = []
    blocked = Counter()
    for q in questions:
        assessment = question_eligibility(q, nodes.get(q.kp_id))
        if q.answer_provenance == "ai_generated" and assessment.practice_eligible and consistency_method(q):
            result.append(q)
        elif q.answer_provenance == "ai_generated":
            blocked.update(assessment.blocking_reasons or ("bounded_consistency_not_applicable",))
    return result, blocked


def run(args) -> dict:
    settings = get_settings()
    url = make_url(str(settings.active_database_url))
    if (url.database or "").lower().endswith("_test") or (url.database or "").lower() == "test":
        raise ValueError("refuse to run the maintainer consistency command against a test database")
    engine = create_db_engine(str(settings.active_database_url))
    factory = create_session_factory(engine)
    selected = []
    blocked = Counter()
    try:
        with factory() as db:
            db.execute(text("SET TRANSACTION READ ONLY"))
            eligible, blocked = _eligible_questions(db)
            selected = eligible[:args.limit]
        summary = {
            "database": url.database,
            "mode": "execute" if args.execute else "dry_run",
            "prompt_version": ANSWER_CONSISTENCY_PROMPT_VERSION,
            "ai_answer_candidates": len(eligible),
            "selected_questions": len(selected),
            "blocked_reason_counts": dict(blocked),
            "provider_calls": 0,
            "database_written": False,
            "results": [],
        }
        if not args.execute:
            summary["reason"] = "dry_run_only_no_prompt_sent_no_database_write"
            return summary

        if not all((settings.llm_api_key, settings.llm_base_url, settings.llm_model)):
            raise ValueError("model endpoint is not configured; no request sent")
        from backend.chat.service import Provider
        provider = Provider(api_key=settings.llm_api_key.get_secret_value(),
            base_url=settings.llm_base_url, model=settings.llm_model,
            timeout=min(settings.llm_timeout_seconds, 45), max_tokens=min(settings.llm_max_output_tokens, 700))

        for picked in selected:
            calls_this_question = 0
            with factory() as db:
                q = db.scalar(select(Question).where(Question.id == picked.id))
                if q is None:
                    summary["results"].append({"question_id": str(picked.id), "status": "stale_question"})
                    continue
                input_hash = consistency_input_hash(q)
                check_key = consistency_check_key(q, model=settings.llm_model)
                prior = list(db.scalars(select(QuestionAnswerConsistencyRun).where(
                    QuestionAnswerConsistencyRun.check_key == check_key
                ).order_by(QuestionAnswerConsistencyRun.run_number)))
                outcome = consistency_outcome(q, prior)
                if outcome["status"] in {"AI_CONSISTENT", "AI_DISAGREEMENT"}:
                    changed = apply_consistency_reliability(q, outcome)
                    if changed:
                        db.commit()
                    summary["results"].append({"question_id": str(q.id), **outcome,
                        "provider_calls": 0, "resumed": True})
                    continue
                next_run = max((row.run_number for row in prior), default=0) + 1
                if next_run > MAX_RUNS_PER_CHECK:
                    summary["results"].append({"question_id": str(q.id), "status": "attempt_limit_reached",
                        "provider_calls": 0})
                    continue
                to_call = min(args.calls_per_question, MAX_RUNS_PER_CHECK - next_run + 1)

            for _ in range(to_call):
                started = time.perf_counter()
                status, normalized, usage, error_code = "failed", None, None, None
                try:
                    with factory() as db:
                        q = db.scalar(select(Question).where(Question.id == picked.id))
                        if q is None or consistency_input_hash(q) != input_hash:
                            raise RuntimeError("stale_question_snapshot")
                        messages = build_solver_messages(q)
                    raw, usage = provider.complete(messages, attempt=1)
                    answer = parse_solver_output(raw)
                    if answer is None:
                        status, error_code = "unsupported", "model_output_not_final_answer_json"
                    else:
                        method = consistency_method(picked)
                        normalized = normalize_consistency_answer(question_type=picked.question_type,
                            method=method, answer=answer, options=picked.options,
                            expected=picked.correct_answer)
                        if normalized is None:
                            status, error_code = "unsupported", "answer_outside_bounded_normalizer"
                        else:
                            status = "completed"
                except Exception as exc:  # isolate a provider failure to this solve
                    error_code = getattr(exc, "code", None) or type(exc).__name__
                    error_code = "".join(ch for ch in str(error_code) if ch.isalnum() or ch in "_.-")[:80] or "provider_error"
                latency_ms = round((time.perf_counter() - started) * 1000)
                with factory.begin() as db:
                    q = db.scalar(select(Question).where(Question.id == picked.id).with_for_update())
                    if q is None or consistency_input_hash(q) != input_hash:
                        raise RuntimeError("Question changed during consistency call; preserving run as stale is not allowed")
                    existing = list(db.scalars(select(QuestionAnswerConsistencyRun).where(
                        QuestionAnswerConsistencyRun.check_key == check_key
                    ).order_by(QuestionAnswerConsistencyRun.run_number)))
                    run_number = max((row.run_number for row in existing), default=0) + 1
                    if run_number > MAX_RUNS_PER_CHECK:
                        break
                    run = build_run(question=q, check_key=check_key, run_number=run_number,
                        model=settings.llm_model, normalized_answer=normalized, status=status,
                        latency_ms=latency_ms, usage=usage, error_code=error_code)
                    db.add(run)
                    db.flush()
                    all_runs = [*existing, run]
                    outcome = consistency_outcome(q, all_runs)
                    changed = apply_consistency_reliability(q, outcome)
                    summary["database_written"] = True
                calls_this_question += 1
                summary["provider_calls"] += 1
                if outcome["status"] in {"AI_CONSISTENT", "AI_DISAGREEMENT"}:
                    break
            summary["results"].append({"question_id": str(picked.id), **outcome,
                "provider_calls": calls_this_question,
                "answer_provenance": "ai_generated",
                "official_answer_promotion": False,
                "content_or_history_rewritten": False})
        return summary
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="explicitly call the configured model")
    parser.add_argument("--limit", type=int, default=1, help="at most 4 eligible questions")
    parser.add_argument("--calls-per-question", type=int, default=2, help="at most 2 new calls per invocation")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.limit <= 4 or not 1 <= args.calls_per_question <= 2:
        parser.error("--limit must be 1..4; --calls-per-question must be 1..2")
    output = _report_path(args.output)
    report = run(args)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("mode", "database", "ai_answer_candidates",
        "selected_questions", "provider_calls", "database_written", "blocked_reason_counts")},
        ensure_ascii=False, indent=2))
    print(f"report={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
