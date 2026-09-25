"""问答检索意图分类与动态证据数量。"""

from __future__ import annotations

import pytest

from backend.chat.service import (
    Provider,
    build_chat_retrieval_plan,
    classify_answer_style,
    _is_overview_question,
)


@pytest.mark.parametrize(
    ("question", "intent", "top_k", "candidate_k", "diversify"),
    [
        ("什么是洛必达法则", "precise", 8, 24, False),
        ("为什么使用洛必达法则前要先判断类型", "explain", 12, 36, False),
        ("列举洛必达法则的适用场景", "comprehensive", 16, 48, True),
    ],
)
def test_local_rules_choose_retrieval_size(
    question: str,
    intent: str,
    top_k: int,
    candidate_k: int,
    diversify: bool,
) -> None:
    plan = build_chat_retrieval_plan(question)
    assert (plan.intent, plan.top_k, plan.candidate_k, plan.diversify) == (
        intent,
        top_k,
        candidate_k,
        diversify,
    )
    assert plan.classified_by == "rules"


def test_ambiguous_question_uses_llm_classifier_fallback() -> None:
    class Classifier:
        calls = 0

        def classify_retrieval_intent(self, _question: str) -> str:
            self.calls += 1
            return "comprehensive"

    provider = Classifier()
    plan = build_chat_retrieval_plan("勾股定理与圆的联系", provider=provider)
    assert provider.calls == 1
    assert plan.intent == "comprehensive"
    assert plan.top_k == 16 and plan.candidate_k == 48 and plan.diversify
    assert plan.classified_by == "llm"


def test_known_intent_does_not_spend_an_llm_call() -> None:
    class Classifier:
        calls = 0

        def classify_retrieval_intent(self, _question: str) -> str:
            self.calls += 1
            return "precise"

    provider = Classifier()
    plan = build_chat_retrieval_plan("什么是导数", provider=provider)
    assert provider.calls == 0
    assert plan.intent == "precise" and plan.classified_by == "rules"


def test_classifier_failure_falls_back_to_explanatory_size() -> None:
    class Classifier:
        def classify_retrieval_intent(self, _question: str) -> None:
            return None

    plan = build_chat_retrieval_plan("勾股定理与圆的联系", provider=Classifier())
    assert plan.intent == "explain"
    assert plan.top_k == 12 and plan.candidate_k == 36
    assert plan.diversify is False
    assert plan.classified_by == "default"


def test_provider_classifier_uses_small_bounded_request(monkeypatch) -> None:
    provider = Provider.__new__(Provider)
    provider.api_key = "test-key"
    provider.base_url = "https://llm.invalid/v1"
    provider.model = "test-model"
    provider.timeout = 60.0
    captured = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": "EXPLAIN"}}]}

    def fake_post(url, *, headers, json, timeout):
        captured.update(url=url, headers=headers, body=json, timeout=timeout)
        return Response()

    monkeypatch.setattr("backend.chat.service.httpx.post", fake_post)
    assert provider.classify_retrieval_intent("这是一个模糊问题") == "explain"
    assert captured["body"]["max_tokens"] == 48
    assert captured["timeout"] == 6.0


@pytest.mark.parametrize(
    ("question", "style", "full_document"),
    [
        ("什么是洛必达法则？", "brief", False),
        ("解释一下洛必达法则的适用条件", "normal", False),
        ("大概说一下验收文件讲了什么", "brief", True),
        ("每一个阶段都给我细讲一下", "detailed", True),
        ("请把所有步骤逐一展开说明", "detailed", True),
    ],
)
def test_answer_style_is_independent_from_document_coverage(
    question: str, style: str, full_document: bool
) -> None:
    assert classify_answer_style(question) == style
    assert _is_overview_question(question) is full_document
