"""Preparation evidence + narrowly scoped existing-plan API permit, no models."""
from pathlib import Path
import sys,json,hashlib,time,secrets
from datetime import datetime
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.restore_naiwa_experience_20261020 import snapshot,save,RUN,existing_manager,database_url,TABLES
from scripts.naiwa_freeze_preflight_20261021 import LEDGERS
OUT=ROOT/'storage/quality-audits/naiwa-freeze-preflight-20261021/stage1-closeout'
ROUND=OUT.parent/'round5'
QUESTION='9ba9c177-26a2-4918-bf84-b85159f9b002'
VERSION='92c57d4d-f0bf-4df2-b9b2-c949a3d43904'
KP='32a29e1e-8ae3-41fc-9322-43f727596819'

def normalized_snapshot(tag):return json.loads(json.dumps(snapshot('stage1-closeout-'+tag),default=str))
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def before():
    assert not (OUT/'baseline.json').exists(),'baseline already exists; do not overwrite'
    old=normalized_snapshot('before')
    for table in ('chat_messages','learning_tasks','personal_generation_batches','materials'):
        assert not [r for r in old[table] if r.get('status') in {'running','generating','queued','pending','created','processing'}],table
    assert next(q for q in old['questions'] if q['id']==QUESTION)['current_version_id']==VERSION
    hashes={str(p.relative_to(ROOT)):digest(p) for p in [*LEDGERS,ROUND/'provider-ledger.json']}
    assert len(json.loads((ROUND/'provider-ledger.json').read_text())['requests'])==0
    save(OUT/'baseline.json',{'database':old,'ledger_hashes':hashes,'runtime':json.loads((RUN/'runtime.json').read_text(encoding='utf-8'))})
    # Business selector preview in a transaction that is ALWAYS rolled back.
    # It predicts the normal UI's pool selection without leaving any records.
    from sqlalchemy import create_engine,select
    from sqlalchemy.orm import sessionmaker
    from backend.models.learning import PracticeItem,Question
    from backend.services.practice_service import create_initial_plan
    from uuid import UUID
    engine=create_engine(database_url(existing_manager()))
    try:
        with sessionmaker(engine)() as db:
            now=datetime.now(ZoneInfo('Asia/Shanghai'))
            try:
                plan=create_initial_plan(db,study_date=now.date(),selected_kp_ids=[UUID(KP)],now=now,budget='light')
                db.flush()
                picked=[{'question_id':str(i.question_id),'question_version_id':str(i.question_version_id),
                    'stem':db.get(Question,i.question_id).stem} for i in db.scalars(select(PracticeItem).where(PracticeItem.plan_id==plan.id))]
                save(OUT/'selector-preview-rolled-back.json',{'preview_only':True,'persisted':False,'items':picked})
            finally:db.rollback()
    finally:engine.dispose()
    current=normalized_snapshot('after-preview')
    assert current==old,'rolled-back selector preview changed data'
    print(json.dumps({'baseline_saved':True,'selector_preview':picked,'real_calls':0},ensure_ascii=False))

def permit():
    assert (OUT/'baseline.json').exists()
    assert not json.loads((ROUND/'control.json').read_text())['paid_enabled']
    assert json.loads((ROUND/'provider-ledger.json').read_text())['requests']==[]
    save(RUN/'study-setup-permit.json',{'enabled':True,'nonce':secrets.token_urlsafe(32),'expires_at':time.time()+1800,
        'append_path':None,'label':'奶蛙最终复验·隔离今日学习测试卷','question_id':QUESTION,'question_version_id':VERSION})
    print('Narrow isolated study setup permit ready; paid exit remains closed')

def revoke():
    path=RUN/'study-setup-permit.json'
    if path.exists():
        value=json.loads(path.read_text(encoding='utf-8'));value['enabled']=False;save(path,value)
    print('All isolated setup writes closed')

def after():
    old=json.loads((OUT/'baseline.json').read_text(encoding='utf-8'));current=normalized_snapshot('after')
    changes={}
    for table in TABLES:
        key=lambda r:str(r.get('id',r.get('kp_id')))
        a={key(r):r for r in old['database'][table]};b={key(r):r for r in current[table]}
        assert all(k in b and b[k]==v for k,v in a.items()),'historical rows changed:'+table
        additions=[r for k,r in b.items() if k not in a]
        assert not additions or table in {'daily_plans','practice_items'},'unexpected business writes:'+table
        changes[table]={'before':len(a),'after':len(b),'historical_unchanged':True,'new_ids':[key(r) for r in additions]}
    date=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    today=[p for p in current['daily_plans'] if p['study_date']==date]
    assert len(today)==1,'today paper missing or duplicated'
    items=[i for i in current['practice_items'] if i['plan_id']==today[0]['id']]
    bound=[i for i in items if i['question_id']==QUESTION]
    assert len(bound)==1 and bound[0]['question_version_id']==VERSION and bound[0]['kp_id']==KP
    assert all(i['completed_at'] is None for i in items)
    hashes={p:digest(ROOT/p) for p in old['ledger_hashes']}
    assert hashes==old['ledger_hashes'],'ledger changed'
    assert json.loads((ROUND/'provider-ledger.json').read_text())['requests']==[]
    assert not json.loads((ROUND/'control.json').read_text())['paid_enabled']
    assert not json.loads((RUN/'study-setup-permit.json').read_text(encoding='utf-8'))['enabled']
    loaded=json.loads((RUN/'loaded-code.json').read_text(encoding='utf-8'))
    source_checks={p:digest(ROOT/p)==h for p,h in loaded['source_sha256'].items()}
    assert all(source_checks.values()),'loaded source not current'
    assert loaded['physical_gate']['installed'] and loaded['physical_gate']['global_limit']==5
    save(OUT/'final-verification.json',{'status':'PASS','identity':current['identity'],'table_changes':changes,
        'ledger_hashes':hashes,'loaded_sources_match':source_checks,'loaded_manifest':loaded,
        'label':'奶蛙最终复验·隔离今日学习测试卷（清单标记，模型无卷名字段）',
        'today':today[0],'target_practice_item':bound[0],'total_items':len(items),'real_calls':0,'paid_enabled':False})
    print(json.dumps({'status':'PASS','new_plan':today[0]['id'],'target_item':bound[0]['id'],'total_items':len(items),'real_calls':0}))

if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    {'before':before,'permit':permit,'revoke':revoke,'after':after}[sys.argv[1]]()
