"""Read-only reconciliation after the single RAG request; no Provider is loaded."""
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    from desktop.postgres import ManagedPostgres, APP_USER
    from desktop.runtime_paths import RuntimePaths
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from scripts.naiwa_closeout_fixtures_20261024 import business_snapshot
    out=ROOT/'storage/quality-audits/naiwa-four-item-closeout-20261024'
    run=ROOT/'storage/quality-audits/naiwa-differentiated-acceptance-20261024/fresh-runtime-closeout1'
    evidence=ROOT/'storage/quality-audits/naiwa-differentiated-acceptance-20261024/D-RAG-1792834260588297900.json'
    def read(p):return json.loads(p.read_text(encoding='utf-8'))
    material=read(run/'rag-material.json');answer=read(evidence)
    stopped=read(run/'postgres-stop-verification.json');assert stopped['stop_verified']
    expected=read(run/'ports-and-database-identity.json')['identity']
    pg=ManagedPostgres(RuntimePaths.windows(resources=ROOT/'backend',
        local_app_data=ROOT/'storage/manual-experience/naiwa-differentiated-test-20261024-r8/owned-pg'),
        Path('C:/Program Files/PostgreSQL/18/bin'),port=expected['port'])
    pg.start()
    try:
        assert pg.owner['cluster_id']==expected['cluster_id']=='75c291dd1be548158fd57c5f03c37e02'
        url=make_url(pg.database_url).set(database=expected['database']).render_as_string(hide_password=False)
        after=business_snapshot(url);before=read(run/'learning-record-authorization.json')['after']
        engine=create_engine(url)
        try:
            with engine.connect() as db:
                db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
                identity=tuple(db.execute(text('SELECT current_database(),current_user,host(inet_server_addr()),inet_server_port()')).one())
                assert identity==(expected['database'],APP_USER,'127.0.0.1',expected['port'])
                chunks={str(row['id']):dict(row) for row in db.execute(text(
                    'SELECT id,material_id,index_version,content,start_offset,end_offset,heading_path FROM document_chunks WHERE material_id=CAST(:m AS uuid)'),{'m':material['material_id']}).mappings()}
                persisted=db.execute(text('SELECT content FROM chat_messages WHERE id=CAST(:id AS uuid)'),
                    {'id':answer['persisted_history'][-1]['message_id']}).scalar_one()
                citation_rows=[dict(row) for row in db.execute(text(
                    'SELECT to_jsonb(c) AS row FROM message_citations c WHERE message_id=CAST(:id AS uuid)'),
                    {'id':answer['persisted_history'][-1]['message_id']}).mappings()]
        finally:engine.dispose()
        frames=answer['turn_evidence'][0]['events']
        done=next(d for n,d in frames if n=='done');stream=''.join(d['text'] for n,d in frames if n=='delta')
        citations=done['citations'];assert citations and citation_rows
        checks=[]
        for citation in citations:
            chunk=chunks[citation['chunk_id']]
            checks.append({'label':citation['label'],'chunk_id':citation['chunk_id'],
                'material_matches':str(chunk['material_id'])==material['material_id']==citation['material_id'],
                'version_matches':chunk['index_version']==material['active_index_version'],
                'offset_matches':chunk['content']==material['normalized_text'][chunk['start_offset']:chunk['end_offset']],
                'heading_matches':chunk['heading_path']==citation['heading_path'],
                'has_expected_marker':'LH-THREE-CONDITIONS-824' in chunk['content'],
                'chunk_content':chunk['content']})
        assert all(all(c[k] for k in ('material_matches','version_matches','offset_matches','heading_matches','has_expected_marker')) for c in checks)
        assert stream==done['answer']==persisted==answer['persisted_history'][-1]['content']
        assert before==after
        ledger=ROOT/'storage/quality-audits/naiwa-freeze-preflight-20261021/round40-v33-exploratory-r8z/provider-ledger.json'
        doc=read(ledger);assert len(doc['requests'])==15 and all(r.get('finished') for r in doc['requests'])
        control=read(ROOT/'storage/quality-audits/naiwa-v33-closeout-20261023/paid-continuation-r8z/control.json')
        assert control.get('paid_enabled') is False
        manifest=read(run/'startup-verification.json')['loaded_code_sha256']
        mismatches=[f for f,h in manifest.items() if hashlib.sha256((ROOT/f).read_bytes()).hexdigest()!=h]
        assert not mismatches
        report={'database_identity':identity,'cluster_id':pg.owner['cluster_id'],'source_epoch':31,
            'loaded_source_matches_workspace':True,'business_before':before,'business_after':after,
            'business_unchanged':True,'citation_checks':checks,'persisted_citations':citation_rows,
            'stream_done_database_history_equal':True,'rag_answer':done['answer'],
            'real_requests_this_closeout':1,'canonical_count':15,'global_remaining':25,
            'ledger_sha256':hashlib.sha256(ledger.read_bytes()).hexdigest(),
            'unfinished_requests':0,'paid_enabled':False,'browser_ui_tested':False}
        with (out/'final-verification.json').open('x',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,indent=2,default=str)
        print(json.dumps({'business_unchanged':True,'citations_checked':len(checks),'canonical_count':15,'paid_enabled':False}))
    finally:
        pg.stop()
        with (out/'readonly-verification-stopped.json').open('x',encoding='utf-8') as f:
            json.dump({'postmaster':pg._identity(),'verified':pg._identity() is None},f)


if __name__=='__main__':main()
