import asyncio
import json

import pytest
from backend.chat.call_trace import ACTIVE_ATTEMPT, CallTrace, clean_usage, observe_payload, safe_failure_reason
from backend.chat.service import Provider, _stream_deltas, _complete_with_retry
from backend.errors import AppError


class Alive:
    async def is_disconnected(self): return False


@pytest.mark.parametrize("detail, expected", [
    ("stream:http_503", "http_503"), ("stream:http_429", "http_429"),
    ("stream:ConnectError", "network_ConnectError"),
    ("stream:ReadTimeout", "network_ReadTimeout"),
    ("stream:total_timeout", "total_timeout"),
    ("provider returned an empty answer", "empty_answer"),
    ("stream:http_503 secret=do-not-store", "unknown"),
    ("stream:RuntimeError private path C:/hidden", "unknown"),
])
def test_safe_failure_reason_never_persists_untrusted_detail(detail, expected):
    assert safe_failure_reason(detail) == expected


class Response:
    def __init__(self, payloads): self.payloads = payloads
    async def __aenter__(self): return self
    async def __aexit__(self, *_): pass
    def raise_for_status(self): pass
    async def aiter_lines(self):
        for payload in self.payloads:
            await asyncio.sleep(0)
            yield "data: " + json.dumps(payload)
        yield "data: [DONE]"


def mocked_client(monkeypatch, *, include_usage=True):
    requests = []
    class Client:
        def __init__(self, **_): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        def stream(self, method, url, **kwargs):
            body = kwargs["json"]
            requests.append(body)
            value = int(body["messages"][0]["content"])
            payloads = [
                {"choices": [{"delta": {"reasoning_content": "不能记录或显示的草稿"}}]},
                {"choices": [{"delta": {"content": f"回答{value}"}, "finish_reason": "stop"}]},
            ]
            if include_usage:
                payloads.append({"choices": [], "usage": {"prompt_tokens": value, "completion_tokens": 2, "total_tokens": value + 2, "unexpected_private_field": "不能保存"}})
            return Response(payloads)
    monkeypatch.setattr("backend.chat.service.httpx.AsyncClient", Client)
    return requests


def test_shared_provider_concurrent_requests_do_not_mix_usage(monkeypatch):
    requests = mocked_client(monkeypatch)
    provider = Provider(api_key="synthetic-key", base_url="https://example.invalid", model="synthetic", timeout=1, max_tokens=100, stream_include_usage=True)
    async def run(value):
        trace = CallTrace(provider, transport="stream")
        parts = []
        async for _ in _stream_deltas(provider, [{"role": "user", "content": str(value)}], parts, Alive(), {"disconnected": False}, "测试", call_trace=trace): pass
        assert ACTIVE_ATTEMPT.get() is None
        return parts, trace.summary(str(value))
    async def run_all(): return await asyncio.gather(run(3), run(17))
    results = asyncio.run(run_all())
    assert [result[1]["observed_usage"]["total_tokens"] for result in results] == [5, 19]
    for parts, summary in results:
        assert summary["calls"][0]["finish_reason"] == "stop"
        assert summary["total_usage_complete"] is True
        assert "草稿" not in str(parts) + str(summary)
        assert "synthetic-key" not in str(summary)
        assert "unexpected_private_field" not in str(summary)
    assert all(req["stream_options"] == {"include_usage": True} for req in requests)


def test_missing_usage_is_unknown_and_option_is_off_by_default(monkeypatch):
    requests = mocked_client(monkeypatch, include_usage=False)
    provider = Provider(api_key="synthetic", base_url="https://example.invalid", model="test", timeout=1, max_tokens=100)
    trace = CallTrace(provider, transport="stream")
    async def run():
        async for _ in _stream_deltas(provider, [{"role": "user", "content": "2"}], [], Alive(), {"disconnected": False}, "测试", call_trace=trace): pass
    asyncio.run(run())
    summary = trace.summary("test")
    assert summary["observed_usage"] is None and summary["usage_observed"] is False
    assert summary["total_usage_complete"] is False
    assert summary["calls"][0]["output_budget"] == 100
    assert "stream_options" not in requests[0]


