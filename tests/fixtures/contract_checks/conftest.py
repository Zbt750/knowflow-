import pytest
from sqlalchemy.engine import Engine

@pytest.fixture(autouse=True)
def prohibit_database_access(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Factory contracts are offline; do not connect to any database")
    monkeypatch.setattr(Engine,"connect",denied)
