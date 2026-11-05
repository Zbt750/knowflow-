"""Offline model adapter for browser regression, never a production provider."""
from __future__ import annotations

import os

from backend.errors import AppError


class OfflineProvider:
    """Deterministic protocol fixture; does not measure answer quality."""

    def __init__(self, **kwargs):
        self.model = "e2e-offline-fixture"
        self.max_tokens = 4000

    def _token_budget(self, attempt):
        return self.max_tokens

    def classify_retrieval_intent(self, question):
        return None

    def complete(self, messages, *, attempt=1):
        return (
            "这是浏览器回归用的离线回答，不代表模型质量。\n\n"
            "洛必达法则需满足未定式、可导等适用条件，不能只看到分式就使用。[C1]",
            None,
        )

    async def stream(self, messages, *, attempt=1):
        answer, _ = self.complete(messages, attempt=attempt)
        for index in range(0, len(answer), 24):
            yield answer[index:index + 24]

    def tool_turn(self, messages, tools, *, timeout):
        # Browser Agent scenarios provide explicit route fixtures. Fail closed
        # if a new test unexpectedly tries to reach an actual model instead.
        raise AppError("llm_not_configured")


def create_e2e_app():
    if os.environ.get("APP_ENV") != "test":
        raise RuntimeError("Offline E2E backend only supports APP_ENV=test")
    # Override dotenv credentials for this child process only. Do not modify
    # the user's .env or local model settings.
    os.environ["LLM_API_KEY"] = "e2e-placeholder"
    os.environ["LLM_BASE_URL"] = "http://127.0.0.1:9"
    os.environ["LLM_MODEL"] = "e2e-offline-fixture"
    from backend.config import get_settings
    from backend.chat import service
    from backend.app import create_app
    get_settings.cache_clear()
    service.Provider = OfflineProvider
    return create_app()
