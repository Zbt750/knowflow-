"""Explicit simulation fixtures, no paid calls or human verification."""
from copy import deepcopy
from uuid import uuid4
from types import SimpleNamespace
import pytest
from backend.models.learning import Question,KnowledgePoint
from backend.services.question_generation import Budget,Output,generate,assess_output,current_generation_binding,configured_provider
from backend.services.question_generation import PERSONAL_PROMPT_VERSION,GENERATION_OUTPUT_LIMIT
from backend.services.personal_question_families import contract_for,resolve_family
from backend.services.question_eligibility import question_eligibility
from scripts.run_question_generation_pilot import FixtureModel


def node():
    return KnowledgePoint(id=uuid4(),code="TEST_FIXTURE.derivative",name="导数与微分的计算",subject="考研数学",
        is_active=True,is_assessable=True,is_reference_only=True)


def parent(n,answer="31e"):
    return Question(id=uuid4(),kp_id=n.id,stem=r"已知 $f(x)=x^2(e^x-1)$，求 $f^{(5)}(1)$。",question_type="fill_blank",
        correct_answer=answer,explanation="TEST_FIXTURE existing explanation",options=None,question_role="basic",difficulty="basic",skill_tags=[n.name],
        estimated_minutes=5,is_variant=False,is_active=True,grading_mode="self_assessed",grading_config={"verified":False},
        question_provenance="legacy_unknown",content_trust="unreviewed",source_status="unknown",answer_provenance="unknown",answer_reliability="unknown")


def candidate(mode="original",family="power_derivative",p=None,sample=1,qt="fill_blank",fault=None):
    n=node() if p is None else node()
    if p: n.id=p.kp_id
    request={"mode":mode,"family":family,"sample":sample,"question_type":qt,"fault":fault}
    if p: request["parent"]={"stem":p.stem}
    out,trace=generate(FixtureModel(),request,Budget())
    return assess_output(out,n,request_id="TEST_FIXTURE-"+str(uuid4()),mode=mode,family=family,parent=p,trace=trace),n


def test_missing_original_answer_can_be_completed_without_changing_stem():
    n=node(); p=parent(n,""); before=deepcopy(p.stem)
    c,_=candidate("completion","historic_fifth_derivative",p,qt="fill_blank")
    assert c["status"]=="AUTO_PASS" and c["question"].correct_answer=="31e"
    assert p.correct_answer=="" and p.stem==before


def test_unsolvable_completion_never_invents_missing_conditions():
    n=node(); p=parent(n,""); p.stem="求这个未定义函数在一点处的导数。"
    c,_=candidate("completion","historic_fifth_derivative",p)
    assert c["status"]!="AUTO_PASS"


def test_existing_answer_conflict_with_independent_solution_is_quarantined():
    p=parent(node(),"30e")
    c,_=candidate("completion","historic_fifth_derivative",p)
    assert c["status"]=="REJECTED" and "existing_answer_conflict_requires_versioned_review" in c["errors"]
    assert p.correct_answer=="30e"


def test_fill_question_can_be_adapted_to_unique_choice_with_new_id():
    p=parent(node(),""); c,_=candidate("adapted","historic_fifth_derivative",p,qt="single_choice")
    assert c["status"]=="AUTO_PASS" and c["question"].id!=p.id
    assert c["question"].correct_answer=="A" and c["record"]["identity_label"]=="历史题目改编练习"


def test_two_equivalent_correct_options_rejected():
    p=parent(node()); c,n=candidate("adapted","historic_fifth_derivative",p,qt="single_choice")
    out=Output(**c["output"]); out.options["B"]="31*e"
    bad=assess_output(out,n,request_id="TEST_FIXTURE duplicate",mode="adapted",family="historic_fifth_derivative",parent=p)
    assert bad["status"]=="REJECTED" and bad["record"]["independent_verification"]["reason"]=="non_unique_correct_option"


