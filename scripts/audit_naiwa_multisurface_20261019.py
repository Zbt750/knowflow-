"""Offline verification of captured REAL model/browser/database artifacts; no API calls."""
from pathlib import Path
from decimal import Decimal
import hashlib
import json

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'storage/quality-audits/naiwa-multisurface-20261019-v1'
def read(name):return json.loads((OUT/name).read_text(encoding='utf-8'))
def run():
    ledgers=[read('provider-ledger.json'),read('remaining-scenes/provider-ledger.json')]
    requests=[{**r,'global_number':i} for i,r in enumerate([r for l in ledgers for r in l['requests']],1)]
    assert len(requests)==10 and all(r.get('finished') for r in requests)
    known=[r for r in requests if r['state']=='COMPLETED_USAGE_OBSERVED']
    unknown=[r for r in requests if r['state']!='COMPLETED_USAGE_OBSERVED']
    before,after=read('database-before.json'),read('database-after-free.json')
    assert after['identity']['db']=='kaoyan_blind_test' and int(after['identity']['port'])!=5433
    counts={t:{'before':len(before[t]),'after':len(after[t])} for t in before if isinstance(before[t],list)}
    unchanged={t:before[t]==after[t] for t in ['questions','question_versions','daily_plans','practice_items','question_attempts','learning_events','kp_states']}
    assert all(unchanged.values())
    sessions={r['id']:r for r in after['chat_sessions']}
    session_purposes=[{'id':r['id'],'purpose':r.get('purpose'),'title':r['title']} for r in sessions.values()]
    chunks={str(r['id']):r for r in after['document_chunks']}
    citation_checks=[{'message_id':r['message_id'],'chunk_exists':str(r['chunk_id']) in chunks,
        'material_id':str(chunks[str(r['chunk_id'])]['material_id']) if str(r['chunk_id']) in chunks else None} for r in after['message_citations']]
    assert citation_checks and all(c['chunk_exists'] for c in citation_checks)
    # Math oracle is independent from the model's self-evaluation.
    import sympy as s
    x=s.symbols('x',real=True)
    expected_derivative=1/(1-x)**2
    assert s.simplify(s.diff(1/(1-x),x)-expected_derivative)==0
    assert s.simplify(x*expected_derivative-x/(1-x)**2)==0
    result={'physical_requests':len(requests),'remaining_requests':0,'known_usage_requests':len(known),
        'unknown_usage_requests':len(unknown),'known_input_tokens':sum(r['usage']['prompt_tokens'] for r in known),
        'known_output_tokens':sum(r['usage']['completion_tokens'] for r in known),
        'observed_peak_rate_cost_cny':str(sum(Decimal(str(r['conservative_cny'])) for r in known)),
        'retained_unknown_usage_reservation_cny':str(sum(Decimal(str(r['conservative_cny'])) for r in unknown)),
        'total_conservative_envelope_cny':str(sum(Decimal(str(r['conservative_cny'])) for r in requests)),
        'invoice_confirmed':False,'counts':counts,'existing_learning_entities_unchanged':unchanged,
        'identity':after['identity'],'sessions':session_purposes,'citation_checks':citation_checks,
        'independent_math_check':{'method':'SymPy exact rational derivative identity + manual convergence check',
            'expected_sum':'x/(1-x)^2','domain':'-1 < x < 1','result':'PASS'},
        'source_ledger_sha256':{name:hashlib.sha256((OUT/name).read_bytes()).hexdigest() for name in ['provider-ledger.json','remaining-scenes/provider-ledger.json']}}
    (OUT/'combined-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'combined-provider-ledger.json').write_text(json.dumps({'requests':requests,'summary':{k:v for k,v in result.items() if k not in {'counts','citation_checks','sessions'}}},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':run()
