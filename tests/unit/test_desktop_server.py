from pathlib import Path
import os
import subprocess
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.config import get_settings
from desktop.runtime_paths import RuntimePaths
from desktop.server import attach_frontend, configure_environment, validate_boot

URL = "postgresql+psycopg://synthetic:synthetic@127.0.0.1:5433/desktop_fixture"
PORT = 18750


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def runtime(tmp_path):
    resources = tmp_path / "只读资源"
    frontend = resources / "frontend" / "dist"
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text("<html>桌面测试</html>", encoding="utf-8")
    (frontend / "assets" / "app-123.js").write_text("export const ok = true;", encoding="utf-8")
    (frontend / "assets" / "_plugin-vue_export-helper-123.js").write_text("export default {};", encoding="utf-8")
    (frontend / ".env").write_text("SHOULD_NOT_BE_EXPOSED", encoding="utf-8")
    return RuntimePaths.windows(resources=resources, local_app_data=tmp_path / "用户数据")


def test_boot_is_readonly_and_requires_local_database(runtime):
    assert validate_boot(runtime, URL, PORT).name == "dist"
    assert not runtime.data.exists()


@pytest.mark.parametrize("url,port", [
    ("broken-secret-url", PORT),
    (URL.replace("127.0.0.1", "remote.example"), PORT),
    (URL + "?host=remote.example", PORT),
    (URL, 80), (URL, True),
])
def test_invalid_boot_never_echoes_dsn(runtime, url, port):
    with pytest.raises(ValueError) as error:
        validate_boot(runtime, url, port)
    assert "synthetic" not in str(error.value) and "broken-secret" not in str(error.value)


def test_missing_frontend_rejected_before_data_directories(runtime):
    (runtime.resources / "frontend/dist/index.html").unlink()
    with pytest.raises(ValueError, match="frontend_build_missing"):
        validate_boot(runtime, URL, PORT)
    assert not runtime.data.exists()


