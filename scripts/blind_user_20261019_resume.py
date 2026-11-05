"""Resume the SAME owned test DB and SAME paid ledger, never reset allowance."""
import json
import os
import subprocess
import sys
import time
import httpx
from sqlalchemy.engine import make_url
from scripts.blind_user_20261019 import ROOT,OUT,write,snapshot
from scripts.blind_user_20261019_inspect import owned_manager


def run():
    from backend.config import get_settings
    from backend.services.model_settings_service import load_local_settings
    effective=load_local_settings(get_settings())
    runtime=json.loads((OUT/'runtime.json').read_text(encoding='utf-8'))
    manager=owned_manager();children=[];logs=[]
    phase=os.environ.get('BLIND_PHASE','followup')
    assert phase in {'followup','continuation','closure','final-model'}
    try:
        with manager:
            url=make_url(manager.database_url).set(database='kaoyan_blind_test').render_as_string(hide_password=False)
            if phase=='continuation':
                # Correct only our recorded invalid test fixture: a paper with
                # persisted items is active, not an unbuilt draft. Never touch
                # the original development DB or manufacture learning events.
                from sqlalchemy import create_engine,text
                engine=create_engine(url)
                fixture=json.loads((OUT/'fixture.json').read_text(encoding='utf-8'))
                with engine.begin() as conn:
                    old=conn.execute(text('select status from daily_plans where id=:id'),{'id':fixture['plan_id']}).scalar_one()
                    if old=='draft':conn.execute(text("update daily_plans set status='active' where id=:id"),{'id':fixture['plan_id']})
                engine.dispose()
                write('continuation-fixture-correction.json',{'plan_id':fixture['plan_id'],'old_status':old,'new_status':'active','scope':'owned test fixture only','question_or_evidence_changed':False})
            env={**os.environ,'APP_ENV':'test','DATABASE_URL':url,'TEST_DATABASE_URL':url,
                'KAOYAN_OWNED_TEST_PORT':str(runtime['pg_port']),'PHASE45E_OWNED_TEST_PORT':str(runtime['pg_port']),
                'LLM_API_KEY':effective.llm_api_key.get_secret_value(),'LLM_BASE_URL':effective.llm_base_url,
                'LLM_MODEL':effective.llm_model,'LLM_STREAM_INCLUDE_USAGE':'true','CAPTURE_TEST_EVIDENCE':'true',
                'MODEL_SETTINGS_PATH':str(OUT/'config/model-settings.bin'),'UPLOAD_DIR':str(OUT/'uploads'),
                'CHROMA_DIR':str(OUT/'chroma'),'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','PYTHONIOENCODING':'utf-8',
                'BLIND_RESUME_SAME_RUN':'1','VITE_API_PROXY_TARGET':f"http://127.0.0.1:{runtime['api_port']}",
                'BLIND_FRONT_URL':f"http://127.0.0.1:{runtime['front_port']}",'BLIND_OUT':str(OUT),
                'BLIND_FINAL_TWO':'1' if phase=='final-model' else '0',
                'ALLOWED_WEB_ORIGINS':json.dumps([f"http://127.0.0.1:{runtime['front_port']}"])}
            for name,args,cwd in [('backend-resume',[sys.executable,'-m','uvicorn','scripts.blind_user_20261019:app','--factory','--host','127.0.0.1','--port',str(runtime['api_port'])],ROOT),
                                 ('frontend-resume',['node','node_modules/vite/bin/vite.js','--host','127.0.0.1','--port',str(runtime['front_port']),'--strictPort'],ROOT/'frontend')]:
                log=(OUT/f'{name}.log').open('a',encoding='utf-8');logs.append(log)
                children.append(subprocess.Popen(args,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW))
            for _ in range(100):
                assert all(p.poll() is None for p in children),'resume_service_exited'
                try:
                    if httpx.get(f"http://127.0.0.1:{runtime['api_port']}/api/health",trust_env=False,timeout=2).status_code==200:break
                except httpx.HTTPError:pass
                time.sleep(1)
            else:raise RuntimeError('resume_health_timeout')
            write('resume-health.json',httpx.get(f"http://127.0.0.1:{runtime['api_port']}/api/health",trust_env=False).json())
            with (OUT/'targeted-pytest.log').open('w',encoding='utf-8') as log:
                result=subprocess.run([sys.executable,'-m','pytest','tests/unit/test_blind_user_findings.py','-q','-o','addopts='],env=env,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
            write('targeted-pytest-exit.json',{'exit_code':result.returncode})
            with (OUT/f'browser-{phase}.log').open('w',encoding='utf-8') as log:
                browser_script=('scripts/blind_user_20261019_continuation.cjs' if phase in {'continuation','final-model'} else
                                'scripts/blind_user_20261019_closure.cjs' if phase=='closure' else
                                'scripts/blind_user_20261019_free.cjs' if os.environ.get('BLIND_FREE_ONLY')=='1' else 'scripts/blind_user_20261019_followup.cjs')
                result=subprocess.run(['node',browser_script],env=env,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
            write('browser-followup-exit.json',{'exit_code':result.returncode})
            snapshot(url,f'database-after-{phase}.json' if phase!='followup' else 'database-after-free.json' if os.environ.get('BLIND_FREE_ONLY')=='1' else 'database-after.json')
    finally:
        for p in reversed(children):
            if p.poll() is None:p.terminate();p.wait(timeout=20)
        for log in logs:log.close()
        write('resume-cleanup.json',{'owned_services_stopped':all(p.poll() is not None for p in children),'cluster_stopped':not(manager.cluster/'postmaster.pid').exists(),'data_retained':True})


if __name__=='__main__':run()
