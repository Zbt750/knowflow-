from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from backend.mastery.enums import EvidenceLevel
from backend.mastery.policy import MasteryPolicy, LEGACY_POLICY_FIELDS
from backend.mastery.rules import graduation_check, analyze_gaps
from backend.mastery.storage import evidence_from_storage, evidence_to_storage
from backend.mastery.types import Evidence
from backend.services.graduation_policy_migration import (
    convert_policy, policy_hash, review_policy_guard, remove_exam_source_quotas,
)

NOW = datetime(2026, 10, 8, tzinfo=timezone.utc)


def legacy_row():
    return {"kp_id":str(uuid4()),"min_confirmations":3,"min_real_questions":3,
        "required_question_types":{"external_exam":3},"excluded_question_types":[],
        "required_skill_tags":["Synthetic topic"],"required_variant_count":0,"min_day_span":2,
        "manual_mastered_credit":2,"review_intervals_days":[7,15,30],"max_evidence_window":20,
        "note":"历年真题索引策略：synthetic test only", "updated_at":NOW-timedelta(days=2)}


def audited(row):
    return {"node_id":row["kp_id"],"node_code":"synthetic.policy","node_name":"Synthetic topic",
        "subject":"math2","node_active":True,"reference_only":True,"reference_count":6,
        "matches_reference_seed_formula":True,"before_policy":{k:deepcopy(row[k]) for k in LEGACY_POLICY_FIELDS}}


def node(row):
    return {"id":row["kp_id"],"code":"synthetic.policy","name":"Synthetic topic","subject":"math2",
        "is_active":True,"is_reference_only":True,"is_assessable":True}


def test_policy_versions_parse_with_separate_namespaces():
    assert MasteryPolicy(required_question_types={"external_exam":3}).policy_version==1
    p=MasteryPolicy(policy_version=2,required_question_types={"single_choice":1},required_question_origins={"real_exam":3})
    assert p.total_required_question_count==1
    assert "external_exam" not in p.available_question_types
    process_policy=MasteryPolicy(policy_version=2,required_question_types={"discussion":1,"program":1})
    assert {"discussion","program"}.issubset(process_policy.available_question_types)
    for values in ({"policy_version":1,"required_question_origins":{"real_exam":1}},
                   {"policy_version":2,"required_question_types":{"external_exam":1}},
                   {"policy_version":2,"required_question_origins":{"external_exam":1}},
                   {"policy_version":2,"required_question_origins":{"legacy_unknown":1}},
                   {"policy_version":2,"required_question_origins":{"real_exam":True}},
                   {"policy_version":2,"required_question_origins":{"real_exam":0}}):
        with pytest.raises(ValueError): MasteryPolicy(**values)
    # v3 may exist before its set is frozen; an empty set never graduates.
    empty=MasteryPolicy(policy_version=3)
    assert graduation_check((),manual_credit_count=0,manual_confirmed_at=None,policy=empty)[0] is False


def test_conversion_preserves_every_other_field_and_other_type_quotas():
    original=legacy_row(); original["required_question_types"]["single_choice"]=1
    saved=deepcopy(original); new=convert_policy(original)
    assert original==saved
    assert new["policy_version"]==2 and new["required_question_origins"]=={"real_exam":3}
    assert new["required_question_types"]=={"single_choice":1}
    assert all(new[k]==original[k] for k in LEGACY_POLICY_FIELDS if k!="required_question_types")


def test_remove_exam_source_quotas_preserves_other_thresholds_and_version():
    v2={**legacy_row(),"policy_version":2,"required_question_origins":{"real_exam":3},
        "required_question_types":{"single_choice":1},"min_day_span":4}
    v2_saved=deepcopy(v2); result=remove_exam_source_quotas(v2)
    assert v2==v2_saved
    assert result["policy_version"]==2 and result["required_question_origins"]=={}
    assert result["required_question_types"]=={"single_choice":1}
    assert result["min_day_span"]==4 and result["min_real_questions"]==3
    v1={**legacy_row(),"required_question_types":{"external_exam":4,"single_choice":1},
        "min_real_questions":2}
    result=remove_exam_source_quotas(v1)
    assert result["policy_version"]==1 and result["required_question_origins"]=={}
    assert result["required_question_types"]=={"single_choice":1}
    assert result["min_real_questions"]==4
    assert result["min_confirmations"]==v1["min_confirmations"]
    assert result["min_day_span"]==v1["min_day_span"]
    assert remove_exam_source_quotas(result)==result


def test_guard_exact_audit_and_idempotency():
    row=legacy_row(); audit=audited(row); mapping=node(row)
    result=review_policy_guard(row,mapping,6,audit,NOW)
    assert result["status"]=="ELIGIBLE"
    assert result["old_hash"]==policy_hash(row)
    converted=convert_policy(row); converted["updated_at"]=NOW+timedelta(days=1)
    assert review_policy_guard(converted,mapping,6,audit,NOW)["status"]=="NOOP_ALREADY_MIGRATED"
    converted["min_day_span"]=0
    assert review_policy_guard(converted,mapping,6,audit,NOW)["status"]=="POLICY_CHANGED_SINCE_AUDIT"


