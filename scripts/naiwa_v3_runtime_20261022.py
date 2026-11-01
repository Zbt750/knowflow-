"""V3 audit runtime: append-only continuation of the existing 40-call phase.

No historic baseline is rewritten. Existing ledger schema/limits stay unchanged;
the A3 restriction is checked under the SAME reservation locks before begin().
Only isolated ports are used; runtime starts CLOSED and never retries models.
"""
from pathlib import Path
import json
import os
import sys
import time
import subprocess
import hashlib

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import scripts.naiwa_agent_full_v2_20261021 as old
from scripts.naiwa_freeze_gate_20261021 import FinalRoundGate as BaseGate, SCENE, atomic_json, process_started

OUT=ROOT/'storage/quality-audits/naiwa-freeze-preflight-20261021/naiwa-v3-20261022'
RUN=old.HOME/'agent-full-v3-20261022'
LEDGER_DIR=old.OUT
LEDGER=LEDGER_DIR/'provider-ledger.json'
TASK=Path(r'C:\Users\ZBT\.codex\attachments\41d2d52c-25f9-4867-aa6c-71061a86ce1d\已粘贴的文本.txt')
STAGE0=ROOT/'storage/quality-audits/naiwa-v3-stage0-20261022-103246-868529'
read=old.read
sha=old.sha
save=old.save
LEGACY_CAPS=dict(old.SCENE_CAPS)
PURPOSE_POLICY=old.PURPOSE_POLICY
_old_source_files=old.source_files


class V3Gate(BaseGate):
    def __init__(self,output=LEDGER_DIR,**kwargs):
        # Parent is allowed to read existing schema, never reset/release records.
        super().__init__(output,**kwargs)
        if Path(output).resolve()==LEDGER_DIR.resolve():
            self.output=OUT
            self.control=OUT/'control.json'
            if not self.control.is_file():
                raise RuntimeError('v3_control_must_be_prepared_closed')

    def begin(self,request):
        with self.authorization.hold(),self.lock,self.disk_lock:
            self.reload()
            if SCENE.get()=='A' and sum(r['case_id']=='A' for r in self.records)>=3:
                raise self.refusal('v3_a_scene_cap3')
            return super().begin(request)


def files():
    return sorted(set(_old_source_files()+[Path(__file__).resolve(),
        ROOT/'scripts/naiwa_agent_full_v2_20261021.py',
        ROOT/'frontend/acceptance/naiwa-agent-full-v3.cjs']))


def hashes():
    return {p.relative_to(ROOT).as_posix():sha(p) for p in files() if p.is_file()}


def bind():
    old.OUT=OUT;old.RUN=RUN
    old.LEDGER_DIR=LEDGER_DIR;old.LEDGER_PATH=LEDGER
    old.CONTROL_PATH=OUT/'control.json'
    old.BASELINE_PATH=OUT/'v3-baseline.json'
    old.ACTIVE_SOURCE_PATH=RUN/'active-source-hashes.json'
    old.EXPERIENCE_HEADER='naiwa-v3-20261022'
    old.FinalRoundGate=V3Gate
    old.source_hashes=hashes


def protected_current():
    before=read(STAGE0/'protected-before.json')
    # Ledger is explicitly append-authorized; preserve its prior bytes separately.
    excluded={(LEDGER.relative_to(ROOT).as_posix()),
        (LEDGER_DIR/'control.json').relative_to(ROOT).as_posix()}
    return {name:sha(ROOT/name) for name in before if name not in excluded}


def validate_history():
    expected=read(OUT/'protected-start.json')
    current=protected_current()
    if expected!=current:raise RuntimeError('v3_protected_history_changed_STOP')
    base=read(OUT/'v3-baseline.json')
    assert {p.relative_to(ROOT).as_posix():sha(p) for p in old.OLD_LEDGERS}==base['old_ledger_sha256']


