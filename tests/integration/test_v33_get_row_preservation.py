"""Real PG + official GET routes, independent new-cluster data, no model."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
import hashlib,json,socket,sys
from uuid import uuid4
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine,inspect,text,event
from sqlalchemy.orm import sessionmaker
from tests.conftest import TEST_DATABASE_URL
from backend.models.chat import ChatSession
from backend.models.learning_task import LearningTask
from backend.models.practice_request import PracticeRequest
from backend.api.deps import get_db,get_time_provider
from backend.api.routes.practice_requests import router as requests_router
from backend.api.routes.chat import router as chat_router
from backend.api.routes.study import router as study_router
from backend.api.routes.learning_tasks import router as tasks_router


def test_repeated_cross_session_concurrent_gets_preserve_all_business_rows():
    engine=create_engine(TEST_DATABASE_URL,pool_size=12,max_overflow=12)
    assert engine.url.port!=5433 and engine.url.database.endswith('_test')
    factory=sessionmaker(bind=engine,expire_on_commit=False)
    now=datetime(2040,4,1,tzinfo=timezone.utc)
    sessions=[];ids=[];task_ids=[]
    # Only newly created synthetic rows in this dedicated cluster.
    with factory.begin() as db:
        for index in range(2):
            s=ChatSession(title='V33 GET preservation synthetic '+str(index),mode='builtin',purpose='qa')
            db.add(s);db.flush();sessions.append(s.id)
            for state,task_state in [('proposed','ready'),('planning','ready'),('planning','failed'),('planning','cancelled'),('draft','created'),('planning','running')]:
                task=LearningTask(session_id=s.id,goal='V33 READ ONLY SYNTHETIC',budget_minutes=30,
                    status=task_state,started_at=datetime(2000,1,1,tzinfo=timezone.utc),
                    context={'current_plan':{'study_date':'2040-03-31'}},draft=None)
                db.add(task);db.flush()
                task_ids.append(task.id)
                row=PracticeRequest(source_conversation_id=s.id,user_request='synthetic historical pending request',
                    status=state,planner_task_id=task.id,expires_at=now+timedelta(days=7),request={})
                db.add(row);db.flush();ids.append(row.id)
    def snapshot():
        with engine.connect() as c:
            c.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
            return {table:sorted(hashlib.sha256(json.dumps(dict(row._mapping),sort_keys=True,default=str).encode()).hexdigest()
                for row in c.execute(text('SELECT * FROM public."'+table+'"')))
                for table in inspect(c).get_table_names(schema='public')}
    before=snapshot();writes=[]
    def no_write(conn,cursor,statement,parameters,context,many):
        if statement.lstrip().split(None,1)[0].upper() in {'INSERT','UPDATE','DELETE','MERGE','ALTER','DROP','CREATE','TRUNCATE'}:
            writes.append(statement);raise AssertionError('GET attempted a database write')
    event.listen(engine,'before_cursor_execute',no_write)
    app=FastAPI();app.state.session_factory=factory
    app.include_router(requests_router,prefix='/api');app.include_router(chat_router,prefix='/api');app.include_router(study_router,prefix='/api')
    app.include_router(tasks_router,prefix='/api')
    def db_dependency():
        with factory() as db:yield db
    app.dependency_overrides[get_db]=db_dependency
    app.dependency_overrides[get_time_provider]=lambda:lambda:now
    def guard(evt,args):
        if evt=='socket.getaddrinfo' and args[0] not in {'127.0.0.1','localhost','::1'}:raise AssertionError('external DNS forbidden')
        if evt=='socket.connect' and isinstance(args[1],tuple) and args[1][0] not in {'127.0.0.1','::1'}:raise AssertionError('external connection forbidden')
    sys.addaudithook(guard)
    urls=['/api/practice-requests']+[f'/api/practice-requests?source_conversation_id={s}' for s in sessions]+[f'/api/practice-requests/{i}' for i in ids]
    urls+=['/api/chat/sessions?purpose=qa']+[f'/api/chat/sessions/{s}/messages' for s in sessions]
    urls+=['/api/plans/today','/api/plans/today/recommendations']
    urls += [f'/api/learning-tasks/{i}' for i in task_ids]
    try:
        with TestClient(app) as client:
            for repeat in range(3):
                for url in urls:assert client.get(url).status_code==200,url
                assert snapshot()==before,'full-row drift after repeat/refresh'
            with ThreadPoolExecutor(max_workers=8) as pool:
                statuses=list(pool.map(lambda url:client.get(url).status_code,urls*4))
            assert all(status==200 for status in statuses)
        assert snapshot()==before and writes==[]
    finally:
        event.remove(engine,'before_cursor_execute',no_write);engine.dispose()
