"""TEST_FIXTURE only; no human attestation or production writes."""
from copy import deepcopy
import pytest
from tests.unit.test_question_quality import item, abc, source_pass
from backend.services.question_quality import audit_teaching_question
from backend.services.question_eligibility import question_eligibility
from backend.services.quality_sources import compare_teaching_field
from backend.services.question_attestation import question_content_sha256
from backend.services.answer_consistency import answer_attestation_result_hash
from backend.services.question_verification_upgrade import snapshot


UNKNOWN = {"status":"UNKNOWN","reason":"scan_not_extractable"}


def rebind(q):
    q.source_attestation_sha256=question_content_sha256(q)
    q.answer_attestation_sha256=answer_attestation_result_hash(q)


@pytest.mark.parametrize("a,b", [("计算1+1", "计算1+1。"), ("1/2", "0.5"), ("$1/2$", r"$\frac{1}{2}$")])
def test_bounded_typographic_or_constant_equivalence(a,b):
    assert compare_teaching_field(a,b)["status"]=="PASS"


@pytest.mark.parametrize("a,b", [("$1/x$","$-1/x$"), (r"$\int f(x)dx$",r"$\int_0^1 f(x)dx$")])
def test_missing_material_symbols_not_formatting(a,b):
    assert compare_teaching_field(a,b)["status"]=="FAIL"
    q,n=item()
    source={**UNKNOWN,"teaching_field_checks":{"stem":compare_teaching_field(a,b)}}
    assert audit_teaching_question(q,n,source_check=source)["primary_use"]=="BLOCKED_MATERIAL_ERROR"


def test_unknown_source_with_independent_answer_is_candidate_not_strict():
    q,n=item()
    before=snapshot(q)
    r=audit_teaching_question(q,n,source_check=UNKNOWN)
    assert r["teaching_practice_eligible"] and r["objective_grading_eligible"]
    assert not r["strict_source_verified"] and not r["strict_graduation_evidence_eligible"]
    assert snapshot(q)==before


@pytest.mark.parametrize("answer,options", [("B",None),("A",{"A":"1","B":"1.0","C":"3","D":"4"})])
def test_wrong_key_or_two_correct_options_block(answer,options):
    q,n=item(answer=answer)
    if options: q.options=options
    rebind(q)
    r=audit_teaching_question(q,n,source_check=UNKNOWN)
    assert r["material_error"] and not r["objective_grading_eligible"]


def test_alternate_explanation_is_explicit_reference_not_exact_official_gate():
    q,n=item()
    q.explanation="TEST_FIXTURE: use a different exact rational derivation."
    r=audit_teaching_question(q,n,source_check=UNKNOWN)
    assert r["teaching_practice_eligible"] and r["explanation_label"]=="参考解析"


def test_ai_consensus_is_reference_only_never_reliable():
    q,n=item("Select the statement about a test concept.")
    r=audit_teaching_question(q,n,source_check=UNKNOWN,runs=abc(q))
    assert r["primary_use"]=="REFERENCE_ONLY" and not r["objective_grading_eligible"]
    e=question_eligibility(q,n,teaching_enabled=True)
    assert not e.practice_eligible and e.answer_comparison_method is None
    assert e.evidence_capability=="archive_only" and e.verified_grading_method is None
    assert "public_formal_review_required" in e.blocking_reasons


def test_proof_with_current_content_can_be_reference_learning_only():
    q,n=item("Prove the TEST_FIXTURE mathematical statement.")
    q.question_type="proof"; q.options=None; q.correct_answer="TEST_FIXTURE reference proof"
    rebind(q)
    r=audit_teaching_question(q,n,source_check=UNKNOWN)
    assert r["reference_practice_eligible"] and not r["objective_grading_eligible"]


def test_unknown_origin_does_not_become_exam_even_if_mathematically_usable():
    q,n=item(); q.question_provenance="legacy_unknown"
    r=audit_teaching_question(q,n,source_check=UNKNOWN)
    assert r["teaching_practice_eligible"] and r["presentation_label"]=="来源待核练习"
    assert q.question_provenance=="legacy_unknown"


