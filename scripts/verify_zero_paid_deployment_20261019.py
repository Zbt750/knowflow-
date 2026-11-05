"""Read-only deployment evidence. No app startup, migrations, seeds or model calls."""
import argparse,hashlib,importlib.util,json,marshal,sys,types
from pathlib import Path
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT=ROOT/'storage/quality-audits/zero-paid-ux-deploy-20261019-v1'
FILES=['backend/chat/service.py','backend/services/learning_task_service.py',
 'backend/services/learning_assistant_service.py','backend/services/generation_formula_consistency.py',
 'frontend/src/lib/chatAnswerText.ts','frontend/src/pages/ChatPage.vue','frontend/src/main.ts','frontend/src/product-theme.css']
def write(name,data):
    target=OUT/name
    assert not target.exists(),'do not overwrite deployment evidence'
    target.write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
def hashes():return {f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in FILES}
def code_key(code):
    constants=[]
    for i,c in enumerate(code.co_consts):
        if i==0 and isinstance(c,(str,type(None))):constants.append(None)
        else:constants.append(code_key(c) if isinstance(c,types.CodeType) else c)
    return (code.co_code,tuple(constants),code.co_names,code.co_varnames,code.co_freevars,code.co_cellvars,
        code.co_argcount,code.co_kwonlyargcount,code.co_posonlyargcount,code.co_flags)
