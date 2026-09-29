"""Offline regression tests for the optional RAGAS evaluation harness."""

from __future__ import annotations

import asyncio
import pytest

from scripts.run_ragas_chat_eval import EvalCase, phrase_check, score_metrics


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
