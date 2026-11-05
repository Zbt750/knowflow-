from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, event
from backend.api.routes.study import router, read_knowledge_tree
from backend.api.deps import get_time_provider
from backend.models.learning import KnowledgePoint, KpState
from backend.services.knowledge_tree_cache import invalidate_knowledge_tree_cache
from scripts.run_question_repair_pilot import isolated_factory


def test_conditional_tree_read_preserves_full_schema_and_revalidates_after_commit(test_database_url):
    with isolated_factory(test_database_url) as (factory,_):
        with factory.begin() as db:
            node=KnowledgePoint(code='TEST_HTTP.leaf',name='缓存前知识点',subject='数学二',is_active=True,is_assessable=True)
            db.add(node);db.flush();db.add(KpState(kp_id=node.id));node_id=node.id
        app=FastAPI();app.include_router(router,prefix='/api');app.state.session_factory=factory
        clock=datetime(2026,10,19,4,tzinfo=timezone.utc)
        app.dependency_overrides[get_time_provider]=lambda:lambda:clock
        with TestClient(app) as client:
            first=client.get('/api/knowledge/tree')
            assert first.status_code==200 and first.headers['cache-control']=='private, no-cache'
            with factory() as db:
                expected=read_knowledge_tree(db,lambda:clock).model_dump(mode='json')
            assert first.json()==expected
            statements=[];engine=factory.kw['bind']
            def counted(*args):statements.append(args[2])
            event.listen(engine,'before_cursor_execute',counted)
            try:
                same=client.get('/api/knowledge/tree',headers={'If-None-Match':first.headers['etag']})
                assert same.status_code==304 and same.content==b'' and statements==[]
            finally:event.remove(engine,'before_cursor_execute',counted)
            with factory.begin() as db:db.get(KnowledgePoint,node_id).name='已更新知识点'
            fresh=client.get('/api/knowledge/tree',headers={'If-None-Match':first.headers['etag']})
            assert fresh.status_code==200 and fresh.headers['etag']!=first.headers['etag']
            assert fresh.json()['nodes'][0]['name']=='已更新知识点'
            assert client.get('/api/knowledge/tree',headers={'If-None-Match':'W/'+fresh.headers['etag']}).status_code==304
        invalidate_knowledge_tree_cache()
