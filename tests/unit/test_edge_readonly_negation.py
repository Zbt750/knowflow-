import pytest
from backend.services.assistant_data_queries import classify_read_only_data_query
from backend.services.assistant_router import route_message


@pytest.mark.parametrize('text', [
    '你刚才说本次没有记录，那我不用自己粘贴，你能直接查一下系统里数学二有多少道可以练的题吗？先只查询，不要给我安排练习。',
    '数学二有几道题？别安排练习。',
    '请查询我的题库数量，不需要创建学习计划。',
])
def test_negated_arrangement_is_not_positive_planning(text):
    assert classify_read_only_data_query(text) == 'inventory'
    assert route_message(text, {}).capability == 'data_query'


def test_positive_planning_still_planning():
    text = '根据学习记录给我安排90分钟复习，先给建议，不要创建计划。'
    assert classify_read_only_data_query(text) is None
    assert route_message(text, {}).capability == 'planner'


def test_explicit_subject_overrides_incidental_antecedent(monkeypatch):
    from types import SimpleNamespace
    from backend.services import assistant_data_queries as queries
    monkeypatch.setattr(queries, 'TaskTools', lambda *a, **kw: SimpleNamespace(explicit_scope=[]))
    roots, origin = queries._resolve_query_scope(None, factory=None, session_id=None,
        ctx=SimpleNamespace(knowledge_node_ids=['old-node'],question_id=None,task_id=None),
        message='你刚才说没有记录，那数学二有多少道可以练的题？')
    assert roots == []
    assert origin == 'global_or_subject_inventory'


@pytest.mark.parametrize('prefix', ['先不安排了。', '暂不安排练习。', '不再安排了。'])
def test_withdraw_operation_then_explain(prefix):
    from types import SimpleNamespace
    text = prefix + '刚才预览的sin(x)/x在x趋于0时为什么能用洛必达？请简单讲，但把0/0和无穷比无穷的条件都说清楚，再给我一个不能直接求导相比的例子。'
    assert route_message(text, SimpleNamespace(question_id=None, knowledge_node_ids=[])).capability == 'qa'
