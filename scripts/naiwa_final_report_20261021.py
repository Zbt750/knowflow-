"""Read-only closeout after the global stop. No Provider creation or sends."""
from pathlib import Path
import sys,json,shutil,hashlib
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.naiwa_final_real_20261021 import OUT,ROUND,read,verify
from scripts.restore_naiwa_experience_20261020 import RUN,save

current=verify()
baseline=read(OUT/'database-before.json')
save(OUT/'database-after.json',current)
diff={}
for table,old in baseline.items():
    if not isinstance(old,list):continue
    key=lambda r:str(r.get('id',r.get('kp_id')))
    a={key(r):r for r in old};b={key(r):r for r in current[table]}
    diff[table]={'before':len(a),'after':len(b),'new_ids':sorted(b.keys()-a.keys()),
        'removed_ids':sorted(a.keys()-b.keys()),'changed_original_ids':[k for k in a.keys()&b.keys() if a[k]!=b[k]]}
    assert not diff[table]['removed_ids'] and not diff[table]['changed_original_ids']
    assert not diff[table]['new_ids'] or table in {'chat_sessions','chat_messages','learning_tasks'}
save(OUT/'database-diff.json',diff)
ledger=read(ROUND/'provider-ledger.json');control=read(ROUND/'control.json')
assert ledger['requests']==[] and control['paid_enabled'] is False
shutil.copy2(ROUND/'provider-ledger.json',OUT/'provider-ledger.json')
loaded=read(RUN/'loaded-code.json');runtime=read(RUN/'runtime.json')
assert loaded['provider']=='FIXED-OFFLINE-NO-PAID-MODEL'
assert loaded['physical_gate']['preparation_permanently_closed'] and loaded['guard_self_check_passed']
assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in loaded['source_sha256'].items())
save(OUT/'independent-math-review.json',{'status':'BLOCKED','reason':'Agent transport blocked before physical model dispatch; generation scenario not started',
    'generated_question':None,'generated_question_math':None,'difficulty':None,'math_gate_exercised':False,
    'original_question':{'id':'9ba9c177-26a2-4918-bf84-b85159f9b002','version_id':'92c57d4d-f0bf-4df2-b9b2-c949a3d43904',
        'expected_limit':'1/2','independent_basis':'e^x-1-x=x²/2+O(x³); divide by x²'},'real_model_requests':0})
session_id=read(OUT/'sessions.json')['AGENT']
task=next(t for t in current['learning_tasks'] if t['id'] in diff['learning_tasks']['new_ids'])
save(OUT/'agent-task-database.json',task)
save(OUT/'final-verification.json',{'engineering':'PARTIAL','agent_real_quality':'BLOCKED','variant_math':'BLOCKED','variant_difficulty':'BLOCKED',
    'browser':'PARTIAL','data_and_budget':'PASS','real_model_physical_requests':0,'service_provider_attempts':1,
    'remaining_not_reusable_automatically':{'AGENT':4,'GENERATE':1,'total':5},'paid_enabled':False,
    'fixed_provider_restored':True,'runtime':runtime,'loaded_manifest':loaded,'database_identity':current['identity'],
    'all_original_rows_unchanged':True,'daily_paper_practice_attempt_learning_events_unchanged':True,
    'canonical_ledger':str(ROUND/'provider-ledger.json'),'report_ledger_is_readonly_copy':True,
    'old_ledger_sha256_unchanged':read(OUT/'baseline.json')['old_ledger_hashes'],
    'actual_failure_session_id':session_id,'agent_task_id':task['id'],
    'transport_diagnostic':read(OUT/'zero-network-transport-diagnostic.json')})
for name in ['runtime.json','loaded-code.json','backend.log','supervisor.log']:
    shutil.copy2(RUN/name,OUT/('after-'+name))
lines=['# 本轮真实Vue失败会话（数据库只读导出）','',
    '没有DeepSeek回复。下面的助手正文是应用返回的错误提示，不是模型生成内容。','']
for m in sorted((m for m in current['chat_messages'] if m['session_id']==session_id),key=lambda m:m['seq']):
    lines += ['## '+m['role']+' · '+m['status'],'',m['content'],'']
(OUT/'conversation.md').write_text('\n'.join(lines),encoding='utf-8')
print(json.dumps({'engineering':'PARTIAL','model':'BLOCKED','data_budget':'PASS','physical_calls':0,'new_rows':{t:len(v['new_ids']) for t,v in diff.items() if v['new_ids']}}))
