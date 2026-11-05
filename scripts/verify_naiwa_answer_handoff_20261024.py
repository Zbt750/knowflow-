"""Read identity/fixture + one labelled QA-session auth probe; no student attempts."""
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
DATA=ROOT/'storage/manual-experience/naiwa-student-ui-acceptance-20261024-handoffc1'
OUT=ROOT/'storage/quality-audits/naiwa-student-ui-acceptance-20261024-handoffc1'


def save(name,payload):
    with (OUT/name).open('x',encoding='utf-8') as stream:
        json.dump(payload,stream,ensure_ascii=False,indent=2,default=str)


def main():
    import httpx
    from desktop.postgres import ManagedPostgres,APP_USER
    from desktop.runtime_paths import RuntimePaths
    runtime=json.loads((DATA/'runtime.json').read_text(encoding='utf-8'))
    expected='naiwa_student_ui_20261024_handoffc1_test'
    assert runtime['status']=='running' and runtime['database']==expected
    assert runtime['ports']=={'postgres':64765,'api':63121,'web':63122}
    assert runtime['paid_enabled'] is False and runtime['real_model_requests']==0
    paths=RuntimePaths.windows(resources=ROOT/'backend',local_app_data=DATA/'owned-pg')
    pg=ManagedPostgres(paths,Path('C:/Program Files/PostgreSQL/18/bin'),port=64765)
    assert pg.marker.is_file() and pg.credentials.is_file()
    pg._load_owner(); pg._load_passwords()
    assert pg._identity() is not None and pg.owner['cluster_id']==runtime['database_identity']['cluster_id']
    with pg._connect(user=APP_USER,database=expected) as db:
        observed=db.execute('SELECT current_database(),current_user,host(inet_server_addr()),inet_server_port()').fetchone()
        assert observed==(expected,APP_USER,'127.0.0.1',64765)
    def snapshot():
        with pg._connect(user=APP_USER,database=expected) as db:
            db.execute('BEGIN READ ONLY')
            names=[r[0] for r in db.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
            result={}
            from psycopg import sql
            for name in names:
                rows=[r[0] for r in db.execute(sql.SQL('SELECT to_jsonb(t) FROM public.{} t').format(sql.Identifier(name)))]
                canonical=sorted(json.dumps(row,ensure_ascii=False,sort_keys=True,default=str) for row in rows)
                result[name]={'count':len(rows),'sha256':hashlib.sha256(json.dumps(canonical,ensure_ascii=False).encode()).hexdigest(),'rows':rows}
            db.rollback()
            return result
    resume='--resume-auth-probe' in sys.argv
    before=(json.loads((OUT/'developer-database-before.json').read_text(encoding='utf-8')) if resume else snapshot())
    if not resume:
        save('developer-database-before.json',before)
    assert all(before[t]['count']==0 for t in ('kp_states','question_attempts','learning_events','daily_plans','practice_items','chat_sessions'))
    assert before['kp_mastery_policies']['count']==1
    assert before['kp_mastery_policies']['rows'][0]['policy_version']==3
    assert before['kp_graduation_question_set_versions']['count']==1
    with httpx.Client(trust_env=False,timeout=8,follow_redirects=False) as web:
        health=web.get('http://127.0.0.1:63122/api/health'); assert health.status_code==200
        assert health.json()['database']=='connected' and health.json()['environment']=='test'
        page=web.get('http://127.0.0.1:63122/study');assert page.status_code==200 and '<div id="app">' in page.text
        # Vite proxies /api only. The test identity is read directly from the
        # isolated backend, while the ordinary health route verifies the proxy.
        loaded=web.get('http://127.0.0.1:63121/__test/runtime');assert loaded.status_code==200
        loaded=loaded.json()
        mismatches=[name for name,digest in loaded['source_sha256'].items() if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest]
        assert not mismatches
        invalid=web.post('http://127.0.0.1:63122/api/chat/sessions',json={'title':'REJECTED_DEVELOPER_PROBE','mode':'builtin','purpose':'qa'},headers={'Origin':'http://untrusted.invalid','Sec-Fetch-Site':'cross-site'})
        assert invalid.status_code==403
        if resume:
            # The first probe committed successfully; recover its real receipt
            # without repeating that write after the verifier's parsing error.
            current=snapshot()
            sessions=current['chat_sessions']['rows']
            assert len(sessions)==1 and sessions[0]['title']=='DEVELOPER_AUTH_PROBE_NOT_STUDENT_UI'
            assert 'POST /api/chat/sessions HTTP/1.1" 201 Created' in (OUT/'backend.log').read_text(encoding='utf-8')
            probe_id=sessions[0]['id']
        else:
            valid=web.post('http://127.0.0.1:63122/api/chat/sessions',json={'title':'DEVELOPER_AUTH_PROBE_NOT_STUDENT_UI','mode':'builtin','purpose':'qa'},headers={'Origin':'http://127.0.0.1:63122','Sec-Fetch-Site':'same-origin'})
            assert valid.status_code==201,valid.text
            save('developer-auth-http.json',{'status':valid.status_code,'response':valid.json()})
            probe_id=valid.json()['session_id']
    after=snapshot();save('developer-database-after.json',after)
    changed=[name for name in before if before[name]['sha256']!=after[name]['sha256']]
    assert changed==['chat_sessions'] and after['chat_sessions']['count']==1
    assert after['chat_sessions']['rows'][0]['id']==probe_id
    assert after['chat_messages']['count']==0
    summary={'captured_at':time.time(),'database_identity':list(observed),'cluster_id':pg.owner['cluster_id'],
        'host_health_status':200,'host_vue_html_status':200,'same_origin_write_status':201,'cross_origin_write_status':403,
        'developer_probe_session_id':probe_id,'changed_tables':changed,'student_attempts_seeded':0,'learning_events_seeded':0,
        'probe_recovered_without_repeating_write':resume,
        'loaded_code':loaded,'source_mismatches':mismatches,'real_model_requests':0,'paid_enabled':False,
        'browser_page_verified':False,'validation_level':'host HTTP + actual isolated PostgreSQL; not browser UI'}
    save('developer-verification.json',summary)
    print(json.dumps({k:v for k,v in summary.items() if k!='loaded_code'},ensure_ascii=False))


if __name__=='__main__':main()