def prepare():
    assert not OUT.exists() and not RUN.exists(),'do_not_overwrite_v3_run'
    runtime=read(old.OLD_RUN/'runtime.json')
    pg=old.existing_manager();identity=pg._identity()
    assert identity and identity[0]==runtime['postgres_pid']
    # postmaster.pid and runtime.json survive process exit; neither proves life.
    for key in ('postgres_pid','backend_pid','frontend_pid'):
        process_started(runtime[key])
    assert pg.owner['cluster_id']=='eb3800c77c3c40f6ac12eb21112df36c'
    # All stage0 facts must still hold before a new binding is recorded.
    for name,value in read(STAGE0/'protected-after.json').items():
        assert sha(ROOT/name)==value, 'protected stage0 drift:'+name
    assert sha(LEDGER)==sha(LEDGER_DIR/'A1-ledger-original.json')
    doc=read(LEDGER)
    assert len(doc['requests'])==1 and doc['requests'][0]['finished'] and not doc['stop_reason']
    assert not read(LEDGER_DIR/'control.json')['paid_enabled']
    for row in doc['requests']:
        assert row['state']=='COMPLETED_USAGE_OBSERVED'
    OUT.mkdir();RUN.mkdir()
    save(OUT/'control.json',{'paid_enabled':False,'authorization_received':False,'active_scene':None,
        'reason':'V3_prepared_closed'})
    save(OUT/'protected-start.json',protected_current())
    save(OUT/'inherited-ledger-original.json',doc)
    save(OUT/'inherited-control-original.json',read(LEDGER_DIR/'control.json'))
    bind()
    source=hashes()
    save(RUN/'active-source-hashes.json',{'epoch':0,'source_sha256':source,
        'supersedes_without_rewriting':str(LEDGER_DIR/'v2-baseline.json'),'time':time.time()})
    save(OUT/'v3-baseline.json',{'old_ledger_sha256':{p.relative_to(ROOT).as_posix():sha(p) for p in old.OLD_LEDGERS},
        'source_sha256':source,'attachment_sha256':sha(TASK),'existing_ledger':str(LEDGER),
        'inherited_requests':1,'global_limit':40,'effective_A_cap':3,
        'legacy_scene_caps_unchanged':LEGACY_CAPS,'no_budget_reset':True,
        'original_incident':str(LEDGER_DIR/'history-preservation-incident.json'),
        'cluster_id':pg.owner['cluster_id'],'created':time.time()})
    old.snapshot_database(OUT/'database-before.json',allow_live_identity=identity)
    save(RUN/'session-registry.json',{'sessions':[]})
    save(OUT/'runtime-v2.json',{'status':'prepared'})
    print('V3 PREPARED CLOSED: existing ledger 1/40; effective A1/3; old baseline untouched')


def complete_preparation():
    """Resume only the failed DB-read preparation; do not reset the directory."""
    bind();validate_history()
    assert not read(OUT/'control.json')['paid_enabled']
    assert not (OUT/'database-before.json').exists()
    assert sha(LEDGER)==sha(OUT/'inherited-ledger-original.json')
    runtime=read(old.OLD_RUN/'runtime.json')
    for key in ('postgres_pid','backend_pid','frontend_pid'):process_started(runtime[key])
    pg=old.existing_manager();identity=pg._identity()
    assert identity and identity[0]==runtime['postgres_pid']
    before=read(RUN/'active-source-hashes.json')
    current=hashes()
    changed=[name for name in set(before['source_sha256'])|set(current)
        if before['source_sha256'].get(name)!=current.get(name)]
    assert changed==['scripts/naiwa_v3_runtime_20261022.py'],changed
    revision={'epoch':1,'source_sha256':current,'prior_epoch_sha256':sha(RUN/'active-source-hashes.json'),
        'changed_paths':changed,'reason':'live process proof and interrupted preparation recovery',
        'time':time.time()}
    assert not (RUN/'preparation-revision-1.json').exists()
    save(RUN/'preparation-revision-1.json',revision)
    save(RUN/'active-source-hashes.json',revision)
    data=old.snapshot_database(OUT/'database-before.json',allow_live_identity=identity)
    previous=read(STAGE0/'database-after.json')
    assert data==previous,'recovered fixed station has changed data STOP'
    save(RUN/'session-registry.json',{'sessions':[]})
    save(OUT/'runtime-v2.json',{'status':'prepared'})
    print('V3 PREPARATION COMPLETED: retained DB equals stage0, closed, ledger unchanged')


def real_app():
    bind()
    if hashes()!=read(RUN/'active-source-hashes.json')['source_sha256']:
        raise RuntimeError('v3_start_source_hash_changed')
    validate_history()
    app=old.real_app()
    inherited=old.verify_integrity
    def integrity(**kwargs):
        validate_history()
        inherited(**kwargs)
    # The gate callback resolves old.verify_integrity at send time.
    old.verify_integrity=integrity
    return app


def gate():
    return V3Gate(LEDGER_DIR,simulated=False,preparation=False,global_limit=40,
        scene_caps=LEGACY_CAPS,purpose_policy=PURPOSE_POLICY,seal_on_scene_cap=False)