def test_changed_parameters_recompute_answer_not_inherit():
    p=parent(node(),"31e"); c,_=candidate("adapted","power_derivative",p,sample=2)
    assert c["status"]=="AUTO_PASS" and c["question"].correct_answer=="27"
    assert c["question"].answer_verification_event_id is None and c["question"].grading_config["verified"] is False


def test_incomplete_parent_can_only_become_explicit_new_adaptation():
    p=parent(node(),""); p.stem="求这个函数的导数，原函数条件缺失。"
    c,_=candidate("adapted","power_derivative",p)
    assert c["status"]=="AUTO_PASS" and c["question"].stem!=p.stem and c["mode"]=="adapted"


def test_wrong_generated_answer_is_independently_rejected():
    c,_=candidate(sample=4,qt="single_choice",fault="wrong_answer")
    assert c["status"]=="REJECTED" and "independent_answer_conflict" in c["errors"]


@pytest.mark.parametrize("kind",["steps","final","narrative"])
def test_explanation_conflict_does_not_pass(kind):
    c,n=candidate(); out=Output(**c["output"])
    if kind=="steps": out.steps=[{"expression":"2+2","value":"5"}]
    if kind=="final": out.final_value="999"
    if kind=="narrative": out.explanation="通过计算，最终答案为 999。"
    bad=assess_output(out,n,request_id="TEST_FIXTURE bad explanation",mode="original",family="power_derivative")
    assert bad["status"]=="REJECTED"


def test_unknown_proof_withheld_not_fake_objective():
    c,_=candidate(qt="proof",fault="unsupported_proof")
    assert c["status"]=="NEEDS_EVIDENCE" and not c["quality"]["objective_grading_eligible"]


def test_budget_exhaustion_before_next_call():
    b=Budget(max_calls=1); request={"family":"power_derivative","sample":1}
    generate(FixtureModel(),request,b)
    with pytest.raises(ValueError,match="budget_exhausted"): generate(FixtureModel(),request,b)
    assert b.calls==1


def test_timeout_stops_and_explicit_retry_is_bounded():
    class TimeoutModel:
        model="TEST_FIXTURE timeout"; simulation=True
        def complete(self,*a,**k): raise TimeoutError("TEST_FIXTURE timeout")
    b=Budget(max_calls=5)
    with pytest.raises(TimeoutError): generate(TimeoutModel(),{},b,max_retries=1)
    assert b.calls==2 and b.stopped and len(b.records)==2
    with pytest.raises(ValueError):generate(TimeoutModel(),{},b)


def test_unpaid_provider_construction_refused():
    with pytest.raises(ValueError,match="authorization"):configured_provider(SimpleNamespace(),Budget())


def test_real_provider_cannot_bypass_output_budget_before_call():
    p=SimpleNamespace(simulation=False,max_tokens=9000)
    b=Budget(max_output_tokens=3000)
    with pytest.raises(ValueError,match="output limit"):generate(p,{},b)
    assert b.calls==0 and b.records==[]


def test_c4_requires_registry_contract_before_budget_or_provider_call():
    class Counting:
        model="TEST_FIXTURE counted"; simulation=True
        def __init__(self): self.calls=0
        def complete(self,*a,**k):
            self.calls+=1
            return '{"stem":"设函数f(x)=x^3+2x^2+2x，求f\'(x)。","question_type":"single_choice",' \
                '"options":{"A":"3x^2+4x+2","B":"3x^2+4x+3","C":"3x^2+4x+1","D":"3x^2+2x+2"},' \
                '"correct_answer":"A","explanation":"逐项求导得到对应导数。","final_value":"3x^2+4x+2","steps":[]}', None
    spec=resolve_family("math.exam.de439863790e","single_choice")
    request={"family":spec.family_id,"question_type":"single_choice","difficulty":"basic",
        "node":{"code":spec.node_codes[0]},
        "family_contract":contract_for(spec,node_code=spec.node_codes[0],question_type="single_choice",difficulty="basic")}
    provider=Counting();budget=Budget(max_calls=1,max_reserved_tokens=10000,max_output_tokens=GENERATION_OUTPUT_LIMIT)
    output,trace=generate(provider,request,budget,prompt_version="question-generation-c4-v1")
    assert output.correct_answer=="A" and provider.calls==1
    assert trace["prompt_version"]=="question-generation-c4-v1"
    assert trace["max_output_tokens"]==1800

    invalid={**request,"family_contract":{**request["family_contract"],"node_code":"TEST_FIXTURE.derivative"}}
    before_calls=provider.calls;before_budget=budget.calls
    invalid_budget=Budget(max_calls=1,max_reserved_tokens=10000,max_output_tokens=GENERATION_OUTPUT_LIMIT)
    with pytest.raises(ValueError,match="family_contract"):
        generate(provider,invalid,invalid_budget,prompt_version="question-generation-c4-v1")
    assert provider.calls==before_calls and invalid_budget.calls==0 and budget.calls==before_budget


