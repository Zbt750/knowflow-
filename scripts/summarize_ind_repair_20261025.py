"""Summarize recorded runs only; no application/database/network operations."""
from pathlib import Path
import hashlib,json,xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'storage/quality-audits/naiwa-ind-repair-20261025'
def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def main():
    def counts(path):
        cases=list(ET.parse(path).getroot().iter('testcase'))
        failed=sum(c.find('failure') is not None or c.find('error') is not None for c in cases)
        skipped=sum(c.find('skipped') is not None for c in cases)
        return {'tests':len(cases),'passed':len(cases)-failed-skipped,'failed':failed,'skipped':skipped}
    frontend=read(OUT/'frontend-ready/run.json');backend=read(OUT/'backend-final/run.json')
    current={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in frontend['source_after']}
    assert current==frontend['source_after']
    assert all(current[p]==digest for p,digest in backend['source_after'].items() if p.startswith('backend/') or p.startswith('tests/'))
    pg=read(OUT/'backend-final/pg/run-summary.json')
    guard=read(OUT/'backend-final/pg/offline-network-guard.json')
    protected=read(OUT/'independent-reports-sha256.json')
    assert all(hashlib.sha256((ROOT/'storage/quality-audits/naiwa-independent-acceptance-20261025'/row['file']).read_bytes()).hexdigest().upper()==row['sha256'] for row in protected)
    result={'frontend':counts(OUT/'frontend-ready/vitest.xml'),'postgres':counts(OUT/'backend-final/pg/pytest-junit.xml'),
        'source_sha256':current,'postgres_identity':pg['database_identity'],'temporary_postgres_stopped':pg['temporary_postgres_stopped'],
        'original_cluster_touched':pg['original_cluster_touched'],'network_guard':guard,'real_model_requests':0,'browser_operations':0,
        'historical_independent_reports_unchanged':True,'deployment':'not deployed; old station backend retained',
        'frontend_commands':frontend['runs'],'backend_commands':backend['runs']}
    with (OUT/'final-verification-ready.json').open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({k:result[k] for k in ['frontend','postgres','temporary_postgres_stopped','real_model_requests','browser_operations']}))
if __name__=='__main__':main()