def serve():
    bind()
    from desktop.postgres import _run
    import httpx
    from datetime import datetime
    from zoneinfo import ZoneInfo
    old.assert_ports_free()
    assert hashes()==read(RUN/'active-source-hashes.json')['source_sha256']
    validate_history()
    pg,owner=old.pg_owner_preflight()
    pg.lock.acquire();children=[];logs=[];runtime=None
    try:
        result=_run([pg.binary('pg_ctl'),'-D',str(pg.cluster),'-l',str(OUT/'postgres.log'),
            '-o',f'-p {pg.port} -c listen_addresses=127.0.0.1 -c log_statement=none -c log_min_error_statement=panic',
            '-w','-t','30','start'],timeout=45,capture=False)
        identity=pg._identity()
        assert result.returncode==0 and identity
        pg._owned_identity=identity
        data=old.snapshot_database(OUT/'database-start.json',allow_live_identity=identity)
        assert data==read(OUT/'database-before.json'),'data changed while switching runtime'
        assert not any(r.get('status') in {'running','queued','pending'} for r in data['learning_tasks'])
        assert not any(r.get('status') in {'generating','streaming','pending'} for r in data['chat_messages'])
        date=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
        plans=[r for r in data['daily_plans'] if r.get('study_date')==date and r.get('status')=='active']
        assert len(plans)<=1
        save(RUN/'runtime-data.json',{'cluster_id':owner['cluster_id'],'today_plan_id':str(plans[0]['id']) if plans else None,
            'study_date':date,'today_plan_count':len(plans)})
        (RUN/'browser-nonce.txt').write_text(os.urandom(32).hex(),encoding='ascii')
        effective,key=old._load_live_settings()
        from sqlalchemy.engine import URL
        db=URL.create('postgresql+psycopg',username='kaoyan_app',password=pg._passwords['kaoyan_app'],
            host='127.0.0.1',port=63044,database=old.DATABASE).render_as_string(hide_password=False)
        env={**os.environ,'APP_ENV':'test','DATABASE_URL':db,'TEST_DATABASE_URL':db,
            'KAOYAN_OWNED_TEST_PORT':'63044','PHASE45E_OWNED_TEST_PORT':'63044',
            'LLM_API_KEY':key,'LLM_BASE_URL':effective.llm_base_url,'LLM_MODEL':effective.llm_model,
            'LLM_STREAM_INCLUDE_USAGE':'true','MODEL_SETTINGS_PATH':str(RUN/'model-settings.bin'),
            'UPLOAD_DIR':str(old.HOME/'uploads'),'CHROMA_DIR':str(old.HOME/'chroma'),
            'MODEL_CACHE_DIR':str(ROOT/'storage/models'),'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1',
            'ANONYMIZED_TELEMETRY':'False','DO_NOT_TRACK':'1','OTEL_SDK_DISABLED':'true','PYTHONIOENCODING':'utf-8',
            'ALLOWED_WEB_ORIGINS':json.dumps(['http://127.0.0.1:63046']),
            'VITE_API_PROXY_TARGET':'http://127.0.0.1:63045',
            'NAIWA_REAL_RETEST_BUDGET7':'0','NAIWA_FINAL_ROUND_STAGE2':'0'}
        commands=[[sys.executable,'-m','uvicorn','scripts.naiwa_v3_runtime_20261022:real_app','--factory',
            '--host','127.0.0.1','--port','63045'],
            [r'D:\应用安装包\node.exe','node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','63046','--strictPort']]
        runtime={'status':'starting','postgres_identity':list(identity),'postgres_pid':identity[0],
            'supervisor_pid':os.getpid(),'cluster_id':owner['cluster_id'],'commands':commands,
            'workspace':str(ROOT),'stop_request':str(RUN/'stop.request'),'database':data['identity']}
        save(OUT/'runtime-v2.json',runtime)
        for name,command,cwd in zip(('backend','frontend'),commands,(ROOT,ROOT/'frontend')):
            log=(OUT/(name+'.log')).open('x',encoding='utf-8');logs.append(log)
            children.append(subprocess.Popen(command,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)))
        runtime.update(backend_pid=children[0].pid,frontend_pid=children[1].pid,
            backend_started=process_started(children[0].pid),frontend_started=process_started(children[1].pid))
        save(OUT/'runtime-v2.json',runtime)
        with httpx.Client(trust_env=False,timeout=3) as client:
            for _ in range(90):
                assert all(p.poll() is None for p in children),'isolated_child_exited'
                try:
                    response=client.get('http://127.0.0.1:63046/api/health')
                    if response.status_code==200 and response.headers.get('x-naiwa-experience')=='naiwa-v3-20261022':
                        assert not read(OUT/'control.json')['paid_enabled']
                        runtime.update(status='running',health=response.json())
                        save(OUT/'runtime-v2.json',runtime);break
                except httpx.HTTPError:pass
                time.sleep(1)
            else:raise RuntimeError('startup_health_timeout')
        while not (RUN/'stop.request').exists():
            assert all(p.poll() is None for p in children),'isolated_child_exited'
            time.sleep(1)
    finally:
        gate().seal('v3_runtime_stopped')
        for p in reversed(children):
            if p.poll() is None:p.terminate();p.wait(timeout=25)
        for log in logs:log.close()
        if pg._owned_identity is not None:pg.stop()
        else:pg.lock.release()
        if runtime:runtime.update(status='stopped');save(OUT/'runtime-v2.json',runtime)


def open_scene(scene):
    bind();validate_history()
    assert scene in LEGACY_CAPS
    assert read(OUT/'zero-network-status.json')['passed']
    g=gate();g.reload()
    assert not g.stop_reason and all(r.get('finished') for r in g.records)
    assert len(g.records)<40
    if scene=='A':assert sum(r['case_id']=='A' for r in g.records)<3
    # Parent performs process, loaded epoch, integrity, global & original caps.
    old.open_scene(scene)


if __name__=='__main__':
    action=sys.argv[1]
    if action=='prepare':prepare()
    elif action=='complete-prepare':complete_preparation()
    elif action=='serve':serve()
    elif action=='open':open_scene(sys.argv[2])
    elif action=='close':bind();old.close_paid('v3_operator_closed')
    elif action=='stop':
        bind();old.close_paid('v3_stop_requested');(RUN/'stop.request').touch()
    else:raise SystemExit('prepare | serve | open SCENE | close | stop')
