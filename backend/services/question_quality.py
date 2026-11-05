"""Shadow-only, version-bound quality audit. Never changes practice/trust/state."""
from copy import deepcopy
from difflib import SequenceMatcher
from hashlib import sha256
import json
import re

from backend.services.golden_learning_slice import digest
from backend.services.question_production_pipeline import validate_question_content
from backend.services.question_attestation import question_content_sha256, has_current_source_attestation
from backend.services.answer_verification import answer_version_sha256
from backend.services.answer_consistency import (answer_attestation_content_hash, answer_attestation_outcome,
    normalize_consistency_answer, ANSWER_ATTESTATION_PROMPT_VERSION, ANSWER_NORMALIZER_VERSION)
from backend.services.answer_grading import available_practice_grading_method, grade_practice_final_answer
from backend.services.question_eligibility import legacy_question_eligibility as question_eligibility
from backend.services.question_verification_upgrade import snapshot
from backend.services.quality_verifiers import verify_problem, option_value, VERSION as VERIFIER_VERSION

RULE_VERSION = "question-quality-shadow-v1"
TEACHING_RULE_VERSION = "question-teaching-use-v2"
STATUSES = frozenset({"PASS","FAIL","UNKNOWN","NOT_APPLICABLE","ERROR"})


def stage(status, reason, **details):
    if status not in STATUSES:
        raise ValueError("Unknown stage status")
    return {"status":status,"reason":reason,**details}


def source_identity(source):
    subject = {"数学二":"math2","考研数学":"math2","math2":"math2","408":"408"}.get(source.get("subject"))
    return subject, source.get("year"), source.get("question_number")


def duplicates(questions):
    identities, texts = {}, {}
    for q in questions:
        src = (q.grading_config or {}).get("provenance",{}).get("source",{})
        key = source_identity(src)
        if all(key): identities.setdefault(key,[]).append(str(q.id))
        content = re.sub(r"\s+","",q.stem or "")
        texts.setdefault((q.question_type,content,json.dumps(q.options,sort_keys=True,ensure_ascii=False)),[]).append(str(q.id))
    result = {}
    for q in questions:
        src = (q.grading_config or {}).get("provenance",{}).get("source",{})
        key = (q.question_type,re.sub(r"\s+","",q.stem or ""),json.dumps(q.options,sort_keys=True,ensure_ascii=False))
        exact = sorted({*identities.get(source_identity(src),[]),*texts[key]}-{str(q.id)})
        near = []
        numeric_template = re.sub(r"\d+(?:\.\d+)?","#",key[1])
        for other in questions:
            if other.id == q.id or str(other.id) in exact or other.question_type != q.question_type or other.kp_id != q.kp_id:
                continue
            other_text = re.sub(r"\s+","",other.stem or "")
            if (len(key[1])>=20 and (numeric_template == re.sub(r"\d+(?:\.\d+)?","#",other_text)
                    or SequenceMatcher(None,key[1],other_text,autojunk=False).ratio()>=.96)):
                near.append(str(other.id))
        result[str(q.id)] = {"exact":exact,"near":sorted(near),"semantic_dedup_executed":False}
    return result


