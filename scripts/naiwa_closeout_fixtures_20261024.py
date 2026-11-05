"""Explicitly authorized fixture ingestion, using local BGE and production worker."""
from pathlib import Path
import asyncio
from dataclasses import asdict
import hashlib
import io
import json
import os
import time


def business_snapshot(database_url):
    from sqlalchemy import create_engine, text
    engine=create_engine(database_url)
    try:
        with engine.connect() as conn:
            conn.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
            tables={}
            for table in ('questions','question_versions','daily_plans','practice_items',
                          'question_attempts','learning_events','learning_tasks','practice_requests'):
                rows=conn.execute(text(f'SELECT to_jsonb(t) FROM public.{table} t ORDER BY id')).scalars().all()
                canonical=json.dumps(rows,sort_keys=True,ensure_ascii=False,default=str).encode()
                tables[table]={'count':len(rows),'sha256':hashlib.sha256(canonical).hexdigest(),'rows':rows}
            return tables
    finally:engine.dispose()


def probe_record_authorization(runtime, *, audit, database_url, api_port, web_port):
    """One normally scoped Agent-setup write. A 403 stops record preparation."""
    import httpx
    from scripts.naiwa_freeze_gate_20261021 import atomic_json
    before=business_snapshot(database_url)
    ledger_before=hashlib.sha256(runtime.LEDGER.read_bytes()).hexdigest()
    if runtime.read(runtime.OUT/'control.json').get('paid_enabled'):
        raise RuntimeError('record_setup_requires_initially_closed_gate')
    nonce=(runtime.RUN/'browser-nonce.txt').read_text(encoding='ascii').strip()
    gate=runtime.paid.gate()
    try:
        atomic_json(runtime.OUT/'control.json',{'paid_enabled':True,'authorization_received':True,
            'active_scene':'E','reason':'authorized_agent_learning_record_preparation',
            'opened_at':time.time(),'scope':'single_scoped_record_preparation'})
        with httpx.Client(trust_env=False,follow_redirects=False,timeout=15) as client:
            response=client.post(f'http://127.0.0.1:{api_port}/api/plans/today/generate',
                headers={'Origin':f'http://127.0.0.1:{web_port}',
                    'X-Naiwa-V2-Scene':'E','X-Naiwa-V2-Nonce':nonce},
                json={'selected_kp_ids':['32a29e1e-8ae3-41fc-9322-43f727596819'],'budget':'light'})
        after=business_snapshot(database_url)
        ledger_after=hashlib.sha256(runtime.LEDGER.read_bytes()).hexdigest()
        payload={'purpose':'isolated Agent learning-record preparation','http_status':response.status_code,
            'response':response.json(),'scene':'E','authorization_active':True,
            'route':'POST /api/plans/today/generate','before':before,'after':after,
            'business_unchanged':before==after,'ledger_unchanged':ledger_before==ledger_after,
            'ledger_sha256_before':ledger_before,'ledger_sha256_after':ledger_after,
            'followup_writes_attempted':False,'real_model_requests':0,
            'result':'BLOCKED' if response.status_code==403 else 'NOT_PREPARED'}
        with (audit/'learning-record-authorization.json').open('x',encoding='utf-8') as out:
            json.dump(payload,out,ensure_ascii=False,indent=2,default=str)
        if before!=after or ledger_before!=ledger_after:
            raise RuntimeError('unexpected_record_setup_side_effect_stop')
    finally:gate.seal('learning_record_preparation_finished_closed')


def prepare_material(factory, *, data_home: Path, audit: Path):
    if os.environ.get('APP_ENV')!='test' or os.environ.get('HF_HUB_OFFLINE')!='1':
        raise RuntimeError('fixture_requires_isolated_offline_setup')
    from starlette.datastructures import UploadFile
    from backend.config import get_settings
    from backend.services.material_service import create_material_record
    from backend.jobs.runner import MaterialJobRunner
    from backend.models.rag import Material, DocumentChunk
    from backend.retrieval.stack import build_retrieval_stack
    from sqlalchemy import select
    root=Path(__file__).resolve().parents[1]
    source=root/'tests/fixtures/naiwa_closeout_lhopital_20261024.md'
    raw=source.read_bytes()
    get_settings.cache_clear();settings=get_settings()
    stack=build_retrieval_stack(embedding_model=settings.embedding_model,reranker_model=settings.reranker_model,
        chroma_dir=data_home/'chroma',model_cache_dir=root/'storage/models')
    if not stack.available:raise RuntimeError('local_retrieval_stack_unavailable:'+str(stack.unavailable_reason))
    try:
        with factory.begin() as db:
            created=asyncio.run(create_material_record(db,upload=UploadFile(io.BytesIO(raw),filename=source.name),
                title='TEST_FIXTURE 洛必达资料验收 20261024',materials_root=data_home/'uploads',source_type='user'))
        runner=MaterialJobRunner(session_factory=factory,stack=stack,materials_root=data_home/'uploads')
        jobs=runner.run_once()
        if len(jobs)!=1 or jobs[0].status!='succeeded':raise RuntimeError('fixture_ingest_failed:'+str(jobs))
        with factory() as db:
            material=db.get(Material,created.material_id)
            chunks=list(db.scalars(select(DocumentChunk).where(DocumentChunk.material_id==material.id).order_by(DocumentChunk.ordinal)))
            assert material.status=='ready' and material.active_index_version and chunks
            assert all(c.content==material.normalized_text[c.start_offset:c.end_offset] for c in chunks)
            payload={'fixture':True,'external_embedding_calls':0,'embedding_model':settings.embedding_model,
                'reranker_model':settings.reranker_model,'source_path':str(source),'source_sha256':hashlib.sha256(raw).hexdigest(),
                'material_id':str(material.id),'title':material.title,'status':material.status,
                'content_hash':material.content_hash,'active_index_version':material.active_index_version,
                'normalized_text':material.normalized_text,'vector_count':stack.vector_store.count(),
                'jobs':[asdict(j) for j in jobs],
                'chunks':[{'chunk_id':str(c.id),'ordinal':c.ordinal,'content':c.content,
                    'heading_path':c.heading_path,'start_offset':c.start_offset,'end_offset':c.end_offset,
                    'index_version':c.index_version} for c in chunks]}
        with (audit/'rag-material.json').open('x',encoding='utf-8') as out:
            json.dump(payload,out,ensure_ascii=False,indent=2,default=str)
        return payload
    finally:
        stack.vector_store.close()
