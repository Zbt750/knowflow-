"""Read-only audit of the single owned blind-test database, never 5433."""
import json
from pathlib import Path
from scripts.blind_user_20261019 import ROOT,OUT,snapshot
from desktop.postgres import ManagedPostgres
from desktop.runtime_paths import RuntimePaths
from sqlalchemy import create_engine,select
from sqlalchemy.orm import Session
from sqlalchemy.engine import make_url


def owned_manager():
    runtime=json.loads((OUT/'runtime.json').read_text(encoding='utf-8'))
    assert runtime['database']=='kaoyan_blind_test' and runtime['pg_port']>18000
    manager=ManagedPostgres(RuntimePaths.windows(resources=ROOT/'backend',local_app_data=Path(runtime['data_path'])),
        Path('C:/Program Files/PostgreSQL/18/bin'),port=runtime['pg_port'])
    manager.owner=json.loads(manager.marker.read_text(encoding='utf-8'))
    manager._load_passwords()
    return manager


if __name__=='__main__':
    manager=owned_manager()
    url=make_url(manager.database_url).set(database='kaoyan_blind_test').render_as_string(hide_password=False)
    snapshot(url,'database-checkpoint.json')
    from backend.models.learning import Question,KnowledgePoint
    from backend.services.question_eligibility import question_eligibility
    from backend.services.personal_question_general import current_general_binding
    engine=create_engine(url)
    with Session(engine) as db:
        rows=[]
        for q in db.scalars(select(Question)):
            node=db.get(KnowledgePoint,q.kp_id)
            rows.append({'question_id':str(q.id),'bank_scope':q.bank_scope,'grading_config':q.grading_config,
                'general_binding':bool(current_general_binding(q,node)),
                'eligibility':question_eligibility(q,node).public_dict()})
    (OUT/'eligibility-checkpoint.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps(rows,ensure_ascii=False,default=str))