def test_desktop_ignores_checkout_env_and_inherited_model_key(runtime, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("DATABASE_URL=postgresql://wrong:wrong@remote.example/leak\nLLM_API_KEY=private-development-key\n", encoding="utf-8")
    monkeypatch.setattr("desktop.server.os.environ", dict(APP_ENV="test", TEST_DATABASE_URL=URL, LLM_API_KEY="inherited-development-key"))
    configure_environment(runtime, URL, PORT)
    settings = get_settings()
    assert settings.app_runtime_profile == "desktop" and settings.app_env == "dev"
    assert str(settings.active_database_url) == URL
    assert settings.llm_api_key is None
    assert os.environ["HF_HUB_OFFLINE"] == "1" and os.environ["TRANSFORMERS_OFFLINE"] == "1"
    assert not settings.capture_test_evidence
    assert settings.upload_dir == runtime.data / "uploads"
    assert settings.model_settings_path == runtime.data / "config/model-settings.bin"
    assert settings.allowed_web_origins == [f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"]
    assert not runtime.data.exists()


def app_client(runtime, *, client_host="127.0.0.1"):
    app = FastAPI()
    @app.get("/api/health")
    def health(): return {"source": "api"}
    attach_frontend(app, runtime.resources / "frontend/dist", port=PORT)
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}", client=(client_host, 12345))


@pytest.mark.parametrize("page", ["/", "/study", "/chat", "/knowledge", "/materials", "/settings", "/knowledge/cs.network.tcp/lesson"])
def test_spa_deep_routes_and_api_priority(runtime, page):
    with app_client(runtime) as client:
        response = client.get(page)
        assert response.status_code == 200 and "桌面测试" in response.text
        assert response.headers["cache-control"] == "no-store"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert client.get("/api/health").json() == {"source": "api"}


@pytest.mark.parametrize("path", ["/api/missing", "/api", "/assets/missing.js", "/.env", "/assets/../.env", "/unknown", "/storage/data", "/assets/source.map"])
def test_missing_or_private_routes_do_not_fallback_to_html(runtime, path):
    with app_client(runtime) as client:
        response = client.get(path)
        assert response.status_code == 404
        assert "桌面测试" not in response.text and "SHOULD_NOT" not in response.text


@pytest.mark.parametrize("headers", [
    {"Host": "attacker.example"}, {"Host": "127.0.0.1:9999"},
    {"Origin": "https://attacker.example"}, {"Sec-Fetch-Site": "cross-site"},
    {"X-Forwarded-For": "127.0.0.1"},
])
def test_desktop_denies_rebinding_and_cross_origin(runtime, headers):
    with app_client(runtime) as client:
        assert client.get("/api/health", headers=headers).status_code == 403
        assert client.get("/study", headers=headers).status_code == 403


def test_asset_head_and_remote_peer(runtime):
    with app_client(runtime) as client:
        response = client.get("/assets/app-123.js")
        assert response.status_code == 200 and "export const" in response.text
        assert client.get("/assets/_plugin-vue_export-helper-123.js").status_code == 200
        assert client.head("/chat").status_code == 200
        assert client.head("/chat").content == b""
        assert client.post("/study").status_code == 405
    with app_client(runtime, client_host="192.0.2.1") as client:
        assert client.get("/study").status_code == 403


def test_launcher_preflight_does_not_create_data_or_connect(runtime):
    command = [sys.executable, "scripts/run_desktop_backend.py", "--resources", str(runtime.resources),
               "--local-app-data", str(runtime.data.parent), "--check"]
    result = subprocess.run(command, cwd=Path(__file__).resolve().parents[2], env={**os.environ, "DESKTOP_DATABASE_URL": URL}, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0 and "desktop_preflight_ok" in result.stdout
    assert "synthetic" not in result.stdout + result.stderr
    assert not runtime.data.exists()
    invalid = subprocess.run(command, cwd=Path(__file__).resolve().parents[2], env={**os.environ, "DESKTOP_DATABASE_URL": "bad-private-secret"}, capture_output=True, text=True, timeout=15)
    assert invalid.returncode == 2 and "bad-private-secret" not in invalid.stdout + invalid.stderr


@pytest.mark.parametrize("external,pg_port,category", [
    (URL, 18760, "external_and_managed_database_conflict"),
    ("", PORT, "database_and_http_port_conflict"),
])
def test_managed_launcher_rejects_conflicts_before_initialization(runtime, external, pg_port, category):
    env = {key: value for key, value in os.environ.items() if key != "DESKTOP_DATABASE_URL"}
    if external: env["DESKTOP_DATABASE_URL"] = external
    result = subprocess.run([sys.executable, "scripts/run_desktop_backend.py", "--resources", str(runtime.resources),
                             "--local-app-data", str(runtime.data.parent), "--managed-postgres", "--pg-port", str(pg_port), "--check"],
                            cwd=Path(__file__).resolve().parents[2], env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 2 and category in result.stderr
    assert "synthetic" not in result.stdout + result.stderr
    assert not runtime.data.exists()


def test_managed_cli_preflight_with_real_binaries_remains_readonly(tmp_path):
    pg_bin = os.environ.get("KAOYAN_MANAGED_PG_TEST_BIN")
    if os.name != "nt" or not pg_bin: pytest.skip("explicit Windows PG18 binaries required")
    root = Path(__file__).resolve().parents[2]
    user = tmp_path / "readonly-user"
    result = subprocess.run([sys.executable, "scripts/run_desktop_backend.py", "--resources", str(root),
                             "--local-app-data", str(user), "--managed-postgres", "--pg-bin", pg_bin, "--check"],
                            cwd=root, env={k: v for k, v in os.environ.items() if k != "DESKTOP_DATABASE_URL"},
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0 and "desktop_preflight_ok" in result.stdout
    assert not user.exists()
