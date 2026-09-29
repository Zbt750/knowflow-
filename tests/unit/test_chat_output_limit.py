"""A model's length stop must never masquerade as a completed answer."""
import asyncio
import json

import httpx
import pytest

from backend.chat.service import Provider, _complete_with_retry, _stream_deltas
from backend.errors import AppError


def provider() -> Provider:
    return Provider(api_key="test-only", base_url="http://127.0.0.1:9", model="fake", timeout=1, max_tokens=100, retry_max_tokens=200)


def test_complete_retries_truncation_with_larger_budget(monkeypatch):
    budgets = []

    def post(url, **kwargs):
        budgets.append(kwargs["json"]["max_tokens"])
        return httpx.Response(200, request=httpx.Request("POST", url), json={
            "choices": [{"message": {"content": "半截" if len(budgets) == 1 else "完整回答"},
                         "finish_reason": "length" if len(budgets) == 1 else "stop"}],
        })

    monkeypatch.setattr("backend.chat.service.httpx.post", post)
    answer, _ = _complete_with_retry(provider(), [], "问题")
    assert answer == "完整回答"
    assert budgets == [100, 200]


def test_complete_reports_truncation_after_retry_budget_is_exhausted(monkeypatch):
    def post(url, **kwargs):
        return httpx.Response(200, request=httpx.Request("POST", url), json={
            "choices": [{"message": {"content": "半截"}, "finish_reason": "length"}],
        })

    monkeypatch.setattr("backend.chat.service.httpx.post", post)
    with pytest.raises(AppError) as caught:
        _complete_with_retry(provider(), [], "问题")
    assert caught.value.code == "answer_truncated"


@pytest.mark.parametrize("partial", [False, True])
def test_stream_length_stop_retries_once_even_after_partial_answer(monkeypatch, partial):
    calls = []
    original_client = httpx.AsyncClient

    def handler(request):
        calls.append(json.loads(request.content)["max_tokens"])
        choice = {"delta": {"content": "尚未讲完" if partial else ""}, "finish_reason": "length"}
        body = "data: " + json.dumps({"choices": [choice]}) + "\n\ndata: [DONE]\n\n"
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    monkeypatch.setattr("backend.chat.service.httpx.AsyncClient", lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))

    class Request:
        async def is_disconnected(self):
            return False

    async def collect():
        parts = ["## 通用知识参考\n"]
        async for _ in _stream_deltas(provider(), [], parts, Request(), {"disconnected": False}, "问题"):
            pass

    with pytest.raises(AppError) as caught:
        asyncio.run(collect())
    assert caught.value.code == "answer_truncated"
    assert calls == [100, 200]


def test_partial_truncation_replaces_answer_keeps_prefix_and_sequence(monkeypatch):
    calls = []
    original_client = httpx.AsyncClient

    def handler(request):
        calls.append(json.loads(request.content)["max_tokens"])
        choice = {"delta": {"content": "第一轮残句" if len(calls) == 1 else "第二轮完整回答"},
                  "finish_reason": "length" if len(calls) == 1 else "stop"}
        return httpx.Response(200, text="data: " + json.dumps({"choices": [choice]}) + "\n\ndata: [DONE]\n\n")

    monkeypatch.setattr("backend.chat.service.httpx.AsyncClient", lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))

    class Request:
        async def is_disconnected(self):
            return False

    async def collect():
        parts = ["通用参考\n"]
        frames = []
        async for frame in _stream_deltas(provider(), [], parts, Request(), {"disconnected": False}, "问题"):
            frames.append(json.loads(frame.decode().split("data: ")[1]))
        return parts, frames

    parts, frames = asyncio.run(collect())
    assert calls == [100, 200]
    assert "".join(parts) == "通用参考\n第二轮完整回答"
    assert [f["seq"] for f in frames] == [2, 3, 4]
    assert frames[1] == {"seq": 3, "text": "通用参考\n", "replace": True, "recovering": True}


def test_retry_budget_grows_when_configured_budget_equals_first():
    p = Provider(api_key="test-only", base_url="http://127.0.0.1:9", model="fake", timeout=1, max_tokens=8000, retry_max_tokens=8000)
    assert p._token_budget(2) == 16000
