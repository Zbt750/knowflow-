import pytest

from scripts.prepare_e2e_learning import validate_test_target


@pytest.mark.parametrize("url,owner", [
    (None, "59241"),
    ("postgresql+psycopg://postgres@127.0.0.1:5433/kaoyan_test", "5433"),
    ("postgresql+psycopg://postgres@127.0.0.1:59241/kaoyan", "59241"),
    ("postgresql+psycopg://postgres@127.0.0.1:59241/fixture_test", "59242"),
    ("postgresql+psycopg://postgres@remote:59241/fixture_test", "59241"),
])
def test_e2e_target_rejects_missing_or_unowned_or_development_database(url, owner):
    with pytest.raises(ValueError):
        validate_test_target(url, owner)


def test_e2e_target_accepts_explicit_owned_loopback_test_database():
    url = "postgresql+psycopg://postgres@127.0.0.1:59241/fixture_test"
    assert validate_test_target(url, "59241") == url
