"""Synthetic local sources/results only. No production certification or writes."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import hashlib
import pytest

from backend.models.learning import Question
from backend.services.golden_learning_slice import digest
from backend.services.question_attestation import question_content_sha256
from backend.services.answer_consistency import (answer_attestation_content_hash,answer_attestation_result_hash,
    ANSWER_ATTESTATION_PROMPT_VERSION,ANSWER_NORMALIZER_VERSION)
from backend.services.question_verification_upgrade import snapshot
from backend.services.question_quality import audit_question,duplicates,grader_checks
from backend.services.quality_sources import inspect_source,NativePageReader,material_descriptor
from backend.services.quality_verifiers import verify_problem
from scripts.audit_question_quality import candidate_rows,safe_output


def item(stem="Compute 1/2+1/2.",answer="A"):
    node=SimpleNamespace(id=uuid4(),code="math.TEST_FIXTURE",name="TEST_FIXTURE arithmetic",subject="math2",
        is_active=True,is_assessable=True,is_reference_only=False)
    q=Question(id=uuid4(),kp_id=node.id,question_type="single_choice",stem=stem,
        options={"A":"1","B":"2","C":"3","D":"4"},correct_answer=answer,explanation="TEST_FIXTURE explanation only",
        question_role="basic",difficulty="basic",estimated_minutes=3,skill_tags=["arithmetic"],is_variant=False,
        is_active=True,grading_mode="self_assessed",grading_config={"verified":False,"method":None,"practice_method":"single_choice",
            "provenance":{"content_status":"source_transcribed","source":{"source_type":"exam","subject":"math2","year":2020,"question_number":1,"citation":"TEST_FIXTURE local PDF"}}},
        question_provenance="real_exam",content_trust="source_attested",source_status="traceable",
        answer_provenance="ai_generated",answer_reliability="ai_generated_consistent")
    q.source_attestation_key="TEST_FIXTURE_SOURCE"
    q.source_attestation_sha256=question_content_sha256(q)
    q.answer_attestation_key="TEST_FIXTURE_ANSWER"
    q.answer_attestation_sha256=answer_attestation_result_hash(q)
    return q,node


def source_pass():
    return {"status":"PASS","reason":"TEST_FIXTURE exact native match","material_accessible":True}


def abc(q,failed=False):
    rows=[]
    for i,role in enumerate(("solve_a","solve_b","verify_c"),1):
        rows.append(SimpleNamespace(id=uuid4(),question_id=q.id,question_content_sha256=answer_attestation_content_hash(q),
            prompt_version=ANSWER_ATTESTATION_PROMPT_VERSION,normalizer_version=ANSWER_NORMALIZER_VERSION,
            check_key="TEST_FIXTURE_CURRENT",run_number=i,run_role=role,status="failed" if failed else "completed",
            normalized_final_answer="choice:A",final_answer="A",configured_model="TEST_FIXTURE_MODEL",
            verification_result={"status":"supports","supported_answers":["choice:A"],"note":"TEST_FIXTURE"}))
    return rows


def test_structure_complete_but_wrong_key_is_quarantined_not_fixed():
    q,n=item(answer="B")
    before=snapshot(q)
    r=audit_question(q,n,source_check=source_pass())
    assert r["status"]=="QUARANTINED" and r["stages"]["structure"]["status"]=="PASS"
    assert r["stages"]["independent_answer"]["reason"]=="derived_key_conflict"
    assert snapshot(q)==before and not r["database_written"]


def test_deterministic_standard_answer_separate_from_real_comparer():
    q,n=item()
    r=audit_question(q,n,source_check=source_pass())
    assert r["status"]=="AUTO_PASS" and r["stages"]["grading"]["status"]=="PASS"
    assert r["independent_standard_answer_verified"]
    assert "OBJECTIVE_EVIDENCE_CANDIDATE" in r["allowed_uses"] and not r["actual_newly_activated"]
    assert q.answer_provenance=="ai_generated" and q.grading_config["verified"] is False


def test_abc_consensus_only_does_not_become_math_proof():
    q,n=item("Select the statement about a test concept.")
    r=audit_question(q,n,source_check=source_pass(),runs=abc(q))
    assert r["stages"]["answer_consistency"]["status"]=="PASS"
    assert r["stages"]["answer_consistency"]["mathematical_proof"] is False
    assert r["stages"]["independent_answer"]["status"]=="NOT_APPLICABLE"
    assert r["allowed_uses"]==["STRICT_VERIFICATION_REQUIRED","PRACTICE_REFERENCE"]


def test_model_failed_is_needs_review_not_bad_question():
    q,n=item("Select the statement about a test concept.")
    r=audit_question(q,n,source_check=source_pass(),runs=abc(q,failed=True))
    assert r["status"]=="NEEDS_REVIEW" and r["stages"]["answer_consistency"]["status"]=="ERROR"
    assert "deferred_tool_retry" in r["followup_actions"]


def test_q7_style_ambiguity_unknown_not_prejudged_wrong():
    q,n=item(r"若存在p>1，使\lim x^p f(x)存在，判断命题。")
    r=audit_question(q,n,source_check=source_pass())
    assert r["status"]=="NEEDS_REVIEW"
    assert r["stages"]["uniqueness"]["reason"]=="finite_limit_convention_requires_context"
    assert r["stages"]["uniqueness"]["question_is_wrong"] is False


def test_equivalent_correct_options_detected_by_derived_result():
    q,n=item("Compute 1/2.")
    q.options={"A":"1/2","B":"0.5","C":"2","D":"3"}
    r=audit_question(q,n,source_check=source_pass())
    assert r["status"]=="QUARANTINED"
    assert r["stages"]["uniqueness"]["matching_options"]==["A","B"]


def test_missing_source_and_canonical_declaration_not_enough(tmp_path):
    q,n=item()
    src=inspect_source(q,{"path":str(tmp_path/"absent.pdf")},NativePageReader())
    assert src["reason"]=="SOURCE_UNVERIFIED"
    r=audit_question(q,n,source_check=src)
    assert r["status"]=="NEEDS_REVIEW" and not r["source_full_concordance_verified"]
    q.question_provenance="legacy_unknown"
    r=audit_question(q,n,source_check=source_pass())
    assert r["stages"]["identity"]["status"]=="UNKNOWN"


def test_declared_mock_cannot_claim_canonical_real_exam():
    q,n=item()
    q.grading_config["provenance"]["source"]["source_type"]="mock"
    r=audit_question(q,n,source_check=source_pass())
    assert r["status"]=="QUARANTINED" and r["stages"]["identity"]["status"]=="FAIL"


def test_missing_figure_and_process_grader_applicability():
    q,n=item("根据下图计算这个测试图形的结果。")
    assert audit_question(q,n,source_check=source_pass())["status"]=="QUARANTINED"
    q.question_type="proof";q.options=None;q.stem="证明这个合成测试命题。";q.correct_answer="TEST_FIXTURE proof"
    r=audit_question(q,n,source_check=source_pass())
    assert r["stages"]["grading"]["status"]=="NOT_APPLICABLE"
    assert r["stages"]["independent_answer"]["status"]=="NOT_APPLICABLE"


def test_duplicate_and_source_subject_mapping_conflict():
    q,n=item(); other,_=item()
    other.kp_id=q.kp_id
    dup=duplicates([q,other])
    assert audit_question(q,n,source_check=source_pass(),duplicate=dup[str(q.id)])["status"]=="QUARANTINED"
    q.grading_config["provenance"]["source"]["subject"]="408"
    assert audit_question(q,n,source_check=source_pass())["stages"]["mapping"]["status"]=="FAIL"


def test_binding_changes_for_options_answer_explanation_mapping_and_cached_runs():
    q,n=item()
    first=audit_question(q,n,source_check=source_pass())
    q.options["C"]="-3"
    second=audit_question(q,n,source_check=source_pass())
    assert first["input_fingerprint"]!=second["input_fingerprint"]
    q.explanation="TEST_FIXTURE different steps"
    assert second["input_fingerprint"]!=audit_question(q,n,source_check=source_pass())["input_fingerprint"]
    before=audit_question(q,n,source_check=source_pass())
    assert before["input_fingerprint"]!=audit_question(q,n,source_check=source_pass(),runs=abc(q))["input_fingerprint"]
    n.name="TEST_FIXTURE changed mapping description"
    assert before["input_fingerprint"]!=audit_question(q,n,source_check=source_pass())["input_fingerprint"]


def test_same_semantic_input_reproducible():
    q,n=item();rows=abc(q)
    a=audit_question(q,n,source_check=source_pass(),runs=rows)
    b=audit_question(q,n,source_check=source_pass(),runs=list(reversed(rows)))
    assert a["decision_sha256"]==b["decision_sha256"]


@pytest.mark.parametrize("answer", ["[-8,7]", "[-512,511]", "[-32768,32767]"])
def test_personal_range_grader_boundary_cases_follow_actual_word_size(answer):
    q=SimpleNamespace(question_type="fill_blank",correct_answer=answer,options=None,
        grading_config={"generated_practice_method":"range_final","generation":{"version":"TEST_FIXTURE"}},
        answer_provenance="ai_generated",answer_reliability="unverified",content_trust="unreviewed")
    result=grader_checks(q)
    assert result["status"]=="PASS",result
    assert {case["case"] for case in result["cases"]} >= {"wrong","equivalent_spacing"}


def test_native_pdf_source_match_is_executed_not_assumed(tmp_path):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
    q,_=item()
    pdf=tmp_path/"TEST_FIXTURE_2020_math2.pdf"
    writer=PdfWriter();page=writer.add_blank_page(width=612,height=792)
    font=DictionaryObject({NameObject("/Type"):NameObject("/Font"),NameObject("/Subtype"):NameObject("/Type1"),NameObject("/BaseFont"):NameObject("/Helvetica")})
    page[NameObject("/Resources")]=DictionaryObject({NameObject("/Font"):DictionaryObject({NameObject("/F1"):writer._add_object(font)})})
    lines=["TEST_FIXTURE source","1. "+q.stem,*[f"{k}. {v}" for k,v in q.options.items()]]
    commands="BT /F1 12 Tf 40 760 Td "+" ".join(("0 -24 Td " if i else "")+"("+line.replace("\\","\\\\").replace("(","\\(").replace(")","\\)")+") Tj" for i,line in enumerate(lines))+" ET"
    stream=DecodedStreamObject();stream.set_data(commands.encode("ascii"))
    page[NameObject("/Contents")]=writer._add_object(stream)
    with pdf.open("wb") as out: writer.write(out)
    sha=hashlib.sha256(pdf.read_bytes()).hexdigest()
    r=inspect_source(q,{"path":str(pdf),"expected_sha256":sha,"page":1,"question_number":1},NativePageReader())
    assert r["status"]=="PASS" and r["full_concordance_verified"]
    assert "stem" in r["coverage"]


def test_q6_style_negative_sign_correction_reference_and_no_whole_source_certificate(tmp_path):
    q,_=item()
    pdf=tmp_path/"TEST_FIXTURE.pdf";pdf.write_bytes(b"TEST_FIXTURE content only")
    q.options["C"]="$-1/ln2$"
    context={"stem":q.stem,"question_type":q.question_type,"kp_id":str(q.kp_id),"options":{k:v for k,v in q.options.items() if k!="C"}}
    descriptor={"path":str(pdf),"expected_sha256":hashlib.sha256(pdf.read_bytes()).hexdigest(),"page":1,"question_number":1,
        "partial_observations":[{"field":"options.C","value":"$-1/ln2$","context_sha256":digest(context)}]}
    reader=lambda *a:{"status":"PASS","text":""}
    current=inspect_source(q,descriptor,reader)
    assert current["status"]=="UNKNOWN" and current["partial_checks"][0]["status"]=="PASS"
    q.options["C"]="$1/ln2$"
    old=inspect_source(q,descriptor,reader)
    assert old["status"]=="FAIL" and old["location"]=="options.C"
    assert old["full_concordance_verified"] is False


def test_source_changed_or_parser_failed_not_question_error(tmp_path):
    q,n=item();p=tmp_path/"TEST_FIXTURE.pdf";p.write_bytes(b"TEST_FIXTURE")
    bad=inspect_source(q,{"path":str(p),"expected_sha256":"0"*64},NativePageReader())
    assert bad["status"]=="UNKNOWN" and bad["reason"]=="source_material_version_changed"
    broken=inspect_source(q,{"path":str(p),"page":1,"question_number":1},lambda *a:{"status":"ERROR","reason":"TEST_TOOL_TIMEOUT"})
    assert audit_question(q,n,source_check=broken)["status"]=="NEEDS_REVIEW"


def test_bounded_math_and_tree_verifiers_do_not_use_identity_as_truth():
    q,_=item()
    q.question_type="fill_blank";q.options=None;q.stem="计算 ∫_0^∞ ln(1+x)/(1+x)² dx。";q.correct_answer="1"
    good=verify_problem(q)
    assert good["status"]=="PASS" and good["proof"]["primitive_derivative_checked"]
    q.stem="计算 ∫_0^∞ ln(1+x)/(1+x)³ dx。"
    assert verify_problem(q)["status"]=="NOT_APPLICABLE"
    q.stem="非空完全二叉树所有叶在同层，且每个非叶结点有2个孩子；若叶数为 k，求总结点数。"
    q.question_type="single_choice";q.options={"A":"2k−1","B":"2k","C":"k²","D":"2^k−1"};q.correct_answer="A"
    assert verify_problem(q)["status"]=="PASS"
    q.stem=q.stem.replace("每个非叶结点有2个孩子","每个非叶结点至多有2个孩子")
    assert verify_problem(q)["status"]=="NOT_APPLICABLE"


def test_candidate_adapter_creates_no_persisted_question_or_human_stamp():
    _,node=item()
    payload={"questions":[{"content":{"source_id":"TEST_FIXTURE","kp_code":node.code,"question_type":"single_choice",
        "stem":"Compute 1/2+1/2.","options":{"A":"1","B":"2"},"correct_answer":"A",
        "explanation":"TEST_FIXTURE explanation only","estimated_minutes":2,"skill_tags":["arithmetic"]},
        "source":{"source_type":"exam","subject":"math2","year":2020,"question_number":1}}]}
    q=candidate_rows(payload,{node.id:node})[0]
    r=audit_question(q,node,source_check=source_pass(),candidate=True)
    assert r["binding"]["question_id"] is None and r["binding"]["is_candidate"]
    assert not r["current_practice_eligible"] and q.content_reviewed_by is None
    assert not r["human_verified_created"]


def test_private_output_does_not_overwrite_history(tmp_path):
    from scripts.audit_question_quality import ROOT
    with pytest.raises(ValueError,match="private"):
        safe_output(ROOT/"docs"/"public-report")


def test_source_year_conflict_is_localised_not_silently_relabelled(tmp_path):
    q,_=item();p=tmp_path/"TEST_FIXTURE_2021_math2.pdf";p.write_bytes(b"TEST_FIXTURE")
    r=inspect_source(q,{"path":str(p),"page":1,"question_number":1},lambda *a:{"status":"PASS","text":""})
    assert r["status"]=="FAIL" and r["reason"]=="source_paper_year_conflict"
    assert q.grading_config["provenance"]["source"]["year"]==2020


def test_multi_year_compilation_not_falsely_called_wrong_year(tmp_path):
    q,_=item();p=tmp_path/"TEST_FIXTURE_2000-2026.pdf";p.write_bytes(b"TEST_FIXTURE")
    r=inspect_source(q,{"path":str(p),"page":1,"question_number":1},lambda *a:{"status":"PASS","text":""})
    assert r["status"]=="UNKNOWN" and r["reason"]=="multi_year_material_needs_page_identity"


def test_rule_version_and_format_suggestions_cannot_change_question():
    q,n=item();q.options["C"]="3\n-"
    before=snapshot(q)
    r=audit_question(q,n,source_check=source_pass())
    assert r["repair_suggestions"][0]["field"]=="options.C"
    assert r["repair_suggestions"][0]["applied"] is False and snapshot(q)==before
    with pytest.raises(ValueError,match="version"):
        audit_question(q,n,source_check=source_pass(),rule_version="unknown-version")


def test_restricted_ai_candidate_cannot_masquerade_as_real_exam():
    _,node=item()
    payload={"questions":[{"input_kind":"ai_variant_candidate","proposed_origin":"real_exam",
        "content":{"source_id":"TEST_GENERATED","kp_code":node.code,"question_type":"fill_blank",
            "stem":"Compute 1+1.","correct_answer":"2","explanation":"TEST_FIXTURE arithmetic",
            "estimated_minutes":1,"skill_tags":["arithmetic"]},"source":{"source_type":"exam"}}]}
    with pytest.raises(ValueError,match="cannot claim"):
        candidate_rows(payload,{node.id:node})


def test_exact_constant_verifier_keeps_typed_euler_constant_not_string_roundtrip():
    q,_=item("Compute e.");q.question_type="fill_blank";q.options=None;q.correct_answer="e"
    assert verify_problem(q)["status"]=="PASS"
