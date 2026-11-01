import pytest

from tests.conftest import _validate_isolated_test_database


def test_explicit_owned_high_port_loopback_test_database_allowed():
    url = "postgresql+psycopg://user:password@127.0.0.1:18432/kaoyan_test"
    assert _validate_isolated_test_database(url, "18432") == url


@pytest.mark.parametrize(("url", "port"), [
    (None, "18432"),
    ("postgresql+psycopg://user:password@127.0.0.1:5433/kaoyan_test", "5433"),
    ("postgresql+psycopg://user:password@127.0.0.1:18432/kaoyan_test", "18433"),
    ("postgresql+psycopg://user:password@db.example:18432/kaoyan_test", "18432"),
    ("postgresql+psycopg://user:password@127.0.0.1:18432/kaoyan", "18432"),
    ("sqlite:///./tests.db", "18432"),
])
def test_unsafe_test_database_config_is_refused(url, port):
    with pytest.raises(RuntimeError):
        _validate_isolated_test_database(url, port)
