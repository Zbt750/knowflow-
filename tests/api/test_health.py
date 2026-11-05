from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from backend.app import create_app
from backend.api.deps import get_db


class FakeResult:
    """模拟 SQLAlchemy Result；SELECT 1 在这里固定返回 1。"""

    def scalar(self) -> int:
        return 1


class FakeSession:
    """只模拟 health 路由实际需要的 execute() 行为。"""

    def __init__(self, *, fail: bool) -> None:
        self._fail = fail

    def execute(self, *_args: Any, **_kwargs: Any) -> FakeResult:
        if self._fail:
            # 故意带上连接串样式的文本，用来验证它不会出现在响应里。
            raise SQLAlchemyError(
                "simulated database failure postgresql://kaoyan:secret@127.0.0.1/kaoyan"
            )
        return FakeResult()


def override_healthy_db() -> Iterator[FakeSession]:
    yield FakeSession(fail=False)


def override_broken_db() -> Iterator[FakeSession]:
    yield FakeSession(fail=True)


@pytest.fixture
def healthy_client() -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_db] = override_healthy_db
    # 必须用 with：否则 lifespan 不执行，测试会变成假绿灯。
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def broken_client() -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_db] = override_broken_db
    # 关闭异常直抛，断言的是应用返回的 503 契约，而不是测试框架抛出的异常。
    # 与 healthy_client 一样必须用 with，否则 lifespan 不执行。
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.dependency_overrides.clear()


def test_health_returns_200_when_database_query_succeeds(healthy_client: TestClient) -> None:
    response = healthy_client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "connected"
    assert body["environment"] in {"dev", "test", "prod"}
    # 阶段 C 起健康检查还要报告检索栈与任务线程状态，便于区分
    # 「后端活着但检索不可用」这种情况。
    assert body["retrieval"] in {"ready", "unavailable"}
    assert body["worker"] in {"running", "stopped"}
    assert isinstance(body["llm_configured"], bool)
    assert body["llm_model"] is None or isinstance(body["llm_model"], str)

def test_health_does_not_leak_paths_or_secrets(healthy_client: TestClient) -> None:
    """健康检查新增字段只允许是状态词，不得泄露绝对路径、连接串或密钥。"""
    body = healthy_client.get("/api/health").text.lower()
    for leaked in ("postgresql://", "password", "d:\\", "c:\\", "secret", "storage/"):
        assert leaked not in body


def test_health_returns_503_without_database_details_when_query_fails(
    broken_client: TestClient,
) -> None:
    response = broken_client.get("/api/health")

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "database_unavailable",
            "message": "database unavailable",
        }
    }
    # 驱动异常文本、连接串与密码都不得回传到浏览器。
    body = response.text.lower()
    assert "simulated database failure" not in body
    assert "postgresql://" not in body
    assert "secret" not in body