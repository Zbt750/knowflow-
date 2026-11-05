"""Production knowledge APIs on a fresh owned PG; synthetic scale data only."""
import os
from time import perf_counter
from datetime import datetime, timezone

from sqlalchemy import select, func, event
from backend.db import create_db_engine, create_session_factory
from backend.models.learning import KnowledgePoint, Question, KpState
from scripts.prepare_e2e_learning import validate_test_target


def create_e2e_app():
    url = validate_test_target(os.environ.get('TEST_DATABASE_URL'), os.environ.get('KAOYAN_OWNED_TEST_PORT'))
    engine = create_db_engine(url)
    with create_session_factory(engine).begin() as db:
        if db.scalar(select(func.count()).select_from(KnowledgePoint)):
            raise RuntimeError('Knowledge performance fixture requires its own empty database')
        parents = []
        for ordinal,(code,name) in enumerate([('cs408','408 计算机学科专业基础'),('math.calculus','高等数学'),('math.linear-algebra','线性代数')],1):
            root=KnowledgePoint(code=code,name=name,subject=name,ordinal=ordinal,is_assessable=False,is_active=True)
            db.add(root);db.flush()
            for chapter in range(6):
                parent=KnowledgePoint(code=f'{code}.chapter.{chapter}',name=f'{name}第{chapter+1}章',
                    subject=name,parent_id=root.id,ordinal=chapter,is_assessable=False,is_active=True)
                db.add(parent);db.flush();parents.append(parent)
        for i in range(283):
            parent = parents[i % len(parents)]
            node = KnowledgePoint(code=f'TEST_PERF.topic.{i:03}', name=f'隔离性能知识点{i:03}',
                subject=parent.subject, parent_id=parent.id, ordinal=i + 100,
                is_assessable=True, is_active=True)
            db.add(node); db.flush(); db.add(KpState(kp_id=node.id))
        db.flush()
        leaves = list(db.scalars(select(KnowledgePoint).where(KnowledgePoint.is_assessable.is_(True))))
        existing = db.scalar(select(func.count()).select_from(Question))
        for i in range(max(0, 1935 - existing)):
            db.add(Question(kp_id=leaves[i % len(leaves)].id, stem=f'隔离性能题{i}：求 {i}+1 的值。',
                question_type='single_choice', options={'A':str(i+1),'B':str(i+2),'C':str(i+3),'D':str(i+4)},
                correct_answer='A', explanation=f'按整数加法得到{i+1}。仅为测试内容，不具有正式审核资格。',
                is_active=True, bank_scope='public'))
    engine.dispose()
    from scripts.e2e_backend import create_e2e_app as offline_app
    app = offline_app()
    # No RAG or model calls in this suite. Retain the production lifespan and
    # real knowledge-tree cache warmup instead of waiting for embedding startup.
    import backend.app as backend_app
    def no_retrieval(application, settings):
        application.state.retrieval_stack = None
        application.state.retrieval_error = 'knowledge_performance_fixture_without_retrieval'
        return False
    backend_app._try_build_retrieval_stack = no_retrieval

    @app.get('/api/test/knowledge-benchmark')
    def benchmark():
        from backend.api.routes.study import read_knowledge_tree
        from backend.services.knowledge_tree_cache import _reset_knowledge_tree_cache_for_tests
        factory = app.state.session_factory
        timings = []; sql_times = []; started = []
        def before(*args): started.append(perf_counter())
        def after(*args): sql_times.append(perf_counter()-started.pop())
        event.listen(app.state.engine, 'before_cursor_execute', before)
        event.listen(app.state.engine, 'after_cursor_execute', after)
        now = datetime(2026,10,19,4,tzinfo=timezone.utc)
        try:
            for cold in [True,False,False]:
                if cold: _reset_knowledge_tree_cache_for_tests()
                sql_times.clear(); begin = perf_counter()
                with factory() as db: result = read_knowledge_tree(db,lambda:now)
                built = perf_counter(); payload = result.model_dump_json()
                timings.append({'cold':cold,'build_ms':round((built-begin)*1000,2),
                    'json_ms':round((perf_counter()-built)*1000,2),'sql_count':len(sql_times),
                    'sql_ms':round(sum(sql_times)*1000,2),'json_bytes':len(payload.encode())})
        finally:
            event.remove(app.state.engine,'before_cursor_execute',before)
            event.remove(app.state.engine,'after_cursor_execute',after)
        with factory() as db:
            from backend.api.routes.study import read_knowledge_tree_http
            from starlette.requests import Request
            begin=perf_counter()
            http=read_knowledge_tree_http(Request({'type':'http','headers':[]}),db,lambda:now)
            http_ms=round((perf_counter()-begin)*1000,3)
            return {'nodes':db.scalar(select(func.count()).select_from(KnowledgePoint)),
                'questions':db.scalar(select(func.count()).select_from(Question)),'timings':timings,
                'cached_http_ms':http_ms,'http_bytes':len(http.body)}
    return app
