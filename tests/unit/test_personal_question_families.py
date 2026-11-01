from types import SimpleNamespace

import pytest

from backend.services.personal_question_families import (
    BY_NODE_CODE, FAMILIES, VERSION, contract_for, resolve_family, validate_contract,
    build_problem_spec, verify_problem_spec_candidate, supports_difficulty,
    learning_focus_from_progress, render_problem_spec,
)


def test_registry_has_ten_exact_canonical_targets_and_rejects_name_similarity():
    assert len(FAMILIES) == 10
    assert len(BY_NODE_CODE) == 10
    assert resolve_family("math.exam.c431f98f817c").family_id == "power_integral"
    assert resolve_family("TEST_FIXTURE.math.exam.c431f98f817c") is None
    assert resolve_family("unknown", "single_choice") is None
    assert resolve_family("math.exam.fd2f9e3739d9", "fill_blank") is None


@pytest.mark.parametrize("spec", FAMILIES.values(), ids=lambda item: item.family_id)
def test_every_registered_family_declares_solver_and_explicit_boundaries(spec):
    assert spec.subject in {"数学二", "408"}
    assert spec.node_codes and all(code.strip() for code in spec.node_codes)
    assert spec.question_types and set(spec.question_types) <= {"single_choice", "fill_blank"}
    assert all((spec.stem_template, spec.parameter_bounds, spec.solver, spec.choice_check,
        spec.answer_comparer, spec.explanation_checks, spec.unsupported, spec.adapters))


def test_contract_is_node_type_difficulty_bound_and_not_client_editable():
    spec = resolve_family("math.exam.de439863790e", "single_choice")
    contract = contract_for(spec, node_code=spec.node_codes[0], question_type="single_choice", difficulty="improved")
    request = {"family": spec.family_id, "question_type": "single_choice", "difficulty": "improved",
        "node": {"code": spec.node_codes[0], "name": "arbitrary display name"}, "family_contract": contract}
    assert contract["registry_version"] == VERSION
    assert validate_contract(request) is spec
    request["family_contract"] = {**contract, "independent_solver": "trust the model"}
    assert validate_contract(request) is None
    request["family_contract"] = contract
    request["node"] = {"code": "TEST_FIXTURE.derivative", "name": "导数与微分的计算"}
    assert validate_contract(request) is None


@pytest.mark.parametrize("family_id",list(FAMILIES))
def test_problem_spec_is_server_solved_and_independently_verifiable_for_every_family(family_id):
    spec=FAMILIES[family_id]
    for question_type in spec.question_types:
        outputs=[]
        for seed in ("TEST_FIXTURE:A", "TEST_FIXTURE:B", "TEST_FIXTURE:C"):
            item=build_problem_spec(node_code=spec.node_codes[0],question_type=question_type,
                difficulty="basic",seed=seed)
            assert item.family_id==family_id
            assert item.knowledge_node_code==spec.node_codes[0]
            assert item.canonical_answer and item.verification_metadata["adapter"] in spec.adapters
            assert verify_problem_spec_candidate(stem=item.canonical_problem,spec=item)["status"]=="PASS"
            outputs.append((item.canonical_problem,item.canonical_answer,
                __import__("json").dumps(item.options,sort_keys=True,ensure_ascii=False)))
        # Some families intentionally have a fixed stem (e.g. p-integral),
        # but choices or parameterized families must vary deterministically.
        assert len(set(outputs)) >= (1 if family_id=="improper_integral_parameter" else 2)


@pytest.mark.parametrize("family_id",list(FAMILIES))
def test_problem_spec_condition_drift_is_fail_closed(family_id):
    family=FAMILIES[family_id]
    item=build_problem_spec(node_code=family.node_codes[0],question_type=family.question_types[0],
        difficulty="improved" if supports_difficulty(family,"improved") else "basic",
        seed="TEST_FIXTURE drift:"+family_id)
    assert verify_problem_spec_candidate(stem=item.canonical_problem+" 条件已被改写",spec=item)["status"]=="FAIL"


def test_problem_spec_seed_reproducibility_and_unknown_node_rejection():
    family=FAMILIES["page_replacement_faults"]
    kwargs={"node_code":family.node_codes[0],"question_type":"single_choice","difficulty":"comprehensive","seed":"TEST_FIXTURE fixed seed"}
    first=build_problem_spec(**kwargs); second=build_problem_spec(**kwargs)
    assert first.as_dict()==second.as_dict()
    with pytest.raises(ValueError,match="unsupported"):
        build_problem_spec(node_code="TEST_FIXTURE.unknown",question_type="single_choice",difficulty="basic",seed="TEST_FIXTURE")


def test_higher_difficulty_only_claimed_for_families_with_real_structure_change():
    assert {key for key in FAMILIES if supports_difficulty(FAMILIES[key],"improved")} == {
        "power_derivative", "power_integral", "page_replacement_faults", "binary_float"}
    determinant=FAMILIES["determinant_2x2"]
    with pytest.raises(ValueError,match="difficulty_unsupported"):
        build_problem_spec(node_code=determinant.node_codes[0],question_type="single_choice",
            difficulty="improved",seed="TEST_FIXTURE unsupported difficulty")


@pytest.mark.parametrize(("status","expected_focus"),[
    ("NOT_STARTED","foundation"),("NEEDS_CONSOLIDATION","consolidate"),
    ("RETEST_RECOMMENDED","delayed_retest"),("IMPROVING","transfer"),
    ("STABLE_PRACTICE","spaced_review"),("PRACTICING","practice"),
])
def test_learning_focus_is_a_bounded_status_and_count_summary(status,expected_focus):
    progress=SimpleNamespace(status=status,observed_attempt_count=4,distinct_question_count=3,
        reliable_wrong_count=1,assisted_correct_question_count=1)
    focus=learning_focus_from_progress(progress)
    assert focus["focus"]==expected_focus and focus["reliable_wrong_count"]==1
    assert set(focus)=={"status","focus","selection_instruction","observed_attempt_count",
        "distinct_question_count","reliable_wrong_count","assisted_correct_count"}
    assert "answer" not in str(focus).lower()


