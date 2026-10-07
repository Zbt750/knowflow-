import os

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import get_settings
from desktop.runtime_paths import RuntimePaths
from desktop.server import attach_frontend, configure_environment
from tests.integration.test_learning_loop import session_factory, clean_database


def test_desktop_lifespan_local_settings_and_spa_use_isolated_paths(tmp_path, monkeypatch, test_database_url, session_factory, clean_database):
    resources = tmp_path / "应用资源"
    frontend = resources / "frontend/dist"
    frontend.mkdir(parents=True)
    (frontend / "index.html").write_text("<html>isolated desktop</html>", encoding="utf-8")
    paths = RuntimePaths.windows(resources=resources, local_app_data=tmp_path / "用户")
    # Configure only this test process; neither the development DB nor model is used.
    monkeypatch.setattr("desktop.server.os.environ", dict(os.environ))
    monkeypatch.setattr("backend.app._try_build_retrieval_stack", lambda *args: False)
    try:
        configure_environment(paths, test_database_url, 18750)
        paths.ensure_data_dirs()
        app = attach_frontend(create_app(), frontend, port=18750)
        with TestClient(app, base_url="http://127.0.0.1:18750", client=("127.0.0.1", 12345)) as client:
            health = client.get("/api/health")
            assert health.status_code == 200 and health.json()["database"] == "connected"
            assert app.state.settings.upload_dir == paths.data / "uploads"
            assert app.state.settings.chroma_dir == paths.data / "chroma"
            assert not app.state.settings.capture_test_evidence
            model = client.get("/api/settings/model")
            assert model.status_code == 200
            assert model.json()["key_configured"] is False
            assert model.json()["csrf_token"]
            assert "isolated desktop" in client.get("/knowledge/math.calculus.limit.lhopital/lesson").text
            assert client.get("/api/missing").status_code == 404
            assert client.get("/api/health", headers={"Origin": "https://foreign.example"}).status_code == 403
        assert list(resources.rglob("*")) == [resources / "frontend", frontend, frontend / "index.html"]
    finally:
        get_settings.cache_clear()
