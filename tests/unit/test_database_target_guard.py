import sys

import pytest

from scripts import check_database_target


@pytest.mark.parametrize("test_url", [
    "postgresql+psycopg://kaoyan_app:secret@127.0.0.1:5433/kaoyan_test",
    "postgresql+psycopg://kaoyan_app:secret@example.com:18761/kaoyan_test",
    "postgresql+psycopg://kaoyan_app:secret@127.0.0.1:18760/kaoyan_test",
    "postgresql+psycopg://kaoyan_app:secret@127.0.0.1:18761/kaoyan",
])
def test_test_mode_rejects_unsafe_target_before_connect(monkeypatch, test_url):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("TEST_DATABASE_URL", test_url)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://ignored:secret@127.0.0.1:5432/kaoyan")
    monkeypatch.setenv("KAOYAN_OWNED_TEST_PORT", "18761")
    monkeypatch.setattr(sys, "argv", ["check_database_target.py"])
    with pytest.raises(SystemExit):
        check_database_target.main()


def test_test_mode_never_falls_back_to_database_url(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://kaoyan:secret@127.0.0.1:5432/kaoyan")
    monkeypatch.setenv("KAOYAN_OWNED_TEST_PORT", "18761")
    monkeypatch.setattr(sys, "argv", ["check_database_target.py"])
    with pytest.raises(SystemExit, match="缺少 TEST_DATABASE_URL"):
        check_database_target.main()
