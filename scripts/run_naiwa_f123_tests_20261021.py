"""Redirect evidence only; never change original F1/F2/F3 assertions."""
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
OUT=ROOT/'storage/quality-audits/naiwa-f123-repair-zero-20261021'
import pytest
class Artifacts:
    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self,item,call):
        outcome=yield
        report=outcome.get_result()
        if report.when=='call' and report.failed:
            gate=item.funcargs.get('gate')
            if gate is not None:
                name=item.name.replace('/','_').replace(':','_')
                value={'records':gate.records,'control':json.loads(gate.control.read_text()),'failure':str(call.excinfo.value)}
                (OUT/('failed-state-'+name+'.json')).write_text(json.dumps(value,indent=2,default=str),encoding='utf-8')
    def pytest_collection_modifyitems(self,session,config,items):
        paths={Path('storage/quality-audits/naiwa-dns-audit-zero-20261021'):OUT/'dns-evidence'}
        for p in paths.values():p.mkdir(exist_ok=True)
        def mapped(*args):
            p=Path(*args);return paths.get(p,p)
        for m in list(sys.modules.values()):
            name=Path(getattr(m,'__file__','') or '').name
            if name=='test_dns_audit_phases.py':m.Path=mapped
            if name=='test_dns_independent_review.py':m.OUT=OUT/'original-evidence';m.OUT.mkdir(exist_ok=True)
if __name__=='__main__':
    group=sys.argv[1]
    if group in {'F1','F2','F3'}:
        args=['tests/unit/test_dns_independent_review.py','-k',{'F1':'revoked_ticket','F2':'dns_multicast','F3':'visual_payload'}[group]]
    else:args=['tests/unit/test_dns_independent_review.py','tests/unit/test_dns_audit_phases.py',
        'tests/unit/test_final_round_gate.py','tests/unit/test_isolated_proxy_attribution.py',
        'tests/unit/test_agent_tool_context.py','tests/unit/test_learning_task_evidence_guards.py',
        'tests/unit/test_f123_transport_guards.py']
    suffix=sys.argv[2] if len(sys.argv)>2 else group
    code=pytest.main(['--confcutdir=tests/unit',*args,'-q','--tb=short','--junitxml='+str(OUT/('junit-'+suffix+'.xml'))],plugins=[Artifacts()])
    (OUT/('exit-'+suffix+'.json')).write_text(json.dumps({'pytest_exit':int(code),'group':group}),encoding='utf-8')
    sys.exit(code)
