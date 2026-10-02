"""Retired self-report graduation demo must refuse before opening a database."""
import pytest
from scripts import graduate_demo


@pytest.mark.parametrize("action", ["first", "retest"])
def test_retired_demo_refuses_before_database_access(action, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["graduate_demo.py", action])
    def forbidden(*args, **kwargs):
        pytest.fail("retired demo must not open a database")
    monkeypatch.setattr(graduate_demo, "create_db_engine", forbidden)
    with pytest.raises(SystemExit) as error:
        graduate_demo.main()
    assert error.value.code == 2
    assert "不会修改学习数据" in capsys.readouterr().err
