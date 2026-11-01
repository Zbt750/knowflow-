from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

# 项目根目录：tests/ 的上一级。
PROJECT_ROOT = Path(__file__).resolve().parents[1]

def _validate_isolated_test_database(test_url: str | None, owned_port: str | None) -> str:
    """Require an explicitly owned loopback test cluster; never fall back to dev."""
    from sqlalchemy.engine import make_url

    if not test_url:
        raise RuntimeError("TEST_DATABASE_URL must be explicitly set by an isolated test runner")
    try:
        url = make_url(test_url)
        port = int(url.port or 0)
        marker = int(owned_port or 0)
    except Exception as exc:
        raise RuntimeError("Invalid isolated test database configuration") from exc
    if (url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"}
            or port <= 18000 or port == 5433 or marker != port
            or not (url.database or "").endswith("_test")):
        raise RuntimeError("Refusing database test run: URL must target its explicitly owned loopback _test cluster (port != 5433)")
    return test_url


def _configure_test_environment() -> str:
    """在导入任何 backend 模块之前固定测试环境；返回活动测试库 URL。"""
    # APP_ENV=test is a second guard; explicit URL ownership is checked first.
    os.environ["APP_ENV"] = "test"
    owned_port = os.environ.get("KAOYAN_OWNED_TEST_PORT") or os.environ.get("PHASE45E_OWNED_TEST_PORT")
    test_url = _validate_isolated_test_database(os.environ.get("TEST_DATABASE_URL"), owned_port)
    os.environ["TEST_DATABASE_URL"] = test_url
    # Keep both settings pointed at the same isolated database; never derive a dev URL.
    os.environ["DATABASE_URL"] = test_url
    return test_url


TEST_DATABASE_URL = _configure_test_environment()
if os.environ.get('PHASE45I_CLOSE_OFFLINE')=='1':
    from scripts.phase45i_offline_guard import install
    install()

# 环境变量先就位，再导入应用代码。
from backend.app import create_app  # noqa: E402
from backend.config import get_settings  # noqa: E402

# 校验：应用确实选择了测试库，而不是开发库。
get_settings.cache_clear()


@pytest.fixture(scope="session", autouse=True)
def migrated_test_database() -> None:
    """整个测试会话开始前，把测试库显式迁移到 head。

    为什么必须有这一步，而不是指望「反正有测试会建表」：
    早先测试库的表是 `test_alembic_upgrade_head_creates_learning_tables_from_empty_database`
    顺手建的（它先 downgrade base 再 upgrade head）。于是出现两种糟糕情况：
    - 模型加了新列以后直接跑集成测试，会报 `column "xxx" does not exist` ——
      看起来像代码 bug，实际只是库没迁移；
    - 单独运行某一个集成测试文件时，测试库可能一张表都没有，直接大面积报错。

    这两种都是「必须先按特定顺序跑某个测试」的脆弱依赖。这里用一个会话级夹具
    一次性迁移到位，跑法不再影响结果；同步跑 `alembic upgrade head` 的
    迁移测试仍然会各自验证一遍空库重建与模型一致性。
    """
    from alembic import command
    from alembic.config import Config

    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    command.upgrade(config, "head")


@pytest.fixture(scope="session")
def test_database_url() -> str:
    return TEST_DATABASE_URL


def pytest_sessionfinish(session,exitstatus):
    if os.environ.get('PHASE45I_CLOSE_OFFLINE')!='1':return
    import json
    from scripts.phase45i_offline_guard import BLOCKED
    output=Path(os.environ['PHASE45I_CLOSE_OUTPUT']).resolve()
    if not output.is_relative_to(PROJECT_ROOT/'storage/quality-audits'):
        raise RuntimeError('Private closeout report directory required')
    (output/'offline-network-guard.json').write_text(json.dumps({'exitstatus':int(exitstatus),
        'blocked_network_attempts':BLOCKED,'configured_models':'offline fixtures only'},indent=2),encoding='utf-8')


@pytest.fixture
def settings_guard() -> Iterator[None]:
    """每个用例结束清缓存，避免下一个用例复用被改过的 Settings。"""
    yield
    get_settings.cache_clear()


@pytest.fixture
def app(settings_guard: None):
    # 每个用例一个应用实例；TestClient 的 with 会真实执行 lifespan。
    return create_app()
