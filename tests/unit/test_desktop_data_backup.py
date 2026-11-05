import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from desktop import backup
from desktop.postgres import DataDirectoryLock


@pytest.fixture
def cold_data(tmp_path, monkeypatch):
    data = tmp_path / 'KaoyanStudy'
    files = {
        'postgres/cluster/PG_VERSION': '18\n', 'postgres/cluster/base/1/123': 'synthetic-db',
        'config/postgres-credentials.bin': 'synthetic-encrypted-key',
        'config/model-settings.bin': 'synthetic-encrypted-model-key',
        'config/bootstrap.json': json.dumps({'format': 1, 'initialized': True, 'cluster_id': 'a' * 32}),
        'config/postgres-owner.json': json.dumps({'format': 1, 'major': 18, 'cluster_id': 'a' * 32,
            'root_hash': hashlib.sha256(str(data / 'postgres/cluster').encode()).hexdigest()}),
        'uploads/lecture.md': 'synthetic-private-material', 'chroma/index.bin': 'synthetic-vector',
        'models/weights.bin': 'excluded', 'logs/debug.log': 'excluded', 'backups/old.zip': 'excluded',
    }
    for name, text in files.items():
        path = data / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
    (data / 'postgres/cluster/pg_notify').mkdir()
    pg = tmp_path / 'pg'; pg.mkdir()
    (pg / ('pg_controldata.exe' if backup.os.name == 'nt' else 'pg_controldata')).touch()
    monkeypatch.setattr(backup, '_private_file', lambda _: None)
    monkeypatch.setattr('desktop.postgres._run', lambda *a, **k: SimpleNamespace(returncode=0,
        stdout=b'Database cluster state:               shut down\n'))
    return data, pg, tmp_path / 'cold.zip'


def test_roundtrip_preserves_owned_private_data_and_excludes_caches(cold_data):
    data, pg, destination = cold_data
    result = backup.create_backup(data, destination, pg_bin=pg)
    assert result['encrypted'] is False
    manifest = backup.inspect_backup(destination)
    names = {row['path'] for row in manifest['files']}
    assert 'uploads/lecture.md' in names and 'chroma/index.bin' in names
    assert not any(name.startswith(('models/', 'logs/', 'backups/')) for name in names)
    data.rename(data.with_name('retained-original'))
    assert backup.restore_backup(destination, data)['models_need_reinstall']
    assert (data / 'uploads/lecture.md').read_text() == 'synthetic-private-material'
    assert (data / 'postgres/cluster/pg_notify').is_dir()
    assert backup._owned(data)['cluster_id'] == 'a' * 32


def test_no_overwrite_existing_archive_or_user_data(cold_data):
    data, pg, destination = cold_data
    backup.create_backup(data, destination, pg_bin=pg)
    with pytest.raises(ValueError, match='destination_invalid'):
        backup.create_backup(data, destination, pg_bin=pg)
    with pytest.raises(ValueError, match='target_exists'):
        backup.restore_backup(destination, data)
    assert (data / 'uploads/lecture.md').exists()


def test_backup_does_not_adopt_developer_or_running_database(cold_data):
    data, pg, destination = cold_data
    (data / 'postgres/cluster/postmaster.pid').write_text('synthetic')
    with pytest.raises(ValueError, match='cluster_running'):
        backup.create_backup(data, destination, pg_bin=pg)
    assert not destination.exists()
    assert not list(destination.parent.glob('*.part'))


def test_clean_shutdown_required_even_if_pid_absent(cold_data, monkeypatch):
    data, pg, destination = cold_data
    monkeypatch.setattr('desktop.postgres._run', lambda *a, **k: SimpleNamespace(returncode=0,
        stdout=b'Database cluster state:               in production\n'))
    with pytest.raises(ValueError, match='clean_shutdown_required'):
        backup.create_backup(data, destination, pg_bin=pg)


def test_lock_prevents_backup_while_app_owns_data(cold_data):
    data, pg, destination = cold_data
    lock = DataDirectoryLock(data); lock.acquire()
    try:
        with pytest.raises(ValueError, match='data_in_use'):
            backup.create_backup(data, destination, pg_bin=pg)
    finally:
        lock.release()


@pytest.mark.parametrize('name', ['../escape', 'uploads/../../escape', 'uploads/x:stream',
                                  'uploads/x\\escape', 'uploads/x.', 'config/private.env',
                                  'postgres/cluster/postmaster.pid'])
def test_archive_names_are_allowlisted(name):
    with pytest.raises(ValueError): backup._name(name)


def test_corruption_never_restores_partial_user_data(cold_data):
    data, pg, destination = cold_data
    backup.create_backup(data, destination, pg_bin=pg)
    with zipfile.ZipFile(destination) as original:
        content = {name: original.read(name) for name in original.namelist()}
    content['uploads/lecture.md'] = b'altered'
    broken = destination.with_name('corrupted.zip')
    with zipfile.ZipFile(broken, 'w') as archive:
        for name, value in content.items(): archive.writestr(name, value)
    data.rename(data.with_name('retained-original'))
    with pytest.raises(ValueError): backup.restore_backup(broken, data)
    assert not data.exists()
    assert not list(data.parent.glob('.kaoyan-restore-*'))


def test_restore_requires_original_absolute_path(cold_data):
    data, pg, destination = cold_data
    backup.create_backup(data, destination, pg_bin=pg)
    with pytest.raises(ValueError, match='original_path'):
        backup.restore_backup(destination, data.with_name('other-user-data'))


def test_acl_failure_does_not_publish_private_archive(cold_data, monkeypatch):
    data, pg, destination = cold_data
    def refuse(_): raise ValueError('desktop_credentials_acl_failed')
    monkeypatch.setattr(backup, '_private_file', refuse)
    with pytest.raises(ValueError): backup.create_backup(data, destination, pg_bin=pg)
    assert not destination.exists() and not list(destination.parent.glob('*.part'))