def test_c5_requires_server_problem_spec_before_call_and_rejects_answer_fields():
    from backend.services.personal_question_families import build_problem_spec
    from backend.services.question_generation import C5Output

    class Counting:
        model="TEST_FIXTURE C5 counted"; simulation=True
        def __init__(self): self.calls=0; self.messages=[]
        def complete(self,messages,*,attempt=1):
            self.calls+=1; self.messages=messages
            request=__import__("json").loads(messages[-1]["content"])
            spec=request["problem_spec"]
            return __import__("json").dumps({"stem":spec["canonical_problem"],
                "question_type":spec["question_type"],
                "teaching_note":"先整理题目条件，再按规则检查。"},ensure_ascii=False),None

    family=resolve_family("math.exam.c431f98f817c","single_choice")
    ps=build_problem_spec(node_code=family.node_codes[0],question_type="single_choice",difficulty="basic",seed="TEST_FIXTURE c5")
    request={"family":family.family_id,"question_type":"single_choice","difficulty":"basic",
        "node":{"code":family.node_codes[0]},
        "family_contract":contract_for(family,node_code=family.node_codes[0],question_type="single_choice",difficulty="basic"),
        "problem_spec":ps.as_dict()}
    provider=Counting(); budget=Budget(max_calls=1,max_output_tokens=1200)
    output,trace=generate(provider,request,budget,prompt_version=PERSONAL_PROMPT_VERSION)
    assert output.stem==ps.canonical_problem and provider.calls==1
    assert trace["prompt_version"]=="question-generation-c5-v1" and trace["max_output_tokens"]==1200
    assert "canonical_answer" in provider.messages[1]["content"]
    with pytest.raises(Exception):
        C5Output.model_validate({"stem":ps.canonical_problem,"question_type":"single_choice",
            "teaching_note":"先理解问题。","correct_answer":"A"})

    invalid={**request}; invalid.pop("problem_spec")
    before=provider.calls
    with pytest.raises(ValueError,match="problem_spec"):
        generate(provider,invalid,budget,prompt_version=PERSONAL_PROMPT_VERSION)
    assert provider.calls==before