@pytest.mark.parametrize("first_usage", [None, {"total_tokens": 5}])
def test_empty_retry_keeps_attempt_usage_separate(first_usage):
    class Fake:
        async def stream(self, messages, *, attempt=1):
            observe_payload({"usage": first_usage if attempt == 1 else {"total_tokens": 7},
                             "choices": [{"finish_reason": "stop"}]})
            if attempt == 2: yield "回答"
    provider = Fake()
    trace = CallTrace(provider, transport="stream")
    async def run():
        async for _ in _stream_deltas(provider, [], [], Alive(), {"disconnected": False}, "测试", call_trace=trace): pass
    asyncio.run(run())
    summary = trace.summary("test")
    assert summary["retry_count"] == 1
    assert summary["calls"][0]["status"] == "failed"
    assert summary["calls"][1]["status"] == "completed"
    assert summary["observed_usage"]["total_tokens"] == (12 if first_usage else 7)
    assert summary["total_usage_complete"] is bool(first_usage)
    assert trace.final_usage() == {"total_tokens": 7}


def test_sync_truncation_and_retry_records_finish_reason():
    class Fake:
        def complete(self, messages, *, attempt=1):
            observe_payload({"usage": {"total_tokens": attempt * 3}, "choices": [{"finish_reason": "length" if attempt == 1 else "stop"}]})
            if attempt == 1: raise AppError("answer_truncated", retryable=True)
            return "完整回答", {"total_tokens": 6}
    provider = Fake()
    trace = CallTrace(provider, transport="complete")
    assert _complete_with_retry(provider, [], "测试", call_trace=trace)[0] == "完整回答"
    summary = trace.summary("test")
    assert [call["finish_reason"] for call in summary["calls"]] == ["length", "stop"]
    assert summary["observed_usage"]["total_tokens"] == 9
    assert ACTIVE_ATTEMPT.get() is None


def test_sync_failure_reason_is_redacted_in_trace():
    class Fake:
        def complete(self, messages, *, attempt=1):
            raise AppError("generation_failed", detail="complete:http_503", retryable=False)
    trace = CallTrace(Fake(), transport="complete")
    with pytest.raises(AppError):
        _complete_with_retry(Fake(), [], "synthetic", call_trace=trace)
    assert trace.summary("test")["calls"][0]["failure_reason"] == "http_503"


@pytest.mark.parametrize("value", [None, {}, {"total_tokens": True}, {"total_tokens": -1}, {"private": "原文"}])
def test_invalid_or_non_counter_usage_is_not_observed(value):
    assert clean_usage(value) is None


def test_complete_without_usage_does_not_turn_output_budget_into_consumption(monkeypatch):
    import httpx
    def post(url, **kwargs):
        return httpx.Response(200, request=httpx.Request("POST", url), json={
            "choices": [{"message": {"content": "回答"}, "finish_reason": "stop"}]})
    monkeypatch.setattr("backend.chat.service.httpx.post", post)
    provider = Provider(api_key="synthetic", base_url="https://example.invalid", model="test", timeout=1, max_tokens=100)
    trace = CallTrace(provider, transport="complete")
    assert _complete_with_retry(provider, [], "测试", call_trace=trace) == ("回答", None)
    assert trace.summary("test")["usage_observed"] is False
    assert trace.summary("test")["calls"][0]["finish_reason"] == "stop"


def test_unknown_finish_reason_cannot_copy_arbitrary_upstream_content():
    provider = object()
    trace = CallTrace(provider, transport="stream")
    record, token, started = trace.begin(1, provider)
    try:
        observe_payload({"choices": [{"finish_reason": {"private": "不能保存"}}]})
    finally:
        trace.end(record, token, started)
    assert record["finish_reason"] == "unknown"
    assert "不能保存" not in str(trace.summary("test"))
