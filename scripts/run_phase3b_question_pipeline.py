"""Dry-run/execute Phase 3B local source attestation and A/B/C answer checks.

Reports omit stems, options, raw answers, citations, secrets, and absolute source
paths. Execute mode writes only explicitly selected, previously unattempted
questions and never changes review stamps or existing attempt/evidence history.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import csv
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from backend.config import get_settings
from backend.db import create_db_engine, create_session_factory
from backend.models.learning import (
    KnowledgePoint, Question, QuestionAnswerConsistencyRun,
    QuestionAttempt, QuestionSourceAttestation,
)
from backend.services.answer_consistency import (
    ANSWER_ATTESTATION_PROMPT_VERSION, ANSWER_ATTESTATION_RUN_ROLES,
    answer_attestation_check_key, answer_attestation_content_hash,
    answer_attestation_method, answer_attestation_outcome,
    answer_attestation_result_hash, build_attestation_solver_messages,
    build_attestation_verifier_messages, build_attestation_run,
    normalize_consistency_answer, parse_final_answer_payload,
    parse_verifier_payload,
)
from backend.services.question_attestation import (
    assess_source_attestation, create_source_attestation_record,
)
from backend.services.question_pack import QuestionPack

PACK_PATH = ROOT / "storage" / "question-intake" / "past-exam-import-20261005-v3-160318" / "question-pack.json"
DEFAULT_CANDIDATE_MAP = ROOT / "tmp" / "phase3_20261006" / "candidate_question_mapping.csv"
DEFAULT_ARCHIVE_SHA = "7eef938fcd772f9e11492e589cda49c6240421bac04813b73a9056d3fac136ea"
MAX_BATCH = 20
MAX_ATTEMPTS_PER_ROLE = 3
MAX_INITIAL_OUTPUT_TOKENS = 700
MAX_RETRY_OUTPUT_TOKENS = 2800


def _answer_check_state(runs: list[QuestionAnswerConsistencyRun]) -> str:
    if not runs:
        return "not_started"
    completed_roles = {row.run_role for row in runs if row.status == "completed"}
    if set(ANSWER_ATTESTATION_RUN_ROLES).issubset(completed_roles):
        return "complete"
    failed_by_role = Counter(row.run_role for row in runs if row.status != "completed")
    if len(runs) >= 6 or any(count >= MAX_ATTEMPTS_PER_ROLE for count in failed_by_role.values()):
        return "exhausted"
    return "resumable"


def _subject(value) -> str:
    raw = re.sub(r"\s+", "", str(value or "")).lower()
    if raw in {"408", "计算机408", "计算机学科专业基础", "计算机学科专业基础综合（408）"}:
        return "408"
    if raw in {"math2", "数学二", "数学（二）", "考研数学二"}:
        return "math2"
    return raw


def _candidate_path(source: dict) -> str:
    folder = "408" if _subject(source.get("subject")) == "408" else "数学二"
    return f"{folder}/{int(source['year'])}/Q{int(source['question_number']):02d}.md"


def _read_candidate_map(path: Path) -> tuple[dict[str, dict], str]:
    raw = path.read_bytes()
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    return {str(row.get("candidate_path") or ""): row for row in rows}, sha256(raw).hexdigest()


def _json_source(q: Question) -> dict:
    config = q.grading_config if isinstance(q.grading_config, dict) else {}
    provenance = config.get("provenance", {}) if isinstance(config.get("provenance"), dict) else {}
    return provenance.get("source", {}) if isinstance(provenance.get("source"), dict) else {}


def _source_key(pack_id: str, item) -> str:
    return f"{pack_id}:{item.source_id}"


def _candidate_index(pack: QuestionPack, map_rows: dict[str, dict],
                     db_questions: list[Question], nodes: dict) -> tuple[list[dict], Counter]:
    by_key = {}
    for q in db_questions:
        source = _json_source(q)
        key = ((q.grading_config or {}).get("provenance", {}).get("key")
               if isinstance(q.grading_config, dict) else None)
        if key:
            by_key[str(key)] = q
    duplicates = Counter()
    stems = defaultdict(list)
    for q in db_questions:
        if q.is_active:
            stems[(str(q.kp_id), q.question_type, q.stem, json.dumps(q.options, ensure_ascii=False, sort_keys=True))].append(q.id)
    exact_identity_counts = Counter()
    raw = []
    for item in pack.questions:
        source = item.source.model_dump(mode="json")
        path = _candidate_path(source)
        row = map_rows.get(path, {})
        q = by_key.get(_source_key(pack.pack_id, item))
        if row.get("mapping_status", "").upper() == "EXACT":
            identity = (_subject(source.get("subject")), source.get("year"), source.get("question_number"))
            exact_identity_counts[identity] += 1
        node = nodes.get(item.kp_code)
        assessment = None
        if q is not None:
            assessment = assess_source_attestation(question=q, node=node,
                pack_question=item, pack_id=pack.pack_id, pack_version=pack.version,
                candidate_archive_sha256=DEFAULT_ARCHIVE_SHA, candidate_map_row=row)
            duplicate_key = (str(q.kp_id), q.question_type, q.stem,
                             json.dumps(q.options, ensure_ascii=False, sort_keys=True))
            if len(stems[duplicate_key]) > 1:
                from dataclasses import replace
                assessment = replace(assessment, status="needs_review",
                    issues=tuple(dict.fromkeys((*assessment.issues, "duplicate_active_question_content"))))
        raw.append({"item": item, "source": source, "candidate_path": path,
                    "candidate_row": row, "question": q, "node": node,
                    "assessment": assessment})
    for record in raw:
        if not record["assessment"]:
            continue
        source = record["source"]
        identity = (_subject(source.get("subject")), source.get("year"), source.get("question_number"))
        if exact_identity_counts[identity] > 1 and record["candidate_row"].get("mapping_status", "").upper() == "EXACT":
            from dataclasses import replace
            old = record["assessment"]
            record["assessment"] = replace(old, status="conflict",
                issues=tuple(dict.fromkeys((*old.issues, "duplicate_exact_source_identity"))))
    return raw, duplicates


def _question_attempted(db, qid) -> bool:
    return db.scalar(select(QuestionAttempt.id).where(QuestionAttempt.question_id == qid).limit(1)) is not None


def _record_summary(record: dict, db, *, attempted_ids: set | None = None,
                    runs_by_check_key: dict[str, list[QuestionAnswerConsistencyRun]] | None = None,
                    model: str | None = None) -> dict:
    q = record["question"]
    item = record["item"]
    assessment = record["assessment"]
    source = record["source"]
    mapping = record["candidate_row"]
    method = answer_attestation_method(q) if q is not None else None
    check_key = (answer_attestation_check_key(q, model=model)
                 if q is not None and model else None)
    check_state = _answer_check_state((runs_by_check_key or {}).get(check_key, [])) if check_key else "unknown"
    if q is None:
        attempted = None
    elif attempted_ids is not None:
        attempted = q.id in attempted_ids or str(q.id) in attempted_ids
    else:
        attempted = _question_attempted(db, q.id)
    return {
        "candidate_id": mapping.get("candidate_id"),
        "question_id": str(q.id) if q else None,
        "subject": "408" if _subject(source.get("subject")) == "408" else "数学二",
        "year": source.get("year"), "question_number": source.get("question_number"),
        "kp_code": item.kp_code, "question_type": item.question_type,
        "mapping_status": mapping.get("mapping_status", "UNMATCHED"),
        "attestation_status": assessment.status if assessment else "missing_question_row",
        "attestation_issues": list(assessment.issues) if assessment else ["imported_question_not_found"],
        "answer_comparer": method,
        "answer_check_state": check_state,
        "attempted": attempted,
        "selectable_for_ai_check": bool(assessment and assessment.status == "source_attested"
            and method and not attempted and check_state in {"not_started", "resumable"}
            and item.question_type in {"single_choice", "fill_blank", "calculation"}),
    }


def _load_bundle(candidate_map: Path):
    pack = QuestionPack.model_validate_json(PACK_PATH.read_text(encoding="utf-8"))
    map_rows, map_sha = _read_candidate_map(candidate_map)
    settings = get_settings()
    url = make_url(str(settings.active_database_url))
    if (url.database or "").lower().endswith("_test") or (url.database or "").lower() == "test":
        raise ValueError("refuse to run Phase 3B against a test database")
    engine = create_db_engine(str(settings.active_database_url))
    factory = create_session_factory(engine)
    return pack, map_rows, map_sha, settings, url, engine, factory


def _append_attestation(db, question, assessment, candidate_id, pack, archive_sha):
    current = db.scalar(select(QuestionSourceAttestation).where(
        QuestionSourceAttestation.attestation_key == assessment.attestation_key))
    if current is None:
        db.add(create_source_attestation_record(question=question, assessment=assessment,
            candidate_id=candidate_id, pack_id=pack.pack_id, pack_version=pack.version,
            candidate_archive_sha256=archive_sha))
    question.source_attestation_key = assessment.attestation_key
    question.source_attestation_sha256 = assessment.question_content_sha256
    question.content_trust = "source_attested"
    question.source_status = "traceable"
    source_type = _json_source(question).get("source_type")
    question.question_provenance = "real_exam" if source_type == "exam" else "trusted_practice"
    # Deliberately leave content_reviewed_by/at empty: this is not human review.
    return current


def _persist_run(factory, question_id, check_key, run, source_hash):
    with factory.begin() as db:
        q = db.scalar(select(Question).where(Question.id == question_id).with_for_update())
        if q is None or answer_attestation_content_hash(q) != source_hash:
            raise RuntimeError("question prompt changed during an external model call; run not persisted")
        existing = list(db.scalars(select(QuestionAnswerConsistencyRun).where(
            QuestionAnswerConsistencyRun.check_key == check_key).order_by(QuestionAnswerConsistencyRun.run_number)))
        if any(row.run_role == run.run_role and row.status == "completed" for row in existing):
            return False
        db.add(run)
        return True


def _select_records(candidates: list[dict], summaries: list[dict], *, question_ids: list[str] | None,
                    batch_limit: int, exclude_question_ids: list[str] | None
                    ) -> tuple[list[dict], list[str], dict[str, dict]]:
    by_id = {summary["question_id"]: (record, summary)
             for record, summary in zip(candidates, summaries) if summary["question_id"]}
    summary_by_id = {question_id: pair[1] for question_id, pair in by_id.items()}
    if question_ids:
        unique_ids = list(dict.fromkeys(str(value) for value in question_ids))
        selected = [by_id[value][0] for value in unique_ids if value in by_id]
        return selected, [value for value in unique_ids if value not in by_id], summary_by_id

    excluded = {str(value) for value in (exclude_question_ids or [])}
    pool = [record for record, summary in zip(candidates, summaries)
            if summary["selectable_for_ai_check"] and str(summary["question_id"]) not in excluded]
    if batch_limit:
        by_subject = {key: [] for key in ("数学二", "408")}
        for record in pool:
            subject = "408" if _subject(record["source"].get("subject")) == "408" else "数学二"
            by_subject[subject].append(record)
        for records in by_subject.values():
            records.sort(key=lambda record: (int(record["source"].get("year") or 0), record["candidate_path"]))
        selected = []
        while len(selected) < batch_limit and any(by_subject.values()):
            for subject in ("数学二", "408"):
                if by_subject[subject] and len(selected) < batch_limit:
                    selected.append(by_subject[subject].pop(0))
    else:
        selected = pool[:10]
    return selected, [], summary_by_id


def _call_role(*, role, q, method, check_key, factory, provider, settings,
               existing_runs, source_answer_hash):
    completed = next((r for r in reversed(existing_runs)
                      if r.run_role == role and r.status == "completed"), None)
    if completed is not None:
        return completed, 0, []
    failed = [r for r in existing_runs if r.run_role == role and r.status != "completed"]
    if len(failed) >= MAX_ATTEMPTS_PER_ROLE:
        return None, 0, ["role_attempt_limit_reached"]
    calls = 0
    errors = []
    for attempt_index in range(MAX_ATTEMPTS_PER_ROLE - len(failed)):
        run_number = max((r.run_number for r in existing_runs), default=0) + 1
        if run_number > 6:
            return None, calls, [*errors, "global_run_limit_reached"]
        started = time.perf_counter()
        status, final_answer, normalized, verification, usage, error = "failed", None, None, None, None, None
        candidate_hash = None
        provider_attempt = 1 if not failed and attempt_index == 0 else 2
        try:
            if role in {"solve_a", "solve_b"}:
                raw, usage = provider.complete(build_attestation_solver_messages(q), attempt=provider_attempt)
                final_answer = parse_final_answer_payload(raw)
                if final_answer is None:
                    status, error = "unsupported", "final_answer_payload_invalid_or_empty"
                else:
                    normalized = normalize_consistency_answer(question_type=q.question_type,
                        method=method, answer=final_answer, options=q.options, expected=q.correct_answer)
                    status, error = ("completed", None) if normalized else ("unsupported", "bounded_answer_normalization_failed")
            else:
                solves = {r.run_role: r for r in existing_runs if r.status == "completed"}
                a, b = solves.get("solve_a"), solves.get("solve_b")
                if a is None or b is None or not a.normalized_final_answer or not b.normalized_final_answer:
                    return None, calls, [*errors, "verifier_requires_two_completed_solves"]
                raw, usage = provider.complete(build_attestation_verifier_messages(q,
                    answer_a=a.normalized_final_answer, answer_b=b.normalized_final_answer), attempt=provider_attempt)
                verification = parse_verifier_payload(raw)
                if verification is None:
                    status, error = "unsupported", "verifier_payload_invalid"
                else:
                    status = "completed"
                    final_answer = None
                    candidates = [a.normalized_final_answer, b.normalized_final_answer]
                    candidate_hash = sha256(json.dumps(candidates, ensure_ascii=False,
                        separators=(",", ":")).encode()).hexdigest()
        except Exception as exc:
            code = getattr(exc, "code", None) or type(exc).__name__
            error = "".join(ch for ch in str(code) if ch.isalnum() or ch in "_.-")[:80] or "provider_error"
            errors.append(error)
        latency = round((time.perf_counter() - started) * 1000)
        run = build_attestation_run(question=q, check_key=check_key, run_number=run_number,
            run_role=role, model=settings.llm_model, final_answer=final_answer,
            normalized_answer=normalized, status=status, latency_ms=latency, usage=usage,
            verification_result=verification, candidate_answers_sha256=candidate_hash,
            source_answer_sha256=source_answer_hash, error_code=error)
        inserted = _persist_run(factory, q.id, check_key, run, answer_attestation_content_hash(q))
        if inserted:
            existing_runs.append(run)
            calls += 1
        if status == "completed":
            return run, calls, errors
    return None, calls, errors


def _process_question(record, *, factory, provider, settings, pack, archive_sha) -> dict:
    qid = record["question"].id
    candidate_id = str(record["candidate_row"].get("candidate_id") or "")
    assessment = record["assessment"]
    item = record["item"]
    if assessment.status != "source_attested":
        return {"question_id": str(qid), "candidate_id": candidate_id,
                "status": "NEEDS_REVIEW", "reason": list(assessment.issues),
                "provider_calls": 0, "source_attested": False}
    with factory.begin() as db:
        q = db.scalar(select(Question).where(Question.id == qid).with_for_update())
        node = db.get(KnowledgePoint, q.kp_id) if q else None
        if q is None:
            return {"question_id": str(qid), "candidate_id": candidate_id,
                    "status": "STALE_OR_ATTESTATION_FAILED", "reason": ["question_row_missing"],
                    "provider_calls": 0, "source_attested": False}
        fresh = assess_source_attestation(question=q, node=node, pack_question=item,
            pack_id=pack.pack_id, pack_version=pack.version,
            candidate_archive_sha256=archive_sha, candidate_map_row=record["candidate_row"])
        if fresh.status != "source_attested":
            return {"question_id": str(qid), "candidate_id": candidate_id,
                    "status": "STALE_OR_ATTESTATION_FAILED", "reason": list(fresh.issues),
                    "provider_calls": 0, "source_attested": False}
        _append_attestation(db, q, fresh, candidate_id, pack, archive_sha)
        if _question_attempted(db, q.id):
            return {"question_id": str(qid), "candidate_id": candidate_id,
                    "status": "SKIPPED_HAS_HISTORY", "provider_calls": 0,
                    "source_attested": True}
        if not q.correct_answer or not q.explanation:
            return {"question_id": str(qid), "candidate_id": candidate_id,
                    "status": "SKIPPED_ANSWER_OR_EXPLANATION_MISSING", "provider_calls": 0,
                    "source_attested": True}
        method = answer_attestation_method(q)
        if method is None or q.question_type not in {"single_choice", "fill_blank", "calculation"}:
            return {"question_id": str(qid), "candidate_id": candidate_id,
                    "status": "PROCESS_REVIEW_ONLY", "provider_calls": 0,
                    "source_attested": True}
        input_hash = answer_attestation_content_hash(q)
        check_key = answer_attestation_check_key(q, model=settings.llm_model)
        source_answer_hash = sha256(str(q.correct_answer).encode("utf-8")).hexdigest()
    with factory() as db:
        q = db.scalar(select(Question).where(Question.id == qid))
        existing_runs = list(db.scalars(select(QuestionAnswerConsistencyRun).where(
            QuestionAnswerConsistencyRun.check_key == check_key).order_by(QuestionAnswerConsistencyRun.run_number)))
    calls = 0
    errors = []
    completed_by_role = {r.run_role: r for r in existing_runs if r.status == "completed"}
    for role in ("solve_a", "solve_b"):
        if role not in completed_by_role:
            run, used, failed = _call_role(role=role, q=q, method=method, check_key=check_key,
                factory=factory, provider=provider, settings=settings, existing_runs=existing_runs,
                source_answer_hash=source_answer_hash)
            calls += used
            errors.extend(failed)
            if run:
                completed_by_role[role] = run
    if "solve_a" in completed_by_role and "solve_b" in completed_by_role:
        if "verify_c" not in {r.run_role for r in existing_runs if r.status == "completed"}:
            _, used, failed = _call_role(role="verify_c", q=q, method=method, check_key=check_key,
                factory=factory, provider=provider, settings=settings, existing_runs=existing_runs,
                source_answer_hash=source_answer_hash)
            calls += used
            errors.extend(failed)
    outcome = answer_attestation_outcome(existing_runs)
    with factory.begin() as db:
        live = db.scalar(select(Question).where(Question.id == qid).with_for_update())
        if live is None or answer_attestation_content_hash(live) != input_hash:
            raise RuntimeError("Question prompt changed during the three-role evaluation")
        if outcome["status"] == "AI_CONSISTENT":
            raw_answer = outcome.get("final_answer")
            normalized = outcome.get("normalized_answer")
            if not raw_answer or not normalized:
                outcome = {"status": "NEEDS_REVIEW", "reason": "consensus_answer_missing"}
            else:
                # Explicitly replace only the unverified transcription answer with
                # the agreed model final answer; original source pack remains intact.
                live.correct_answer = raw_answer
                live.answer_provenance = "ai_generated"
                live.answer_reliability = "ai_generated_consistent"
                live.answer_reviewed_by = None
                live.answer_reviewed_at = None
                config = dict(live.grading_config or {})
                prefix = "reference_" if method.startswith("reference_") else "ai_generated_" if method.startswith("ai_generated_") else ""
                method_name = method.removeprefix(prefix)
                config["practice_method"] = method_name
                config["verified"] = False
                config["method"] = None
                live.grading_config = config
                live.grading_mode = "self_assessed"
                live.answer_attestation_key = check_key
                live.answer_attestation_sha256 = answer_attestation_result_hash(live)
        elif outcome["status"] == "AI_DISAGREEMENT":
            # Keep the transcribed answer unchanged and stop automatic grading.
            live.answer_reliability = "ai_disagreement"
            live.answer_attestation_key = check_key
            live.answer_attestation_sha256 = None
        assessment = __import__("backend.services.question_eligibility", fromlist=["question_eligibility"]).question_eligibility(
            live, db.get(KnowledgePoint, live.kp_id))
        qresult = {
            "question_id": str(qid), "candidate_id": candidate_id,
            "status": outcome["status"], "reason": outcome.get("reason"),
            "source_attested": True,
            "source_answer_changed_by_consensus": bool(
                outcome.get("status") == "AI_CONSISTENT" and outcome.get("final_answer")
                and sha256(str(outcome.get("final_answer")).encode("utf-8")).hexdigest() != source_answer_hash),
            "imported_explanation_independently_verified": False,
            "provider_calls": calls, "role_statuses": {
                role: next((r.status for r in existing_runs if r.run_role == role and r.status == "completed"),
                           next((r.status for r in reversed(existing_runs) if r.run_role == role), "not_run"))
                for role in ANSWER_ATTESTATION_RUN_ROLES},
            "verified_reference": False,
            "human_review_stamp_written": False,
            "answer_provenance": live.answer_provenance,
            "answer_reliability": live.answer_reliability,
            "practice_eligible": assessment.practice_eligible,
            "evidence_capability": assessment.evidence_capability,
            "blocking_reasons": list(assessment.blocking_reasons),
            "latency_ms_total": sum(r.latency_ms or 0 for r in existing_runs),
            "usage_observed_runs": sum(isinstance(r.usage, dict) for r in existing_runs),
            "usage_unobserved_runs": sum(r.usage is None for r in existing_runs),
            "errors": errors,
        }
    return qresult


def run(args) -> dict:
    pack, candidate_map, map_sha, settings, url, engine, factory = _load_bundle(args.candidate_map)
    archive_sha = DEFAULT_ARCHIVE_SHA
    if not settings.llm_api_key or not settings.llm_base_url or not settings.llm_model:
        engine.dispose()
        raise ValueError("configured text model is incomplete; no request sent")
    report = {
        "schema_version": "phase3b-machine-attested-question-pipeline-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "execute" if args.execute else "dry_run",
        "database": url.database, "model": settings.llm_model,
        "code_version": __import__("subprocess").run(["git", "rev-parse", "HEAD"],
            cwd=ROOT, capture_output=True, text=True).stdout.strip(),
        "workspace_dirty": True,
        "dataset": {"pack_id": pack.pack_id, "pack_version": pack.version,
            "pack_path": str(PACK_PATH.relative_to(ROOT)).replace("\\", "/"),
            "pack_sha256": sha256(PACK_PATH.read_bytes()).hexdigest(),
            "candidate_archive_sha256": archive_sha,
            "candidate_archive_sha256_source": "reused_prior_phase3_audit; original archive unavailable for recomputation",
            "candidate_archive_sha256_recomputed": False, "candidate_map_sha256": map_sha,
            "candidate_map_path": str(args.candidate_map.relative_to(ROOT)).replace("\\", "/")},
        "prompt_version": ANSWER_ATTESTATION_PROMPT_VERSION,
        "model_call_profile": {
            "timeout_seconds": min(settings.llm_timeout_seconds, 45),
            "initial_max_output_tokens": min(settings.llm_max_output_tokens, MAX_INITIAL_OUTPUT_TOKENS),
            "truncation_retry_max_output_tokens": min(
                max(min(settings.llm_max_output_tokens, MAX_INITIAL_OUTPUT_TOKENS) * 4, 1400),
                MAX_RETRY_OUTPUT_TOKENS),
            "retry_policy": "subsequent attempts use a bounded larger output budget; maximum three persisted runs per role and six per check",
        },
        "selected": [], "results": [], "provider_calls": 0, "database_written": False,
        "human_review_stamps_written": 0, "history_rows_changed": 0,
    }
    try:
        attempted_ids = set()
        with factory() as db:
            db.execute(text("SET TRANSACTION READ ONLY"))
            db_questions = list(db.scalars(select(Question)))
            nodes = {n.code: n for n in db.scalars(select(KnowledgePoint))}
            attempted_ids = set(db.scalars(select(QuestionAttempt.question_id).distinct()))
            runs_by_check_key: dict[str, list[QuestionAnswerConsistencyRun]] = defaultdict(list)
            for answer_run in db.scalars(select(QuestionAnswerConsistencyRun)):
                runs_by_check_key[answer_run.check_key].append(answer_run)
            candidates, _ = _candidate_index(pack, candidate_map, db_questions, nodes)
            summaries = [_record_summary(row, db, attempted_ids=attempted_ids,
                runs_by_check_key=runs_by_check_key, model=settings.llm_model) for row in candidates]
            funnel = Counter()
            blocked = Counter()
            for row in summaries:
                funnel["pack_candidates"] += 1
                funnel[str(row["mapping_status"]).upper()] += 1
                funnel[str(row["attestation_status"])] += 1
                if row["attestation_issues"]:
                    blocked.update(row["attestation_issues"])
            report["candidate_funnel"] = dict(funnel)
            report["attestation_issue_counts"] = dict(blocked)
            report["candidate_scope"] = {
                "pack_candidates": len(candidates),
                "mapping_exact_rows": sum(row["mapping_status"].upper() == "EXACT" for row in summaries),
                "machine_attestable": sum(row["attestation_status"] == "source_attested" for row in summaries),
                "answer_comparer_supported": sum(bool(row["answer_comparer"]) for row in summaries),
                "unattempted_answer_comparable": sum(row["selectable_for_ai_check"] for row in summaries),
                "answer_check_states": dict(Counter(row["answer_check_state"] for row in summaries)),
                "by_subject": {subject: sum(row["selectable_for_ai_check"] and row["subject"] == subject for row in summaries)
                               for subject in ("数学二", "408")},
            }
        selected_records, unresolved_ids, summary_by_id = _select_records(
            candidates, summaries, question_ids=args.question_ids,
            batch_limit=args.batch_limit, exclude_question_ids=args.exclude_question_ids)
        report["selection"] = {
            "strategy": "explicit_ids" if args.question_ids else "balanced_subject_batch" if args.batch_limit else "first_10_selectable",
            "batch_limit": args.batch_limit or None,
            "unresolved_requested_ids": unresolved_ids,
            "excluded_question_ids": list(args.exclude_question_ids or []),
        }
        report["selected"] = [summary_by_id.get(str(row["question"].id)) for row in selected_records]
        if not args.execute:
            report["reason"] = "dry_run_no_model_call_no_business_write"
            return report

        if unresolved_ids:
            raise ValueError(f"requested question IDs not present in current candidate pack: {len(unresolved_ids)}")
        if not selected_records:
            raise ValueError("no requested question IDs resolve to the candidate pack")
        if len(selected_records) > MAX_BATCH:
            raise ValueError(f"at most {MAX_BATCH} questions may be run per controlled batch")
        blocked = [summary_by_id[str(row["question"].id)] for row in selected_records
                   if not summary_by_id[str(row["question"].id)]["selectable_for_ai_check"]]
        if blocked:
            raise ValueError(f"refuse external calls for {len(blocked)} selected rows that fail current source/answer/history gates")
        from backend.chat.service import Provider
        initial_budget = min(settings.llm_max_output_tokens, MAX_INITIAL_OUTPUT_TOKENS)
        retry_budget = min(max(initial_budget * 4, 1400), MAX_RETRY_OUTPUT_TOKENS)
        provider = Provider(api_key=settings.llm_api_key.get_secret_value(), base_url=settings.llm_base_url,
            model=settings.llm_model, timeout=min(settings.llm_timeout_seconds, 45),
            max_tokens=initial_budget, retry_max_tokens=retry_budget)
        for row in selected_records:
            result = _process_question(row, factory=factory, provider=provider,
                settings=settings, pack=pack, archive_sha=archive_sha)
            report["results"].append(result)
            report["provider_calls"] += int(result.get("provider_calls", 0))
            report["database_written"] = report["database_written"] or bool(result.get("source_attested")) or result.get("status") in {"AI_CONSISTENT", "AI_DISAGREEMENT"}
        report["batch_summary"] = {
            "selected": len(selected_records),
            "source_attested": sum(r.get("source_attested") is True or r.get("practice_eligible") is True for r in report["results"]),
            "ai_consistent": sum(r.get("status") == "AI_CONSISTENT" for r in report["results"]),
            "ai_disagreement": sum(r.get("status") == "AI_DISAGREEMENT" for r in report["results"]),
            "needs_review_or_incomplete": sum(r.get("status") not in {"AI_CONSISTENT", "AI_DISAGREEMENT"} for r in report["results"]),
            "practice_eligible": sum(bool(r.get("practice_eligible")) for r in report["results"]),
            "evidence_eligible": sum(r.get("evidence_capability") == "ai_consistent_objective" for r in report["results"]),
            "provider_failures": sum(bool(r.get("errors")) for r in report["results"]),
        }
        return report
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-map", type=Path, default=DEFAULT_CANDIDATE_MAP)
    parser.add_argument("--execute", action="store_true", help="explicitly attest selected candidates and call configured model")
    parser.add_argument("--question-id", dest="question_ids", action="append", help="repeat to select a real candidate question ID")
    parser.add_argument("--batch-limit", type=int, default=0, help=f"balanced Math/408 controlled batch, maximum {MAX_BATCH}")
    parser.add_argument("--exclude-question-id", dest="exclude_question_ids", action="append")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.batch_limit < 0 or args.batch_limit > MAX_BATCH:
        parser.error(f"--batch-limit must be 0..{MAX_BATCH}")
    if args.question_ids and args.batch_limit:
        parser.error("use explicit question IDs or --batch-limit, not both")
    if args.execute and not args.question_ids and not args.batch_limit:
        parser.error("execute requires explicit question IDs or a bounded controlled batch")
    output = (args.output or ROOT / "tmp" / "phase3b_20261006" /
        f"pipeline-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json").resolve()
    if not any(output.is_relative_to(ROOT / folder) for folder in ("tmp", "eval/reports")):
        parser.error("report output must stay under tmp/ or eval/reports/")
    if output.exists():
        parser.error("refuse to overwrite an existing report")
    report = run(args)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report.get(key) for key in (
        "mode", "database", "model", "candidate_scope", "selected", "provider_calls",
        "database_written", "batch_summary")}, ensure_ascii=False, indent=2))
    print(f"report={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
