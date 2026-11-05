"""Browser bootstrap for the retained isolated audit runtime; never a business API."""
import hashlib
import hmac
import json
import secrets
import threading
import time
import re
from http.cookies import SimpleCookie
from urllib.parse import parse_qs

from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

PATH = '/api/__naiwa-edge/session'
COOKIE = 'naiwa_edge_session'


class EdgeAuthorization:
    def __init__(self, app, *, run_dir, epoch, scene, database, port, environment,
                 clock=time.time):
        if (environment, database, port) != ('test', 'naiwa_experience_test', 63044):
            raise RuntimeError('edge_auth_isolated_environment_required')
        self.app, self.run, self.epoch, self.scene = app, run_dir, epoch, scene
        self.clock, self.lock = clock, threading.RLock()
        self.sessions = {}
        self.used = False
        self.deadline = clock() + 600
        code = secrets.token_urlsafe(32)
        self.digest = hashlib.sha256(code.encode()).digest()
        target = run_dir / f'edge-bootstrap-epoch-{epoch}.txt'
        with target.open('x', encoding='ascii') as handle:
            handle.write(code)

    def valid(self, headers):
        cookie = SimpleCookie()
        try:
            cookie.load(headers.get('cookie', ''))
        except Exception:
            return None
        token = cookie.get(COOKIE)
        if not token:
            return None
        with self.lock:
            entry = self.sessions.get(token.value)
            if not entry or entry['expires'] <= self.clock():
                return None
            active = json.loads((self.run / 'active-source-hashes.json').read_text())
            if active['epoch'] != self.epoch:
                return None
            control = json.loads((self.run / 'edge-window.json').read_text())
            if (not control.get('enabled') or control.get('epoch') != self.epoch
                    or control.get('scene') != self.scene
                    or control.get('expires_at', 0) <= self.clock()):
                return None
            return entry

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        method, path = scope['method'], scope['path']
        headers = {k.decode().lower(): v.decode() for k, v in scope['headers']}
        allowed_origins = {'http://127.0.0.1:63046'}
        peer = scope.get('client', ('',))[0]
        local = peer in {'127.0.0.1', '::1', 'testclient'}
        if path == PATH:
            if not local:
                return await JSONResponse({'error': 'edge_local_only'}, 403)(scope, receive, send)
            if method == 'GET':
                return await HTMLResponse('<!doctype html><meta charset="utf-8"><h1>奶蛙隔离验收连接</h1>'
                    '<p>仅绑定本轮浏览器会话，不开启模型出口。</p>'
                    '<form method="post"><label>一次性授权<input name="code" type="password" '
                    'autocomplete="off" maxlength="128"></label><button>连接隔离会话</button></form>',
                    headers={'Cache-Control': 'no-store', 'Content-Security-Policy':
                             "default-src 'none'; form-action 'self'; frame-ancestors 'none'"})(scope, receive, send)
            if method != 'POST' or headers.get('origin') not in allowed_origins:
                return await JSONResponse({'error': 'edge_origin_rejected'}, 403)(scope, receive, send)
            body = b''
            while True:
                message = await receive()
                body += message.get('body', b'')
                if len(body) > 512:
                    return await JSONResponse({'error': 'edge_body_rejected'}, 413)(scope, receive, send)
                if not message.get('more_body'):
                    break
            code = parse_qs(body.decode()).get('code', [''])[0]
            with self.lock:
                if (self.used or self.deadline <= self.clock()
                        or not hmac.compare_digest(hashlib.sha256(code.encode()).digest(), self.digest)):
                    return await JSONResponse({'error': 'edge_bootstrap_rejected'}, 403)(scope, receive, send)
                self.used = True
                token = secrets.token_urlsafe(32)
                self.sessions[token] = {'expires': self.clock() + 1800, 'ids': set()}
            response = RedirectResponse('/chat', 303, headers={'Cache-Control': 'no-store'})
            response.set_cookie(COOKIE, token, max_age=1800, httponly=True, samesite='strict', path='/')
            return await response(scope, receive, send)
        if method in {'GET', 'HEAD', 'OPTIONS'}:
            return await self.app(scope, receive, send)
        entry = self.valid(headers) if local else None
        if not entry or headers.get('origin') not in allowed_origins:
            return await JSONResponse({'error': 'edge_write_session_rejected'}, 403)(scope, receive, send)
        # Only this browser's newly created chat sessions may reach the legacy
        # resource checker. Old registry entries do not grant this browser access.
        create = method == 'POST' and path == '/api/chat/sessions'
        parts = path.split('/')
        chat = len(parts) == 6 and parts[1:4] == ['api', 'chat', 'sessions']
        decline = re.fullmatch(r'/api/practice-requests/([0-9a-f-]{36})/decline', path)
        owned_decline = False
        if method == 'POST' and decline:
            from scripts.naiwa_agent_full_v2_20261021 import _practice_request_owned
            factory = getattr(self.app, 'audit_session_factory', None)
            if factory is not None:
                owned_decline = _practice_request_owned(factory(), decline[1], {'sessions': [
                    {'session_id': sid, 'scene_created': self.scene, 'purpose': 'qa'}
                    for sid in entry['ids']]}, self.scene)
        if not create and not owned_decline and (not chat or parts[4] not in entry['ids']):
            return await JSONResponse({'error': 'edge_resource_not_bound'}, 403)(scope, receive, send)
        nonce = (self.run / 'browser-nonce.txt').read_text().strip()
        forwarded = dict(scope)
        forwarded['headers'] = [(k, v) for k, v in scope['headers']
                                if k.lower() not in {b'x-naiwa-v2-scene', b'x-naiwa-v2-nonce'}]
        forwarded['headers'] += [(b'x-naiwa-v2-scene', self.scene.encode()),
                                 (b'x-naiwa-v2-nonce', nonce.encode())]
        chunks, status = [], None
        async def capture(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
            if create and message['type'] == 'http.response.body':
                chunks.append(message.get('body', b''))
                if not message.get('more_body') and status and 200 <= status < 300:
                    payload = json.loads(b''.join(chunks))
                    if payload.get('session_id'):
                        with self.lock:
                            entry['ids'].add(str(payload['session_id']))
            await send(message)
        return await self.app(forwarded, receive, capture)