def test_missing_figure_remains_blocked():
    q,n=item("根据下图求树的结点数。")
    rebind(q)
    r=audit_teaching_question(q,n,source_check=UNKNOWN)
    assert r["material_error"] and not r["reference_practice_eligible"]


def test_q7_convention_risk_remains_unknown_not_false_pass():
    q,n=item(r"若存在p>1，使\lim x^p f(x)存在，判断命题。")
    r=audit_teaching_question(q,n,source_check=UNKNOWN)
    assert r["primary_use"]=="INSUFFICIENT_EVIDENCE" and r["manual_review_candidate"]


def test_version_drift_no_recertification_or_old_receipt_promotion():
    q,n=item("Select the statement about a test concept.")
    old=deepcopy(snapshot(q))
    q.correct_answer="B"
    r=audit_teaching_question(q,n,source_check=UNKNOWN)
    assert r["primary_use"]=="INSUFFICIENT_EVIDENCE"
    assert old["correct_answer"]=="A" and q.correct_answer=="B"
    assert not r["human_verified_created"]


def test_legacy_teaching_flag_cannot_bypass_public_formal_review(monkeypatch):
    from backend.config import get_settings
    assert get_settings().teaching_practice_enabled is False
    q,n=item()
    assert not question_eligibility(q,n,teaching_enabled=False).practice_eligible
    assert not question_eligibility(q,n).practice_eligible
    before=snapshot(q)
    enabled=question_eligibility(q,n,teaching_enabled=True)
    assert not enabled.practice_eligible
    assert snapshot(q)==before


def test_formal_source_failure_not_ignored_for_teaching():
    q,n=item()
    r=audit_teaching_question(q,n,source_check={"status":"FAIL","reason":"source_paper_year_conflict"})
    assert r["material_error"] and not r["teaching_practice_eligible"]


def test_mapping_missing_and_unsupported_semantics_do_not_default_pass():
    q,n=item("Choose the TEST_FIXTURE statement.")
    q.source_attestation_sha256=None
    r=audit_teaching_question(q,n,source_check=UNKNOWN)
    assert r["primary_use"]=="INSUFFICIENT_EVIDENCE"


def test_q6_historical_correction_cannot_be_silently_regressed():
    q,n=item("Choose the TEST_FIXTURE statement.")
    before=snapshot(q)
    q.grading_config["content_revisions"]=[{"before":before,"changes":{"options":{"C":"-3"}}}]
    r=audit_teaching_question(q,n,source_check=UNKNOWN)
    assert r["material_error"] and "source:approved_material_correction_regressed" in r["blocking_reasons"]


def test_known_misleading_explanation_is_not_excused_as_reference():
    from backend.services.question_quality import audit_question
    q,n=item()
    evidence=audit_question(q,n,source_check=UNKNOWN)
    evidence["stages"]["explanation"]={"status":"FAIL","reason":"TEST_FIXTURE proven misleading step"}
    r=audit_teaching_question(q,n,source_check=UNKNOWN,old_audit=evidence)
    assert r["material_error"] and not r["teaching_practice_eligible"]


def test_previous_audit_cannot_be_used_for_changed_answer():
    from backend.services.question_quality import audit_question
    q,n=item(); old=audit_question(q,n,source_check=UNKNOWN)
    q.correct_answer="B"
    with pytest.raises(ValueError,match="stale audit"):
        audit_teaching_question(q,n,source_check=UNKNOWN,old_audit=old)


def test_unknown_wording_equivalence_is_not_automatically_signed_or_sent_to_human():
    q,n=item()
    r=audit_teaching_question(q,n,source_check={**UNKNOWN,"teaching_field_checks":{
        "stem":{"status":"UNKNOWN","reason":"semantic_equivalence_outside_bounded_scope"}}})
    assert r["primary_use"]=="INSUFFICIENT_EVIDENCE" and not r["manual_review_candidate"]
