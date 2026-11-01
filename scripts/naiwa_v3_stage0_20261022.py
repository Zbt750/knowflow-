"""Read-only V3 preflight. Never constructs a gate or a model client.

All artifacts are exclusive-create inside a fresh directory; old evidence and
ledgers are inputs only. Only owned local PostgreSQL and health GETs are used.
"""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
V2 = ROOT / 'storage/quality-audits/naiwa-freeze-preflight-20261021/round40-agent-full-v2-20261021'
HOME = ROOT / 'storage/manual-experience/naiwa-real-20261020'
TASK = Path(r'C:\Users\ZBT\.codex\attachments\41d2d52c-25f9-4867-aa6c-71061a86ce1d\已粘贴的文本.txt')


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    out = ROOT / 'storage/quality-audits' / ('naiwa-v3-stage0-' + stamp)
    out.mkdir(exist_ok=False)
    def save(name, value):
        with (out / name).open('x', encoding='utf-8') as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, default=str)
    # Protect current bytes, including the known incident, not invented originals.
    historical = [ROOT/'storage/quality-audits'/name for name in (
        'naiwa-dns-audit-zero-20261021', 'naiwa-dns-independent-review-20261021',
        'naiwa-f123-repair-zero-20261021')]
    protected_paths = sorted(set([p for d in historical for p in d.rglob('*') if p.is_file()]
        + [p for p in V2.rglob('*') if p.is_file()]))
    before = {p.relative_to(ROOT).as_posix(): sha(p) for p in protected_paths}
    save('protected-before.json', before)
    blockers = []
    try:
        import httpx
        from scripts.naiwa_agent_full_v2_20261021 import (
            OLD_LEDGERS, source_hashes, snapshot_database, _row_multiset)
        from scripts.restore_naiwa_experience_20261020 import existing_manager
        runtime = read(HOME/'restored-offline-20261020/runtime.json')
        loaded = read(HOME/'restored-offline-20261020/loaded-code.json')
        active = read(HOME/'agent-full-v2-20261021/active-source-hashes.json')
        baseline = read(V2/'v2-baseline.json')
        current = source_hashes()
        loaded_drift = [{'path':name, 'loaded':value, 'current':sha(ROOT/name)}
            for name,value in loaded['source_sha256'].items() if sha(ROOT/name)!=value]
        old_launcher_drift = [{'path':name,'old_baseline':value,'current':current.get(name)}
            for name,value in active['source_sha256'].items() if current.get(name)!=value]
        save('source-verification.json', {'loaded_manifest':loaded,
            'current_source_hashes':current,'loaded_source_drift':loaded_drift,
            'old_v2_source_epoch':active['epoch'],'old_v2_launcher_drift':old_launcher_drift})
        if loaded_drift:
            blockers.append('RUNNING_FIXED_SOURCE_HASH_MISMATCH')
            raise RuntimeError('running source identity does not match; STOP')
        ps = r"""$ports=@(63044,63045,63046,5433,8000,5173); $l=@(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object {$_.LocalPort -in $ports} | Select-Object LocalAddress,LocalPort,OwningProcess); $ids=@($l.OwningProcess)+@(44512); $p=@($ids | Sort-Object -Unique | ForEach-Object {Get-CimInstance Win32_Process -Filter ('ProcessId='+$_) | Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine,CreationDate}); @{listeners=$l;processes=$p} | ConvertTo-Json -Depth 5"""
        processes=json.loads(subprocess.check_output(['powershell','-NoProfile','-Command',ps],encoding='utf-8-sig'))
        save('processes.json',processes)
        for port,key in ((63044,'postgres_pid'),(63045,'backend_pid'),(63046,'frontend_pid')):
            owners={r['OwningProcess'] for r in processes['listeners'] if r['LocalPort']==port}
            assert owners=={runtime[key]}, f'port identity mismatch:{port}'
        for key in ('backend_pid','frontend_pid'):
            proc=next(p for p in processes['processes'] if p['ProcessId']==runtime[key])
            assert proc['ParentProcessId']==runtime['supervisor_pid']
        assert loaded['pid']==runtime['backend_pid']
        assert runtime['cluster_id']=='eb3800c77c3c40f6ac12eb21112df36c'
        pg=existing_manager()
        identity=pg._identity()
        assert identity and identity[0]==runtime['postgres_pid']
        assert pg.owner['cluster_id']==runtime['cluster_id']
        health={}
        with httpx.Client(trust_env=False,timeout=8,follow_redirects=False) as client:
            for port in (63045,63046):
                response=client.get(f'http://127.0.0.1:{port}/api/health')
                health[str(port)]={'status':response.status_code,'body':response.json(),
                    'backend_pid':response.headers.get('x-naiwa-backend-pid')}
                assert response.status_code==200
                assert response.json()['database']=='connected'
                assert response.headers.get('x-naiwa-backend-pid')==str(runtime['backend_pid'])
        save('health.json',health)
        assert loaded['provider']=='FIXED-OFFLINE-NO-PAID-MODEL'
        assert loaded['physical_gate']['preparation_permanently_closed']
        assert loaded['guard_self_check_passed']
        db=snapshot_database(out/'database-before.json',allow_live_identity=identity)
        previous=read(V2/'database-after-fixed-restore.json')
        tables=[name for name,rows in db.items() if isinstance(rows,list)]
        db_diff={name:{'before_rows':len(previous.get(name,[])),'current_rows':len(db[name]),
            'identical_complete_rows':_row_multiset(previous.get(name,[]))==_row_multiset(db[name])}
            for name in tables}
        save('historical-database-verification.json',db_diff)
        if not all(v['identical_complete_rows'] for v in db_diff.values()):
            blockers.append('UNEXPECTED_HISTORY_DATABASE_CHANGE')
            raise RuntimeError('history database drift; STOP')
        ledgers=[]
        for p in [*OLD_LEDGERS,V2/'provider-ledger.json']:
            doc=read(p)
            relative=p.relative_to(ROOT).as_posix()
            expected=baseline['old_ledger_sha256'].get(relative)
            if p==V2/'provider-ledger.json': expected=sha(V2/'A1-ledger-original.json')
            assert sha(p)==expected, 'ledger hash changed:'+relative
            ledgers.append({'path':relative,'sha256':sha(p),'expected_sha256':expected,
                'reservations':len(doc['requests']),'stop_reason':doc.get('stop_reason'),
                'summary':doc.get('summary'),'scene_limits':doc.get('scene_limits'),
                'requests':[{'id':r.get('request_id'),'scene':r.get('case_id'),
                    'state':r.get('state'),'finished':r.get('finished'),
                    'http_status':r.get('http_status'),'dispatch_attempts':r.get('http_dispatch_attempts'),
                    'finish_reason':r.get('finish_reason'),'usage':r.get('usage'),
                    'phases':r.get('phases')} for r in doc['requests']]})
        save('ledger-verification.json',{'ledgers':ledgers,'authorized_phase_max':40,
            'existing_v2_reservations':1,'remaining_conservative_ceiling':39,
            'new_v3_requests':0,'no_new_ledger_created':True})
        incident=read(V2/'history-preservation-incident.json')
        checks=[dict(row,unchanged_since_incident=(sha(ROOT/row['path'])==row['current_sha256']))
            for row in incident['files']]
        assert all(r['unchanged_since_incident'] for r in checks),'incident files changed again'
        save('evidence-integrity-incident.json',{'cause_owner':'previous agent test execution, not business code or user',
            'status':'FORMALLY_RECORDED_NOT_RECOVERED','original_record_sha256':sha(V2/'history-preservation-incident.json'),
            'files':checks,'original_hashes_not_rewritten':True,'original_bytes_restored':False})
        v2doc=read(V2/'provider-ledger.json')
        control=read(V2/'control.json')
        round5_control=read(OLD_LEDGERS[2].parent/'control.json')
        assert not control['paid_enabled'] and not round5_control['paid_enabled']
        save('runtime-admission.json',{'fixed_provider_runtime':runtime,
            'provider_real_egress_closed':True,'v2_control':control,'round5_control':round5_control,
            'running_gate_is_preparation_only_round5':True,
            'v2_launcher_source_baseline_stale':bool(old_launcher_drift),
            'v2_A_cap':v2doc['scene_limits']['A'],'v3_A_cap_required':3,
            'v3_runtime_registered':False,
            'current_working_directory_evidence':'startup manifest and process command; no direct OS cwd read',
            'socket_audit_evidence':'loaded process startup self-check; no fresh network probes'})
        # Never reuse old startup or silently change ledger limits/baseline.
        if old_launcher_drift: blockers.append('OLD_REAL_LAUNCHER_BASELINE_STALE')
        if v2doc['scene_limits']['A']!=3: blockers.append('EXISTING_SCENE_POLICY_NOT_V3_A3')
        blockers.append('NO_CURRENT_V3_CONTROLLED_RUNTIME_BOUND_TO_EXISTING_LEDGER')
        after_db=snapshot_database(out/'database-after.json',allow_live_identity=identity)
        save('database-diff.json',{'all_rows_identical':db==after_db,
            'writes_performed':False,'read_only_transactions':True})
        assert db==after_db,'preflight changed database'
        save('current-baseline.json',{'timestamp':stamp,'attachment_sha256':sha(TASK),
            'workspace':str(ROOT),'source_sha256':current,'runtime_manifest_sha256':sha(HOME/'restored-offline-20261020/runtime.json'),
            'loaded_manifest_sha256':sha(HOME/'restored-offline-20261020/loaded-code.json'),
            'cluster_id':runtime['cluster_id'],'db_identity':db['identity'],
            'model_exit':'closed','real_model_readiness':'BLOCKED','blockers':blockers,
            'physical_requests_new_v3':0,'prior_v2_physical_requests':1,'budget_ceiling_remaining':39})
    except Exception as exc:
        blockers.append('PREFLIGHT_EXCEPTION:'+type(exc).__name__)
        save('failure.json',{'type':type(exc).__name__,'message':str(exc),
            'real_requests':0,'no_restart_or_gate_enable_attempted':True})
    after={p.relative_to(ROOT).as_posix():sha(p) for p in protected_paths}
    save('protected-after.json',after)
    changed=[name for name,value in before.items() if after.get(name)!=value]
    if changed:blockers.append('UNEXPECTED_PROTECTED_ARTIFACT_CHANGE')
    save('final-verification.json',{'phase':'0','status':'BLOCKED' if blockers else 'READY',
        'blockers':blockers,'protected_file_count':len(before),'protected_drift':changed,
        'new_real_model_requests':0,'services_restarted':False,'business_writes':False,
        'old_evidence_overwritten':False,'old_ledgers_mutated':False})
    print(json.dumps({'audit_directory':str(out),'blockers':blockers,'protected_drift':changed,
        'real_model_requests':0},ensure_ascii=False))


if __name__=='__main__':main()
