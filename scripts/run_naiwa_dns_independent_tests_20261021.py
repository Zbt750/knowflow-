"""Preserve old audit outputs while executing unchanged acceptance assertions."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
OUT=ROOT/'storage/quality-audits/naiwa-dns-independent-review-20261021'
import pytest

class EvidenceOnlyRedirect:
    def pytest_collection_modifyitems(self,session,config,items):
        # Prior test helpers emit evidence to a hardcoded historical directory.
        # Redirect only those artifact Paths, never production/test conditions.
        old=Path('storage/quality-audits/naiwa-dns-audit-zero-20261021')
        new=OUT/'baseline-test-evidence';new.mkdir(exist_ok=True)
        def artifact_path(*parts):
            value=Path(*parts)
            return new if value==old else value
        for module in list(sys.modules.values()):
            if Path(getattr(module,'__file__','') or '').name=='test_dns_audit_phases.py':
                module.Path=artifact_path

if __name__=='__main__':
    args=['--confcutdir=tests/unit','tests/unit/test_dns_audit_phases.py',
        'tests/unit/test_final_round_gate.py','tests/unit/test_isolated_proxy_attribution.py',
        'tests/unit/test_agent_tool_context.py','tests/unit/test_learning_task_evidence_guards.py',
        'tests/unit/test_dns_independent_review.py','-q','--tb=short',
        '--junitxml='+str(OUT/'junit-all.xml')]
    sys.exit(pytest.main(args,plugins=[EvidenceOnlyRedirect()]))
