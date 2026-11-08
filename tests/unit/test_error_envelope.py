import json
import asyncio
import traceback
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException, Query
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.exc import OperationalError
from backend.errors import unexpected_error_handler

from backend.errors import AppError, register_error_handlers


@pytest.fixture
def client():
    app = FastAPI()
    register_error_handlers(app)

    @app.get('/limited')
    def limited(limit: int = Query(ge=1, le=100)):
        return limit

    class Body(BaseModel):
        count: int

    @app.post('/body')
    def body(value: Body):
        return value

    @app.get('/crash')
    def crash():
        raise RuntimeError('SECRET-PASSWORD-DO-NOT-RETURN')

    @app.get('/business')
    def business():
        raise AppError('material_not_found')

    @app.get('/http')
    def http():
        raise HTTPException(403, detail='SECRET-PASSWORD-DO-NOT-RETURN')

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.mark.parametrize('method,path,status,code', [
    ('get', '/unknown', 404, 'not_found'), ('post', '/limited', 405, 'method_not_allowed'),
    ('get', '/limited?limit=0', 422, 'validation_failed'),
    ('get', '/limited?limit=abc', 422, 'validation_failed'),
    ('get', '/limited', 422, 'validation_failed'),
    ('get', '/business', 404, 'material_not_found'),
    ('get', '/http', 403, 'forbidden'), ('get', '/crash', 500, 'internal_error'),
])
def test_all_errors_use_safe_envelope(client, method, path, status, code):
    result = getattr(client, method)(path)
    assert result.status_code == status
    assert result.json()['error']['code'] == code
    assert 'detail' not in result.json()
    assert 'SECRET-PASSWORD' not in result.text
    if status == 405:
        assert 'GET' in result.headers['allow']


def test_validation_identifies_rule_without_echoing_user_input(client):
    result = client.get('/limited?limit=0')
    assert result.json()['error']['details'] == [{'field': 'query.limit', 'code': 'greater_than_equal', 'message': '应大于或等于 1'}]
    result = client.post('/body', json={'count': 'SECRET-PASSWORD-DO-NOT-RETURN'})
    assert result.status_code == 422
    assert 'SECRET-PASSWORD' not in result.text
    assert result.json()['error']['details'][0]['field'] == 'body.count'


def test_invalid_json_does_not_echo_raw_body(client):
    result = client.post('/body', content='SECRET-PASSWORD-invalid-json', headers={'content-type': 'application/json'})
    assert result.status_code == 422
    assert 'SECRET-PASSWORD' not in result.text


def test_unexpected_error_logs_traceback_but_keeps_client_response_safe():
    try:
        raise RuntimeError('SECRET-PASSWORD-DO-NOT-RETURN')
    except RuntimeError as exc:
        with patch('backend.errors.logger.error') as log_error:
            response = asyncio.run(unexpected_error_handler(None, exc))

    assert response.status_code == 500
    payload = json.loads(response.body)
    assert payload['error']['code'] == 'internal_error'
    assert 'SECRET-PASSWORD' not in response.body.decode()
    exc_info = log_error.call_args.kwargs['exc_info']
    assert exc_info[0] is RuntimeError
    assert 'SECRET-PASSWORD-DO-NOT-RETURN' in ''.join(traceback.format_exception(*exc_info))


def test_database_disconnect_is_retryable_503_and_logs_traceback():
    try:
        raise OperationalError('SELECT 1', {}, OSError('connection refused'))
    except OperationalError as exc:
        with patch('backend.errors.logger.error') as log_error:
            response = asyncio.run(unexpected_error_handler(None, exc))

    assert response.status_code == 503
    assert response.headers['Retry-After'] == '2'
    payload = json.loads(response.body)
    assert payload['error']['code'] == 'database_unavailable'
    assert 'connection refused' not in response.body.decode()
    assert log_error.call_args.kwargs['exc_info'][0] is OperationalError
