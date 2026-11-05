"""Retry corrected submission regressions in a fresh owned test database."""
from __future__ import annotations
import contextlib,json,os,sys
from pathlib import Path
from xml.etree import ElementTree
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
OUT=ROOT/'storage/quality-audits/phase45z5-20261013/final-candidate/regression-retry1'
TEST='phase45z5_regression_retry1_20261013_test'
def main():
 if OUT.exists():raise SystemExit('existing_retry_refuse_overwrite')
 OUT.mkdir()
 from scripts import run_phase45i_agent_real as infra
 from scripts.run_phase45hx_batch01 import all_table_fingerprints
 from sqlalchemy import create_engine
 import psycopg
 from psycopg import sql
 _,cluster,port=infra.load_existing_owner()
 if port!=59227:raise RuntimeError('owned_port_mismatch')
 infra.OUT_DIR=OUT/'runtime';infra.OUT_DIR.mkdir()
 started=infra.start_owned_database(cluster,port)
 engine=create_engine('postgresql+psycopg://postgres@127.0.0.1:59227/phase45z5_work_20261013_test')
 try:
  infra.verify_database(cluster,port)
  with engine.connect() as conn:before=all_table_fingerprints(conn)
  with psycopg.connect(host='127.0.0.1',port=port,user='postgres',dbname='postgres',sslmode='disable',connect_timeout=8,autocommit=True) as conn:
   if conn.execute('SELECT 1 FROM pg_database WHERE datname=%s',(TEST,)).fetchone():raise RuntimeError('retry_database_exists')
   conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(TEST)))
  url=f'postgresql+psycopg://postgres@127.0.0.1:{port}/{TEST}'
  os.environ.update({'APP_ENV':'test','DATABASE_URL':url,'TEST_DATABASE_URL':url,'KAOYAN_OWNED_TEST_PORT':str(port),
   'PHASE45I_CLOSE_OFFLINE':'1','PHASE45I_CLOSE_OUTPUT':str(OUT)})
  from scripts.phase45i_offline_guard import install,BLOCKED
  install()
  import pytest
  with (OUT/'pytest.log').open('w',encoding='utf-8') as log,contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
   rc=pytest.main(['tests/integration/test_answer_submissions.py','-q','-o','addopts=',
    '--basetemp',str(OUT/'pytest-temp'),'--junitxml',str(OUT/'pytest.xml')])
  xml=ElementTree.parse(OUT/'pytest.xml').getroot()
  counts={k:sum(int(e.attrib.get(k,0)) for e in xml.findall('testsuite')) for k in ('tests','failures','errors','skipped')}
  with engine.connect() as conn:after=all_table_fingerprints(conn)
  if before!=after:raise RuntimeError('work_database_changed_during_retry')
  result={'status':'PASS' if rc==0 else 'FAIL','exit_code':int(rc),'counts':counts,'test_database':TEST,
   'work_database_unchanged_all_25_tables':True,'model_calls':0,'development_5433_accessed':False,'network_guard_events':BLOCKED,
   'updated_expectations':'unreviewed and non-objectively-gradable public items must stop at formal admission'}
  (OUT/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
  print(json.dumps(result,ensure_ascii=True),flush=True)
 finally:
  engine.dispose()
  if started:
   stop=infra.command([str(infra.PG_BIN/'pg_ctl.exe'),'-D',str(cluster),'-m','fast','-w','-t','60','stop'],timeout=75,check=False,capture=False)
   print('ISOLATED_CLUSTER_STOPPED_NORMALLY' if stop.returncode==0 else 'NORMAL_STOP_FAILED',flush=True)
if __name__=='__main__':main()