def audit_teaching_question(q, node, *, source_check=None, runs=(), duplicate=None,
                            baseline=None, old_audit=None, build_sha=""):
    """Read-only, current-content assessment. Never accepts stored AUTO_PASS.

    Whole-source UNKNOWN is separate from teaching correctness. No absence of
    detected errors can replace an independent answer/semantic check.
    """
    baseline = baseline or question_eligibility(q, node)
    source_check = source_check or stage("UNKNOWN", "full_source_not_checked_at_runtime")
    old = old_audit or audit_question(q, node, source_check=source_check, runs=runs,
        duplicate=duplicate, build_sha=build_sha)
    if (old["binding"]["question_content_sha256"] != question_content_sha256(q)
            or old["binding"]["answer_version_sha256"] != answer_version_sha256(q)
            or old["binding"]["live_snapshot_sha256"] != digest(snapshot(q))):
        raise ValueError("Reject stale audit: current content/answer/snapshot binding changed")
    checks = old["stages"]
    hard = [f"{k}:{v['reason']}" for k, v in checks.items()
            if k in {"structure", "identity", "source", "mapping", "uniqueness", "independent_answer", "explanation"}
            and v["status"] == "FAIL"]
    field_checks = source_check.get("teaching_field_checks", {})
    hard.extend(f"source.{k}:{v['reason']}" for k, v in field_checks.items() if v["status"] == "FAIL")
    # Protect approved material corrections even when no PDF extraction runs.
    # The context must match the historical pre-correction record exactly.
    from backend.services.quality_sources import normalise
    for revision in (q.grading_config or {}).get("content_revisions", []):
        before = revision.get("before", {})
        corrected = revision.get("changes", {}).get("options")
        if not isinstance(corrected, dict) or not isinstance(before.get("options"), dict):
            continue
        if (before.get("stem") != q.stem or before.get("question_type") != q.question_type
                or before.get("kp_id") != str(q.kp_id)):
            continue
        for key, expected in corrected.items():
            if all(normalise(v) == normalise((q.options or {}).get(k, ""))
                   for k, v in before["options"].items() if k != key):
                if normalise(expected) != normalise((q.options or {}).get(key, "")):
                    hard.append("source:approved_material_correction_regressed")
    unresolved = [f"{k}:{checks[k]['reason']}" for k in ("uniqueness", "independent_answer")
                  if checks[k]["status"] in {"UNKNOWN", "ERROR"}]
    from backend.services.question_generation import current_generation_binding
    if isinstance((q.grading_config or {}).get("generation"),dict) and not current_generation_binding(q,node):
        unresolved.append("generation:current_generated_evidence_binding_invalid")
    unresolved.extend(f"source.{k}:{v['reason']}" for k, v in field_checks.items() if v["status"] in {"UNKNOWN", "ERROR"})
    if checks["answer_consistency"]["status"] == "FAIL" or q.answer_reliability == "ai_disagreement":
        unresolved.append("answer:unresolved_solver_conflict")
    mapping_ok = checks["mapping"]["status"] == "PASS"
    strict = baseline.practice_eligible and baseline.evidence_capability == "verified_objective"
    independent = checks["independent_answer"]["status"] == "PASS"
    reliable_answer = independent or strict
    from backend.services.answer_consistency import has_current_answer_attestation
    reference = (checks["answer_consistency"]["status"] == "PASS"
                 or q.answer_reliability == "ai_generated_consistent" and has_current_answer_attestation(q))
    process = q.question_type in {"proof", "discussion", "subjective", "program"}
    # Process solutions can be studied as references, but only with an existing
    # current content/mapping binding. An arbitrary unreviewed proof is not safe.
    reference = reference or process and baseline.practice_eligible
    ready = bool(q.is_active and mapping_ok and not hard and not unresolved)
    teaching = ready and reliable_answer
    reference_only = ready and not reliable_answer and reference
    grading = teaching and checks["grading"]["status"] == "PASS"
    strict_source = (q.question_provenance == "real_exam" and q.content_trust == "verified"
        and q.source_status == "verified" and baseline.source_attestation_current
        and bool(q.content_reviewed_by and q.content_reviewed_at))
    primary = ("BLOCKED_MATERIAL_ERROR" if hard else "OBJECTIVE_GRADING_ELIGIBLE" if grading else
        "TEACHING_PRACTICE_ELIGIBLE" if teaching else "REFERENCE_ONLY" if reference_only else "INSUFFICIENT_EVIDENCE")
    reasons = hard or unresolved or ([] if teaching or reference_only else
        ["teaching_quality_evidence_incomplete"] + ([] if mapping_ok else ["mapping_not_confirmed"]))
    label = ("历年真题整理版" if q.question_provenance == "real_exam" and baseline.source_attestation_current
        and q.source_status in {"traceable", "verified"} else "原创练习" if
        q.question_provenance == "ai_generated_practice" else "来源待核练习")
    from backend.services.question_generation import current_generation_binding
    if current_generation_binding(q,node):
        label=(q.grading_config or {})["generation"]["identity_label"]
    result = {"rule_version": TEACHING_RULE_VERSION, "binding": {**old["binding"], "rule_version": TEACHING_RULE_VERSION},
        "primary_use": primary, "teaching_practice_eligible": teaching,
        "reference_practice_eligible": reference_only, "objective_grading_eligible": grading,
        "comparison_method": checks["grading"].get("configured_method") if grading else None,
        "strict_source_verified": strict_source,
        "native_source_concordance_pass": checks["source"]["status"] == "PASS",
        "strict_graduation_evidence_eligible": strict and ready,
        "presentation_label": label, "explanation_label": "参考解析",
        "blocking_reasons": reasons, "material_error": bool(hard),
        "manual_review_candidate": bool(hard or any(not reason.startswith(("source.","generation:")) for reason in unresolved)),
        "actual_newly_activated": False, "database_written": False,
        "human_verified_created": False, "model_calls": 0,
        "scope": "current stored statement; reference feedback is not objective confirmation"}
    result["decision_sha256"] = digest(result)
    return result


