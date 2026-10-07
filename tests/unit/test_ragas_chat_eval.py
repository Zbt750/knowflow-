"""Offline regression tests for the optional RAGAS evaluation harness."""

from __future__ import annotations

import asyncio
import pytest

from scripts.run_ragas_chat_eval import EvalCase, phrase_check, precision_conflict_review, score_metrics


def make_case(*, answerability: str, required: tuple[tuple[str, ...], ...] = ()) -> EvalCase:
    return EvalCase(
        case_id="unit-test",
        mode="builtin",
        question="测试问题",
        reference="测试参考答案",
        strategy="search",
        answerability=answerability,
        material_title=None,
        required_any_groups=required,
        forbidden_any=(),
    )


def test_phrase_check_recognizes_latex_infinity_notation() -> None:
    case = make_case(answerability="answerable", required=(("∞/∞", "无穷比无穷"),))

    result = phrase_check(case, r"洛必达法则处理 \(\infty/\infty\) 型。", "hybrid")

    assert result["passed"] is True
    assert result["missing_required_groups"] == []


@pytest.mark.parametrize("fraction", [r"\frac12", r"\dfrac12", r"\tfrac12", r"\tfrac{1}{2}"])
def test_phrase_check_recognizes_unbraced_latex_fraction(fraction: str) -> None:
    case = make_case(answerability="answerable", required=(("1/2", "二分之一"),))

    result = phrase_check(case, "极限结果为 " + fraction + "。", "hybrid")

    assert result["passed"] is True
    assert result["missing_required_groups"] == []


def test_unanswerable_cases_skip_all_ragas_metrics_and_use_behavior_check() -> None:
    class Scorer:
        calls = 0

        async def ascore(self, **_kwargs):
            self.calls += 1
            return 1.0

    scorers = {name: Scorer() for name in (
        "context_precision",
        "context_recall",
        "faithfulness",
    )}
    result = asyncio.run(
        score_metrics(
            case=make_case(answerability="unanswerable"),
            answer="资料中没有足够依据回答这个问题。",
            contexts=["检索到的正向资料片段"],
            scorers=scorers,
            timeout_seconds=1,
        )
    )

    assert set(result) == set(scorers)
    assert all(metric["status"] == "skipped" for metric in result.values())
    assert all(scorer.calls == 0 for scorer in scorers.values())


def test_answer_relevancy_scores_general_answer_without_retrieval_contexts() -> None:
    class Scorer:
        async def ascore(self, *, user_input, response):
            assert user_input == "测试问题"
            assert "通用知识参考" in response
            return 0.9

    result = asyncio.run(score_metrics(
        case=make_case(answerability="general"),
        answer="## 通用知识参考\n参考回答。", contexts=[],
        scorers={"answer_relevancy": Scorer()}, timeout_seconds=1,
    ))
    assert result["answer_relevancy"]["value"] == 0.9


def test_faithfulness_receives_only_grounded_part_of_mixed_answer() -> None:
    class Scorer:
        async def ascore(self, *, user_input, retrieved_contexts, response):
            assert "503 [C1]" in response
            assert "TCP" not in response
            return 1.0

    result = asyncio.run(score_metrics(
        case=make_case(answerability="answerable"),
        answer="## 资料依据\n健康检查返回 503 [C1]。\n## 通用知识参考\nTCP 用于可靠传输。",
        contexts=["健康检查返回 503。"], scorers={"faithfulness": Scorer()}, timeout_seconds=1,
    ))
    assert result["faithfulness"]["value"] == 1.0


def test_precision_diagnostics_do_not_change_score_or_leak_between_cases():
    from types import SimpleNamespace
    class Scorer:
        llm = SimpleNamespace(precision_audit=[{"context_index": 99, "reason": "old"}])
        calls = 0
        async def ascore(self, **kwargs):
            self.calls += 1
            assert self.llm.precision_audit == []
            self.llm.precision_audit.append({"context_index": 0, "verdict": 0, "reason": "only partial coverage"})
            return 0.0
    scorer = Scorer()
    result = asyncio.run(score_metrics(case=make_case(answerability="answerable"), answer="answer", contexts=["context"], scorers={"context_precision": scorer}, timeout_seconds=1))
    assert result["context_precision"]["value"] == 0.0
    assert scorer.calls == 1
    assert result["context_precision"]["diagnostic_context_count"] == 1
    assert result["context_precision"]["diagnostics_complete"] is True
    scorer.llm.precision_audit[0]["reason"] = "later"
    assert result["context_precision"]["diagnostics"][0]["reason"] == "only partial coverage"


