"""Validate real browser captures from the owned DB. No network or DB connections."""
from pathlib import Path
import base64,json
import sympy as s

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'storage/quality-audits/zero-paid-ux-20261019'
def run(report_path=None, output_root=None):
    # Re-audits must read the current run, never silently reuse older evidence.
    output_root=Path(output_root) if output_root else OUT
    report_path=Path(report_path) if report_path else OUT/'browser-ui-confirmed/browser-report.json'
    report=json.loads(report_path.read_text(encoding='utf-8'))
    specs=[spec for suite in report['suites'] for spec in suite.get('specs',[])]
    test=next(spec for spec in specs if '当前版本生题' in spec['title'])
    result=test['tests'][0]['results'][-1]
    assert result['status']=='passed',result['status']
    captures={a['name']:json.loads(base64.b64decode(a['body'])) for a in result['attachments'] if a.get('contentType')=='application/json'}
    before,saved,added,done,final=[captures['database-'+n] for n in ['before','saved-not-added','added','attempt-event','final']]
    q=next(q for q in saved['questions'] if not any(b['id']==q['id'] for b in before['questions']))
    version=next(v for v in saved['question_versions'] if v['id']==q['current_version_id'])
    item=next(i for i in added['practice_items'] if i['question_id']==q['id'])
    attempt=next(a for a in done['question_attempts'] if a['practice_item_id']==item['id'])
    events=[e for e in done['learning_events'] if e['question_version_id']==version['id']]
    assert q['kp_id']==version['kp_id']==item['kp_id']==attempt['kp_id']
    assert item['question_version_id']==attempt['question_version_id']==version['id']
    assert len(events)==1 and attempt['objective_result']=='unknown'
    assert len(saved['practice_items'])==len(before['practice_items'])
    assert len(final['practice_items'])==len(before['practice_items'])+1
    assert len([i for i in final['practice_items'] if i['question_id']==q['id']])==1
    assert len([a for a in final['question_attempts'] if a['question_id']==q['id']])==1
    assert next(i for i in done['practice_items'] if i['id']==item['id'])['answer_revealed_at']
    assert final['blocked_network']==[] and final['real_model_http_requests']==0
    x=s.Symbol('x')
    assert s.simplify(x*s.diff(x/(1-x)**2,x)-x*(1+x)/(1-x)**3)==0
    output={'simulation':True,'real_deepseek_physical_requests':0,'question_id':q['id'],'question_version_id':version['id'],
        'practice_item_id':item['id'],'question_attempt_id':attempt['id'],'learning_event_id':events[0]['id'],
        'knowledge_node_id':q['kp_id'],'objective_result':attempt['objective_result'],
        'grading_evidence':attempt['grading_evidence'],'source_question_version_in_request':saved['fixed_provider_requests'][0]['reference'],
        'counts':{name:{'before':len(before[name]),'after':len(final[name])} for name in ['questions','question_versions','practice_items','question_attempts','learning_events','daily_plans']},
        'model_response_independently_checked':'x*d[x/(1-x)^2]/dx = x(1+x)/(1-x)^3, |x|<1',
        'not_a_production_mathematical_certificate':True,
        'qa_study_purposes':[{'id':r['id'],'purpose':r['purpose']} for r in final['chat_sessions']],
        'network_transport_blocked_attempts':final['blocked_network'],
        'browser_test_statuses':[{'title':spec['title'],'status':spec['tests'][0]['results'][-1]['status']} for spec in specs]}
    (output_root/'closed-loop-database-proof.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in output.items() if k not in {'grading_evidence','source_question_version_in_request'}},ensure_ascii=True,indent=2))
if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--input-report',type=Path)
    parser.add_argument('--output-root',type=Path)
    args=parser.parse_args()
    run(args.input_report,args.output_root)
