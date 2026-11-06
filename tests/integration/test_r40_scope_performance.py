"""Real TCP HTTP + owned PostgreSQL; explicitly synthetic qualified workload."""
import hashlib, json, os, re, socket, statistics, threading, time
from pathlib import Path
from unittest.mock import patch
import httpx, uvicorn
from sqlalchemy import select
from fastapi import FastAPI
from backend.models.learning import KnowledgePoint
from backend.services.learning_task_tools import TaskTools
from backend.api.routes.study import router
from backend.api.deps import get_time_provider
from backend.config import get_settings
from backend.errors import register_error_handlers
from tests.integration.test_learning_loop import session_factory, clean_database
from tests.integration.test_policy_origin_semantics import DAY


def legacy_excluded_scope(self, goal):
    with self.factory() as db:
        excluded=[]
        for node in db.scalars(select(KnowledgePoint).where(KnowledgePoint.is_active.is_(True))):
            patterns=[re.escape(alias) for alias in self._scope_aliases(node.name,node.code)]
            if len(node.code)>=3:
                patterns.append(r'(?<![a-z0-9._-])'+re.escape(node.code)+r'(?![a-z0-9._-])')
            if any(self._is_excluded(goal,m) for pattern in patterns for m in re.finditer(pattern,goal)):
                excluded.append(node.id)
        if not excluded:return set()
        tree=select(KnowledgePoint.id).where(KnowledgePoint.id.in_(excluded)).cte('legacy_excluded',recursive=True)
        tree=tree.union(select(KnowledgePoint.id).join(tree,KnowledgePoint.parent_id==tree.c.id)
            .where(KnowledgePoint.is_active.is_(True)))
        return set(db.scalars(select(tree.c.id)))


def test_literal_prefilter_preserves_exclusions_and_full_nonempty_http_response(session_factory):
    with session_factory.begin() as db:
        db.add_all([KnowledgePoint(code=f'SYNTHETIC.r40.perf.{i}',name=f'合成性能节点{i}',
            subject='408',is_active=True,is_assessable=True) for i in range(190)])
    instance=object.__new__(TaskTools);instance.factory=session_factory
    optimized=TaskTools._excluded_scope
    for goal in ['系统今日推荐','除了洛必达法则','不要复习隐函数求导','排除math.calculus.limit.lhopital',
                 'math.calculus.limit.lhopital.extra之外','合成性能节点18以外','不要合成性能节点18',
                 '先练洛必达法则，不练隐函数求导','不选合成性能节点1，排除合成性能节点18']:
        assert optimized(instance,goal)==legacy_excluded_scope(instance,goal)
    app=FastAPI();app.include_router(router,prefix='/api');register_error_handlers(app)
    app.state.session_factory=session_factory;app.state.settings=get_settings()
    app.dependency_overrides[get_time_provider]=lambda:lambda:DAY
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False))
    worker=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True)
    bodies={};measurements={}
    try:
        worker.start();deadline=time.monotonic()+15
        while not server.started:
            assert worker.is_alive() and time.monotonic()<deadline
            time.sleep(.02)
        with httpx.Client(base_url=f'http://127.0.0.1:{port}',trust_env=False,timeout=30) as client:
            for label,method in [('before',legacy_excluded_scope),('after',optimized)]:
                samples=[]
                with patch.object(TaskTools,'_excluded_scope',method):
                    for index in range(25):
                        start=time.perf_counter();response=client.get('/api/plans/today/home-recommendation')
                        elapsed=(time.perf_counter()-start)*1000
                        assert response.status_code==200,response.text
                        assert response.json()['recommendations'], 'Empty recommendations cannot prove equivalence'
                        if label in bodies:assert bodies[label]==response.content
                        bodies[label]=response.content
                        samples.append({'elapsed_ms':elapsed,'sql_count':int(response.headers['X-SQL-Count']),
                            'sql_seconds':float(response.headers['X-SQL-Seconds']),
                            'service_non_sql_seconds':float(response.headers['X-Service-Non-SQL-Seconds'])})
                values=sorted(r['elapsed_ms'] for r in samples)
                measurements[label]={'p50_ms':statistics.median(values),'p95_ms':values[23],'samples':samples}
        assert bodies['before']==bodies['after']
    finally:
        server.should_exit=True;worker.join(timeout=15);sock.close()
    assert not worker.is_alive()
    out=Path(os.environ['PHASE45I_CLOSE_OUTPUT'])
    (out/'http-performance-equivalence.json').write_text(json.dumps({
        'scope':'synthetic qualified workload, real TCP HTTP and PostgreSQL; not production performance',
        'full_response_bytes_identical':True,'response_sha256':hashlib.sha256(bodies['after']).hexdigest(),
        'recommendation_count':len(json.loads(bodies['after'])['recommendations']),
        'measurements':measurements},ensure_ascii=False,indent=2),encoding='utf-8')