@pytest.mark.parametrize("field,value", [("min_confirmations",2),("min_real_questions",2),
    ("min_day_span",0),("required_skill_tags",[]),("required_variant_count",1),
    ("review_intervals_days",[1]),("required_question_types",{"external_exam":2})])
def test_guard_stops_changed_fields(field,value):
    row=legacy_row(); audit=audited(row); row[field]=value
    assert review_policy_guard(row,node(row),6,audit,NOW)["status"]=="POLICY_CHANGED_SINCE_AUDIT"


def test_guard_stops_timestamp_node_reference_and_custom_changes():
    row=legacy_row(); audit=audited(row); mapping=node(row)
    row["updated_at"]=NOW+timedelta(seconds=1)
    assert review_policy_guard(row,mapping,6,audit,NOW)["reason"]=="modified_after_audit"
    row["updated_at"]=NOW-timedelta(days=2)
    assert review_policy_guard(row,{**mapping,"code":"other"},6,audit,NOW)["status"]=="POLICY_CHANGED_SINCE_AUDIT"
    assert review_policy_guard(row,mapping,5,audit,NOW)["status"]=="POLICY_CHANGED_SINCE_AUDIT"
    assert review_policy_guard({},mapping,6,audit,NOW)["status"]=="POLICY_CHANGED_SINCE_AUDIT"
    assert review_policy_guard(row,mapping,6,{**audit,"matches_reference_seed_formula":False},NOW)["status"]=="CUSTOM_OR_NONMATCHING_POLICY"


def confirmation(index, *, origin="real_exam", facts_change=None, level=EvidenceLevel.CONFIRMED,
                 reliability="verified_objective", question_id=None):
    facts={"attempt_id":str(uuid4()),"policy_version":2,"question_provenance":origin,
        "question_content_sha256":"a"*64,"answer_version_sha256":"b"*64,
        "answer_verification_event_id":str(uuid4()),"question_content_trust":"verified",
        "source_status":"verified","answer_provenance":"human_verified","answer_reliability":"verified",
        "grading_capability":"deterministic","method":"single_choice_v1","result":"right",
        "evidence_reliability":"verified_objective","assisted":False,"assistance_level":"none",
        "sequence_version":"attempt-sequence-v1","sequence_category":"first_independent_correct"}
    facts.update(facts_change or {})
    return Evidence(question_id or str(uuid4()),level,False,NOW+timedelta(days=index),
        "objective_final","single_choice",("topic",),reliability,facts)


def origin_policy():
    return MasteryPolicy(policy_version=2,min_confirmations=3,min_real_questions=3,
        required_question_origins={"real_exam":3},required_variant_count=0,
        required_skill_tags=frozenset({"topic"}),min_day_span=2)


def check(window, policy=None):
    return graduation_check(tuple(window),manual_credit_count=2,manual_confirmed_at=NOW-timedelta(days=10),
        policy=policy or origin_policy())


def test_trusted_independent_real_exam_confirmations_satisfy_origin_without_changing_type():
    window=tuple(confirmation(i) for i in range(3))
    assert check(window)==(True,"graduated")
    assert all(e.question_type=="single_choice" for e in window)
    report=analyze_gaps(window,manual_credit_count=2,manual_confirmed_at=NOW,policy=origin_policy())
    assert report.can_graduate
    assert report.missing_origins==()
    assert not any(g.key.startswith("origin:") for g in report.items)


def test_source_origin_is_not_a_graduation_blocker_and_other_strict_gates_remain():
    window=[confirmation(0,origin="trusted_practice"),confirmation(1,origin="trusted_practice"),
        confirmation(2,origin="trusted_practice")]
    assert check(window)==(True,"graduated")
    # Removing origin does not waive distinct-question or cross-day rules.
    assert check([*window[:2],window[1]])==(False,"insufficient_confirmed_evidence")
    assert check([confirmation(0,origin="trusted_practice") for _ in range(3)])==(False,"insufficient_day_span")
    type_policy=replace(origin_policy(),required_question_types={"fill_blank":1})
    assert graduation_check(tuple(window),manual_credit_count=0,manual_confirmed_at=None,
        policy=type_policy)==(False,"missing_question_type:fill_blank")


