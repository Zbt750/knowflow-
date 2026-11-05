"""Full payload equivalence and SQL/profile evidence for batch ancestry lookup."""
import cProfile,hashlib,io,json,os,pstats
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import event
from backend.models.learning import KnowledgePoint
from tests.integration.test_learning_loop import session_factory,clean_database
from tests.integration.test_policy_origin_semantics import DAY
import backend.services.question_availability as availability


def test_projected_ancestors_preserve_full_inventory_and_reduce_parent_reads(session_factory):
    with session_factory.begin() as db:
        parent=KnowledgePoint(code='synthetic.r38.path.parent',name='已停用的祖先节点',subject='408',is_active=False,is_assessable=False)
        db.add(parent);db.flush()
        child=KnowledgePoint(code='synthetic.r38.path.child',name='路径子节点',subject='408',parent_id=parent.id,is_active=True,is_assessable=True)
        db.add(child);db.flush();child_id=child.id
    engine=session_factory.kw['bind'];counter=[]
    def count(*args):counter.append(1)
    original=availability._node_path
    event.listen(engine,'before_cursor_execute',count)
    try:
        with session_factory() as db,patch.object(availability,'_node_path',lambda db,node,index=None:original(db,node)):
            before=availability.question_availability(db,now=DAY,limit=1000,include_node_summaries=True)
        before_sql=len(counter);counter.clear()
        profiler=cProfile.Profile()
        with session_factory() as db:
            after=profiler.runcall(availability.question_availability,db,now=DAY,limit=1000,include_node_summaries=True)
        after_sql=len(counter)
    finally:event.remove(engine,'before_cursor_execute',count)
    assert before==after
    row=next(n for n in after['node_summaries'] if n['kp_id']==str(child_id))
    assert row['path']==['已停用的祖先节点','路径子节点']
    assert after_sql<before_sql,(before_sql,after_sql)
    output=Path(os.environ['PHASE45I_CLOSE_OUTPUT'])
    profiler.dump_stats(output/'availability-after.pstats')
    stream=io.StringIO();pstats.Stats(profiler,stream=stream).sort_stats('cumulative').print_stats(35)
    (output/'availability-profile.txt').write_text(stream.getvalue(),encoding='utf-8')
    signature=lambda payload:hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    (output/'availability-equivalence.json').write_text(json.dumps({'full_payload_equal':True,'legacy_fallback_sql_count':before_sql,'projected_sql_count':after_sql,'before_sha256':signature(before),'after_sha256':signature(after),'scope':'isolated synthetic fixture; legacy fallback retains unused projected-tree query, so use browser HTTP before/after for final timing'},indent=2),encoding='utf-8')


def test_home_http_full_response_equivalence_on_same_database(session_factory):
    import statistics,time
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api.routes.study import router
    from backend.api.deps import get_time_provider
    from backend.config import get_settings
    from backend.errors import register_error_handlers
    app=FastAPI();app.include_router(router,prefix='/api');register_error_handlers(app)
    app.state.session_factory=session_factory;app.state.settings=get_settings()
    app.dependency_overrides[get_time_provider]=lambda:lambda:DAY
    original=availability._node_path
    measurements={};bodies={}
    with TestClient(app) as client:
        for label in ['legacy_parent_reads','projected_parent_reads']:
            hook=(lambda db,node,index=None:original(db,node)) if label=='legacy_parent_reads' else original
            with patch.object(availability,'_node_path',hook):
                milliseconds=[];sql=[]
                for index in range(11):
                    start=time.perf_counter();response=client.get('/api/plans/today/home-recommendation')
                    elapsed=(time.perf_counter()-start)*1000
                    assert response.status_code==200,response.text
                    payload=response.json();assert payload['recommendations']
                    if index:milliseconds.append(elapsed);sql.append(int(response.headers['x-sql-count']))
                    if label in bodies:assert bodies[label]==payload
                    bodies[label]=payload
                measurements[label]={'p50_ms':statistics.median(milliseconds),'median_sql_count':statistics.median(sql),'samples_ms':milliseconds}
    assert bodies['legacy_parent_reads']==bodies['projected_parent_reads']
    output=Path(os.environ['PHASE45I_CLOSE_OUTPUT'])
    (output/'home-http-equivalence.json').write_text(json.dumps({'full_http_payload_equal':True,'same_database_and_clock':True,'scope':'actual FastAPI HTTP entry through TestClient; browser network timing reported separately','measurements':measurements,'response_sha256':hashlib.sha256(json.dumps(bodies['projected_parent_reads'],sort_keys=True,ensure_ascii=False).encode()).hexdigest()},indent=2),encoding='utf-8')