def test_registered_wording_changes_presentation_only_and_cannot_change_problem_conditions():
    family=FAMILIES["power_integral"]
    spec=build_problem_spec(node_code=family.node_codes[0],question_type="single_choice",
        difficulty="basic",seed="TEST_FIXTURE wording boundary")
    guided=render_problem_spec(spec,"guided")
    assert guided.endswith(spec.canonical_problem)
    assert verify_problem_spec_candidate(stem=guided,spec=spec,wording_id="guided")["status"]=="PASS"
    assert verify_problem_spec_candidate(stem=guided+" 条件被改变",spec=spec,wording_id="guided")["status"]=="FAIL"


@pytest.mark.parametrize(("family_id","question_type"),
    [(family_id,question_type) for family_id,family in FAMILIES.items() for question_type in family.question_types])
def test_c5_candidate_uses_server_answer_and_rejects_condition_or_explanation_drift(family_id,question_type):
    from backend.models.learning import KnowledgePoint
    from backend.services.question_generation import C5Output, assess_problem_spec_output

    family=FAMILIES[family_id]
    node=KnowledgePoint(id=__import__("uuid").uuid4(),code=family.node_codes[0],
        name=family.family_id,subject=family.subject,is_active=True,is_assessable=True,is_reference_only=False)
    problem=build_problem_spec(node_code=node.code,question_type=question_type,
        difficulty="basic",seed="TEST_FIXTURE C5 assessment:"+family_id)
    base={"stem":problem.canonical_problem,"question_type":problem.question_type,
          "teaching_note":"先整理题目条件，再按规则检查。"}
    valid=assess_problem_spec_output(C5Output.model_validate(base),node,request_id="TEST_FIXTURE:c5:"+family_id,
        trace={"mode":"simulation","prompt_version":"question-generation-c5-v1","model":"TEST_FIXTURE"},
        problem_spec=problem,family_spec=family)
    assert valid["status"]=="AUTO_PASS",valid["errors"]
    assert valid["question"].correct_answer==problem.canonical_answer
    assert valid["question"].options==problem.options
    assert valid["question"].question_provenance=="ai_generated_practice"
    assert valid["question"].answer_reliability=="unverified"
    assert "server-owned derivation" in valid["record"]["explanation_scope"]

    changed=assess_problem_spec_output(C5Output.model_validate({**base,"stem":base["stem"]+" 条件更改"}),
        node,request_id="TEST_FIXTURE:drift:"+family_id,trace={"mode":"simulation"},problem_spec=problem,family_spec=family)
    assert changed["status"]=="REJECTED" and "problem_spec_condition_drift" in changed["errors"]
    unsafe=assess_problem_spec_output(C5Output.model_validate({**base,"teaching_note":"答案为999，因此选择该结果。"}),
        node,request_id="TEST_FIXTURE:note:"+family_id,trace={"mode":"simulation"},problem_spec=problem,family_spec=family)
    assert unsafe["status"]=="REJECTED" and "teaching_note_contains_unverified_claim" in unsafe["errors"]


def test_next_pilot_batches_cover_each_registered_node_twice_without_unsupported_types():
    from scripts.run_phase45i_real_batch import load_targets, make_next_batch_targets

    fixture, _, _, _ = load_targets()
    batches = [make_next_batch_targets(fixture, index) for index in range(4)]
    assert [len(batch) for batch in batches] == [5, 5, 5, 5]
    assert [batch[0]["subject"] for batch in batches] == ["数学二", "408", "数学二", "408"]
    all_targets = [target for batch in batches for target in batch]
    assert len({target["target_id"] for target in all_targets}) == 20
    by_node = {}
    for target in all_targets:
        node = target["node"]
        profile = target["profile"]
        spec = resolve_family(node["code"], profile["question_type"])
        assert spec is not None and spec.family_id == target["family_id"] == node["expected_family"]
        by_node.setdefault(node["code"], []).append(profile["question_type"])
    assert len(by_node) == 10
    assert all(len(types) == 2 for types in by_node.values())
    assert by_node["math.exam.fd2f9e3739d9"] == ["single_choice", "single_choice"]


def test_c4_capture_guard_uses_1800_output_cap_without_issuing_http_request(tmp_path):
    from scripts.run_phase45i_real_batch import CapturingProvider, NEXT_MAX_OUTPUT_TOKENS

    class NoNetworkProvider:
        model = "deepseek-flash"
        base_url = "https://api.deepseek.com"
        max_tokens = NEXT_MAX_OUTPUT_TOKENS
        simulation = False

        def complete(self, *_args, **_kwargs):
            raise RuntimeError("TEST_FIXTURE no network request")

    provider = CapturingProvider(NoNetworkProvider(), tmp_path / "calls.jsonl", {},
        max_authorized_calls=20, total_output_tokens=20 * NEXT_MAX_OUTPUT_TOKENS,
        conservative_tokens=20 * (8000 + 512 + NEXT_MAX_OUTPUT_TOKENS),
        cost_budget_cny=2.0, prompt_version="question-generation-c4-v1")
    assert provider.output_ceiling == NEXT_MAX_OUTPUT_TOKENS == 1800
    with pytest.raises(RuntimeError, match="TEST_FIXTURE no network"):
        provider.complete([{"role":"system","content":"TEST_FIXTURE"},
                           {"role":"user","content":"TEST_FIXTURE"}], attempt=1)
    assert provider.actual_calls == 0
