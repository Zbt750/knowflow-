"""One owned-PG, real-Provider run. Never connects to the development DB.

The HTTP meter surrounds the real transport (including classifiers), not a mock.
Restarting this run after any ledger exists is deliberately forbidden.
"""
from pathlib import Path
import json
import os
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'storage/quality-audits/blind-user-20261019-v2'


def write(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def app():
    from backend.config import get_settings
    from backend.services.model_settings_service import load_local_settings
    from backend.chat.service import Provider
    from backend.errors import AppError
    from scripts.phase5_eval_meter import Meter
    from backend.app import create_app
    from fastapi.responses import JSONResponse
    s = load_local_settings(get_settings())
    assert s.app_env == 'test' and str(s.active_database_url).split('@')[-1].endswith('/kaoyan_blind_test')
    assert s.llm_model == 'deepseek-flash' and s.llm_base_url.rstrip('/') == 'https://api.deepseek.com'
    previous = None
    if (OUT / 'provider-ledger.json').exists():
        assert os.environ.get('BLIND_RESUME_SAME_RUN')=='1', 'never reset a paid ledger'
        previous=json.loads((OUT/'provider-ledger.json').read_text(encoding='utf-8'))
        assert previous['limits']['max_requests']==10 and all(r.get('finished') for r in previous['requests'])
    meter = Meter(OUT, max_requests=10, max_input_tokens=150000, max_output_tokens=80000,
                  stop_cny='0.90', input_cny_per_million='2', output_cny_per_million='8')
    if previous:
        meter.records=previous['requests']
        meter.stop_reason=previous['stop_reason']
    meter.install()
    meter.flush()
    if os.environ.get('BLIND_FREE_ONLY')=='1':
        from scripts.phase5_eval_meter import BudgetStop
        real_begin=meter.begin
        def free_begin(request):
            if request.url.host=='api.deepseek.com':
                raise BudgetStop('free_followup_no_model_requests_allowed')
            return real_begin(request)
        meter.begin=free_begin
    # Disable application recovery requests BEFORE the real transport. Production
    # Provider, prompt, parsing and persistence remain unchanged on attempt 1.
    complete, stream = Provider.complete, Provider.stream
    def once_complete(self, messages, *, attempt=1):
        if attempt != 1:
            raise AppError('generation_failed', detail='blind_run_auto_retry_disabled', retryable=False)
        return complete(self, messages, attempt=attempt)
    async def once_stream(self, messages, *, attempt=1):
        if attempt != 1:
            raise AppError('generation_failed', detail='blind_run_auto_retry_disabled', retryable=False)
        async for delta in stream(self, messages, attempt=attempt):
            yield delta
    Provider.complete, Provider.stream = once_complete, once_stream
    application = create_app()
    @application.middleware('http')
    async def scoped(request, call_next):
        is_model = request.method == 'POST' and request.url.path.endswith(('/assistant:stream', '/answers:stream'))
        if is_model:
            case = request.headers.get('x-blind-case')
            if not case or meter.stop_reason:
                return JSONResponse({'error': meter.stop_reason or 'case_required'}, status_code=409)
            meter.case_id = case
        return await call_next(request)
    @application.get('/__blind/ledger')
    def ledger():
        return {'summary': meter.summary(), 'stop_reason': meter.stop_reason}
    return application


def snapshot(url, filename):
    from sqlalchemy import create_engine, text
    engine = create_engine(url)
    with engine.connect() as conn:
        tables = ['chat_sessions','chat_messages','questions','question_versions','personal_generation_batches',
                  'daily_plans','practice_items','question_attempts','learning_events','kp_states']
        data = {table: [dict(r._mapping) for r in conn.execute(text(f'SELECT * FROM {table}'))] for table in tables}
        data['identity'] = dict(conn.execute(text("select current_database() db,current_user role,current_setting('port') port")).one()._mapping)
    engine.dispose()
    write(filename, data)


def run():
    import httpx
    from psycopg import sql
    from sqlalchemy.engine import make_url
    from desktop.runtime_paths import RuntimePaths
    from desktop.postgres import ManagedPostgres, APP_USER
    from backend.config import get_settings
    from backend.services.model_settings_service import load_local_settings
    effective = load_local_settings(get_settings())  # Configuration read only, no development DB connect.
    assert effective.llm_api_key and effective.llm_model == 'deepseek-flash'
    OUT.mkdir(parents=True, exist_ok=False)
    write('preflight.json', {'provider': effective.llm_base_url, 'model': effective.llm_model,
        'api_key_present': True, 'original_database_accessed': False, 'max_physical_requests': 10,
        'input_token_cap':150000,'output_token_cap':80000,'software_stop_cny':'0.90',
        'prices_cny_per_million': {'uncached_input':2,'output':8,'cached_input':0.04},
        'price_source':'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/',
        'auto_retry':False,'supplier_hard_money_cap':False})
    parent=ROOT/'tmp/managed-test-clusters'; parent.mkdir(parents=True,exist_ok=True)
    temporary=Path(tempfile.mkdtemp(prefix='blind-user-', dir=parent))
    pg_port, api_port, front_port = free_port(), free_port(), free_port()
    manager=ManagedPostgres(RuntimePaths.windows(resources=ROOT/'backend',local_app_data=temporary),
                            Path('C:/Program Files/PostgreSQL/18/bin'),port=pg_port)
    children=[]; logs=[]
    try:
        with manager:
            with manager._connect() as conn:
                conn.execute(sql.SQL("CREATE DATABASE {} OWNER {} TEMPLATE template0 ENCODING 'UTF8'").format(
                    sql.Identifier('kaoyan_blind_test'),sql.Identifier(APP_USER)))
            url=make_url(manager.database_url).set(database='kaoyan_blind_test').render_as_string(hide_password=False)
            env={**os.environ,'APP_ENV':'test','DATABASE_URL':url,'TEST_DATABASE_URL':url,
                 'KAOYAN_OWNED_TEST_PORT':str(pg_port),'PHASE45E_OWNED_TEST_PORT':str(pg_port),
                 'LLM_API_KEY':effective.llm_api_key.get_secret_value(),'LLM_BASE_URL':effective.llm_base_url,
                 'LLM_MODEL':effective.llm_model,'LLM_MAX_OUTPUT_TOKENS':str(effective.llm_max_output_tokens),
                 'LLM_STREAM_INCLUDE_USAGE':'true','CAPTURE_TEST_EVIDENCE':'true','PYTHONIOENCODING':'utf-8',
                 'MODEL_SETTINGS_PATH':str(OUT/'config/model-settings.bin'),
                 'UPLOAD_DIR':str(OUT/'uploads'),'CHROMA_DIR':str(OUT/'chroma'),
                 'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1',
                 'ALLOWED_WEB_ORIGINS':json.dumps([f'http://127.0.0.1:{front_port}']),
                 'VITE_API_PROXY_TARGET':f'http://127.0.0.1:{api_port}',
                 'BLIND_FRONT_URL':f'http://127.0.0.1:{front_port}','BLIND_OUT':str(OUT)}
            # All schema initialization occurs exclusively on this newly owned PG.
            result=subprocess.run([sys.executable,'-m','alembic','upgrade','head'],cwd=ROOT,env=env,capture_output=True)
            (OUT/'migration.log').write_bytes(result.stdout+result.stderr)
            assert result.returncode==0,'isolated_migration_failed'
            from sqlalchemy import create_engine
            from sqlalchemy.orm import Session
            from backend.models.learning import KnowledgePoint,KpState,Question,DailyPlan,PracticeItem
            import backend.services.question_versions  # register production snapshot hooks
            from datetime import datetime
            from zoneinfo import ZoneInfo
            engine=create_engine(url)
            with Session(engine) as db:
                roots=[]
                for code,name in [('math.calculus','高等数学'),('math.linear-algebra','线性代数'),('cs408','计算机408')]:
                    root=KnowledgePoint(code=code,name=name,subject='考研数学' if code.startswith('math') else '408',is_assessable=False)
                    db.add(root);db.flush();roots.append(root)
                chapter=KnowledgePoint(code='math.calculus.series',name='无穷级数',subject='考研数学',parent_id=roots[0].id,is_assessable=False)
                db.add(chapter);db.flush()
                leaf=KnowledgePoint(code='math.calculus.series.power',name='幂级数求和（奶蛙真实体验测试）',subject='考研数学',parent_id=chapter.id,is_assessable=True)
                db.add(leaf);db.flush();db.add(KpState(kp_id=leaf.id))
                q=Question(kp_id=leaf.id,question_type='calculation',grading_mode='self_assessed',
                    stem=r'奶蛙真实体验测试原题：当 $|x|<1$ 时，求级数 $\sum_{n=1}^{\infty}nx^n$ 的和。',
                    correct_answer=r'$x/(1-x)^2$',explanation=r'对几何级数逐项求导，再乘以 $x$，得到 $x/(1-x)^2$，适用于 $|x|<1$。',
                    question_provenance='legacy_unknown',content_trust='unreviewed')
                db.add(q);db.flush()
                # Production ORM snapshot hook creates QuestionVersion; no review evidence is fabricated.
                assert q.current_version_id
                plan=DailyPlan(study_date=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat(),status='draft')
                db.add(plan);db.flush()
                item=PracticeItem(plan_id=plan.id,question_id=q.id,question_version_id=q.current_version_id,kp_id=leaf.id,ordinal=1)
                db.add(item);db.commit()
                write('fixture.json', {'node_id':leaf.id,'question_id':q.id,'version_id':q.current_version_id,'plan_id':plan.id,
                    'practice_item_id':item.id,'source':'unreviewed clearly marked local test fixture, not official evidence'})
            engine.dispose()
            snapshot(url,'database-before.json')
            write('runtime.json', {'pg_port':pg_port,'api_port':api_port,'front_port':front_port,
                'database':'kaoyan_blind_test','pg_role':APP_USER,'python':sys.executable,'workspace':str(ROOT),
                'data_path':str(temporary),'original_services_restarted':False})
            for name,args,cwd in [('backend',[sys.executable,'-m','uvicorn','scripts.blind_user_20261019:app','--factory','--host','127.0.0.1','--port',str(api_port)],ROOT),
                                  ('frontend',['node','node_modules/vite/bin/vite.js','--host','127.0.0.1','--port',str(front_port),'--strictPort'],ROOT/'frontend')]:
                log=(OUT/f'{name}.log').open('w',encoding='utf-8');logs.append(log)
                children.append(subprocess.Popen(args,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW))
            for _ in range(120):
                assert all(p.poll() is None for p in children),'isolated_service_exited'
                try:
                    if httpx.get(f'http://127.0.0.1:{api_port}/api/health',trust_env=False,timeout=2).status_code==200 and httpx.get(f'http://127.0.0.1:{front_port}',trust_env=False,timeout=2).status_code==200:break
                except httpx.HTTPError:pass
                time.sleep(1)
            else:raise RuntimeError('isolated_health_timeout')
            write('health.json',httpx.get(f'http://127.0.0.1:{api_port}/api/health',trust_env=False).json())
            with (OUT/'browser.log').open('w',encoding='utf-8') as log:
                result=subprocess.run(['node','scripts/blind_user_20261019.cjs'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
            write('browser-exit.json',{'exit_code':result.returncode})
            snapshot(url,'database-after.json')
    finally:
        for child in reversed(children):
            if child.poll() is None:child.terminate();child.wait(timeout=20)
        for log in logs:log.close()
        write('cleanup.json',{'owned_services_stopped':all(p.poll() is not None for p in children),'cluster_stopped':not(manager.cluster/'postmaster.pid').exists(),'data_retained':True})


if __name__=='__main__':
    run()