def test_c6_model_can_only_choose_server_solved_variant_and_registered_teaching():
    from backend.services.personal_question_families import build_problem_spec
    from backend.services.question_generation import C6Output, PERSONAL_C6_PROMPT_VERSION
    family=resolve_family("math.exam.c431f98f817c","single_choice")
    candidates=[]
    for index in range(1,4):
        spec=build_problem_spec(node_code=family.node_codes[0],question_type="single_choice",
            difficulty="basic",seed=f"TEST_FIXTURE C6 {index}")
        candidates.append({"candidate_id":f"candidate_{index}","profile":"bounded spec",
            "statement":spec.canonical_problem})
    request={"family":family.family_id,"question_type":"single_choice","difficulty":"basic",
        "node":{"code":family.node_codes[0]},
        "family_contract":contract_for(family,node_code=family.node_codes[0],question_type="single_choice",difficulty="basic"),
        "learning_focus":{"status":"NEEDS_CONSOLIDATION","focus":"consolidate","reliable_wrong_count":1},
        "candidates":candidates}
    class Provider:
        model="TEST_FIXTURE c6";simulation=True
        def __init__(self,payload):self.payload=payload;self.calls=0;self.messages=None
        def complete(self,messages,*,attempt=1):
            self.calls+=1;self.messages=messages
            return __import__("json").dumps(self.payload),None
    valid=Provider({"candidate_id":"candidate_2","wording_id":"condition_first","teaching_focus_id":"self_check"})
    output,trace=generate(valid,request,Budget(max_calls=1,max_output_tokens=1200),prompt_version=PERSONAL_C6_PROMPT_VERSION)
    assert isinstance(output,C6Output) and output.candidate_id=="candidate_2" and valid.calls==1
    sent=__import__("json").loads(valid.messages[-1]["content"])
    assert "canonical_answer" not in str(sent) and "correct_answer" not in str(sent)
    assert "已由服务器独立求解" in valid.messages[0]["content"]
    bad=Provider({"candidate_id":"candidate_2","wording_id":"condition_first",
        "teaching_focus_id":"self_check","stem":"model authored problem"})
    with pytest.raises(Exception):
        generate(bad,request,Budget(max_calls=1,max_output_tokens=1200),prompt_version=PERSONAL_C6_PROMPT_VERSION)


def test_c6_candidate_menu_must_be_complete_and_server_contract_bound():
    from backend.services.personal_question_families import build_problem_spec
    from backend.services.question_generation import PERSONAL_C6_PROMPT_VERSION
    family=resolve_family("math.exam.c431f98f817c","single_choice")
    spec=build_problem_spec(node_code=family.node_codes[0],question_type="single_choice",difficulty="basic",seed="TEST_FIXTURE c6 invalid")
    request={"family":family.family_id,"question_type":"single_choice","difficulty":"basic",
        "node":{"code":family.node_codes[0]},
        "family_contract":contract_for(family,node_code=family.node_codes[0],question_type="single_choice",difficulty="basic"),
        "candidates":[{"candidate_id":"candidate_1","profile":"x","statement":spec.canonical_problem}]}
    class NeverCall:
        model="TEST_FIXTURE";simulation=True
        def complete(self,*_args,**_kwargs):raise AssertionError("invalid menu must fail before provider")
    with pytest.raises(ValueError,match="candidate_menu_invalid"):
        generate(NeverCall(),request,Budget(max_calls=1,max_output_tokens=1200),prompt_version=PERSONAL_C6_PROMPT_VERSION)


def test_stale_content_or_metadata_revokes_generated_binding():
    c,n=candidate(); q=c["question"]
    assert current_generation_binding(q,n)
    q.correct_answer="999"
    assert not current_generation_binding(q,n)
    q.correct_answer=c["output"]["correct_answer"]
    q.grading_config["generation"]["identity_label"]="历年真题整理版"
    assert not current_generation_binding(q,n)


def test_public_generated_candidate_requires_formal_review_regardless_of_legacy_feature_flag():
    c,n=candidate(); q=c["question"]
    off=question_eligibility(q,n,teaching_enabled=False); on=question_eligibility(q,n,teaching_enabled=True)
    # H-era public-bank policy has no ordinary public generated pool. A runtime
    # personal binding is the only route for AI practice, and the legacy flag
    # must not bypass public formal review.
    assert not off.practice_eligible and not on.practice_eligible
    assert on.evidence_capability != "verified_objective" and on.verified_grading_method is None
    assert "public_formal_review_required" in on.blocking_reasons


def test_arithmetic_cannot_be_mapped_to_derivative_by_model_claim():
    c,n=candidate(); out=Output(**c["output"]); out.stem="Compute 2+2.";out.correct_answer="4";out.final_value="4"
    bad=assess_output(out,n,request_id="TEST_FIXTURE mapping",mode="original",family="power_derivative")
    assert bad["status"]=="REJECTED"
