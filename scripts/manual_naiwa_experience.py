"""Persistent, offline manual environment. Reuses an existing owned test cluster.

No initdb, migrations, seed, grants, test-only routes, or paid transports.
The normal application routers/services persist user actions in the test DB.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
HOME = ROOT / 'storage/manual-experience/naiwa-offline'
PREVIOUS = ROOT / 'storage/quality-audits/blind-user-20261019-v2'
API_PORT, WEB_PORT = 8188, 5188
MANIFEST = HOME / 'runtime.json'


def save(name, data):
    HOME.mkdir(parents=True, exist_ok=True)
    target = HOME / name
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    temporary.replace(target)


def available(port):
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', port))


def manager():
    from desktop.postgres import ManagedPostgres
    from desktop.runtime_paths import RuntimePaths
    runtime = json.loads((PREVIOUS / 'runtime.json').read_text(encoding='utf-8'))
    directory = Path(runtime['data_path']).resolve()
    assert directory.is_relative_to(ROOT / 'tmp/managed-test-clusters')
    assert runtime['database'] == 'kaoyan_blind_test' and runtime['pg_port'] > 18000
    pg = ManagedPostgres(RuntimePaths.windows(resources=ROOT / 'backend', local_app_data=directory),
                         Path('C:/Program Files/PostgreSQL/18/bin'), port=runtime['pg_port'])
    assert (pg.cluster / 'PG_VERSION').read_text(encoding='ascii').strip() == '18'
    assert pg.marker.is_file() and pg.credentials.is_file()
    pg.preflight()
    pg._load_owner()
    pg._load_passwords()
    return pg


def offline_guard(pg_port):
    """Allow only the owned PostgreSQL socket, regardless of later UI settings."""
    def audit(event, args):
        if event != 'socket.connect' or len(args) < 2:
            return
        address = args[1]
        if not (isinstance(address, tuple) and len(address) >= 2
                and address[0] in {'127.0.0.1', '::1'} and address[1] == pg_port):
            with (HOME / 'blocked-network.jsonl').open('a', encoding='utf-8') as log:
                # No URLs, credentials, payloads, or model prompts.
                log.write(json.dumps({'event': 'blocked_outbound_socket', 'time': time.time()}) + '\n')
            raise RuntimeError('manual_offline_environment_network_blocked')
    sys.addaudithook(audit)


class FixedProvider:
    """Clearly limited deterministic examples, not an intelligent model."""
    simulation = True
    def __init__(self, **kwargs):
        self.model = 'FIXED-OFFLINE-NO-PAID-MODEL'
        self.max_tokens = 4000
        self.retry_max_tokens = 4000
        self.timeout = 30.0
        self.structured_generation = kwargs.get('structured_generation', False)
        self.concept_without_thinking = True

    def _token_budget(self, attempt):
        return self.max_tokens

    def classify_retrieval_intent(self, question):
        return None

    def complete(self, messages, *, attempt=1):
        if self.structured_generation:
            request = json.loads(messages[-1]['content'])
            save('last-fixed-generation-request.json', {'mode': self.model, 'request': request})
            from backend.errors import AppError
            node = request.get('node') or {}
            if not any(s in node.get('name', '') + node.get('code', '') for s in ['级数', 'series']):
                raise AppError('generation_failed', detail='固定体验Provider仅内置幂级数样例，不会为其他知识点伪造题目。', retryable=False)
            kind = request['question_type']
            formula = r'\frac{x(1+x)}{(1-x)^3}'
            if kind not in {'calculation', 'single_choice', 'fill_blank'}:
                raise AppError('generation_failed', detail='固定体验样例仅支持计算、单选或填空。', retryable=False)
            output = {
                'stem': r'【固定体验样题】当 $|x|<1$ 时，求 $\sum_{n=1}^{\infty}n^2x^n$ 的和，并说明逐项求导的适用范围。',
                'question_type': kind,
                'options': {'A': '$' + formula + '$', 'B': r'$\frac{x}{(1-x)^2}$',
                            'C': r'$\frac{x}{1-x}$', 'D': r'$\frac{x(1-x)}{(1+x)^3}$'} if kind == 'single_choice' else None,
                'correct_answer': 'A' if kind == 'single_choice' else '$' + formula + '$',
                'final_value': 'x(1+x)/(1-x)^3',
                'explanation': r'固定Provider示例，非真实AI回答。几何级数在收敛区间内部可逐项求导。先得 $\sum nx^n=x/(1-x)^2$，再次求导后乘以 $x$ 得 $\sum n^2x^n=x(1+x)/(1-x)^3$，上述操作适用于 $|x|<1$。',
                'steps': [],
                'difficulty_assessment': {'estimated_level': 'hard', 'relative_change': 'harder',
                    'reason': '固定样例：相对nx^n求和增加一次逐项求导及适用范围说明；不是模型实测难度。',
                    'mechanisms': ['reasoning_steps', 'method_combination']},
            }
            # Do not manufacture alternative examples merely to evade duplicate checks.
            return json.dumps(output, ensure_ascii=False), None
        import re
        user = next((str(m.get('content', '')) for m in reversed(messages) if m.get('role') == 'user'), '')
        text = '\n'.join(str(m.get('content', '')) for m in messages)
        labels = re.findall(r'\[C\d+\]', text)
        prefix = '**固定 Provider 体验模式：以下是预设教学样例，不是真实AI推理。**\n\n'
        if labels:
            # Only a label present in the real retrieval context can be echoed;
            # no invented material titles or fabricated excerpts.
            return prefix + '本轮资料由实际检索栈提供。固定回答仅用于检查引用显示与历史保存；请展开引用阅读原文，不应据此判断资料问答准确率。' + labels[0], None
        if not re.search(r'幂级数|逐项求导|sum.*n.*x', user, re.I):
            return ('固定 Provider 离线体验模式：当前没有与该问题匹配的预设回答，不能验证这个问题的知识讲解质量。'
                '请明确知识点以读取现有系统讲义；讲义缺失时需要另行授权的真实模型测试。没有用无关教学样例替代回答。'), None
        answer = (r'以幂级数为例，在收敛区间内部可以逐项求导。由 $\sum_{n=0}^{\infty}x^n=\frac{1}{1-x}$，'
                  r'求导并乘以 $x$ 得到：\[\sum_{n=1}^{\infty}nx^n=\frac{x}{(1-x)^2},\quad |x|<1.\]'
                  '\n\n积分是反方向的操作；端点需要单独检查，不能直接沿用开区间结论。'
                  '\n\n你可以继续追问以体验多轮消息、刷新恢复和公式排版，但固定模式不会真正理解任意问题或自动判断你的答案。')
        return prefix + answer, None

    async def stream(self, messages, *, attempt=1):
        answer, _ = self.complete(messages, attempt=attempt)
        for offset in range(0, len(answer), 20):
            yield answer[offset:offset + 20]

    def tool_turn(self, messages, tools, *, timeout):
        return {'message': {'content': json.dumps({'message': '固定Provider体验模式：可以检查建议显示和历史保存，但本模式不推断真实学习安排，不创建计划。',
                'needs_clarification': True}, ensure_ascii=False)}}


def app():
    pg_port = int(os.environ['KAOYAN_OWNED_TEST_PORT'])
    assert os.environ['APP_ENV'] == 'test' and pg_port != 5433
    offline_guard(pg_port)
    from backend.config import get_settings
    get_settings.cache_clear()
    from sqlalchemy.engine import make_url
    settings = get_settings()
    u = make_url(str(settings.active_database_url))
    assert (u.host, u.port, u.database) == ('127.0.0.1', pg_port, 'kaoyan_blind_test')
    from backend.chat import service
    service.Provider = FixedProvider
    from backend.app import create_app
    application = create_app()
    application.state.personal_generation_provider = FixedProvider(structured_generation=True)
    # Normal production routers only. No __test/__zero/fake business endpoints.
    @application.middleware('http')
    async def label_mode(request, call_next):
        response = await call_next(request)
        response.headers['X-Naiwa-Experience'] = 'fixed-provider-offline-persistent'
        response.headers['X-Naiwa-Real-Model-Requests'] = '0'
        return response
    return application


def supervise():
    import httpx
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from desktop.postgres import _run
    pg = manager()
    for port in [pg.port, API_PORT, WEB_PORT]:
        available(port)
    assert not (pg.cluster / 'postmaster.pid').exists(), 'owned cluster already running; refusing adoption'
    pg.lock.acquire()
    children, handles = [], []
    try:
        started = int(time.time())
        result = _run([pg.binary('pg_ctl'), '-D', str(pg.cluster), '-l', str(HOME / 'postgres.log'),
                       '-o', f'-p {pg.port} -c listen_addresses=127.0.0.1', '-w', '-t', '30', 'start'], capture=False)
        identity = pg._identity()
        assert result.returncode == 0 and identity and identity[1] >= started - 1
        pg._owned_identity = identity
        url = make_url(pg.database_url).set(database='kaoyan_blind_test')
        engine = create_engine(url)
        with engine.connect() as c:
            c.execute(text('SET TRANSACTION READ ONLY'))
            db_identity = dict(c.execute(text("SELECT current_database() db,current_user role,current_setting('port') port")).one()._mapping)
            counts = {t: c.scalar(text('SELECT count(*) FROM ' + t)) for t in
                      ['knowledge_points', 'questions', 'question_versions', 'daily_plans', 'practice_items', 'chat_sessions', 'materials']}
            revision = c.scalar(text('SELECT version_num FROM alembic_version'))
            c.rollback()
        engine.dispose()
        assert counts['knowledge_points'] and counts['questions'], 'existing data required; no seed allowed'
        env = {**os.environ, 'APP_ENV': 'test', 'DATABASE_URL': url.render_as_string(hide_password=False),
               'TEST_DATABASE_URL': url.render_as_string(hide_password=False), 'KAOYAN_OWNED_TEST_PORT': str(pg.port),
               'LLM_API_KEY': 'offline-placeholder-not-a-secret', 'LLM_BASE_URL': 'http://127.0.0.1:9',
               'LLM_MODEL': 'FIXED-OFFLINE-NO-PAID-MODEL', 'MODEL_SETTINGS_PATH': str(HOME / 'model-settings.bin'),
               'UPLOAD_DIR': str(PREVIOUS / 'uploads'), 'CHROMA_DIR': str(PREVIOUS / 'chroma'),
               'MODEL_CACHE_DIR': str(ROOT / 'storage/models'), 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
               'ANONYMIZED_TELEMETRY': 'False', 'DO_NOT_TRACK': '1', 'OTEL_SDK_DISABLED': 'true',
               'ALLOWED_WEB_ORIGINS': json.dumps([f'http://127.0.0.1:{WEB_PORT}']),
               'VITE_API_PROXY_TARGET': f'http://127.0.0.1:{API_PORT}', 'PYTHONIOENCODING': 'utf-8'}
        commands = [[sys.executable, '-m', 'uvicorn', 'scripts.manual_naiwa_experience:app', '--factory', '--host', '127.0.0.1', '--port', str(API_PORT)],
                    ['node', 'node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', str(WEB_PORT), '--strictPort']]
        for name, command, cwd in zip(['backend', 'frontend'], commands, [ROOT, ROOT / 'frontend']):
            handle = (HOME / (name + '.log')).open('a', encoding='utf-8'); handles.append(handle)
            children.append(subprocess.Popen(command, cwd=cwd, env=env, stdout=handle, stderr=subprocess.STDOUT,
                                             creationflags=subprocess.CREATE_NO_WINDOW))
        runtime = {'status': 'starting', 'workspace': str(ROOT), 'supervisor_pid': os.getpid(),
                   'backend_pid': children[0].pid, 'frontend_pid': children[1].pid, 'postgres_pid': identity[0],
                   'database': db_identity, 'cluster': str(pg.cluster), 'cluster_id': pg.owner['cluster_id'],
                   'api_url': f'http://127.0.0.1:{API_PORT}', 'frontend_url': f'http://127.0.0.1:{WEB_PORT}',
                   'python': sys.executable, 'commands': commands, 'schema_revision': revision, 'existing_counts': counts,
                   'provider': 'fixed, no external model network; illustrative responses only', 'real_model_requests': 0,
                   'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   'data_retained_on_stop': True, 'migrations_seed_grants': False, 'started_at': time.time()}
        save('runtime.json', runtime)
        with httpx.Client(trust_env=False, timeout=3) as client:
            for _ in range(100):
                assert all(p.poll() is None for p in children), 'experience child exited; inspect logs'
                try:
                    r = client.get(runtime['frontend_url'] + '/api/health')
                    if r.status_code == 200 and r.json().get('database') == 'connected':
                        runtime['health'] = r.json(); break
                except httpx.HTTPError:
                    pass
                time.sleep(1)
            else:
                raise RuntimeError('experience startup timeout')
        runtime['status'] = 'running'; save('runtime.json', runtime)
        while not (HOME / 'stop.request').exists():
            if any(p.poll() is not None for p in children):
                raise RuntimeError('experience service stopped unexpectedly')
            time.sleep(1)
    except BaseException as exc:
        save('last-error.json', {'type': type(exc).__name__, 'message': str(exc)[:180]})
        raise
    finally:
        for process in reversed(children):
            if process.poll() is None:
                process.terminate(); process.wait(timeout=25)
        for handle in handles:
            handle.close()
        pg.stop()
        if MANIFEST.exists():
            state = json.loads(MANIFEST.read_text(encoding='utf-8')); state['status'] = 'stopped'; save('runtime.json', state)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('action', choices=['start', 'stop', 'status', 'serve'])
    action = parser.parse_args().action
    HOME.mkdir(parents=True, exist_ok=True)
    if action == 'serve':
        return supervise()
    if action == 'stop':
        (HOME / 'stop.request').touch()
        print('Stop requested only for this experience supervisor. Database files are retained.')
        return
    if action == 'status':
        print(MANIFEST.read_text(encoding='utf-8') if MANIFEST.exists() else 'Not started')
        return
    import httpx
    try:
        r = httpx.get(f'http://127.0.0.1:{API_PORT}/api/health', timeout=2, trust_env=False)
        if r.headers.get('X-Naiwa-Experience') == 'fixed-provider-offline-persistent':
            print(f'Already running: http://127.0.0.1:{WEB_PORT}'); return
    except httpx.HTTPError:
        pass
    for port in [manager().port, API_PORT, WEB_PORT]:
        available(port)
    (HOME / 'stop.request').unlink(missing_ok=True)
    with (HOME / 'supervisor.log').open('a', encoding='utf-8') as log:
        p = subprocess.Popen([sys.executable, str(Path(__file__)), 'serve'], cwd=ROOT, stdout=log,
                             stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    print(f'Starting persistent offline environment; supervisor PID {p.pid}; http://127.0.0.1:{WEB_PORT}')


if __name__ == '__main__':
    main()