def version():
    OUT.mkdir(parents=True,exist_ok=False)
    checks={}
    for f in FILES[:4]:
        path=ROOT/f;cache=Path(importlib.util.cache_from_source(str(path)))
        raw=cache.read_bytes();cached=marshal.loads(raw[16:]);current=compile(path.read_bytes(),str(path),'exec')
        checks[f]={'cached_code_sha256':hashlib.sha256(raw).hexdigest(),
            'cache_mtime_utc':datetime.fromtimestamp(cache.stat().st_mtime,timezone.utc).isoformat(),
            'source_mtime_utc':datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat(),
            'executable_code_matches_last_test_cache':code_key(cached)==code_key(current)}
        (OUT/(path.stem+'-'+path.parent.name+'-tested.pyc')).write_bytes(raw)
    tests={}
    for scope in ['backend-confirmed','browser-ui-confirmed']:
        path=ROOT/'storage/quality-audits/zero-paid-ux-20261019'/scope/'run-summary.json'
        data=json.loads(path.read_text(encoding='utf-8'))
        assert all(c['exit_code']==0 for c in data['checks']) and not data.get('browser_blocker')
        tests[scope]={'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'checks':data['checks']}
    data={'source_sha256':hashes(),'tested_bytecode':checks,'accepted_tests':tests,
        'docstring_note':'learning_task_service only received a docstring update after final tests; executable constants/instructions are compared recursively, excluding docstrings and source line metadata.'}
    write('version-preflight.json',data)
    assert all(c['executable_code_matches_last_test_cache'] for c in checks.values()),'source differs from accepted executable test cache; stop'
    print(json.dumps({'executable_version_matches':True,'hashes_recorded':len(FILES)}))
def snapshot(stage):
    from backend.config import get_settings
    from backend.services.model_settings_service import load_local_settings
    from sqlalchemy import create_engine,text
    from sqlalchemy.engine import make_url
    s=load_local_settings(get_settings());u=make_url(str(s.active_database_url))
    assert (u.host,u.port,u.database,u.username)==('127.0.0.1',5433,'kaoyan','kaoyan')
    engine=create_engine(u,connect_args={'connect_timeout':5})
    with engine.connect() as c:
        c.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        identity=dict(c.execute(text("SELECT current_database() db,current_user role,current_setting('port') port,host(inet_server_addr()) host,current_setting('transaction_read_only') read_only")).one()._mapping)
        assert identity=={'db':'kaoyan','role':'kaoyan','port':'5433','host':'127.0.0.1','read_only':'on'}
        active={
            'messages':c.scalar(text("SELECT count(*) FROM chat_messages WHERE status='generating'")),
            'learning_tasks':c.scalar(text("SELECT count(*) FROM learning_tasks WHERE status IN ('running','created')")),
            'document_jobs':c.scalar(text("SELECT count(*) FROM document_jobs WHERE status IN ('pending','running','retry')")),
            'generation_batches':c.scalar(text("SELECT count(*) FROM personal_generation_batches WHERE status IN ('pending','running','generating')"))}
        names=c.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")).all()
        tables={};unreadable=[]
        for name in names:
            if not c.scalar(text("SELECT has_table_privilege(current_user,:name,'SELECT')"),{'name':'public.'+name}):
                unreadable.append(name);continue
            safe=engine.dialect.identifier_preparer.quote(name)
            tables[name]=dict(c.execute(text(f"SELECT count(*) rows,md5(coalesce(string_agg(md5(row_to_json(t)::text),'' ORDER BY md5(row_to_json(t)::text)),'')) digest FROM public.{safe} t")).one()._mapping)
        c.rollback()
    engine.dispose()
    data={'at_utc':datetime.now(timezone.utc).isoformat(),'identity':identity,'active':active,'tables':tables,
        'unreadable_tables':unreadable,'source_sha256':hashes(),'provider_requests':0,
        'configuration':{'environment':s.app_env,'env_loading':'Settings .env UTF-8 plus existing local encrypted model settings; no secrets exported','llm_model':s.llm_model}}
    if stage=='after':
        before=json.loads((OUT/'before.json').read_text(encoding='utf-8'))
        data['changed_tables']=[t for t in set(tables)|set(before['tables']) if tables.get(t)!=before['tables'].get(t)]
        data['unchanged']=not data['changed_tables'] and unreadable==before['unreadable_tables']
        assert hashes()==before['source_sha256'],'sources changed during deployment'
    write(stage+'.json',data)
    print(json.dumps({k:v for k,v in data.items() if k not in {'tables','source_sha256'}},ensure_ascii=False))
    assert not any(active.values()),'active tasks present: stop restart'
    assert not unreadable,'cannot verify complete public data: stop'
    if stage=='after':assert data['unchanged'],'business rows changed; investigate'

def http_checks():
    import httpx
    expected=json.loads((OUT/'version-preflight.json').read_text(encoding='utf-8'))['source_sha256']
    assert hashes()==expected,'sources changed since preflight'
    manifest_path=ROOT/'tmp/dev-backend-manifests/runtime-3877e2d858494e3b988ab3f7a1ec9b83.json'
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    assert manifest['pid']==8888 and manifest['workspace']==str(ROOT) and manifest['bind']=='127.0.0.1:8000'
    matching={f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest()==h for f,h in manifest['workspace_files'].items()}
    assert all(matching.values()),'running manifest differs from current files'
    results={}
    endpoints=['http://127.0.0.1:8000/api/health','http://127.0.0.1:5173/api/health',
      'http://127.0.0.1:8000/openapi.json','http://127.0.0.1:8000/api/knowledge/tree',
      'http://127.0.0.1:8000/api/plans/today','http://127.0.0.1:8000/api/chat/sessions?mode=builtin&purpose=qa',
      'http://127.0.0.1:8000/api/materials?source_type=user&limit=1','http://127.0.0.1:8000/api/question-bank?scope=personal&limit=1']
    with httpx.Client(trust_env=False,timeout=30) as client:
        for url in endpoints:
            r=client.get(url);r.raise_for_status();data=r.json()
            result={'http':r.status_code,'latency_seconds':r.elapsed.total_seconds(),
                'body_sha256':hashlib.sha256(r.content).hexdigest(),'response_bytes':len(r.content)}
            if url.endswith('/api/health'):
                assert data['environment']=='dev' and data['database']=='connected' and data['status']=='ok'
                result['health']=data
            if url.endswith('openapi.json'):
                assert len(data['paths'])==manifest['openapi_paths']
                assert not any('__zero' in p for p in data['paths'])
                result['path_count']=len(data['paths'])
                (OUT/'openapi-after.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
            results[url]=result
        markers={'/src/pages/ChatPage.vue':'return !expandedMessageIds.value.has',
            '/src/lib/chatAnswerText.ts':'rest = rest.replace(prefix',
            '/src/main.ts':'link.rel = "preload"',
            '/src/product-theme.css':'bottom:calc(70px + env(safe-area-inset-bottom,0px))'}
        for path,marker in markers.items():
            r=client.get('http://127.0.0.1:5173'+path);r.raise_for_status()
            assert marker in r.text,('frontend module not current',path)
            results[path]={'http':r.status_code,'expected_fix_present':True,'served_sha256':hashlib.sha256(r.content).hexdigest()}
    write('http-after.json',results)
    write('runtime-code-verification.json',{'manifest_path':str(manifest_path),'manifest_pid':manifest['pid'],
        'manifest_files_match':matching,'supplemental_source_sha256':hashes(),
        'formula_import_chain':'generation_formula_consistency is lazily imported inside assess_general_output; no generation was triggered. Its disk hash and executable test-cache equality are verified, but this deployment does not claim it has executed in PID 8888.',
        'no_new_model_requests':True})
    (OUT/'new-runtime-manifest.json').write_bytes(manifest_path.read_bytes())
    print(json.dumps({'http_get_checks':len(endpoints),'frontend_modules_current':len(markers),'manifest_files_match':len(matching),'pid':manifest['pid']}))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['version','before','after','http']);a=p.parse_args()
    version() if a.stage=='version' else http_checks() if a.stage=='http' else snapshot(a.stage)
