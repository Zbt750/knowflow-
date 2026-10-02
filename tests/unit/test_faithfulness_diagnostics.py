import asyncio
from types import SimpleNamespace

import pytest

from scripts.run_ragas_chat_eval import (EvalCase, score_metrics, record_faithfulness_output,
                                        faithfulness_diagnostics_complete)


def test_existing_judge_outputs_record_statements_and_verdicts_only():
    audit = []
    record_faithfulness_output(type("StatementGeneratorOutput", (), {}), SimpleNamespace(statements=["事实一", "事实二"]), audit)
    record_faithfulness_output(type("NLIStatementOutput", (), {}), SimpleNamespace(statements=[
        SimpleNamespace(statement="事实一", reason="原文支持", verdict=1),
        SimpleNamespace(statement="事实二", reason="未陈述", verdict=0)]), audit)
    assert faithfulness_diagnostics_complete(audit, "scored")
    assert audit[1]["statements"][1]["verdict"] == 0
    record_faithfulness_output(type("OtherOutput", (), {}), SimpleNamespace(), audit)
    assert len(audit) == 2


@pytest.mark.parametrize("status,generated,judged", [
    ("error", ["a"], ["a"]), ("scored", ["a", "b"], ["a"]),
    ("scored", ["a", "b"], ["b", "a"]), ("scored", [], []),
])
def test_missing_failed_or_reordered_diagnostics_are_not_complete(status, generated, judged):
    audit = [{"phase": "statement_generation", "statements": generated},
             {"phase": "statement_verdicts", "statements": [{"statement": s, "verdict": 1} for s in judged]}]
    assert not faithfulness_diagnostics_complete(audit, status)


@pytest.mark.parametrize("fail", [False, True])
def test_score_is_unchanged_no_retry_and_audits_do_not_leak(fail):
    class Scorer:
        def __init__(self):
            self.llm = SimpleNamespace(faithfulness_audit=[{"old": "previous case"}])
            self.calls = 0
        async def ascore(self, **kwargs):
            self.calls += 1
            assert not self.llm.faithfulness_audit
            self.llm.faithfulness_audit.append({"phase": "statement_generation", "statements": ["a"]})
            if fail:
                raise RuntimeError("judge unavailable")
            self.llm.faithfulness_audit.append({"phase": "statement_verdicts", "statements": [{"statement": "a", "reason": "no", "verdict": 0}]})
            return 0.0
    scorer = Scorer()
    case = EvalCase(case_id="synthetic", category="test", mode="user", question="q", reference="r",
                    strategy="search", answerability="answerable", material_title=None,
                    required_any_groups=(), forbidden_any=())
    result = asyncio.run(score_metrics(case=case, answer="answer", contexts=["context"], scorers={"faithfulness": scorer}, timeout_seconds=1))["faithfulness"]
    assert scorer.calls == 1
    assert result["diagnostics_complete"] is not fail
    if fail:
        assert result["status"] == "error" and "value" not in result
    else:
        assert result["value"] == 0.0
    scorer.llm.faithfulness_audit[0]["statements"][0] = "mutated"
    assert result["diagnostics"][0]["statements"] == ["a"]
