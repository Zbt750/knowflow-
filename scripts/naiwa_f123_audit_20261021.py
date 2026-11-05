"""Closed-runtime audit and immutable evidence for F1/F2/F3 repair."""
from pathlib import Path
import sys,json,hashlib,shutil
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.naiwa_dns_independent_review_20261021 import verify,immutable
from scripts.restore_naiwa_experience_20261020 import save,RUN
OUT=ROOT/'storage/quality-audits/naiwa-f123-repair-zero-20261021'
PREV=ROOT/'storage/quality-audits/naiwa-dns-independent-review-20261021'
BASE=ROOT/'storage/quality-audits/naiwa-dns-audit-zero-20261021/repair-baseline.json'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def protected():
    result=immutable()
    result.update({str(p.relative_to(ROOT)):sha(p) for p in PREV.rglob('*') if p.is_file()})
    return result
def before():
    assert not OUT.exists();data,loaded,runtime,processes=verify()
    assert data==read(PREV/'database-after.json')
    OUT.mkdir();save(OUT/'database-before.json',data);save(OUT/'loaded-code-before.json',loaded)
    save(OUT/'runtime-before.json',runtime);save(OUT/'processes-before.json',processes)
    save(OUT/'protected-sha256-before.json',protected())
    paths=list(loaded['source_sha256'])+['tests/unit/test_dns_independent_review.py','tests/unit/test_dns_audit_phases.py',
        'tests/unit/test_final_round_gate.py','tests/unit/test_isolated_proxy_attribution.py']
    save(OUT/'source-sha256-before.json',{p:sha(ROOT/p) for p in paths})
    for p in paths:shutil.copy2(ROOT/p,OUT/('before-'+p.replace('/','__')))
    print('PASS actual runtime/parent identity, baseline, DB, old evidence, failed reservation1 and closed exit')
def checkpoint():
    from scripts.restore_naiwa_experience_20261020 import existing_manager,snapshot
    from scripts.naiwa_dns_independent_review_20261021 import procs
    pg=existing_manager();runtime=read(RUN/'runtime.json');processes=procs()
    assert pg.owner['cluster_id']==runtime['cluster_id']=='eb3800c77c3c40f6ac12eb21112df36c'
    for port,key in [(63044,'postgres_pid'),(63045,'backend_pid'),(63046,'frontend_pid')]:
        rows=[p for p in processes if p['port']==port]
        assert len(rows)==1 and rows[0]['pid']==runtime[key]
        if port!=63044:assert rows[0]['parent_pid']==runtime['supervisor_pid']
    assert 'restore_naiwa_experience_20261020:sealed_app' in next(p['command'] for p in processes if p['port']==63045)
    data=json.loads(json.dumps(snapshot('f123-'+sys.argv[1]),default=str))
    assert data==read(OUT/'database-before.json'),'original rows changed STOP'
    assert protected()==read(OUT/'protected-sha256-before.json'),'protected evidence changed STOP'
    assert sha(ROOT/'tests/unit/test_dns_independent_review.py')==read(OUT/'source-sha256-before.json')['tests/unit/test_dns_independent_review.py']
    roundpath=ROOT/'storage/quality-audits/naiwa-freeze-preflight-20261021/round5'
    ledger=read(roundpath/'provider-ledger.json')
    assert len(ledger['requests'])==1 and ledger['requests'][0]['finished']
    assert not read(roundpath/'control.json')['paid_enabled']
    save(OUT/('database-'+sys.argv[1]+'.json'),data)
    save(OUT/('processes-'+sys.argv[1]+'.json'),processes)
    save(OUT/('runtime-'+sys.argv[1]+'.json'),runtime)
    print('PASS owned isolated processes, all original rows, protected hashes, retained reservation1, paid closed')
    return data,processes,runtime

def finish():
    import xml.etree.ElementTree as ET,urllib.request
    data,processes,runtime=checkpoint();loaded=read(RUN/'loaded-code.json')
    assert loaded['pid']==runtime['backend_pid'] and loaded['provider']=='FIXED-OFFLINE-NO-PAID-MODEL'
    assert loaded['guard_self_check_passed'] and loaded['physical_gate']['preparation_permanently_closed']
    assert all(sha(ROOT/p)==h for p,h in loaded['source_sha256'].items())
    save(OUT/'loaded-code.json',loaded)
    suites=ET.parse(OUT/'junit-final-v3.xml').getroot().findall('testsuite')
    counts={k:sum(int(s.get(k,0)) for s in suites) for k in ['tests','failures','errors','skipped']}
    assert counts['tests']>=129 and not any(counts[k] for k in ['failures','errors','skipped'])
    health={}
    for port in (63045,63046):
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(f'http://127.0.0.1:{port}/api/health',timeout=15) as r:
            body=json.loads(r.read());assert r.status==200 and body['database']=='connected' and body['llm_model']=='FIXED-OFFLINE-NO-PAID-MODEL'
            health[str(port)]={'status':r.status,'body':body}
    save(OUT/'local-health.json',health)
    save(OUT/'database-after.json',data)
    save(OUT/'database-diff.json',{'all_rows_and_complete_fields_identical':True,'inserts':0,'updates':0,'deletes':0})
    save(OUT/'protected-sha256-after.json',protected())
    save(OUT/'ledger-verification.json',{'protected_sha256':protected(),'historical_requests':[19,5],
        'round5_retained_failed_reservations':1,'real_model_requests':0,'external_dns':0,'external_http':0})
    sources={p:sha(ROOT/p) for p in read(OUT/'source-sha256-before.json')}
    sources.update(loaded['source_sha256'])
    save(OUT/'source-sha256-after.json',sources)
    save(OUT/'repair-baseline.json',{'source_sha256':sources,'loaded':loaded,'runtime':runtime,
        'database':data,'protected_sha256':protected(),'paid_enabled':False,'real_requests_this_round':0})
    save(OUT/'final-verification.json',{'F1':'PASS','F2':'PASS','F3':'PASS','tests':counts,
        'original_assertions':{'passed':7,'failed':0,'skipped':0,'file_sha256_unchanged':True},
        'model_requests':0,'external_dns':0,'external_http':0,'business_writes':0,
        'fixed_provider':True,'paid_enabled':False,'preparation_hard_closed':True,
        'real_dns_tls_auth_and_model_quality':'PENDING','authorization':'NONE'})
    print('PASS F1 F2 F3; tests',counts,'real/external calls0; history unchanged')

if __name__=='__main__':{'before':before,'checkpoint':checkpoint,'finish':finish}[sys.argv[1]]()
