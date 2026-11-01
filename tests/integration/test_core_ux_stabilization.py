"""Actual read/plan services on isolated DB; all model turns are protocol probes."""
import asyncio
from copy import deepcopy
from datetime import timedelta
import json
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo
from sqlalchemy import select, func

from tests.integration.test_learning_loop import session_factory, clean_database
from tests.integration.test_learning_tasks import clean_tasks
from tests.integration.test_post_graduation_practice import graduated
from tests.integration.test_policy_origin_semantics import DAY
from tests.integration.test_agent_final_repairs import setup_formal
from backend.models.chat import ChatSession
from backend.models.learning import KpState, DailyPlan, QuestionAttempt, LearningEvent
from backend.schemas.learning_assistant import AssistantRequest, StudyContext
from backend.services.learning_assistant_service import assistant_stream
from backend.services.learning_task_context import expand_records
from backend.services.question_availability import question_availability
from backend.config import get_settings


def stream(factory, sid, question, provider=None, now=None):
    async def run():
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=get_settings())))
        return b''.join([piece async for piece in assistant_stream(factory, request=request, session_id=sid,
            body=AssistantRequest(question=question, study_context=StudyContext(surface='study'), request_key=uuid4()),
            stack=None, provider=provider, now=now)]).decode()
    return asyncio.run(run())


def test_qualified_sources_are_counted_from_stored_ownership(session_factory):
    _, kp, _ = setup_formal(session_factory)
    with session_factory() as db:
        result = question_availability(db, now=DAY, kp_ids=[kp])
        assert result['source_category_counts']['development_original'] >= 1
        assert result['bank_scope_counts']['public'] >= 1
        assert sum(result['source_category_counts'].values()) == result['practice_eligible_count']
        assert sum(result['bank_scope_counts'].values()) == result['practice_eligible_count']


def test_exact_source_query_enters_agent_and_reads_inventory_without_writing_plan(session_factory):
    class SourceQuery:
        model = 'offline-source-query-probe'
        calls = 0
        def tool_turn(self, messages, tools, *, timeout):
            self.calls += 1
            if self.calls == 1:
                assert any(t['function']['name'] == 'get_question_availability' for t in tools)
                return {'message': {'tool_calls': [{'id':'inventory', 'type':'function', 'function':
                    {'name':'get_question_availability', 'arguments':'{}'}}]}, 'model':self.model}
            inventory = expand_records(json.loads(messages[-1]['content']))
            assert 'source_category_counts' in inventory and 'bank_scope_counts' in inventory
            return {'message': {'content': json.dumps({'message':'已从真实工具读取可练题来源；这里只查询，没有创建计划。', 'needs_clarification':False})}, 'model':self.model}
    with session_factory.begin() as db:
        session = ChatSession(mode='builtin',purpose='study',study_date=DAY.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat(),title='TEST_FIXTURE source query');db.add(session);db.flush();sid=session.id
        before = db.scalar(select(func.count()).select_from(DailyPlan))
    provider = SourceQuery()
    data = stream(session_factory, sid, '我现在可以练习的题目有哪些？哪些是历年真题，哪些是原创题？', provider, DAY)
    assert '"intent": "query"' in data and 'get_question_availability' in data
    assert provider.calls == 2 and '"status": "answered"' in data
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(DailyPlan)) == before


def test_graduation_explanation_separates_fact_from_recent_practice(graduated):
    factory, kp, _, before, _ = graduated
    with factory.begin() as db:
        from backend.models.learning import KnowledgePoint
        db.get(KnowledgePoint, kp).name = '行列式'
        session = ChatSession(mode='builtin',purpose='study',study_date=(DAY+timedelta(days=5)).astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat(),title='TEST_FIXTURE exact A4');db.add(session);db.flush();sid=session.id
        preserved = {table.__tablename__:db.scalar(select(func.count()).select_from(table)) for table in (QuestionAttempt,LearningEvent,DailyPlan)}
    class NoProvider:
        def __getattr__(self, name):
            raise AssertionError('deterministic graduation explanation must not call a model')
    data = stream(factory, sid, '我的行列式节点已经毕业了吗？之后复习做错会不会把原来的毕业取消？', NoProvider(), DAY+timedelta(days=5))
    for phrase in ('该知识点已经正式毕业','毕业事实不会','近期表现与历史毕业证据不是同一概念','0次不代表历史上没有练习'):
        assert phrase in data
    with factory() as db:
        state = db.get(KpState, kp)
        assert (state.state,state.evidence_window,state.mastered_at) == before
        assert all(db.scalar(select(func.count()).select_from(table)) == preserved[table.__tablename__] for table in (QuestionAttempt,LearningEvent,DailyPlan))