@pytest.mark.parametrize("changes", [
    {"question_provenance":"ai_generated_practice"},
    {"answer_provenance":"ai_generated","answer_reliability":"ai_generated_consistent"},
    {"answer_reliability":"unverified"}, {"answer_verification_event_id":None},
    {"question_content_trust":"source_attested"}, {"source_status":"traceable"},
    {"assisted":True,"assistance_level":"hint_1","sequence_category":"hint_assisted_correct"},
    {"assisted":True,"assistance_level":"solution","sequence_category":"solution_assisted_correct"},
    {"sequence_category":"self_corrected"}, {"sequence_category":"independent_correct_history_unknown"},
    {"result":"wrong"}, {"result":"unknown"},
    {"method":"ai_process_review_v1","grading_capability":"process_review_only"},
    {"method":"program_review","grading_capability":"process_review_only"},
    {"policy_version":1}, {"answer_version_sha256":None}, {"attempt_id":None},
    {"confidence":"guess"}, {"confidence":"no_idea"},
])
def test_ineligible_signals_cannot_supply_a_versioned_origin_confirmation(changes):
    window=[confirmation(0),confirmation(1),confirmation(2,facts_change=changes)]
    assert check(window)==(False,"insufficient_confirmed_evidence")


def test_same_question_dedup_cross_day_and_legacy_no_backfill():
    qid=str(uuid4())
    assert check([confirmation(i,question_id=qid) for i in range(3)])==(False,"insufficient_confirmed_evidence")
    assert check([confirmation(0) for i in range(3)])==(False,"insufficient_day_span")
    old=Evidence(str(uuid4()),EvidenceLevel.CONFIRMED,False,NOW,"objective_final","single_choice",("topic",),"verified_objective")
    saved=evidence_to_storage(old)
    assert check([old,confirmation(1),confirmation(2)])==(False,"insufficient_confirmed_evidence")
    assert evidence_to_storage(evidence_from_storage(saved))==saved
    assert "confirmation_facts" not in saved
    current=confirmation(0)
    assert evidence_to_storage(evidence_from_storage(evidence_to_storage(current)))==evidence_to_storage(current)


def test_new_ungraded_receipts_cannot_inherit_the_nodes_legacy_objective_basis():
    from backend.services.grading_basis import submission_grading_basis

    saved={"version":4,"assessment_basis":"objective_v1","grading_config":{"verified":True},
        "method":"single_choice_v1","evidence_reliability":"ungradable"}
    assert submission_grading_basis(saved)=="ungraded"
    assert submission_grading_basis({**saved,"evidence_reliability":"process_review"})=="ungraded"
    assert submission_grading_basis({**saved,"evidence_reliability":"verified_objective"})=="objective_v1"
    assert submission_grading_basis({**saved,"version":3})=="objective_v1"


@pytest.mark.parametrize("qtype", ["external_exam","proof","discussion","program"])
def test_supported_method_name_cannot_disguise_an_unsupported_question_type(qtype):
    window=[confirmation(0),confirmation(1),replace(confirmation(2),question_type=qtype)]
    assert check(window)==(False,"insufficient_confirmed_evidence")


def test_selection_does_not_prefer_real_exam_origin_and_projection_is_not_graduation_evidence():
    from backend.mastery.selection import QuestionCandidate,select_questions,_with_evidence

    candidates=[QuestionCandidate(str(uuid4()),"single_choice",("topic",),False,3,
        question_provenance="trusted_practice") for _ in range(5)]
    result=select_questions(origin_policy(),(),candidates,budget="standard",reference_time=NOW)
    assert len(result.items)==3
    assert "来源" not in " ".join(item.reason for item in result.items)
    projected=()
    for q in candidates[:3]: projected=_with_evidence(projected,q,NOW)
    assert check(projected)==(False,"insufficient_confirmed_evidence")


def test_traceable_public_variant_needs_captured_auto_class_without_legacy_backfill():
    from backend.mastery.origin_evidence import compatible_confirmation
    changes={'question_provenance':'ai_generated_practice','source_status':'traceable',
        'answer_provenance':'auto_verified','question_content_trust':'auto_verified',
        'answer_reliability':'verified','auto_review_event_id':str(uuid4()),
        'auto_review_version':'public-question-auto-review-v7','auto_review_snapshot_sha256':'c'*64,
        'auto_review_qualification_class':'exam_variant','bank_scope':'public','generation_batch_id':None}
    e=confirmation(0,facts_change=changes)
    assert compatible_confirmation(e,origin_policy())
    for wrong in [None,'development_original','exam_curated']:
        invalid=replace(e,confirmation_facts={**e.confirmation_facts,'auto_review_qualification_class':wrong})
        assert not compatible_confirmation(invalid,origin_policy())
    personal=replace(e,confirmation_facts={**e.confirmation_facts,'bank_scope':'personal'})
    assert not compatible_confirmation(personal,origin_policy())
    historical=confirmation(0,facts_change={k:v for k,v in changes.items() if k!='auto_review_qualification_class'})
    saved=evidence_to_storage(historical)
    assert not compatible_confirmation(historical,origin_policy())
    assert evidence_to_storage(evidence_from_storage(saved))==saved
