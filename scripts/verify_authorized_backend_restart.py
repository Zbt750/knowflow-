"""Read-only before/after checks for the user-authorized 8000 restart."""
import argparse
import json
from datetime import datetime,timezone
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['before','after']);args=parser.parse_args()
    from backend.config import get_settings
    from backend.services.model_settings_service import load_local_settings
    from sqlalchemy import create_engine,text
    from sqlalchemy.engine import make_url
    settings=load_local_settings(get_settings());url=make_url(str(settings.active_database_url))
    assert (url.host,url.port,url.database,url.username)==('127.0.0.1',5433,'kaoyan','kaoyan')
    output=ROOT/'storage/quality-audits/authorized-backend-restart-20261019'
    output.mkdir(parents=True,exist_ok=True)
    path=output/f'{args.stage}.json'
    assert not path.exists(),'never overwrite restart evidence'
    engine=create_engine(url,connect_args={'connect_timeout':5})
    tables=['questions','question_versions','personal_generation_batches','chat_sessions','chat_messages',
            'daily_plans','practice_items','question_attempts','learning_events','kp_states','document_jobs']
    with engine.connect() as conn:
        conn.execute(text('SET TRANSACTION READ ONLY'))
        identity=dict(conn.execute(text("SELECT current_database() db,current_user role,current_setting('port') port,host(inet_server_addr()) host")).one()._mapping)
        print(json.dumps({'verified_connection_identity':identity},ensure_ascii=False))
        assert identity=={'db':'kaoyan','role':'kaoyan','port':'5433','host':'127.0.0.1'}
        active={
          'generating_messages':conn.scalar(text("SELECT count(*) FROM chat_messages WHERE status='generating'")),
          'active_document_jobs':conn.scalar(text("SELECT count(*) FROM document_jobs WHERE status IN ('pending','running','retry')")),
          'active_learning_tasks':conn.scalar(text("SELECT count(*) FROM learning_tasks WHERE status='running'")),
          'active_generation_batches':conn.scalar(text("SELECT count(*) FROM personal_generation_batches WHERE status IN ('pending','running','generating')"))}
        snapshots={table:dict(conn.execute(text(f"SELECT count(*) rows,md5(coalesce(string_agg(md5(row_to_json(t)::text),'' ORDER BY md5(row_to_json(t)::text)),'')) digest FROM {table} t")).one()._mapping) for table in tables}
        conn.rollback()
    engine.dispose()
    data={'stage':args.stage,'at':datetime.now(timezone.utc).isoformat(),'identity':identity,'active':active,
          'tables':snapshots,'read_only':True,'provider_called':False}
    if args.stage=='after':
        before=json.loads((output/'before.json').read_text(encoding='utf-8'))
        data['business_snapshots_unchanged']=snapshots==before['tables']
        data['changed_tables']=[table for table in tables if snapshots[table]!=before['tables'][table]]
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:value for key,value in data.items() if key!='tables'},ensure_ascii=False))
    assert not any(active.values()),'active_work_present_do_not_restart'


if __name__=='__main__':main()
