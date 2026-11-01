"""Archive actual isolated evidence and READ the retained experience DB. No models."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
OUT=ROOT/'storage/quality-audits/naiwa-scope-math-zero-20261021-v9'
OLD=ROOT/'storage/quality-audits/naiwa-real-20261020'
REAL=ROOT/'storage/quality-audits/naiwa-real-retest-20261020-budget7'
def load(path):return json.loads(path.read_text(encoding='utf-8'))
def save(name,data):(OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
def main():
    summary=load(OUT/'run-summary.json')
    assert all(r['exit_code']==0 for r in summary['checks'])
    assert '144 passed' in (OUT/'pytest.log').read_text(encoding='utf-8')
    browser=load(OUT/'browser-report.json');assert browser['stats']['expected']==3 and browser['stats']['unexpected']==0
    ledgers=[OLD/'provider-ledger.json',REAL/'provider-ledger.json']
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in ledgers}
    assert [len(load(p)['requests']) for p in ledgers]==[19,5]
    backup=ROOT/'storage/quality-audits/naiwa-restore-20261020/previous-evidence/provider-ledger.json'
    assert hashlib.sha256(backup.read_bytes()).hexdigest()==hashes[str(ledgers[0].relative_to(ROOT))]
    from scripts.restore_naiwa_experience_20261020 import snapshot,TABLES,RUN
    current=json.loads(json.dumps(snapshot('scope-math-preservation-final'),default=str))
    before=load(REAL/'database-after-real.json')
    preserved={}
    for table in TABLES:
        old={str(r.get('id',r.get('kp_id'))):r for r in before[table]}
        new={str(r.get('id',r.get('kp_id'))):r for r in current[table]}
        preserved[table]={'before':len(old),'after':len(new),'unchanged':old==new}
    assert all(r['unchanged'] for r in preserved.values()),preserved
    assert all(hashlib.sha256(p.read_bytes()).hexdigest()==hashes[str(p.relative_to(ROOT))] for p in ledgers)
    control=load(REAL/'control.json');assert control['paid_enabled'] is False
    loaded=load(RUN/'loaded-code.json')
    save('history-preservation.json',{'identity':current['identity'],'tables':preserved,'ledger_sha256':hashes,
        'historical_model_counts':[19,5],'this_run_real_model_requests':0,'paid_enabled':False,
        'retained_experience_not_restarted':True,'retained_experience_loaded_before_this_fix':True,
        'retained_provider':loaded['provider']})
    scopes=[]
    for index in range(6):
        data=load(OUT/f'database-scope-{index}.json');task=data['learning_tasks'][-1]
        # Select the task by maximal number of existing tasks in the explicit
        # browser step, not by UUID order or a guessed knowledge-node name.
        task=max(data['learning_tasks'],key=lambda row:row['created_at']) if 'created_at' in task else task
        # Snapshots omit mixin columns? Select by the latest message's persisted pointer.
        messages=sorted(data['chat_messages'],key=lambda m:m['seq'])
        task_id=next((m['metadata'].get('planner_task_id') for m in reversed(messages) if m['metadata'].get('planner_task_id')),None)
        task=next(t for t in data['learning_tasks'] if t['id']==task_id)
        stock=next(t['result'] for t in task['trace'] if t['tool']=='get_question_availability')
        state=next(t['result'] for t in task['trace'] if t['tool']=='get_learning_state')
        scopes.append({'step':index,'goal':task['goal'],'status':task['status'],
            'scope':task['context']['planner_handoff'],'inventory_scope_node_ids':stock['scope_node_ids'],
            'inventory_node_names':[n['name'] for n in stock['eligible_nodes']],
            'practice_eligible_count':stock['practice_eligible_count'],
            'learning_state_node_ids':[s['kp_id'] for s in state['states']],
            'final_answer':task['message']})
    save('scope-tool-comparison.json',scopes)
    def counts(data):return {t:len(data[t]) for t in ('questions','question_versions','practice_items','question_attempts','learning_events','daily_plans')}
    bad_before,bad_after=[load(OUT/f'database-bad-{stage}.json') for stage in ('before','after')]
    good_before,good_after=[load(OUT/f'database-good-{stage}.json') for stage in ('before','after')]
    assert counts(bad_before)==counts(bad_after)
    new=[q for q in good_after['questions'] if q['id'] not in {p['id'] for p in good_before['questions']}]
    assert len(new)==1
    q=new[0];assert q['grading_config']['generation']['bounded_calculus_check']['expected']=='0'
    save('math-persistence-proof.json',{'mode':'historical real failure replay and independently derived fixed correct response',
        'wrong_counts_before':counts(bad_before),'wrong_counts_after':counts(bad_after),
        'correct_counts_before':counts(good_before),'correct_counts_after':counts(good_after),'saved_question':q,
        'real_model_quality':'PENDING','real_model_calls_this_run':0})
    shots=OUT/'screenshots';shots.mkdir(exist_ok=True)
    paths=[]
    for name in ['scope-0.png','scope-1.png','scope-2.png','scope-3.png','scope-4.png','scope-5.png','scope-refresh.png','bad-rejected-refresh.png','good-reference-saved.png']:
        matches=list((OUT/'browser-artifacts').rglob(name));assert len(matches)==1,(name,matches)
        shutil.copy2(matches[0],shots/name);paths.append(str((shots/name).relative_to(ROOT)))
    save('screenshots.json',paths)
    print(json.dumps({'backend_passed':144,'chrome_passed':3,'real_requests':0,'historical_rows_unchanged':True,'counts_bad':counts(bad_after),'saved_question_id':q['id']},ensure_ascii=False))
if __name__=='__main__':main()