def test_partial_precision_verdicts_survive_scorer_failure_without_retries():
    from types import SimpleNamespace
    class Scorer:
        llm = SimpleNamespace(precision_audit=[])
        calls = 0
        async def ascore(self, **kwargs):
            self.calls += 1
            self.llm.precision_audit.append({"context_index": 0, "verdict": 1, "reason": "relevant"})
            raise RuntimeError("second context unavailable")
    scorer = Scorer()
    result = asyncio.run(score_metrics(case=make_case(answerability="answerable"), answer="answer", contexts=["first", "second"], scorers={"context_precision": scorer}, timeout_seconds=1))
    metric = result["context_precision"]
    assert metric["status"] == "error" and "value" not in metric
    assert metric["diagnostics_complete"] is False
    assert metric["diagnostic_context_count"] == 2
    assert metric["diagnostics"][0]["context_index"] == 0
    assert scorer.calls == 1


def test_precision_conflict_is_flagged_without_changing_raw_scores():
    metrics = {
        "context_precision": {"status": "scored", "value": 0.0, "diagnostics_complete": True},
        "context_recall": {"status": "scored", "value": 1.0},
    }
    result = precision_conflict_review(
        metrics, {"passed": True},
        {"count": 3, "all_present_in_actual_evidence": True},
    )
    assert result == {
        "required": True,
        "reason": "zero_precision_with_full_recall_and_grounded_citations",
        "score_adjusted": False,
    }
    assert metrics["context_precision"]["value"] == 0.0


def test_cross_file_partial_recall_diagnostics_trigger_review():
    metrics = {
        "context_precision": {"status": "scored", "value": 0.0, "diagnostics_complete": True,
                              "diagnostics": [
                                  {"verdict": 0, "reason": "This context only mentions a common requirement but not the unique contents necessary to fully answer the question."},
                                  {"verdict": 0, "reason": "This context only contains one document and is insufficient to support the answer, which requires a comparison of both documents."},
                              ]},
        "context_recall": {"status": "scored", "value": 2 / 3},
    }
    result = precision_conflict_review(metrics, {"passed": True},
                                      {"count": 2, "all_present_in_actual_evidence": True})
    assert result["required"] is True
    assert result["reason"] == "repeated_single_chunk_completeness_requirement"
    assert result["score_adjusted"] is False
    assert metrics["context_precision"]["value"] == 0.0


@pytest.mark.parametrize("count,complete,required", [(2, True, True), (1, True, False), (2, False, False)])
def test_partial_recall_can_flag_repeated_whole_answer_requirement(count, complete, required):
    metrics = {
        "context_precision": {"status": "scored", "value": 0.0, "diagnostics_complete": complete,
                              "diagnostics": [{"verdict": 0, "reason": "This chunk cannot support the full answer."}] * count},
        "context_recall": {"status": "scored", "value": 2 / 3},
    }
    result = precision_conflict_review(metrics, {"passed": True},
                                      {"count": 2, "all_present_in_actual_evidence": True})
    assert result["required"] is required
    assert result["score_adjusted"] is False
    assert metrics["context_precision"]["value"] == 0.0
    assert metrics["context_recall"]["value"] == 2 / 3
    if required:
        assert result["reason"] == "repeated_single_chunk_completeness_requirement"


@pytest.mark.parametrize("precision,recall,complete,citations_present", [
    (None, 1.0, True, True),
    (0.0, 0.0, True, True),
    (0.0, 1.0, False, True),
    (0.0, 1.0, True, False),
])
def test_precision_conflict_requires_complete_contradictory_evidence(
    precision, recall, complete, citations_present,
):
    metrics = {
        "context_precision": {"status": "scored" if precision is not None else "error", "value": precision, "diagnostics_complete": complete},
        "context_recall": {"status": "scored", "value": recall},
    }
    result = precision_conflict_review(
        metrics, {"passed": True},
        {"count": 2, "all_present_in_actual_evidence": citations_present},
    )
    assert result["required"] is False
    assert result["score_adjusted"] is False
