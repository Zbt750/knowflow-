"""Zero-network gate regression with all legacy evidence paths redirected.

Does not alter any test assertion. Historical artifact hashes are checked again
after the run; the previously observed drift is recorded rather than concealed.
"""
from pathlib import Path
import contextlib
import hashlib
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT=ROOT/'storage/quality-audits/naiwa-freeze-preflight-20261021/round40-agent-full-v2-20261021'
PROTECTED=ROOT/'storage/quality-audits/naiwa-f123-repair-zero-20261021/protected-sha256-before.json'

def hashes():
    expected=json.loads(PROTECTED.read_text(encoding='utf-8'))
    return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in expected if (ROOT/name).is_file()}

def save(name,value):
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

class ArtifactPaths:
    def pytest_collection_modifyitems(self,session,config,items):
        destinations={Path('storage/quality-audits/naiwa-dns-audit-zero-20261021'):OUT/'test-evidence/dns'}
        for value in destinations.values():value.mkdir(parents=True,exist_ok=True)
        def mapped(*args):
            value=Path(*args)
            return destinations.get(value,value)
        for module in list(sys.modules.values()):
            name=Path(getattr(module,'__file__','') or '').name
            if name=='test_dns_audit_phases.py':module.Path=mapped
            if name=='test_dns_independent_review.py':
                module.OUT=OUT/'test-evidence/independent'
                module.OUT.mkdir(parents=True,exist_ok=True)

if __name__=='__main__':
    import pytest
    label=sys.argv[1] if len(sys.argv)>1 else 'final'
    assert label.replace('-','').isalnum()
    before=hashes()
    save(f'protected-current-before-{label}.json',before)
    expected=json.loads(PROTECTED.read_text(encoding='utf-8'))
    save('historical-evidence-drift.json',{'expected_baseline':str(PROTECTED),
        'mismatches':[{'path':name,'expected_sha256':value,'current_sha256':before.get(name)}
                      for name,value in expected.items() if before.get(name)!=value],
        'restoration_claimed':False})
    with (OUT/f'gate-{label}.log').open('x',encoding='utf-8') as log:
        with contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
            result=pytest.main(['--confcutdir=tests/unit',
                'tests/unit/test_naiwa_agent_full_v2_gate.py','tests/unit/test_final_round_gate.py',
                'tests/unit/test_dns_audit_phases.py','tests/unit/test_dns_independent_review.py',
                'tests/unit/test_isolated_proxy_attribution.py','-q','--tb=short',
                '--junitxml='+str(OUT/f'gate-{label}.xml')],plugins=[ArtifactPaths()])
    after=hashes()
    save(f'protected-current-after-{label}.json',after)
    save(f'gate-{label}-status.json',{'exit_code':int(result),'historical_files_unchanged_during_this_run':before==after,
        'no_real_model_or_external_network_intended':True})
    print((OUT/f'gate-{label}.log').read_text(encoding='utf-8'))
    if before!=after:raise RuntimeError('new_historical_artifact_drift_STOP')
    sys.exit(int(result))
