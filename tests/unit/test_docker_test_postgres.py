import json
import pytest
from scripts.docker_test_postgres import DockerTestPostgres


@pytest.mark.parametrize('station,port', [('daily', 65440), ('home1', 5433), ('home1', 8000), ('home1', 5173)])
def test_invalid_target_rejected(station, port, tmp_path):
    with pytest.raises(ValueError):
        DockerTestPostgres(station=station, port=port, audit=tmp_path)


def test_existing_container_never_reused(tmp_path, monkeypatch):
    manager = DockerTestPostgres(station='homeadaptertest', port=65440, audit=tmp_path)
    calls = []
    def command(*args, **kwargs):
        calls.append(args)
        return 'existing-id'
    monkeypatch.setattr(manager, '_cmd', command)
    with pytest.raises(RuntimeError, match='already_exists'):
        manager.start()
    assert len(calls) == 1
    assert calls[0][:2] == ('container', 'ls')


def test_stop_requires_identity_before_command(tmp_path, monkeypatch):
    manager = DockerTestPostgres(station='homeadaptertest', port=65440, audit=tmp_path)
    calls = []
    def identity(*args, **kwargs):
        raise RuntimeError('identity_unknown')
    monkeypatch.setattr(manager, '_assert_owned_resources', identity)
    monkeypatch.setattr(manager, '_cmd', lambda *args: calls.append(args))
    with pytest.raises(RuntimeError, match='identity_unknown'):
        manager.stop()
    assert calls == []


def test_connection_url_contains_only_owned_loopback_identity(tmp_path):
    from sqlalchemy.engine import make_url
    manager = DockerTestPostgres(station='homeadaptertest', port=65440, audit=tmp_path)
    url = make_url(manager.database_url)
    assert (url.host, url.port, url.username) == ('127.0.0.1', 65440, 'kaoyan_app')
    assert url.database == manager.test_database and url.database.endswith('_test')
    assert url.password != manager._passwords['kaoyan_admin']


def test_stop_owned_container_does_not_require_database_readiness(tmp_path, monkeypatch):
    manager = DockerTestPostgres(station='homeadaptertest', port=65440, audit=tmp_path)
    calls = []
    monkeypatch.setattr(manager, '_assert_owned_resources', lambda: {'id': manager._owned_identity})
    monkeypatch.setattr(manager, 'save_logs', lambda: None)
    monkeypatch.setattr(manager, '_cmd', lambda *args: calls.append(args) or '')
    manager._owned_identity = 'owned-container-id'

    manager.stop()

    assert calls == [('stop', '--time', '15', manager.name)]