def cached_consistency(q, runs):
    matching = [r for r in runs if r.question_id == q.id and
        r.question_content_sha256 == answer_attestation_content_hash(q) and
        r.prompt_version == ANSWER_ATTESTATION_PROMPT_VERSION and r.normalizer_version == ANSWER_NORMALIZER_VERSION]
    grouped = {}
    for r in matching: grouped.setdefault(r.check_key,[]).append(r)
    if not grouped:
        return stage("UNKNOWN","no_current_compatible_abc_evidence",model_calls=0)
    outcomes = [(key,answer_attestation_outcome(group)) for key,group in sorted(grouped.items())]
    method = available_practice_grading_method(question_type=q.question_type,config=q.grading_config,
        expected=q.correct_answer,options=q.options,answer_provenance=q.answer_provenance,
        content_trust=q.content_trust,answer_reliability=q.answer_reliability)
    expected = normalize_consistency_answer(question_type=q.question_type,method=method,
        answer=q.correct_answer,options=q.options,expected=q.correct_answer)
    good = [o for _,o in outcomes if o["status"] == "AI_CONSISTENT"]
    disagreement = any(o["status"] == "AI_DISAGREEMENT" for _,o in outcomes)
    if disagreement or (good and (len({o["normalized_answer"] for o in good}) != 1 or
            expected is not None and any(o["normalized_answer"] != expected for o in good))):
        return stage("FAIL","model_answer_conflict_not_mathematical_proof",check_keys=[k for k,_ in outcomes],model_calls=0)
    if good and expected is not None:
        return stage("PASS","cached_abc_and_stored_answer_agree",mathematical_proof=False,
            check_keys=[k for k,_ in outcomes],run_ids=sorted(str(r.id) for r in matching),model_calls=0)
    if any(r.status == "failed" for r in matching):
        return stage("ERROR","cached_model_execution_incomplete_not_question_error",model_calls=0)
    return stage("UNKNOWN","cached_abc_incomplete_or_reference_format_unsupported",model_calls=0)


