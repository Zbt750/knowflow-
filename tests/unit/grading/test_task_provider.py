import asyncio
import httpx
import pytest
from backend.chat.service import Provider
from backend.errors import AppError
from backend.chat.service import _provider_error


def provider():
    return Provider(api_key="synthetic-test-key", base_url="https://example.invalid/v1", model="synthetic-model", timeout=1, max_tokens=4000)


def test_connection_failure_is_retryable_but_authentication_failure_is_not():
    assert _provider_error("learning_task", httpx.ConnectError("synthetic")).retryable
    request = httpx.Request("POST", "https://example.invalid")
    response = httpx.Response(401, request=request)
    error = httpx.HTTPStatusError("synthetic", request=request, response=response)
    assert not _provider_error("learning_task", error).retryable


def test_final_turn_omits_tools_and_tool_choice(monkeypatch):
    seen = {}
    async def post(_client, url, **kwargs):
        seen.update(kwargs["json"])
        return httpx.Response(200, request=httpx.Request("POST", url), json={"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]})
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    provider().tool_turn([], [], timeout=0.5)
    assert "tools" not in seen and "tool_choice" not in seen


def test_provider_sends_tools_and_preserves_usage(monkeypatch):
    seen = {}
    async def post(_client, url, **kwargs):
        seen.update(kwargs)
        return httpx.Response(200, request=httpx.Request("POST", url), json={"choices": [{"message": {"tool_calls": []}, "finish_reason": "stop"}], "usage": {"total_tokens": 12}})
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    result = provider().tool_turn([{"role": "user", "content": "test"}], [{"type": "function"}], timeout=0.5)
    assert seen["json"]["tools"] and seen["json"]["max_tokens"] == 2000
    assert result["usage"]["total_tokens"] == 12


def test_provider_output_limit_is_not_a_success(monkeypatch):
    async def post(_client, url, **kwargs):
        return httpx.Response(200, request=httpx.Request("POST", url), json={"choices": [{"finish_reason": "length"}]})
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    with pytest.raises(AppError) as error:
        provider().tool_turn([], [], timeout=0.5)
    assert error.value.code == "answer_truncated"


def test_provider_has_total_deadline_not_only_network_silence(monkeypatch):
    async def post(*args, **kwargs):
        await asyncio.sleep(1)
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    with pytest.raises(AppError):
        provider().tool_turn([], [], timeout=0.01)
