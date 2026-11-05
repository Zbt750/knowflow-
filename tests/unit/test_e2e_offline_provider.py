import asyncio
import pytest

from backend.errors import AppError
from scripts.e2e_backend import OfflineProvider, create_e2e_app


def test_offline_provider_never_uses_http(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("offline browser fixture must not call a network model")
    monkeypatch.setattr("httpx.post", forbidden)
    monkeypatch.setattr("httpx.AsyncClient", forbidden)
    provider = OfflineProvider(api_key="placeholder", model="irrelevant")
    messages = [{"role": "user", "content": "合成测试"}]
    answer, usage = provider.complete(messages)
    assert "[C1]" in answer and usage is None
    assert provider.classify_retrieval_intent("合成测试") is None
    async def collect():
        return "".join([part async for part in provider.stream(messages)])
    assert asyncio.run(collect()) == answer
    with pytest.raises(AppError):
        provider.tool_turn(messages, [], timeout=1)


def test_e2e_app_refuses_development_environment(monkeypatch):
    monkeypatch.setenv("APP_ENV", "dev")
    with pytest.raises(RuntimeError, match="APP_ENV=test"):
        create_e2e_app()
