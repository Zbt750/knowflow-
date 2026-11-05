"""User-authorized, strictly read-only lookup of the actual Oct24 question incident."""
from pathlib import Path
import hashlib
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT=ROOT/'storage/quality-audits/geometric-actual-question-20261024'

def main():
    from backend.config import get_settings
    from sqlalchemy import create_engine,text
    from sqlalchemy.engine import make_url
    url=make_url(str(get_settings().active_database_url))
    if (url.host,url.port,url.database,url.username)!=('127.0.0.1',5433,'kaoyan','kaoyan'):
        raise RuntimeError('configured daily database identity differs; stop')
    engine=create_engine(url,connect_args={'connect_timeout':4,'options':'-c default_transaction_read_only=on -c statement_timeout=15000'})
    try:
        with engine.connect() as db:
            db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
            identity=list(db.execute(text('SELECT current_database(),current_user,host(inet_server_addr()),inet_server_port(),current_setting(\'transaction_read_only\')')).one())
            assert identity==['kaoyan','kaoyan','127.0.0.1',5433,'on']
            rows=db.execute(text('''SELECT to_jsonb(p) AS plan,to_jsonb(i) AS item,to_jsonb(q) AS question,
                to_jsonb(v) AS version,to_jsonb(k) AS node,to_jsonb(b) AS batch
                FROM daily_plans p JOIN practice_items i ON i.plan_id=p.id
                LEFT JOIN questions q ON q.id=i.question_id
                LEFT JOIN question_versions v ON v.id=i.question_version_id
                JOIN knowledge_points k ON k.id=i.kp_id
                LEFT JOIN personal_generation_batches b ON b.id=q.generation_batch_id
                WHERE p.study_date=:day ORDER BY i.ordinal,i.id'''),{'day':'2026-10-24'}).mappings().all()
            # Only retain the requested node's incident, not unrelated personal content.
            selected=[dict(row) for row in rows if '等比级数' in row['node']['name'] and row['batch'] and row['batch']['result'].get('requested')==2]
            if len(selected)!=1:raise RuntimeError(f'incident match ambiguous:{len(selected)}')
            target=selected[0];qid=target['question']['id'];bid=target['batch']['id']
            attempts=list(db.execute(text('SELECT to_jsonb(t) FROM question_attempts t WHERE question_id=CAST(:q AS uuid)'),{'q':qid}).scalars())
            events=list(db.execute(text('SELECT to_jsonb(t) FROM learning_events t WHERE question_version_id=CAST(:v AS uuid)'),{'v':target['version']['id']}).scalars())
            evidence={'identity':identity,'plan_item_count':len(rows),'display_position':next(n for n,row in enumerate(rows,1) if row['item']['id']==target['item']['id']),
                'incident':target,'attempts':attempts,'events':events,'real_model_requests':0,'transaction':'REPEATABLE READ READ ONLY'}
            evidence['content_sha256']=hashlib.sha256(json.dumps(target,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        OUT.mkdir(parents=True,exist_ok=False)
        with (OUT/'actual-records.json').open('x',encoding='utf-8') as stream:json.dump(evidence,stream,ensure_ascii=False,indent=2)
        print(json.dumps({'question_id':qid,'version_id':target['version']['id'],'batch_id':bid,'plan_total':len(rows),
            'display_position':evidence['display_position'],'stem':target['version']['stem'],'options':target['version']['options'],
            'answer':target['version']['correct_answer'],'explanation':target['version']['explanation'],
            'batch_result':target['batch']['result']},ensure_ascii=False))
    finally:engine.dispose()

if __name__=='__main__':main()
