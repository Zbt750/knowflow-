import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from backend.api.routes.settings import router
from backend.config import Settings
from backend.errors import register_error_handlers
from backend.services import model_settings_service
from backend.services.model_settings_service import ModelSettingsUpdate, load_local_settings


def settings(tmp_path, **kwargs):
    return Settings(_env_file=None, app_env=kwargs.pop('app_env', 'dev'),
        database_url='postgresql+psycopg://fake:fake@127.0.0.1/fake',
        model_settings_path=tmp_path/'config'/'model-settings.bin',
        llm_api_key=SecretStr('original-test-key'), llm_base_url='https://example.com/v1', llm_model='old-model', **kwargs)


def client_for(value, peer='127.0.0.1', host='http://127.0.0.1:8000'):
    app = FastAPI()
    app.state.settings = value
    register_error_handlers(app)
    app.include_router(router, prefix='/api')
    return TestClient(app, base_url=host, client=(peer, 12345))


def update(**kwargs):
    return dict(base_url='https://example.com/v1', model='new-model', max_output_tokens=4096, timeout_seconds=45, **kwargs)


def test_save_preserve_replace_clear_restart_and_no_key_echo(tmp_path):
    initial = settings(tmp_path)
    with client_for(initial) as client:
        response = client.get('/api/settings/model')
        assert response.headers['cache-control'] == 'no-store'
        token = response.json()['csrf_token']
        headers = {'X-Settings-Token': token, 'Origin': 'http://127.0.0.1:5173'}
        for body, expected in [(update(), 'original-test-key'), (update(api_key='replacement-test-key'), 'replacement-test-key'), (update(clear_key=True), None)]:
            result = client.put('/api/settings/model', json=body, headers=headers)
            assert result.status_code == 200
            assert 'original-test-key' not in result.text and 'replacement-test-key' not in result.text
            assert result.json()['key_configured'] is bool(expected)
            effective = client.app.state.settings
            assert effective.llm_model == 'new-model'
            assert effective.llm_max_output_tokens == 4096
            from backend.chat.service import provider_from_settings
            from backend.errors import AppError
            if expected:
                provider = provider_from_settings(effective)
                assert provider.model == 'new-model' and provider.max_tokens == 4096
                assert provider.api_key == expected
            else:
                with pytest.raises(AppError) as caught:
                    provider_from_settings(effective)
                assert caught.value.code == 'llm_not_configured'
            loaded = load_local_settings(initial)
            assert (loaded.llm_api_key.get_secret_value() if loaded.llm_api_key else None) == expected
            if os.name == 'nt':
                assert b'test-key' not in initial.model_settings_path.read_bytes()
            else:
                assert initial.model_settings_path.stat().st_mode & 0o077 == 0


@pytest.mark.parametrize('peer,host,headers', [
    ('10.0.0.9', 'http://127.0.0.1:8000', {}),
    ('127.0.0.1', 'http://attacker.example', {}),
    ('127.0.0.1', 'http://127.0.0.1:8000', {'origin': 'https://attacker.example'}),
    ('127.0.0.1', 'http://127.0.0.1:8000', {'x-forwarded-for': '10.0.0.9'}),
    ('127.0.0.1', 'http://127.0.0.1:8000', {'sec-fetch-site': 'cross-site'}),
])
def test_remote_rebinding_proxy_and_cross_site_are_denied(tmp_path, peer, host, headers):
    value = settings(tmp_path)
    with client_for(value, peer, host) as client:
        response = client.get('/api/settings/model', headers=headers)
        assert response.status_code == 403
        assert response.json()['error']['code'] == 'settings_local_only'
        assert 'original-test-key' not in response.text
    assert not value.model_settings_path.exists()


def test_production_denies_reads_and_writes(tmp_path):
    with client_for(settings(tmp_path, app_env='prod')) as client:
        assert client.get('/api/settings/model').status_code == 403
        assert client.put('/api/settings/model', json=update()).status_code == 403


@pytest.mark.parametrize('token', ['', 'wrong', 'é'])
def test_invalid_csrf_cannot_write(tmp_path, token):
    value = settings(tmp_path)
    with client_for(value) as client:
        client.get('/api/settings/model')
        # Header values are latin-1 on ASGI; bytes permit testing non-ASCII safely.
        result = client.put('/api/settings/model', json=update(), headers=[(b'x-settings-token', token.encode('utf-8'))])
        assert result.status_code == 403
        assert client.app.state.settings.llm_model == 'old-model'
    assert not value.model_settings_path.exists()


def test_storage_failure_does_not_apply_new_config(tmp_path, monkeypatch):
    from backend.errors import AppError
    with client_for(settings(tmp_path)) as client:
        token = client.get('/api/settings/model').json()['csrf_token']
        def fail(*args):
            raise AppError('settings_storage_failed')
        monkeypatch.setattr('backend.api.routes.settings.persist_settings', fail)
        assert client.put('/api/settings/model', json=update(), headers={'x-settings-token': token}).status_code == 503
        assert client.app.state.settings.llm_model == 'old-model'


def test_damaged_override_disables_key_but_preserves_app_availability(tmp_path):
    value = settings(tmp_path)
    value.model_settings_path.parent.mkdir()
    value.model_settings_path.write_bytes(b'damaged')
    loaded = load_local_settings(value)
    assert loaded.llm_api_key is None and loaded.local_model_settings_error
    with client_for(loaded) as client:
        assert client.get('/api/settings/model').json()['storage_warning']


def test_non_windows_never_writes_or_loads_plaintext_api_keys(monkeypatch):
    monkeypatch.setattr(model_settings_service.os, "name", "posix")
    plaintext = b'{"api_key":"secret-test-value","model":"test"}'
    with pytest.raises(OSError, match="secure local credential storage"):
        model_settings_service.encode_settings(plaintext)
    with pytest.raises(ValueError, match="plaintext model API key"):
        model_settings_service.decode_settings(b"LOCAL1\n" + plaintext)

    settings_only = b'{"api_key":null,"model":"test"}'
    encoded = model_settings_service.encode_settings(settings_only)
    assert model_settings_service.decode_settings(encoded) == settings_only


@pytest.mark.parametrize('fields', [
    {'base_url': 'http://public.example/v1'}, {'base_url': 'https://user:secret@example.com/v1'},
    {'base_url': 'https://example.com/v1?api_key=secret'}, {'base_url': 'https://example.com:bad/v1'},
    {'model': ' '}, {'max_output_tokens': 0}, {'timeout_seconds': 0},
])
def test_settings_validation(fields):
    body = update()
    body.update(fields)
    with pytest.raises(ValidationError):
        ModelSettingsUpdate.model_validate(body)