def grader_checks(q):
    method = available_practice_grading_method(question_type=q.question_type,config=q.grading_config,
        expected=q.correct_answer,options=q.options,answer_provenance=q.answer_provenance,
        content_trust=q.content_trust,answer_reliability=q.answer_reliability)
    if method is None:
        return stage("NOT_APPLICABLE","no_bounded_objective_comparer",process_practice_possible=q.question_type in {"proof","subjective","discussion","program"})
    if q.question_type == "single_choice":
        target = q.correct_answer.strip().upper()
        wrong = next((k for k in q.options if k != target),None)
        cases = [("correct",None,target,"right"),("wrong",None,wrong,"wrong"),
            ("blank",None,"","unknown"),("illegal",None,"NOT_AN_OPTION","unknown"),
            ("case_spaces",None," "+target.lower()+" ","right"),
            ("unsupported_text","unparsed expression",None,"unknown")]
    else:
        base = method.removeprefix("ai_generated_").removeprefix("reference_")
        cases = [("correct",q.correct_answer,None,"right"),("blank","",None,"unknown"),
                 ("illegal","1/0",None,"unknown"),("unsupported","untrusted(x)",None,"unknown")]
        if base == "numeric_final":
            from backend.services.answer_grading import _numeric_value
            value = _numeric_value(q.correct_answer)
            if value is not None:
                cases += [("wrong",str(value+1),None,"wrong"),
                    ("equivalent_fraction",f"{value.numerator*2}/{value.denominator*2}",None,"right")]
        elif base == "logarithm_final":
            from backend.services.answer_grading import _log_argument
            value = _log_argument(q.correct_answer)
            if value is not None: cases += [("wrong",f"ln({value+1})",None,"wrong")]
        elif base == "constant_final":
            cases += [("wrong",f"({q.correct_answer.strip().strip('$')})+1",None,"wrong")]
        elif base == "range_final":
            from backend.services.phase45i_quality_verifiers import _range_pair
            bounds = _range_pair(q.correct_answer)
            if bounds is not None and bounds[2:] == (True, True):
                low, high = bounds[:2]
                cases += [("wrong",f"[{low-1},{high}]",None,"wrong"),
                    ("equivalent_spacing",f"[ {low} , {high} ]",None,"right")]
    results=[]
    for label,answer,selected,want in cases:
        actual=grade_practice_final_answer(question_type=q.question_type,config=q.grading_config,
            answer=answer,selected_option=selected,expected=q.correct_answer,options=q.options,
            answer_provenance=q.answer_provenance,content_trust=q.content_trust,answer_reliability=q.answer_reliability)
        results.append({"case":label,"expected":want,"actual":actual.result,"reason":actual.reason,"actual_method":actual.method})
    return stage("PASS" if all(c["expected"]==c["actual"] for c in results) else "FAIL",
        "actual_comparer_boundary_tests",configured_method=method,cases=results,standard_answer_proved=False)


def ambiguity(q, independent):
    if q.question_type != "single_choice": return stage("NOT_APPLICABLE","not_single_choice")
    if independent.get("reason") == "non_unique_correct_option":
        return stage("FAIL","multiple_or_no_correct_options",matching_options=independent.get("matching_options",[]))
    text=q.stem or ""
    if ("\\lim" in text or "极限" in text) and "存在" in text and "有限" not in text:
        return stage("UNKNOWN","finite_limit_convention_requires_context",question_is_wrong=False)
    if independent["status"]=="PASS" and independent.get("matching_options"):
        return stage("PASS","unique_option_from_independently_derived_result",matching_options=independent["matching_options"])
    from backend.services.constant_expression import constant_expression
    values={k:constant_expression(option_value(v)) for k,v in (q.options or {}).items()}
    if values and all(v is not None for v in values.values()):
        from sympy import simplify
        pairs=[(a,b) for a in values for b in values if a<b and simplify(values[a]-values[b])==0]
        if pairs: return stage("UNKNOWN","equivalent_option_values_need_problem_context",pairs=pairs,question_is_wrong=False)
    return stage("NOT_APPLICABLE","semantic_uniqueness_outside_verifier_scope",unique_answer_proved=False)


