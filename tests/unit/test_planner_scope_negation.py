"""Scope precedence regressions using memory objects; no database or model calls."""
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest

from backend.models.learning import KnowledgePoint
from backend.services.learning_planner_scope import resolve_planner_scope


@pytest.mark.parametrize("message,expected_origin,expected_nodes", [
    (
        "给我数学二复习建议，不要只围绕当前这道题",
        "explicit_subject_scope",
        {1, 2, 3},
    ),
    (
        "数学二整体复习安排里，这次只复习当前这道题",
        "explicit_current_question",
        {2},
    ),
    ("给我数学二复习建议，别仅围绕当前知识点", "explicit_subject_scope", {1, 2, 3}),
    ("给我数学二复习建议，不止当前题", "explicit_subject_scope", {1, 2, 3}),
    ("围绕当前题给我数学二复习建议", "explicit_current_question", {2}),
    ("不要创建计划，只复习当前题", "explicit_current_question", {2}),
    ("数学二整体复习，不要只限制在当前题", "explicit_subject_scope", {1, 2, 3}),
])
def test_explicit_scope_respects_current_question_negation(
    message, expected_origin, expected_nodes
):
    nodes = [
        SimpleNamespace(id=UUID(int=1), parent_id=None, subject="考研数学", code="math"),
        SimpleNamespace(id=UUID(int=2), parent_id=UUID(int=1), subject="考研数学", code="math.limit"),
        SimpleNamespace(id=UUID(int=3), parent_id=UUID(int=1), subject="考研数学", code="math.integral"),
    ]

    class MemoryDatabase:
        def scalars(self, statement):
            assert statement.column_descriptions[0]["entity"] is KnowledgePoint
            return nodes

    @contextmanager
    def factory():
        yield MemoryDatabase()

    context = SimpleNamespace(
        conversation_id=UUID(int=100), knowledge_node_ids=[UUID(int=2)], subject="考研数学"
    )
    observed = SimpleNamespace(explicit_scope=None, excluded_scope=set())
    targets, subject, constraints = resolve_planner_scope(
        factory, context, message, observed, datetime(2026, 10, 24, tzinfo=timezone.utc),
        lambda *_: True,
    )

    assert constraints["scope_origin"] == expected_origin
    assert {UUID(value).int for value in constraints["resolved_scope_node_ids"]} == expected_nodes
    assert {target.int for target in targets} == ({1} if 1 in expected_nodes else expected_nodes)
    assert subject == "考研数学"
    assert constraints["scope_explicit"] is True
