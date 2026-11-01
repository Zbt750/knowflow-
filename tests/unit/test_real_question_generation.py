"""C2 fake transport only: never construct authenticated real network requests."""
from copy import deepcopy
import json
from types import SimpleNamespace
import pytest
from scripts.run_real_question_generation import CapturingProvider,classify,initial_call_category
from backend.services.question_generation import parse_generated_output,verify_explanation_step


def ledger():return {"calls":[],"stopped":False}


def test_real_capture_preserves_usage_cache_and_raw_content_without_headers(tmp_path):
    class Fake:
        model="TEST_FIXTURE transport";max_tokens=3000
        def complete(self,messages,attempt=1):
            import backend.chat.service as service
            payload={"model":"TEST_FIXTURE","usage":{"prompt_tokens":10,"completion_tokens":20,"total_tokens":30,"prompt_cache_hit_tokens":3,"prompt_cache_miss_tokens":7},
                "choices":[{"message":{"content":"bad JSON retained","reasoning_content":"NOT_STORED"},"finish_reason":"stop"}]}
            service.observe_payload(payload);return "bad JSON retained",payload["usage"]
    state=ledger();capture=CapturingProvider(Fake(),state,tmp_path,"TEST_FIXTURE_case")
    capture.complete([{"role":"user","content":"TEST_FIXTURE public input"}])
    saved=json.loads((tmp_path/"call-01.json").read_text(encoding="utf-8"))
    assert saved["usage"]["prompt_cache_hit_tokens"]==3
    assert saved["response"]["content"]=="bad JSON retained"
    assert "reasoning_content" not in saved["response"] and "headers" not in saved


def test_capture_exhausted_authorization_never_calls_provider(tmp_path):
    state=ledger();state["calls"]=[{}]*8
    capture=CapturingProvider(SimpleNamespace(model="TEST_FIXTURE",max_tokens=3000),state,tmp_path,"TEST")
    with pytest.raises(ValueError,match="exhausted"):capture.complete([])


def test_verifier_unknown_not_model_content_error():
    c={"errors":["family_node_mapping_not_supported"],"record":{"independent_verification":{"status":"NOT_APPLICABLE"}},"status":"NEEDS_EVIDENCE","output":{"steps":[]}}
    assert classify(c)=="VERIFIER_UNSUPPORTED"
    c["record"]["independent_verification"]["status"]="FAIL"
    assert classify(c)=="MODEL_CONTENT_ERROR"


def test_output_limit_truncation_is_format_error_not_provider_failure():
    case={"category":"PROVIDER_ERROR"}
    assert initial_call_category(case,{"safe_reason":"output_limit"})=="MODEL_FORMAT_ERROR"
    assert initial_call_category(case,{"error_code":"answer_truncated"})=="MODEL_FORMAT_ERROR"
    assert initial_call_category(case,{"safe_reason":"connection_error"})=="PROVIDER_ERROR"


def test_ignoring_requested_question_type_is_model_content_error():
    c={"errors":["requested_type_not_followed"],"record":{"independent_verification":{"status":"PASS"}},
       "status":"REJECTED","output":{"steps":[]}}
    assert classify(c)=="MODEL_CONTENT_ERROR"


def test_symbolic_step_outside_parser_scope_not_proven_wrong():
    c={"errors":["explanation_step_unverified_or_false"],"record":{"independent_verification":{"status":"PASS"}},"status":"REJECTED",
        "output":{"steps":[{"expression":"diff(f(x))","value":"f'(x)"}]}}
    assert classify(c)=="VERIFIER_UNSUPPORTED"
    c["output"]["steps"]=[{"expression":"1+1","value":"3"}]
    assert classify(c)=="MODEL_CONTENT_ERROR"


def test_lossless_numeric_and_explicit_choice_wire_formats_recorded():
    raw=json.dumps({"stem":"TEST_FIXTURE compute a number", "question_type":"single_choice",
        "options":["A. 50","B. 49","C. 51","D. 100"],"correct_answer":"A",
        "explanation":"TEST_FIXTURE final number is 50", "final_value":50,"steps":[{"expression":"100/2","value":50}]})
    out,changes=parse_generated_output(raw,compatibility=True)
    assert out.options=={"A":"50","B":"49","C":"51","D":"100"} and out.final_value=="50"
    assert len(changes)==3
    duplicate=json.loads(raw);duplicate["options"]=["A. 50","A. 49","C. 51","D. 100"]
    with pytest.raises(ValueError):parse_generated_output(json.dumps(duplicate),compatibility=True)


def test_bounded_binomial_step_and_outside_scope():
    assert verify_explanation_step(r"\binom{5}{0}*1^2+\binom{5}{1}*2+\binom{5}{2}*2","31")=="right"
    assert verify_explanation_step(r"\binom{5}{1}","4")=="wrong"
    assert verify_explanation_step(r"\binom{x}{1}","x")=="unknown"
