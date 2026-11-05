import json
import pytest
import httpx
from scripts.naiwa_edge_authorization import EdgeAuthorization, PATH


@pytest.mark.asyncio
async def test_bootstrap_scope_expiry_epoch_and_replay(tmp_path):
    now = [1000.0]
    (tmp_path/'active-source-hashes.json').write_text(json.dumps({'epoch': 8}))
    window = {'enabled': True, 'epoch': 8, 'scene': 'A', 'expires_at': 5000}
    (tmp_path/'edge-window.json').write_text(json.dumps(window))
    (tmp_path/'browser-nonce.txt').write_text('server-only-value')
    seen = []
    async def app(scope, receive, send):
        seen.append(scope)
        await send({'type':'http.response.start','status':200,'headers':[]})
        await send({'type':'http.response.body','body':b'{"session_id":"owned"}'})
    auth = EdgeAuthorization(app,run_dir=tmp_path,epoch=8,scene='A',
        database='naiwa_experience_test',port=63044,environment='test',clock=lambda:now[0])
    code=(tmp_path/'edge-bootstrap-epoch-8.txt').read_text()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=auth),base_url='http://127.0.0.1:63046') as c:
        origin={'origin':'http://127.0.0.1:63046'}
        assert (await c.post('/api/chat/sessions',headers=origin)).status_code==403
        assert not seen
        assert (await c.post(PATH,data={'code':code},headers={'origin':'https://evil.invalid'})).status_code==403
        response=await c.post(PATH,data={'code':code},headers=origin)
        assert response.status_code==303
        assert 'HttpOnly' in response.headers['set-cookie'] and 'SameSite=strict' in response.headers['set-cookie']
        assert (await c.post(PATH,data={'code':code},headers=origin)).status_code==403
        assert (await c.post('/api/chat/sessions',headers=origin)).status_code==200
        headers=dict(seen[-1]['headers'])
        assert headers[b'x-naiwa-v2-nonce']==b'server-only-value'
        assert (await c.post('/api/chat/sessions/other/answers:stream',headers=origin)).status_code==403
        assert (await c.post('/api/chat/sessions/owned/answers:stream',headers=origin)).status_code==200
        assert (await c.post('/api/plans/today/generate',headers=origin)).status_code==403
        window['scene']='B'; (tmp_path/'edge-window.json').write_text(json.dumps(window))
        assert (await c.post('/api/chat/sessions',headers=origin)).status_code==403
        window['scene']='A'; (tmp_path/'edge-window.json').write_text(json.dumps(window))
        (tmp_path/'active-source-hashes.json').write_text(json.dumps({'epoch':9}))
        assert (await c.post('/api/chat/sessions',headers=origin)).status_code==403
        (tmp_path/'active-source-hashes.json').write_text(json.dumps({'epoch':8}))
        now[0]=3000
        assert (await c.post('/api/chat/sessions',headers=origin)).status_code==403
        # Safe GET reaches the underlying app without authenticating or mutating a DB.
        assert (await c.get('/api/health')).status_code==200


def test_production_rejected(tmp_path):
    with pytest.raises(RuntimeError,match='isolated_environment'):
        EdgeAuthorization(None,run_dir=tmp_path,epoch=1,scene='A',database='kaoyan',port=5433,environment='prod')
