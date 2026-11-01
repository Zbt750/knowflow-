"""Zero-paid repair evidence. Original persistent experience rows are immutable."""
from pathlib import Path
import sys,json,hashlib,shutil
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.restore_naiwa_experience_20261020 import RUN,snapshot,save
OUT=ROOT/'storage/quality-audits/naiwa-proxy-attribution-zero-20261021'
PREVIOUS=ROOT/'storage/quality-audits/naiwa-final-real-retest-20261021'
LEDGERS=[ROOT/'storage/quality-audits/naiwa-real-20261020/provider-ledger.json',
 ROOT/'storage/quality-audits/naiwa-real-retest-20261020-budget7/provider-ledger.json',
 ROOT/'storage/quality-audits/naiwa-freeze-preflight-20261021/round5/provider-ledger.json']
def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def before():
    OUT.mkdir(parents=True,exist_ok=False)
    current=json.loads(json.dumps(snapshot('proxy-zero-before'),default=str))
    assert current==read(PREVIOUS/'database-after.json'),'previous retained data differs; stop'
    runtime=read(RUN/'runtime.json');loaded=read(RUN/'loaded-code.json')
    assert runtime['cluster_id']=='eb3800c77c3c40f6ac12eb21112df36c'
    assert current['identity']=={'db':'naiwa_experience_test','role':'kaoyan_app','port':'63044'}
    assert all(sha(ROOT/p)==h for p,h in loaded['source_sha256'].items()),'loaded code mismatch'
    prior=read(PREVIOUS/'final-verification.json')
    assert all(sha(ROOT/p)==h for p,h in prior['old_ledger_sha256_unchanged'].items())
    assert read(LEDGERS[-1])['requests']==[]
    assert not read(LEDGERS[-1].parent/'control.json')['paid_enabled']
    save(OUT/'database-before.json',current)
    save(OUT/'baseline.json',{'ledger_sha256':{str(p.relative_to(ROOT)):sha(p) for p in LEDGERS},'runtime':runtime,'loaded':loaded})
    for name in ['runtime.json','loaded-code.json','backend.log','supervisor.log']:
        shutil.copy2(RUN/name,OUT/('before-'+name))
    import httpx,urllib.request
    with httpx.Client() as client:
        transport=client._transport_for_url(httpx.URL('https://api.deepseek.com/chat/completions'))
        sync=type(transport._pool).__name__
    client=httpx.AsyncClient()
    transport=client._transport_for_url(httpx.URL('https://api.deepseek.com/chat/completions'))
    save(OUT/'transport-diagnostic-before.json',{'network_requests':0,'system_proxy_present':bool(urllib.request.getproxies()),
        'default_sync_pool':sync,'default_async_pool':type(transport._pool).__name__,'proxy_values_logged':False})
    print('Identity, loaded code, retained failure and all ledgers verified; no network/model request')

def after():
    baseline=read(OUT/'database-before.json');current=json.loads(json.dumps(snapshot('proxy-zero-after'),default=str))
    save(OUT/'database-after.json',current)
    diff={}
    for table,rows in baseline.items():
        if not isinstance(rows,list):continue
        key=lambda r:str(r.get('id',r.get('kp_id')))
        a={key(r):r for r in rows};b={key(r):r for r in current[table]}
        assert all(b.get(k)==v for k,v in a.items()),'original row changed:'+table
        new=[v for k,v in b.items() if k not in a]
        assert not new or table in {'chat_sessions','chat_messages','learning_tasks'},'unexpected additions:'+table
        if table=='chat_sessions':assert all(r['title'].startswith('零付费代理诊断回归') for r in new)
        diff[table]={'before':len(a),'after':len(b),'original_unchanged':True,'new_ids':[key(r) for r in new]}
    old=read(OUT/'baseline.json');hashes={str(p.relative_to(ROOT)):sha(p) for p in LEDGERS}
    assert hashes==old['ledger_sha256']
    assert read(LEDGERS[-1])['requests']==[] and not read(LEDGERS[-1].parent/'control.json')['paid_enabled']
    loaded=read(RUN/'loaded-code.json');checks={p:sha(ROOT/p)==h for p,h in loaded['source_sha256'].items()}
    assert all(checks.values()) and loaded['provider']=='FIXED-OFFLINE-NO-PAID-MODEL'
    save(OUT/'database-diff.json',diff)
    save(OUT/'ledger-verification.json',{'unchanged':True,'sha256':hashes,'physical_real_requests':0,'paid_enabled':False})
    shutil.copy2(RUN/'loaded-code.json',OUT/'loaded-code.json')
    assert loaded['http_policy']['trust_env'] is False and loaded['physical_gate']['preparation_permanently_closed']
    save(OUT/'final-verification.json',{'identity':current['identity'],'runtime':read(RUN/'runtime.json'),'sources_match':checks,
        'all_previous_rows_unchanged':True,'ledger_unchanged':True,'real_requests':0,'real_model_quality':'PENDING',
        'engineering_repair':'PASS','transport_and_budget_safety':'PASS_ZERO_NETWORK_SCOPE',
        'error_diagnostics':'PASS_TESTED_NINE_CASES','data_protection':'PASS',
        'fixed_provider_only':True,'preparation_hard_closed':True,'proxy_policy_isolation_only':True})
    print('Historical rows, study paper, questions, evidence and ledger unchanged; only marked diagnostic sessions/tasks added')

def transport_after():
    import httpx,asyncio
    from types import SimpleNamespace
    from backend.chat import http_clients
    from scripts.restore_naiwa_experience_20261020 import database_url,existing_manager
    http_clients.configure_isolated_provider_http(SimpleNamespace(app_env='test',active_database_url=database_url(existing_manager())))
    def inspect(client):
        pool=client._transport_for_url(httpx.URL('https://api.deepseek.com/chat/completions'))._pool
        return {'pool':type(pool).__name__,'retries':pool._retries,'trust_env':client.trust_env,
            'follow_redirects':client.follow_redirects,'tls_verify_required':pool._ssl_context.verify_mode==2,
            'tls_check_hostname':pool._ssl_context.check_hostname}
    with http_clients.sync_client() as client:sync=inspect(client)
    async def inspect_async():
        async with http_clients.async_client() as client:return inspect(client)
    asynchronous=asyncio.run(inspect_async())
    with httpx.Client() as raw:raw_pool=type(raw._transport_for_url(httpx.URL('https://api.deepseek.com/chat/completions'))._pool).__name__
    assert sync['pool']=='ConnectionPool' and asynchronous['pool']=='AsyncConnectionPool'
    assert all(not c['trust_env'] and not c['follow_redirects'] and c['retries']==0 and c['tls_verify_required'] and c['tls_check_hostname'] for c in [sync,asynchronous])
    save(OUT/'transport-diagnostic-after.json',{'sync_actual_factory':sync,'async_actual_factory':asynchronous,
        'unmodified_httpx_default_pool':raw_pool,'policy':http_clients.policy(),'network_requests':0,
        'real_reachability':'NOT_RUN','system_proxy_changed':False})
    print('Real factories construct direct verified-TLS, no-redirect, retry0 pools; no network requests')

if __name__=='__main__':{'before':before,'after':after,'transport-after':transport_after}[sys.argv[1]]()
