from copy import deepcopy
import json
from types import SimpleNamespace

import pytest
from backend.errors import AppError
from backend.services.learning_task_context import compact_tool_result, compact_model_messages
from backend.services.learning_task_service import _model_turn


def test_large_question_result_factoring_preserves_every_qualification_and_version():
    trust={"bank_scope":"public","evidence_capability":"verified_objective","answer_provenance":"auto_verified",
        "practice_eligible":True,"source_status":"traceable","blocking_reasons":[],"answer_verification_event_id":None}
    questions=[{"question_id":str(i),"question_version":f"version-{i}","minutes":5,
        "source_category":"exam_curated" if i%2 else "development_original",
        "question_source":{"year":2025,"question_number":i},
        "question_trust":{**trust,"auto_review_event_id":f"event-{i}","auto_review_snapshot_sha256":str(i)*64},
        "in_today_plan":False} for i in range(16)]
    for q in questions: q["eligibility_snapshot"]=deepcopy(q["question_trust"])
    original={"valid":True,"draft":{"questions":questions,"total_minutes":80,"budget_minutes":90}}
    compact=compact_tool_result(original)
    for before,after in zip(questions,compact["draft"]["questions"]):
        assert {**compact["draft"]["question_trust_defaults"],**after["question_trust"]}==before["question_trust"]
        assert after["eligibility_snapshot_ref"]=="question_trust"
        assert all(before[k]==after[k] for k in ("question_id","question_version","source_category","question_source","minutes"))
    assert len(json.dumps(compact)) < len(json.dumps(original))*.65
    assert "eligibility_snapshot" in original["draft"]["questions"][0]


def test_identical_tool_results_refer_to_latest_but_changed_evidence_is_not_discarded():
    old={"states":[{"kp_id":"kp","recent_attempts":[{"assisted":True,"result":"right"}],"state":"unseen"}]}
    changed={"states":[{"kp_id":"kp","recent_attempts":[{"assisted":False,"result":"right"}],"state":"mastered"}]}
    messages=[{"role":"tool","tool_call_id":str(i),"content":json.dumps(r)} for i,r in enumerate([old,old,changed])]
    compact=compact_model_messages(messages)
    assert json.loads(compact[0]["content"])=={"same_result_as_tool_call_id":"1"}
    assert json.loads(compact[1]["content"])==old
    assert json.loads(compact[2]["content"])==changed
    assert json.loads(messages[0]["content"])==old


def test_utf8_input_limit_blocks_before_provider_and_never_truncates_facts():
    calls=[]
    provider=SimpleNamespace(tool_turn=lambda *_a,**_kw:pytest.fail("must not call Provider"))
    with pytest.raises(AppError) as exc:
        _model_turn(provider,[{"role":"tool","tool_call_id":"x","content":json.dumps({"unbounded_facts":"证据"*20000},ensure_ascii=False)}],calls,turn=1,timeout=1)
    assert exc.value.detail=="context_limit" and calls==[]


def test_wrapped_evaluation_budget_stop_is_not_retried_or_called_provider_failure():
    from scripts.phase5_eval_meter import BudgetStop
    class Provider:
        model="deepseek-flash"
        def tool_turn(self,*_a,**_kw):
            try: raise BudgetStop("single_request_token_bound")
            except BudgetStop as cause: raise AppError("generation_failed",retryable=True) from cause
    calls=[]
    with pytest.raises(AppError) as exc:
        _model_turn(Provider(),[],calls,turn=4,timeout=1)
    assert exc.value.detail=="provider_request_policy_blocked"
    assert len(calls)==1 and calls[0]["error_code"]=="provider_request_policy_blocked"
    assert calls[0]['failure']['reason']=='single_request_token_bound'
    assert calls[0]['physical_request_attempts'] is None
    assert calls[0]["retryable"] is False
