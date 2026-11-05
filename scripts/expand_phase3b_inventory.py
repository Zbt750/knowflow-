"""Coverage-first expansion using the frozen Phase 3B production functions.

Defaults to read-only selection/audit. --execute authorizes at most three batches
of 50 existing EXACT candidates; no new questions or human review are created.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from statistics import median
import subprocess
import sys
from threading import Lock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select, text
from backend.models.learning import KnowledgePoint, Question, QuestionAttempt, QuestionAnswerConsistencyRun
from backend.mastery.capability import capability_keys
from backend.services.question_eligibility import question_eligibility
from backend.services.question_production_pipeline import validate_question_content, content_digest
from scripts.audit_question_production import build_report
from scripts import run_phase3b_question_pipeline as pipeline

MAX_SELECTED = 150
BATCH_SIZE = 50
STOP_POLICY = {"minimum_cases": 10, "disagreement_fraction": .20,
    "incomplete_fraction": .30, "provider_error_fraction": .20,
    "batch_observed_tokens": 300000, "maximum_calls": 900}


def dump(path, value):
    """Atomic local report checkpoint; never overwrites a prior run directory."""
    staging = path.with_suffix(path.suffix + ".partial")
    staging.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    staging.replace(path)


def protected_fingerprints(db):
    result = {}
    for table in ("kp_states", "kp_mastery_policies", "question_attempts", "learning_events", "daily_plans", "practice_items"):
        rows = [dict(row) for row in db.execute(text(f'SELECT * FROM "{table}" ORDER BY 1')).mappings()]
        result[table] = sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()
    reviews = db.execute(select(Question.id, Question.content_reviewed_by, Question.content_reviewed_at,
        Question.answer_reviewed_by, Question.answer_reviewed_at).order_by(Question.id)).all()
    result["human_review_stamps"] = sha256(str(reviews).encode()).hexdigest()
    return result


def inventory(factory, pack, mapping, model):
    with factory() as db:
        db.execute(text("SET TRANSACTION READ ONLY"))
        qs = list(db.scalars(select(Question)))
        nodes = {n.code: n for n in db.scalars(select(KnowledgePoint))}
        attempts = set(db.scalars(select(QuestionAttempt.question_id).distinct()))
        runs = defaultdict(list)
        for run in db.scalars(select(QuestionAnswerConsistencyRun)):
            runs[run.check_key].append(run)
        records, _ = pipeline._candidate_index(pack, mapping, qs, nodes)
        summaries = []
        eligible_counts = Counter()
        eligible_types = defaultdict(set)
        eligible_caps = defaultdict(set)
        for q in qs:
            assessment = question_eligibility(q, next((n for n in nodes.values() if n.id == q.kp_id), None))
            if assessment.practice_eligible:
                eligible_counts[str(q.kp_id)] += 1
                eligible_types[str(q.kp_id)].add(q.question_type)
                eligible_caps[str(q.kp_id)].update(capability_keys(q.question_type, q.question_role, q.is_variant))
        for record in records:
            s = pipeline._record_summary(record, db, attempted_ids=attempts, runs_by_check_key=runs, model=model)
            q, node = record["question"], record["node"]
            integrity = validate_question_content(q) if q else None
            s["integrity_status"] = integrity.status if integrity else "MISSING"
            s["integrity_issues"] = list(integrity.detected_issues) if integrity else ["missing_question"]
            eligible = question_eligibility(q, node).practice_eligible if q else False
            s["practice_eligible"] = eligible
            s["kp_id"] = str(node.id) if node else None
            s["capabilities"] = list(capability_keys(q.question_type, q.question_role, q.is_variant)) if q else []
            s["expansion_selectable"] = bool(s["selectable_for_ai_check"] and q.is_active
                and s["mapping_status"] == "EXACT" and not eligible
                and q.answer_reliability != "ai_disagreement"
                and q.answer_provenance != "verified_reference"
                and integrity.status == "STRUCTURALLY_COMPLETE")
            summaries.append(s)
        return records, summaries, nodes, qs, eligible_counts, eligible_types, eligible_caps


def select_coverage(records, summaries, counts, types, caps, limit, excluded):
    """Recompute virtual coverage after every pick, with stable subject ties."""
    pool = [(r, s) for r, s in zip(records, summaries)
            if s["expansion_selectable"] and s["question_id"] not in excluded]
    virtual = Counter(counts)
    type_sets = {k: set(v) for k, v in types.items()}
    cap_sets = {k: set(v) for k, v in caps.items()}
    subject_counts = Counter()
    chosen = []
    while pool and len(chosen) < limit:
        def rank(pair):
            s = pair[1]; key = s["kp_id"]; count = virtual[key]
            new_dimension = (s["question_type"] not in type_sets.get(key, set())
                or bool(set(s["capabilities"]) - cap_sets.get(key, set())))
            priority = 0 if count == 0 else 1 if count == 1 else 2 if new_dimension else 3
            return priority, count, subject_counts[s["subject"]], s["year"], s["candidate_id"]
        pair = min(pool, key=rank); pool.remove(pair)
        r, s = pair; key = s["kp_id"]
        s = dict(s, selection_priority=rank(pair)[0], node_prebatch_practice_count=counts[key],
                 virtual_count_before_selection=virtual[key])
        chosen.append((r, s)); virtual[key] += 1
        type_sets.setdefault(key, set()).add(s["question_type"])
        cap_sets.setdefault(key, set()).update(s["capabilities"])
        subject_counts[s["subject"]] += 1
    return chosen


def coverage(factory, pack, mapping, model, csv_path):
    records, summaries, nodes, qs, counts, types, caps = inventory(factory, pack, mapping, model)
    with factory() as db:
        db.execute(text("SET TRANSACTION READ ONLY"))
        report = build_report(db, candidate_csv=csv_path)
        attempts = set(db.scalars(select(QuestionAttempt.question_id).distinct()))
        assessments = {q.id: question_eligibility(q, db.get(KnowledgePoint, q.kp_id)) for q in qs}
    q_by_node = defaultdict(list); candidates_by_node = defaultdict(list)
    for q in qs: q_by_node[q.kp_id].append(q)
    for s in summaries:
        if s["kp_id"]: candidates_by_node[s["kp_id"]].append(s)
    mapped = defaultdict(Counter); unassigned = Counter()
    for row in mapping.values():
        try: codes = json.loads(row.get("exact_name_node_codes") or "[]")
        except ValueError: codes = []
        matched = {q.kp_id for q in qs if str(q.id) in json.loads(row.get("matched_question_ids") or "[]")}
        targets = matched or {nodes[c].id for c in codes if c in nodes}
        status = row.get("mapping_status", "UNMATCHED").upper()
        if targets:
            for target in targets: mapped[str(target)][status] += 1
        else: unassigned[status] += 1
    per_node = []
    for base in report["nodes"]:
        if not base["is_assessable"]: continue
        node = nodes[base["code"]]; key = str(node.id)
        rows = [q for q in q_by_node[node.id] if q.is_active]
        eligible = [q for q in rows if assessments[q.id].practice_eligible]
        real = [q for q in eligible if q.question_provenance == "real_exam"]
        years = {pipeline._json_source(q).get("year") for q in real} - {None}
        candidates = candidates_by_node[key]
        remaining = [s for s in candidates if s["expansion_selectable"]]
        gaps = []
        if not eligible:
            if not candidates and not mapped[key]: gaps.append("NO_CANDIDATE")
            if mapped[key]["POSSIBLE"] and not mapped[key]["EXACT"]: gaps.append("ONLY_POSSIBLE")
            if mapped[key]["UNMATCHED"] and not mapped[key]["EXACT"] and not mapped[key]["POSSIBLE"]: gaps.append("ONLY_UNMATCHED")
            if candidates and not any(s["attestation_status"] == "source_attested" for s in candidates): gaps.append("NO_SOURCE_ATTESTABLE_CANDIDATE")
        if any(s["integrity_status"] != "STRUCTURALLY_COMPLETE" for s in candidates): gaps.append("CONTENT_INTEGRITY_BLOCKED")
        if remaining: gaps.append("ANSWER_CONSISTENCY_PENDING")
        if any(q.answer_reliability == "ai_disagreement" for q in rows): gaps.append("AI_DISAGREEMENT")
        if any(not s["answer_comparer"] for s in candidates): gaps.append("COMPARER_UNSUPPORTED")
        process = sum(assessments[q.id].grading_capability == "process_review_only" for q in eligible)
        if process and process == len(eligible): gaps.append("PROCESS_ONLY")
        if len(eligible) < 2: gaps.append("INSUFFICIENT_DISTINCT_QUESTIONS")
        if len(caps.get(key, set())) < 2: gaps.append("INSUFFICIENT_CAPABILITY_DIVERSITY")
        if len(years) < 2: gaps.append("INSUFFICIENT_YEAR_DIVERSITY")
        if not any(assessments[q.id].evidence_capability == "verified_objective" for q in eligible): gaps.append("NO_STRONG_INDEPENDENT_EVIDENCE_SOURCE")
        if any(s["answer_check_state"] == "exhausted" and not s["practice_eligible"] for s in candidates): gaps.append("CONSISTENCY_RUN_LIMIT_EXHAUSTED")
        remedies = []
        if remaining: remedies.append("remaining_real_candidate_expansion")
        if mapped[key]["POSSIBLE"] or mapped[key]["UNMATCHED"]: remedies.append("identity_resolution")
        if any(g in gaps for g in ("NO_SOURCE_ATTESTABLE_CANDIDATE", "CONTENT_INTEGRITY_BLOCKED")): remedies.append("source_repair")
        if "COMPARER_UNSUPPORTED" in gaps: remedies.append("comparer_improvement_or_process_review")
        if process or any(q.question_type in {"proof", "discussion", "program", "subjective"} for q in rows): remedies.append("process_review")
        if any(g in gaps for g in ("NO_CANDIDATE", "INSUFFICIENT_DISTINCT_QUESTIONS", "INSUFFICIENT_CAPABILITY_DIVERSITY")): remedies.append("future_ai_generated_practice_candidate_only")
        if "NO_STRONG_INDEPENDENT_EVIDENCE_SOURCE" in gaps: remedies.append("independent_reference_answer_verification")
        row = {**base, "node_id": key, "classification": "reference_topic" if node.is_reference_only else "assessable",
            "process_review_count": process, "distinct_question_count": len({content_digest(q) for q in eligible}),
            "distinct_real_exam_question_count": len(real), "distinct_year_count": len(years),
            "question_type_distribution": dict(Counter(q.question_type for q in eligible)),
            "capability_dimension_distribution": dict(Counter(c for q in eligible for c in capability_keys(q.question_type,q.question_role,q.is_variant))),
            "unused_practice_count": sum(q.id not in attempts for q in eligible),
            "previously_attempted_practice_count": sum(q.id in attempts for q in eligible),
            "candidate_exact_count": mapped[key]["EXACT"], "candidate_possible_count": mapped[key]["POSSIBLE"],
            "candidate_unmatched_count": mapped[key]["UNMATCHED"],
            "remaining_machine_attestable_candidate_count": sum(s["attestation_status"] == "source_attested" and not s["practice_eligible"] for s in candidates),
            "remaining_expansion_selectable_candidate_count": len(remaining),
            "coverage_gap_reasons": gaps or ["UNKNOWN"], "future_remedies": sorted(set(remedies)),
            "pedagogical_review_needed": bool(node.is_reference_only)}
        per_node.append(row)
    report["assessable_node_coverage"] = per_node
    report["unassignable_candidate_counts"] = dict(unassigned)
    report["coverage_metrics"] = {"assessable": len(per_node), "at_least_one": sum(r["practice_eligible_count"] >= 1 for r in per_node),
        "at_least_two_distinct": sum(r["distinct_question_count"] >= 2 for r in per_node),
        "multiple_types": sum(len(r["question_type_distribution"]) >= 2 for r in per_node),
        "multiple_capabilities": sum(len(r["capability_dimension_distribution"]) >= 2 for r in per_node),
        "zero_practice": sum(r["practice_eligible_count"] == 0 for r in per_node)}
    report["coverage_gap_counts"] = dict(Counter(g for r in per_node for g in r["coverage_gap_reasons"]))
    report["process_review_only"] = sum(r["process_review_count"] for r in per_node)
    report["blocked"] = report["active_questions"] - report["practice_eligible"]
    report["candidate_funnel"] = {"total_candidates": len(mapping), "exact": report["candidate_exact"],
        "source_attestable": sum(s["attestation_status"] == "source_attested" for s in summaries),
        "integrity_pass": sum(s["integrity_status"] == "STRUCTURALLY_COMPLETE" for s in summaries),
        "remaining_selectable": sum(s["expansion_selectable"] for s in summaries)}
    return report


class CountedProvider:
    def __init__(self, provider): self.provider, self.calls, self.lock = provider, 0, Lock()
    def complete(self, *args, **kwargs):
        with self.lock:
            if self.calls >= STOP_POLICY["maximum_calls"]: raise RuntimeError("expansion_model_call_budget_exhausted")
            self.calls += 1
        return self.provider.complete(*args, **kwargs)


def run_metrics(factory, previous_ids):
    with factory() as db:
        runs = [r for r in db.scalars(select(QuestionAnswerConsistencyRun)) if str(r.id) not in previous_ids]
    observed = [r.usage for r in runs if isinstance(r.usage, dict)]
    latencies = [r.latency_ms or 0 for r in runs]
    return {"persisted_run_attempts": len(runs), "completed": sum(r.status == "completed" for r in runs),
        "failed": sum(r.status != "completed" for r in runs),
        "retries": sum(count-1 for count in Counter((r.check_key,r.run_role) for r in runs).values()),
        "truncation": sum(r.error_code == "answer_truncated" for r in runs),
        "provider_errors": sum(r.status == "failed" and r.error_code != "answer_truncated" for r in runs),
        "usage_observable": len(observed), "usage_unknown": len(runs)-len(observed),
        "observed_tokens": {k: sum(u.get(k,0) for u in observed) for k in ("prompt_tokens","completion_tokens","total_tokens")},
        "latency_total_ms": sum(latencies), "latency_median_ms": median(latencies) if latencies else 0,
        "latency_max_ms": max(latencies, default=0),
        "errors": dict(Counter(r.error_code for r in runs if r.error_code))}


def stop_reasons(results, metrics):
    reasons=[]; n=len(results)
    if n >= STOP_POLICY["minimum_cases"]:
        if sum(r.get("status")=="AI_DISAGREEMENT" for r in results)/n > STOP_POLICY["disagreement_fraction"]: reasons.append("excessive_disagreement")
        if sum(r.get("status") not in {"AI_CONSISTENT","AI_DISAGREEMENT"} for r in results)/n > STOP_POLICY["incomplete_fraction"]: reasons.append("excessive_incomplete")
        if metrics["provider_errors"]/max(metrics["persisted_run_attempts"],1) > STOP_POLICY["provider_error_fraction"]: reasons.append("excessive_provider_errors")
    if metrics["observed_tokens"]["total_tokens"] > STOP_POLICY["batch_observed_tokens"]: reasons.append("abnormal_observed_token_volume")
    if any(r.get("status")=="INTERNAL_ERROR" for r in results): reasons.append("pipeline_internal_error")
    return reasons


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute",action="store_true")
    parser.add_argument("--limit",type=int,default=150)
    parser.add_argument("--output-dir",type=Path,required=True)
    args=parser.parse_args()
    if not 1 <= args.limit <= MAX_SELECTED: parser.error("limit must be 1..150")
    out=args.output_dir.resolve()
    if not out.is_relative_to(ROOT/"tmp") or out.exists(): parser.error("new output directory under tmp/ required")
    out.mkdir(parents=True)
    pack,mapping,map_sha,settings,url,engine,factory=pipeline._load_bundle(pipeline.DEFAULT_CANDIDATE_MAP)
    try:
        with factory() as db:
            db.execute(text("SET TRANSACTION READ ONLY")); protected=protected_fingerprints(db)
            initial_runs={str(r) for r in db.scalars(select(QuestionAnswerConsistencyRun.id))}
        pre=coverage(factory,pack,mapping,settings.llm_model,pipeline.DEFAULT_CANDIDATE_MAP); dump(out/"pre-audit.json",pre)
        records,summaries,nodes,qs,counts,types,caps=inventory(factory,pack,mapping,settings.llm_model)
        selection=select_coverage(records,summaries,counts,types,caps,min(BATCH_SIZE,args.limit),set())
        report={"schema_version":"phase3b-expansion-v1","created_at":datetime.now(timezone.utc).isoformat(),
            "mode":"execute" if args.execute else "dry_run","head":subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
            "workspace_dirty":bool(subprocess.check_output(["git","status","--porcelain"],cwd=ROOT,text=True)),
            "database":url.database,"model":settings.llm_model,"prompt_version":pipeline.ANSWER_ATTESTATION_PROMPT_VERSION,
            "dataset":{"pack_id":pack.pack_id,"pack_version":pack.version,"pack_sha256":sha256(pipeline.PACK_PATH.read_bytes()).hexdigest(),
                "mapping_sha256":map_sha,"archive_sha256":pipeline.DEFAULT_ARCHIVE_SHA,"archive_recomputed":False},
            "selection_policy":"coverage-first virtual inventory P0/P1/new type or capability/P3; confidence gates enforced",
            "limit":args.limit,"batch_size":BATCH_SIZE,"concurrency":3,"stop_policy":STOP_POLICY,
            "first_selection":[s for _,s in selection],"batches":[],"stopped_reasons":[]}
        dump(out/"expansion.json",report)
        if not args.execute: print(json.dumps({"mode":"dry_run","pre":pre["coverage_metrics"],"selected":len(selection),"priorities":dict(Counter(s["selection_priority"] for _,s in selection))},ensure_ascii=False)); return 0
        from backend.chat.service import Provider
        budget=min(settings.llm_max_output_tokens,pipeline.MAX_INITIAL_OUTPUT_TOKENS)
        provider=CountedProvider(Provider(api_key=settings.llm_api_key.get_secret_value(),base_url=settings.llm_base_url,
            model=settings.llm_model,timeout=min(settings.llm_timeout_seconds,45),max_tokens=budget,
            retry_max_tokens=min(max(budget*4,1400),pipeline.MAX_RETRY_OUTPUT_TOKENS)))
        processed=set()
        for letter in ("A","B","C"):
            records,summaries,_,_,counts,types,caps=inventory(factory,pack,mapping,settings.llm_model)
            selection=select_coverage(records,summaries,counts,types,caps,min(BATCH_SIZE,args.limit-len(processed)),processed)
            if not selection: break
            with factory() as db: previous_runs={str(r) for r in db.scalars(select(QuestionAnswerConsistencyRun.id))}
            batch={"batch":letter,"selected":[s for _,s in selection],"results":[]}; report["batches"].append(batch)
            def process(pair):
                r,s=pair
                try: return pipeline._process_question(r,factory=factory,provider=provider,settings=settings,pack=pack,archive_sha=pipeline.DEFAULT_ARCHIVE_SHA)
                except Exception as exc: return {"question_id":s["question_id"],"candidate_id":s["candidate_id"],"status":"INTERNAL_ERROR","exception_type":type(exc).__name__,"practice_eligible":False}
            with ThreadPoolExecutor(max_workers=3) as pool:
                for offset in range(0,len(selection),3):
                    chunk=selection[offset:offset+3]
                    results=list(pool.map(process,chunk)); batch["results"].extend(results)
                    processed.update(s["question_id"] for _,s in chunk)
                    batch["metrics"]=run_metrics(factory,previous_runs)
                    report["stopped_reasons"]=stop_reasons(batch["results"],batch["metrics"])
                    dump(out/"expansion.json",report)
                    print(json.dumps({"batch":letter,"processed":len(batch["results"]),"consistent":sum(r.get("status")=="AI_CONSISTENT" for r in batch["results"]),"stopped":report["stopped_reasons"]}),flush=True)
                    if report["stopped_reasons"]: break
            post=coverage(factory,pack,mapping,settings.llm_model,pipeline.DEFAULT_CANDIDATE_MAP); dump(out/f"batch-{letter}-audit.json",post)
            with factory() as db: current=protected_fingerprints(db)
            if current != protected: report["stopped_reasons"].append("protected_data_fingerprint_changed")
            batch["post_coverage"]=post["coverage_metrics"]
            batch["statuses"]=dict(Counter(r["status"] for r in batch["results"]))
            dump(out/"expansion.json",report)
            if report["stopped_reasons"] or len(processed)>=args.limit: break
        final=coverage(factory,pack,mapping,settings.llm_model,pipeline.DEFAULT_CANDIDATE_MAP); dump(out/"final-audit.json",final)
        with factory() as db: report["protected_data_unchanged"]=protected_fingerprints(db)==protected
        report["processed_count"]=len(processed); report["model_call_attempts"]=provider.calls
        report["metrics"]=run_metrics(factory,initial_runs); report["final_coverage"]=final["coverage_metrics"]
        report["new_practice_eligible"]=final["practice_eligible"]-pre["practice_eligible"]
        report["finished_at"]=datetime.now(timezone.utc).isoformat(); dump(out/"expansion.json",report)
        print(json.dumps({k:report[k] for k in ("processed_count","model_call_attempts","new_practice_eligible","protected_data_unchanged","stopped_reasons","final_coverage")},ensure_ascii=False))
        return 0
    finally: engine.dispose()


if __name__=="__main__": raise SystemExit(main())
