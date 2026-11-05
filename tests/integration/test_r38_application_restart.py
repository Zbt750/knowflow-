"""Actual backend process restart over owned PostgreSQL; no mock API responses."""
import json,os,socket,subprocess,sys,time
from pathlib import Path
from datetime import timedelta
import httpx
from sqlalchemy import select
from backend.models.learning import QuestionAttempt,PracticeItem
from tests.integration.test_learning_loop import session_factory,clean_database
from tests.integration.test_policy_origin_semantics import make_origin_slice,attempt,DAY


def create_restart_app():
    from backend.app import create_app
    from backend.api.deps import get_time_provider
    if os.environ.get('APP_ENV')!='test' or os.environ.get('NAIWA_FRESH_TEST_DATABASE')!='1':
        raise RuntimeError('owned restart fixture only')
    app=create_app()
    app.dependency_overrides[get_time_provider]=lambda:lambda:DAY+timedelta(days=2)
    return app


def test_real_backend_process_restart_preserves_adaptive_receipt_and_recommendations(session_factory):
    from backend.services.practice_activity_service import record_activity
    from backend.services.adaptive_schedule_projection import read_projection
    with session_factory.begin() as db:
        node,_policy,questions=make_origin_slice(db)
        outcome=attempt(db,node,questions[0],DAY)
        stored=db.get(QuestionAttempt,outcome.attempt_id)
        saved=json.loads(json.dumps(stored.grading_evidence['adaptive_schedule']))
        attempted_id=stored.id;node_id=node.id
        original=db.get(PracticeItem,stored.practice_item_id)
        skipped=PracticeItem(plan_id=original.plan_id,question_id=questions[1].id,kp_id=node.id,ordinal=2)
        db.add(skipped);db.flush()
        record_activity(db,item_id=skipped.id,kind='skipped',idempotency_key='r38-restart-skip',now=DAY)
    output=Path(os.environ['PHASE45I_CLOSE_OUTPUT']);root=Path(__file__).resolve().parents[2]
    observed=[];pids=[]
    for index in range(2):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        with (output/f'restart-backend-{index}.log').open('w',encoding='utf-8') as log:
            server=subprocess.Popen([sys.executable,'-m','uvicorn','tests.integration.test_r38_application_restart:create_restart_app','--factory','--host','127.0.0.1','--port',str(port)],cwd=root,env=dict(os.environ),stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
            pids.append(server.pid)
            try:
                ready=False;deadline=time.monotonic()+60
                while time.monotonic()<deadline and server.poll() is None:
                    try:
                        health=httpx.get(f'http://127.0.0.1:{port}/api/health',timeout=2,trust_env=False)
                        if health.status_code==200 and health.json().get('environment')=='test':ready=True;break
                    except httpx.HTTPError:pass
                    time.sleep(.2)
                assert ready,f'backend did not start: restart-backend-{index}.log'
                result=httpx.get(f'http://127.0.0.1:{port}/api/plans/today/recommendations',timeout=20,trust_env=False)
                assert result.status_code==200,result.text
                observed.append(result.json()['recommendations'])
            finally:
                if server.poll() is None:server.terminate()
                server.wait(timeout=20)
        with session_factory() as db:
            assert db.get(QuestionAttempt,attempted_id).grading_evidence['adaptive_schedule']==saved
            projection=read_projection(db,DAY+timedelta(days=2),[node_id])
            assert projection.skills[str(node_id)].right==1
            assert projection.skills[str(node_id)].skipped==1
            assert len(projection.cards)==1
    assert pids[0]!=pids[1]
    assert observed[0]==observed[1]
    (output/'application-restart-evidence.json').write_text(json.dumps({'status':'PASS','real_backend_process_restart':True,'backend_pids':pids,'controlled_clock':str(DAY+timedelta(days=2)),'synthetic_content_and_outcomes':True,'persisted_adaptive_json':saved,'recommendations':observed,'skip_preserved_without_memory_card':True},ensure_ascii=False,indent=2),encoding='utf-8')
