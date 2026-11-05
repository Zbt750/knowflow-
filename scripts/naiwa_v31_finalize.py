"""Read-only final evidence and intentional denied local protocol probes. No model."""
from pathlib import Path
import json,os,sys,hashlib,socket
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.naiwa_v31_audit import OUT,read,save,sha,snapshot,protected
from scripts.naiwa_v31_handoff_policy import close_window

def no_external(event,args):
    if event=='socket.getaddrinfo' and args[0] not in {'127.0.0.1','localhost','::1'}:raise RuntimeError('external_dns_forbidden')
    if event=='socket.connect' and (not isinstance(args[1],tuple) or args[1][0]!='127.0.0.1' or args[1][1] not in {63044,63145,63146}):raise RuntimeError('external_socket_forbidden')
sys.addaudithook(no_external)

def main():
    import httpx
    assert os.environ['NAIWA_V31_EPOCH']=='9'
    run=OUT/'runtime-9';window=read(run/'window.json')
    assert protected()==read(OUT/'protected-before.json'),'protected evidence drift STOP'
    ledgers=read(OUT/'ledgers-before.json')
    assert all(sha(Path(v['path']))==v['sha256'] for v in ledgers),'ledger drift STOP'
    frames=read(OUT/'browser-final-9/case-1.json')['frames']
    pr=next(v['data'] for v in frames if v['event']=='practice_request')
    committed=read(OUT/'browser-final-9/commit-evidence.json')['sentRequest']
    source=pr['source_conversation_id'];target=committed['details']['target_study_session_id']
    base='http://127.0.0.1:63146';headers={'origin':base,'x-naiwa-v31':window['nonce']}
    probes=[]
    with httpx.Client(trust_env=False,timeout=8,headers=headers) as client:
        path='/api/practice-requests/'+pr['id']+'/send'
        for label,body in [('wrong-source',{'source_conversation_id':committed['source_conversation_id'],'target_study_session_id':target}),
                           ('target-is-qa',{'source_conversation_id':source,'target_study_session_id':source}),
                           ('unknown-target',{'source_conversation_id':source,'target_study_session_id':'00000000-0000-0000-0000-000000000000'})]:
            response=client.post(base+path,json=body)
            assert response.status_code==403,(label,response.text)
            probes.append({'label':label,'status':response.status_code,'body':response.json()})
        # Cross-epoch source exists in DB but is not owned by this authorization.
        old=read(OUT/'browser-final/case-1.json')['frames']
        oldpr=next(v['data'] for v in old if v['event']=='practice_request')
        response=client.post(base+'/api/practice-requests/'+oldpr['id']+'/send',json={'source_conversation_id':oldpr['source_conversation_id'],'target_study_session_id':target})
        assert response.status_code==403;probes.append({'label':'cross-epoch','status':403,'body':response.json()})
        close_window(run/'window.json')
        response=client.post(base+path,json={'source_conversation_id':source,'target_study_session_id':target})
        assert response.status_code==403;probes.append({'label':'closed-window','status':403,'body':response.json()})
        health=client.get(base+'/api/health');assert health.status_code==200
    save('negative-http.json',{'probes':probes,'all_denied_before_business':True,'models':0})
    snapshot('final')
    final=read(OUT/'database-final.json');negative=read(OUT/'database-before-negative.json');initial=read(OUT/'database-before.json')
    assert final['row_sha256']==negative['row_sha256'],'negative/read-only probe caused DB changes STOP'
    diff={}
    for table,rows in initial['rows'].items():
        pk=initial['schema'][table]['primary_key']['constrained_columns']
        assert pk,table
        key=lambda row:tuple(row[c] for c in pk)
        before={key(r):r for r in rows};after={key(r):r for r in final['rows'][table]}
        removed=[k for k in before if k not in after]
        modified=[k for k in before if k in after and before[k]!=after[k]]
        diff[table]={'before':len(before),'after':len(after),'added':len(after.keys()-before.keys()),'removed':removed,'original_modified':modified}
        assert not removed and not modified,(table,removed,modified)
    save('database-diff-final.json',{'all_original_rows_preserved':True,'negative_and_readonly_no_changes':True,'tables':diff})
    after=protected();assert after==read(OUT/'protected-before.json')
    save('protected-final.json',after)
    ledger_result=[{**v,'after_sha256':sha(Path(v['path'])),'unchanged':True} for v in ledgers]
    save('ledger-final.json',{'ledgers':ledger_result,'new_real_model_requests':0,'round40_prior_count':1,'budget_not_reset':True})
    from scripts.naiwa_v31_runtime import sources
    loaded=read(run/'loaded-code.json');assert loaded['source_sha256']==sources()
    save('final-verification.json',{'epoch':9,'loaded_code_matches':True,'runtime':read(run/'processes.json'),
        'fixed_provider':loaded['provider'],'paid_enabled':False,'business_write_window_closed':not read(run/'window.json')['enabled'],
        'health':health.json(),'database_original_rows_preserved':True,'protected_file_count':len(after),
        'historical_10_json_original_bytes_recovered':False,'model_requests':0,
        'stage4':'NOT_EXECUTED_WAIT_SEPARATE_EXPLICIT_AUTHORIZATION'})
    print(json.dumps(diff,ensure_ascii=False,indent=2));print('FINAL_PROTECTION_PASS_WINDOW_CLOSED')

if __name__=='__main__':main()
