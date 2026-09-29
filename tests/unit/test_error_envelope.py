import json

import pytest
from fastapi import FastAPI, HTTPException, Query
from fastapi.testclient import TestClient
from pydantic import BaseModel

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