def audit_question(q,node,*,source_check,runs=(),duplicate=None,rule_version=RULE_VERSION,build_sha="",candidate=False):
    if rule_version != RULE_VERSION: raise ValueError("Unsupported rule version")
    source=(q.grading_config or {}).get("provenance",{}).get("source",{})
    eligibility=question_eligibility(q,node)
    content=validate_question_content(q)
    issues=[i for i in content.detected_issues if i != "human_content_review_required"]
    if re.search(r"\$[^$]*$",q.stem or "") and (q.stem or "").count("$")%2:
        issues.append("unclosed_math_delimiter")
    if (q.stem or "").count("{") != (q.stem or "").count("}"):
        issues.append("unbalanced_latex_group")
    if q.question_type not in {"single_choice","fill_blank","calculation","proof","discussion","subjective","program"}:
        issues.append("unsupported_question_type")
    structure=stage("FAIL" if issues else "PASS","structure_incomplete" if issues else "structure_pass_not_answer_proof",issues=issues)
    declared=source.get("source_type")
    if q.question_provenance=="real_exam" and declared != "exam":
        identity=stage("FAIL","canonical_exam_conflicts_with_source_declaration")
    elif q.question_provenance=="legacy_unknown" or not all(source_identity(source)):
        identity=stage("UNKNOWN","source_identity_or_canonical_origin_unresolved")
    else:
        identity=stage("PASS","declared_identity_consistent_not_official_authentication")
    binding=has_current_source_attestation(q)
    mapping=stage("FAIL" if node is None or not node.is_active or not node.is_assessable else
        "PASS" if binding or eligibility.evidence_capability=="verified_objective" else "UNKNOWN",
        "existing_mapping_binding" if binding else "existing_verified_content_binding" if eligibility.evidence_capability=="verified_objective" else "mapping_requires_metadata_review",
        semantic_skill_match_verified=False,generic_skill_tags=bool(node and q.skill_tags==[node.name]))
    from backend.services.question_generation import current_generation_binding
    if current_generation_binding(q,node):
        general_personal = (q.grading_config or {}).get("generation", {}).get("version") == "personal-general-generation-v1"
        mapping=stage("PASS","user_confirmed_personal_node_binding" if general_personal else
            "current_generated_content_and_allowlisted_node_binding",semantic_skill_match_verified=False)
    if node is not None and (q.grading_config or {}).get("provenance",{}).get("kp_code",node.code) != node.code:
        mapping=stage("FAIL","pack_node_code_mismatch")
    declared_subject=source_identity(source)[0]
    if node is not None and ((declared_subject=="408" and node.subject!="408") or
            (declared_subject=="math2" and node.subject=="408")):
        mapping=stage("FAIL","source_subject_and_node_conflict")
    duplicate=duplicate or {"exact":[],"near":[],"semantic_dedup_executed":False}
    dup=stage("FAIL" if duplicate["exact"] else "UNKNOWN" if duplicate["near"] else "PASS",
        "exact_duplicate" if duplicate["exact"] else "near_or_numeric_template_risk" if duplicate["near"] else "no_deterministic_duplicate",**duplicate)
    try: independent=verify_problem(q)
    except Exception as exc: independent=stage("ERROR","deterministic_tool_failed_not_question_error",error_type=type(exc).__name__)
    abc=cached_consistency(q,runs)
    formal=stage("PASS" if eligibility.answer_verification_current else "UNKNOWN",
        "existing_hash_bound_answer_verification" if eligibility.answer_verification_current else "no_current_formal_answer_verification",
        event_id=eligibility.answer_verification_event_id,created_by_this_audit=False)
    if q.question_type in {"proof","subjective","discussion","program"}:
        abc=stage("NOT_APPLICABLE","abc_final_answer_solver_not_for_process_questions")
    try: grading=grader_checks(q)
    except Exception as exc: grading=stage("ERROR","grader_tool_failed_not_question_error",error_type=type(exc).__name__)
    unique=ambiguity(q,independent)
    explanation=stage("UNKNOWN","explanation_not_independently_proved",present=bool(q.explanation))
    if independent["status"]=="PASS":
        explanation=stage("UNKNOWN","standard_answer_verified_explanation_steps_not_proved",proof=independent.get("proof"))
    checks={"structure":structure,"identity":identity,"source":deepcopy(source_check),"answer_consistency":abc,"existing_answer_verification":formal,
        "independent_answer":independent,"explanation":explanation,"uniqueness":unique,"mapping":mapping,
        "duplicates":dup,"grading":grading}
    hard=structure["status"]=="FAIL" or source_check["status"]=="FAIL" or identity["status"]=="FAIL" or dup["status"]=="FAIL" or mapping["status"]=="FAIL" or unique["status"]=="FAIL" or independent["status"]=="FAIL"
    core_pass=all(checks[k]["status"]=="PASS" for k in ("structure","identity","source","mapping","duplicates","grading"))
    answer_ready=independent["status"]=="PASS" or abc["status"]=="PASS" or formal["status"]=="PASS"
    state="QUARANTINED" if hard else "AUTO_PASS" if core_pass and answer_ready and unique["status"] not in {"UNKNOWN","ERROR"} else "NEEDS_REVIEW"
    uses=["STRICT_VERIFICATION_REQUIRED"]
    if state=="AUTO_PASS": uses.append("OBJECTIVE_EVIDENCE_CANDIDATE" if independent["status"]=="PASS" else "PRACTICE_REFERENCE")
    else: uses.append("NOT_ELIGIBLE")
    risks=[{"stage":k,"status":v["status"],"reason":v["reason"]} for k,v in checks.items() if v["status"] in {"FAIL","UNKNOWN","ERROR"}]
    manual=any(v["reason"] in {"source_field_difference","canonical_exam_conflicts_with_source_declaration",
        "source_paper_year_conflict","source_paper_subject_conflict","source_question_number_conflict",
        "finite_limit_convention_requires_context","multiple_or_no_correct_options","derived_key_conflict",
        "model_answer_conflict_not_mathematical_proof"} for v in checks.values())
    mapping_payload={"kp_id":str(q.kp_id),"node_code":node.code if node else None,"node_name":node.name if node else None,
        "node_active":node.is_active if node else False,"assessable":node.is_assessable if node else False,
        "reference_only":node.is_reference_only if node else None,"subject":node.subject if node else None,"skill_tags":q.skill_tags}
    evidence_rows=[{"id":str(r.id),"check_key":r.check_key,"number":r.run_number,"role":r.run_role,
        "model":r.configured_model,"final_answer":r.final_answer,
        "status":r.status,"answer":r.normalized_final_answer,"verification":r.verification_result,
        "prompt":r.prompt_version,"normalizer":r.normalizer_version,"hash":r.question_content_sha256}
        for r in sorted(runs,key=lambda r:str(r.id)) if r.question_id==q.id]
    binding_info={"audit_subject_id":str(q.id),"question_id":None if candidate else str(q.id),"is_candidate":candidate,
        "question_content_sha256":question_content_sha256(q),"answer_version_sha256":answer_version_sha256(q),
        "live_snapshot_sha256":digest(snapshot(q)),"consistency_evidence_sha256":digest(evidence_rows),
        "answer_explanation_sha256":digest({"answer":q.correct_answer,"explanation":q.explanation}),
        "source_sha256":digest({"declaration":source,"actual_material":source_check}),
        "mapping_sha256":digest(mapping_payload),"grading_config_sha256":digest(q.grading_config or {}),
        "rule_version":rule_version,"rule_build_sha256":build_sha,"verifier_version":VERIFIER_VERSION}
    result={"binding":binding_info,"status":state,"stages":checks,"risks":risks,"allowed_uses":uses,
        "manual_review_candidate":manual,"current_practice_eligible":eligibility.practice_eligible and not candidate,
        "current_eligibility":eligibility.public_dict(),"independent_standard_answer_verified":independent["status"]=="PASS",
        "source_traceable":bool(source_check.get("material_accessible")),
        "source_full_concordance_verified":source_check["status"]=="PASS",
        "potential_practice_reference":state=="AUTO_PASS", "actual_newly_activated":False,
        "human_verified_created":False,"database_written":False,"model_calls":0,
        "repair_suggestions":[{"field":"options."+k,"before":v,"candidate":option_value(v),
            "kind":"display_separator_candidate","requires_source_comparison":True,"applied":False}
            for k,v in (q.options or {}).items() if isinstance(v,str) and re.search(r"\n-\s*$",v)],
        "followup_actions":sorted({"source_asset_or_extraction_followup" if k=="source" else
            "answer_review" if k=="answer_consistency" and v["status"]=="FAIL" else
            "deferred_tool_retry" if v["status"]=="ERROR" else
            "metadata_followup" if k in {"identity","mapping"} else "scope_or_risk_review"
            for k,v in checks.items() if v["status"] in {"FAIL","UNKNOWN","ERROR"}}),
        "scope_note":"shadow result only; standard answer for stored statement and original fidelity are separate; explanation proof remains pending"}
    result["input_fingerprint"]=digest(binding_info)
    result["decision_sha256"]=digest(result)
    return result
