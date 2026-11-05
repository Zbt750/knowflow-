"""Independent remaining-scenes meter. Part 1 is immutable, INCLUDING its failed request.

The failed transport is NOT retried. Its full 8000-output/byte-input monetary
reservation remains charged against the shared 0.50 CNY envelope. This process
can send at most (10 - part1 physical requests), never a fresh allowance.
"""
import hashlib
import json
import os
from decimal import Decimal
from pathlib import Path
from scripts import naiwa_multisurface_20261019 as original

ROOT, OUT = original.ROOT, original.OUT

def app():
    from scripts import phase5_eval_meter as accounting
    first_path=OUT/'provider-ledger.json'
    data=first_path.read_bytes();first=json.loads(data)
    assert len(first['requests'])==4 and all(r.get('finished') for r in first['requests'])
    assert first['requests'][-1]['error_type']=='RemoteProtocolError'
    assert all(r['state'] in {'COMPLETED_USAGE_OBSERVED','ACTUAL_USAGE_UNKNOWN_RESERVATION_RETAINED'} for r in first['requests'])
    remaining=10-len(first['requests'])
    money=Decimal('0.50')-sum(Decimal(str(r['conservative_cny'])) for r in first['requests'])
    token_input=150000-sum((r.get('usage') or {}).get('prompt_tokens',r['input_reservation']) for r in first['requests'])
    token_output=80000-sum((r.get('usage') or {}).get('completion_tokens',r['output_reservation']) for r in first['requests'])
    part=OUT/'remaining-scenes';part.mkdir(exist_ok=True)
    if (part/'provider-ledger.json').exists():
        prior=json.loads((part/'provider-ledger.json').read_text(encoding='utf-8'))
        assert os.environ.get('MULTISURFACE_RESUME_REMAINING')=='1'
        assert prior['limits']['max_requests']==6 and len(prior['requests']) in {3,6}
        assert not prior['stop_reason'] and all(r['state']=='COMPLETED_USAGE_OBSERVED' for r in prior['requests'])
    else:
        (part/'carry-forward.json').write_text(json.dumps({'previous_ledger_sha256':hashlib.sha256(data).hexdigest(),
        'previous_requests':4,'remaining_requests':remaining,'unknown_usage_count':1,
        'retained_conservative_cost_cny':str(Decimal('0.50')-money),'remaining_money_cny':str(money),
            'network_retry':False,'prior_failure_not_erased':True},indent=2),encoding='utf-8')
    real=accounting.Meter
    class RemainingMeter(real):
        def __init__(self, output, **kwargs):
            kwargs.update(max_requests=remaining,max_input_tokens=token_input,max_output_tokens=token_output,stop_cny=str(money))
            super().__init__(output,**kwargs)
        def begin(self,request):
            assert hashlib.sha256(first_path.read_bytes()).hexdigest()==hashlib.sha256(data).hexdigest()
            return super().begin(request)
    accounting.Meter=RemainingMeter
    os.environ['BLIND_LEDGER_LIMIT']='6'
    original.OUT=part
    return original.app()
