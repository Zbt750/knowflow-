"""Recover a private historical bank and repair only an identified isolated copy."""
from pathlib import Path
import argparse,json,os,subprocess,sys
from uuid import uuid4
from hashlib import sha256
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def write(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str),encoding='utf-8')


def main():
    p=argparse.ArgumentParser();p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--baseline-only',action='store_true');p.add_argument('--resume',action='store_true')
    args=p.parse_args();out=args.output_dir.resolve()
    if not out.is_relative_to(ROOT/'storage/quality-audits'):raise ValueError('Private output required')
    if not args.resume:out.mkdir(parents=True,exist_ok=False)
    from scripts import run_phase45i_agent_real as owner
    _,cluster,port=owner.load_existing_owner()
    if port!=59227 or port==5433:raise ValueError('Owned isolated port required')
    started=owner.start_owned_database(cluster,port)
    try:
        from psycopg import connect,sql
        from scripts.audit_phase45h_completion_archive import validate_backup,BACKUP,PG_BIN,fingerprints
        if args.resume:
            state=json.loads((out/'owner.json').read_text(encoding='utf-8'));name=state['database']
            if state['port']!=port or not name.startswith('phase45hs_') or not name.endswith('_test'):raise ValueError('Resume ownership mismatch')
        else:
            dump,manifest=validate_backup(BACKUP);name='phase45hs_'+uuid4().hex[:12]+'_test'
            with connect(host='127.0.0.1',port=port,user='postgres',dbname='postgres',autocommit=True,connect_timeout=5) as c:
                if str(c.execute('SELECT system_identifier FROM pg_control_system()').fetchone()[0])!='7694698872540080852':raise ValueError('Cluster identity mismatch')
                c.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(name)))
            state={'database':name,'port':port,'system_identifier':'7694698872540080852','backup_sha256':manifest['database_dump_sha256'],
                'development_5433_touched':False,'paid_calls':0}
            write(out/'owner.json',state)
            with (out/'restore.log').open('w',encoding='utf-8') as log:
                r=subprocess.run([str(PG_BIN/'pg_restore.exe'),'--no-owner','--no-acl','--exit-on-error',
                    '--dbname',f'postgresql://postgres@127.0.0.1:{port}/{name}',str(dump)],stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
            if r.returncode:raise ValueError('Isolated restore failed')
        url=f'postgresql+psycopg://postgres@127.0.0.1:{port}/{name}'
        os.environ.update(APP_ENV='test',DATABASE_URL=url,TEST_DATABASE_URL=url,KAOYAN_OWNED_TEST_PORT=str(port),
            PHASE45I_CLOSE_OFFLINE='1',LLM_API_KEY='',LLM_BASE_URL='http://127.0.0.1:9',LLM_MODEL='offline',
            MODEL_SETTINGS_PATH=str(out/'model-settings.bin'),UPLOAD_DIR=str(out/'uploads'),CHROMA_DIR=str(out/'chroma'),PYTHONIOENCODING='utf-8')
        from scripts.phase45i_offline_guard import install
        install()
        if not args.resume:
            before=fingerprints(url)
            with (out/'migration.log').open('w',encoding='utf-8') as log:
                r=subprocess.run([sys.executable,'-m','alembic','upgrade','head'],env=os.environ.copy(),stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
            if r.returncode:raise ValueError('Isolated migration failed')
            if fingerprints(url)!=before:raise ValueError('Protected history changed during isolated migration')
            write(out/'history-before.json',before)
        from backend.models import import_models
        import_models()
        from backend.db import create_db_engine,create_session_factory
        from backend.models.learning import Question,KnowledgePoint,KpMasteryPolicy
        from backend.services.auto_question_review import question_snapshot_payload
        from backend.services.quality_verifiers import verify_problem
        from backend.services.question_production_pipeline import validate_question_content
        from scripts.run_question_repair_pilot import local_pack_registry
        from scripts.audit_phase45h_completion_archive import source_pack_evidence
        from sqlalchemy import select,text
        engine=create_db_engine(url);factory=create_session_factory(engine)
        try:
            def all_fingerprints():
                with engine.connect() as connection:
                    connection.exec_driver_sql('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                    names=connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")).scalars().all()
                    result={}
                    for table in names:
                        quoted=connection.dialect.identifier_preparer.quote(table)
                        payload=[dict(row) for row in connection.execute(text('SELECT * FROM public.'+quoted+' ORDER BY 1')).mappings()]
                        result[table]={'count':len(payload),'sha256':sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()}
                    return result
            resume_before=all_fingerprints() if args.resume else None
            if not args.resume:
                frozen=ROOT/'storage/quality-audits/phase45d-20261009/diagnosis/inventory-snapshot.json'
                latest=json.loads(frozen.read_text(encoding='utf-8'));latest_by_id={q['id']:q for q in latest['questions']}
                registry,rejected=local_pack_registry(ROOT);rows=[];conflicts=[]
                with factory() as db:
                    nodes={n.id:n for n in db.scalars(select(KnowledgePoint))};qs=list(db.scalars(select(Question).order_by(Question.id)))
                    for q in qs:
                        node=nodes[q.kp_id];payload=question_snapshot_payload(q);snapshot=latest_by_id.get(str(q.id))
                        if snapshot:
                            newer=Question(**{'bank_scope':'public','is_hidden':False,**snapshot})
                            if question_snapshot_payload(newer)!=payload:
                                conflicts.append({'question_id':str(q.id),'backup':payload,'latest':question_snapshot_payload(newer),
                                    'changed_fields':[k for k in payload if payload[k]!=question_snapshot_payload(newer)[k]]})
                        evidence=source_pack_evidence(q,registry,node)
                        rows.append({'question_id':str(q.id),'active':q.is_active,'subject':node.subject,'node_code':node.code,'node_name':node.name,
                            'payload':payload,'original_row':{c.name:getattr(q,c.name) for c in Question.__table__.columns},
                            'source_evidence':evidence,'independent':verify_problem(q),'structure':validate_question_content(q).__dict__})
                    baseline={'revision':db.scalar(text('SELECT version_num FROM alembic_version')),'total':len(qs),'active':sum(q.is_active for q in qs),
                        'inactive':sum(not q.is_active for q in qs),'nodes':len(nodes),'policies':len(list(db.scalars(select(KpMasteryPolicy)))),
                        'source_rows':sum(len(v) for v in registry.values()),'rejected_source_files':rejected,'conflicts':conflicts,'rows':rows,
                        'latest_snapshot_sha256':sha256(frozen.read_bytes()).hexdigest()}
                write(out/'baseline.json',baseline)
                print(json.dumps({k:v for k,v in baseline.items() if k not in {'rows','conflicts'}},ensure_ascii=False));print('payload_conflicts='+str(len(conflicts)))
            if not args.baseline_only:
                from backend.services.public_bank_batch import run_batch_repair
                run_batch_repair(factory,out)
            if resume_before is not None:
                resume_after=all_fingerprints()
                record={'before':resume_before,'after':resume_after,'unchanged':resume_before==resume_after,
                    'changed_tables':[name for name in resume_before if resume_before[name]!=resume_after[name]],'paid_calls':0}
                write(out/('resume-audit-'+uuid4().hex[:8]+'.json'),record)
                print('resume_all_table_unchanged='+str(record['unchanged']),flush=True)
        finally:engine.dispose()
        if fingerprints(url)!=json.loads((out/'history-before.json').read_text(encoding='utf-8')):raise ValueError('Historical data protection failed')
        print('protected_history=unchanged',flush=True)
    finally:
        if started:
            owner.command([str(owner.PG_BIN/'pg_ctl.exe'),'-D',str(cluster),'-m','fast','-w','-t','30','stop'],timeout=40,check=False)
    return 0


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
