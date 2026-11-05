"""Export the finished expansion audit as inspectable JSON and node CSV."""
import argparse
from collections import Counter
from datetime import datetime
import csv
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.expand_phase3b_inventory import dump
from scripts.expand_phase3b_inventory import inventory
from scripts import run_phase3b_question_pipeline as pipeline
from sqlalchemy import select, text
from backend.models.learning import QuestionAnswerConsistencyRun


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir",type=Path,required=True); args=parser.parse_args()
    folder=args.run_dir.resolve()
    if not folder.is_relative_to(ROOT/"tmp"): parser.error("run directory under project tmp/ required")
    run=json.loads((folder/"expansion.json").read_text(encoding="utf-8"))
    audit=json.loads((folder/"final-audit.json").read_text(encoding="utf-8"))
    results=[r for b in run["batches"] for r in b["results"]]
    selected=[s for b in run["batches"] for s in b["selected"] if s["question_id"] in {r["question_id"] for r in results}]
    nodes=audit["assessable_node_coverage"]
    assert len(nodes)==audit["assessable_knowledge_nodes"] and len({n["node_id"] for n in nodes})==len(nodes)
    for row in nodes:
        dimensions={"concept_conditions","final_result","application_transfer","reasoning_process"}
        if "408" in row["subject"]: dimensions.add("algorithm_process")
        row["unrepresented_capability_dimensions"] = sorted(dimensions-set(row["capability_dimension_distribution"]))
        row["unrepresented_dimension_scope"] = "descriptive_course_dimensions_not_node_graduation_requirements"
        row["distinct_gap_to_two_report_target"] = max(0,2-row["distinct_question_count"])
        row["only_ai_consistent_practice_answers"] = row["practice_eligible_count"]>0 and row["verified_reference_answer_count"]==0 and row["ai_consistent_answer_count"]>=row["practice_eligible_count"]
        row["candidate_count_scope"]="attributable_mapping_rows_only"
        row["unmatched_assignment_complete"]=not bool(audit["unassignable_candidate_counts"].get("UNMATCHED",0))
    audit["expansion_funnel"]={"total_candidates":audit["candidate_map_rows"],"exact":audit["candidate_exact"],
        "source_attestable":audit["candidate_funnel"]["source_attestable"],
        "selected_and_processed":len(results),"selected_unique":len({r["question_id"] for r in results}),
        "source_attested":sum(r.get("source_attested",False) for r in results),
        "selection_integrity_pass":sum(s["integrity_status"]=="STRUCTURALLY_COMPLETE" for s in selected),
        "answer_reference_existing_selected":0,"ai_consistency_required":len(results),
        "ai_consistent":sum(r["status"]=="AI_CONSISTENT" for r in results),
        "ai_disagreement":sum(r["status"]=="AI_DISAGREEMENT" for r in results),
        "incomplete":sum(r["status"]=="INCOMPLETE" for r in results),
        "other_blocked":sum(r["status"] not in {"AI_CONSISTENT","AI_DISAGREEMENT","INCOMPLETE"} for r in results),
        "practice_eligible":sum(bool(r.get("practice_eligible")) for r in results),
        "evidence_eligible":sum(r.get("evidence_capability")=="ai_consistent_objective" for r in results)}
    audit["model_statistics"]=run["metrics"]
    audit["model_statistics"]["actual_http_call_attempts"]=run["model_call_attempts"]
    pack,mapping,_,settings,_,engine,factory=pipeline._load_bundle(pipeline.DEFAULT_CANDIDATE_MAP)
    try:
        with factory() as db:
            db.execute(text("SET TRANSACTION READ ONLY"))
            all_runs=list(db.scalars(select(QuestionAnswerConsistencyRun)))
        started=datetime.fromisoformat(run["created_at"])
        qids={r["question_id"] for r in results}
        old_roles={(r.check_key,r.run_role) for r in all_runs if r.created_at<started}
        new_roles=Counter((r.check_key,r.run_role) for r in all_runs if str(r.question_id) in qids and r.created_at>=started)
        audit["model_statistics"]["resumed_roles"]=sum(key in old_roles for key in new_roles)
        audit["model_statistics"]["retry_call_attempts_including_resumption"]=sum(count-(0 if key in old_roles else 1) for key,count in new_roles.items())
        _,summaries,_,questions,_,_,_=inventory(factory,pack,mapping,settings.llm_model)
        live_by_id={s["question_id"]:s for s in summaries}
        q_by_id={str(q.id):q for q in questions}
        successes=[r for r in results if r["status"]=="AI_CONSISTENT"]
        failures=[r for r in results if r["status"]!="AI_CONSISTENT"]
        audit["activation_provenance_checks"]={
            "successes_still_practice_eligible":all(live_by_id[r["question_id"]]["practice_eligible"] for r in successes),
            "failed_candidates_closed":all(not live_by_id[r["question_id"]]["practice_eligible"] for r in failures),
            "successes_ai_provenance_preserved":all(q_by_id[r["question_id"]].answer_provenance=="ai_generated" and q_by_id[r["question_id"]].answer_reliability=="ai_generated_consistent" for r in successes),
            "no_human_answer_stamps_created":all(q_by_id[r["question_id"]].answer_reviewed_at is None and q_by_id[r["question_id"]].answer_reviewed_by is None for r in successes),
            "no_verified_reference_created":all(q_by_id[r["question_id"]].answer_provenance!="verified_reference" for r in results)}
        assert all(audit["activation_provenance_checks"].values()), "Activation trust invariant failed"
        for row in nodes:
            candidates=[s for s in summaries if s["kp_id"]==row["node_id"]]
            process_types={"proof","discussion","program","subjective"}
            row["process_candidate_count"]=sum(s["question_type"] in process_types for s in candidates)
            if candidates and all(s["question_type"] in process_types for s in candidates):
                if "PROCESS_ONLY" not in row["coverage_gap_reasons"]: row["coverage_gap_reasons"].append("PROCESS_ONLY")
                if "process_review" not in row["future_remedies"]: row["future_remedies"].append("process_review")
        audit["coverage_gap_counts"]=dict(Counter(g for r in nodes for g in r["coverage_gap_reasons"]))
        audit["global_answer_check_states"]=dict(Counter(s["answer_check_state"] for s in summaries))
        audit["global_incomplete_answer_checks"]=sum(s["answer_check_state"] in {"resumable","exhausted"} and not s["practice_eligible"] for s in summaries)
        audit["global_consistency_error_counts"]=dict(Counter(r.error_code for r in all_runs if r.error_code))
        audit["model_configuration"]={"endpoint_sha256":sha256(settings.llm_base_url.encode()).hexdigest(),
            "initial_output_tokens":min(settings.llm_max_output_tokens,pipeline.MAX_INITIAL_OUTPUT_TOKENS),
            "retry_output_tokens":min(max(min(settings.llm_max_output_tokens,pipeline.MAX_INITIAL_OUTPUT_TOKENS)*4,1400),pipeline.MAX_RETRY_OUTPUT_TOKENS),
            "timeout_seconds":min(settings.llm_timeout_seconds,45),"max_runs_per_check":6}
    finally: engine.dispose()
    audit["raw_reference_answer_changed_count"]=sum(r.get("source_answer_changed_by_consensus",False) for r in results)
    audit["limits"].extend(["NO_CANDIDATE means no candidate attributable to this node in the supplied mapping; unassignable candidates are separately reported, not guessed.",
        "Distinct gap to two is a descriptive audit comparison, never a graduation rule.",
        "Unrepresented course dimensions are not pedagogically required for every node.",
        "Imported explanations are not independently semantically verified; raw reference-answer changes may include equivalent formatting changes."])
    audit["source_files_sha256"]={str(p.relative_to(ROOT)).replace('\\','/'):sha256(p.read_bytes()).hexdigest() for p in [
        ROOT/"scripts/expand_phase3b_inventory.py",ROOT/"scripts/verify_phase3b_expansion_inventory.py",
        ROOT/"scripts/export_phase3b_expansion_coverage.py",ROOT/"tests/unit/test_phase3b_expansion.py",
        ROOT/"scripts/run_phase3b_question_pipeline.py",
        ROOT/"scripts/audit_question_production.py",ROOT/"backend/services/question_attestation.py",
        ROOT/"backend/services/answer_consistency.py",ROOT/"backend/services/question_eligibility.py",
        ROOT/"backend/services/answer_grading.py",ROOT/"backend/services/evidence_pool.py"]}
    dump(folder/"coverage-gap-details.json",audit)
    fields=["node_id","code","name","subject","classification","practice_eligible_count","verified_reference_answer_count",
        "ai_consistent_answer_count","grading_supported_count","process_review_count","distinct_question_count",
        "distinct_real_exam_question_count","distinct_year_count","question_type_distribution","capability_dimension_distribution",
        "unused_practice_count","previously_attempted_practice_count","evidence_pool_status","candidate_exact_count",
        "candidate_possible_count","candidate_unmatched_count","remaining_machine_attestable_candidate_count",
        "remaining_expansion_selectable_candidate_count","coverage_gap_reasons","future_remedies",
        "unrepresented_capability_dimensions","distinct_gap_to_two_report_target","only_ai_consistent_practice_answers","pedagogical_review_needed",
        "candidate_count_scope","unmatched_assignment_complete","process_candidate_count"]
    with (folder/"coverage-gaps.csv").open("w",encoding="utf-8-sig",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=fields); writer.writeheader()
        for row in nodes: writer.writerow({k:json.dumps(row[k],ensure_ascii=False) if isinstance(row[k],(list,dict)) else row[k] for k in fields})
    print(json.dumps({"nodes":len(nodes),"funnel":audit["expansion_funnel"],"coverage":audit["coverage_metrics"],"gaps":audit["coverage_gap_counts"]},ensure_ascii=True))


if __name__=="__main__": main()
