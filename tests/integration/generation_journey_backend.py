"""Actual app with a fixed generation provider, exclusively on owned test PG."""
import json
import os
from sqlalchemy import select
from backend.db import create_db_engine, create_session_factory
from backend.models.learning import KnowledgePoint, KpState
from scripts.prepare_e2e_learning import validate_test_target

NODE_CODE = "TEST_FIXTURE.real_ui_series"


class SeriesProvider:
    simulation = True
    model = "fixed-series-fixture-no-network"

    def complete(self, messages, *, attempt=1):
        request = json.loads(messages[-1]["content"])
        if '.count_' in request['node']['code']:
            from tests.integration.test_personal_generation_quantity import CountModel
            if not hasattr(self,'count_models'):self.count_models={}
            code=request['node']['code']
            # 各场景内容不同；不能靠绕过生产去重来制造部分成功。
            offset=10 if code.endswith('count_mixed') else 20 if code.endswith('count_truncated') else 30 if code.endswith('count_network') else 40 if code.endswith('count_network_multi') else 0
            model=self.count_models.setdefault(code,CountModel(offset=offset))
            if code.endswith('count_mixed') and request['sample']==2:model.faults[model.calls+1]='answer'
            if code.endswith('count_truncated'):model.faults[model.calls+1]='truncated'
            if code.endswith(('count_network','count_network_multi')) and model.calls==0:model.faults[1]='network'
            return model.complete(messages,attempt=attempt)
        if request['node']['code'] == NODE_CODE + '.truncated':
            from backend.errors import AppError
            raise AppError('answer_truncated', retryable=False)
        assert "nx^n" in request["reference"]["statement"]
        assert request["difficulty"] == "improved"
        assert request["question_type"] == "calculation"
        return json.dumps({
            "stem": r"当 $|x|<1$ 时，求 $\sum_{n=1}^{\infty}n^2x^n$ 的和，并说明逐项求导的适用范围。",
            "question_type":"calculation", "options":None,
            "correct_answer":r"$\frac{x(1+x)}{(1-x)^3}$，适用范围为 $|x|<1$。",
            "explanation":r"在幂级数收敛区间内部可逐项求导。由 $\sum nx^n=x/(1-x)^2$，两边求导后乘以 $x$，得 $\sum n^2x^n=x(1+x)/(1-x)^3$。",
            "final_value":"x(1+x)/(1-x)^3", "steps":[],
            'difficulty_assessment':{
                'estimated_level':'basic' if request['node']['code'].endswith('.difficulty_conflict') else 'hard',
                'relative_change':'easier' if request['node']['code'].endswith('.difficulty_conflict') else 'harder',
                'reason':'在原题求和的基础上增加逐项求导和适用范围说明，需要衔接两个推导步骤。',
                'mechanisms':['reasoning_steps','method_combination']},
        }, ensure_ascii=False), {"prompt_tokens":100,"completion_tokens":140,"total_tokens":240}


def create_e2e_app():
    url = validate_test_target(os.environ.get("TEST_DATABASE_URL"), os.environ.get("KAOYAN_OWNED_TEST_PORT"))
    engine = create_db_engine(url)
    try:
        with create_session_factory(engine).begin() as db:
            if not db.scalar(select(KnowledgePoint).where(KnowledgePoint.code == NODE_CODE)):
                node = KnowledgePoint(code=NODE_CODE, name="级数求和（隔离验收）", subject="考研数学",
                    is_active=True, is_assessable=True, is_reference_only=False)
                db.add(node); db.flush(); db.add(KpState(kp_id=node.id))
            if not db.scalar(select(KnowledgePoint).where(KnowledgePoint.code == NODE_CODE + '.truncated')):
                node = KnowledgePoint(code=NODE_CODE + '.truncated', name='级数求和（截断诊断隔离）', subject='考研数学',
                    is_active=True, is_assessable=True, is_reference_only=False)
                db.add(node); db.flush(); db.add(KpState(kp_id=node.id))
            if not db.scalar(select(KnowledgePoint).where(KnowledgePoint.code == NODE_CODE + '.difficulty_conflict')):
                node = KnowledgePoint(code=NODE_CODE + '.difficulty_conflict', name='级数求和（难度冲突隔离）',subject='考研数学',
                    is_active=True,is_assessable=True,is_reference_only=False)
                db.add(node);db.flush();db.add(KpState(kp_id=node.id))
            for suffix,label in [('count_success','数量核对成功隔离'),('count_mixed','数量核对部分成功隔离'),('count_truncated','数量核对单题失败隔离'),
                    ('count_network','默认单题网络失败隔离'),('count_network_multi','多题网络失败隔离')]:
                if not db.scalar(select(KnowledgePoint).where(KnowledgePoint.code==NODE_CODE+'.'+suffix)):
                    node=KnowledgePoint(code=NODE_CODE+'.'+suffix,name=label,subject='考研数学',is_active=True,is_assessable=True,is_reference_only=False)
                    db.add(node);db.flush();db.add(KpState(kp_id=node.id))
    finally:
        engine.dispose()
    from scripts.e2e_backend import create_e2e_app as offline_app
    app = offline_app()
    # This dedicated generation suite exercises real HTTP/SSE and persistence,
    # not retrieval. Loading the embedding stack can exceed the test server's
    # startup deadline on Windows and is unrelated to these user journeys.
    # Keep the production lifespan (DB ownership, recovery and cache warmup).
    import backend.app as backend_app
    def generation_only_retrieval(application, settings):
        application.state.retrieval_stack = None
        application.state.retrieval_error = 'generation_browser_fixture_without_retrieval'
        return False
    backend_app._try_build_retrieval_stack = generation_only_retrieval
    app.state.personal_generation_provider = SeriesProvider()
    from datetime import datetime, timezone
    from backend.api.deps import get_time_provider
    app.dependency_overrides[get_time_provider] = lambda: lambda: datetime(2026,10,18,16,0,2,tzinfo=timezone.utc)
    if os.environ.get('ZERO_PAID_UX_ACCEPTANCE')=='1':
        from tests.integration.zero_paid_ux_fixture import configure
        configure(app)
    return app
