"""Compound statistics retain metrics as well as separate record scopes."""
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

from backend.models.learning import KnowledgePoint, QuestionAttempt
from backend.services import learning_evidence_query as module


def test_composite_correctness_rates_are_calculated_for_both_real_record_subsets(monkeypatch):
    node_id, other_id = UUID(int=1), UUID(int=2)
    now = datetime(2026, 10, 26, 4, tzinfo=timezone.utc)
    nodes = [SimpleNamespace(id=node_id, name="洛必达法则", subject="数学二"),
             SimpleNamespace(id=other_id, name="定积分", subject="数学二")]
    attempts = [
        SimpleNamespace(id=UUID(int=11), kp_id=node_id, submitted_at=now,
                        objective_result="right", grading_evidence={"assisted": False}),
        SimpleNamespace(id=UUID(int=12), kp_id=node_id, submitted_at=now,
                        objective_result="wrong", grading_evidence={"assisted": False}),
        SimpleNamespace(id=UUID(int=13), kp_id=other_id, submitted_at=now,
                        objective_result="right", grading_evidence={"assisted": True, "assistance_level": "solution"}),
        SimpleNamespace(id=UUID(int=14), kp_id=other_id, submitted_at=now,
                        objective_result="unknown", grading_evidence={}),
    ]

    class ReadOnlyRecords:
        def scalars(self, statement):
            entity = statement.column_descriptions[0]["entity"]
            params = statement.compile().params
            if entity is KnowledgePoint:
                ids = params.get("id_1")
                return [n for n in nodes if ids is None or n.id in ids]
            assert entity is QuestionAttempt
            ids = params["kp_id_1"]
            return [a for a in attempts if a.kp_id in ids
                    and params["submitted_at_1"] <= a.submitted_at <= params["submitted_at_2"]]

    monkeypatch.setattr("backend.services.learning_task_tools.TaskTools",
                        lambda *args, **kwargs: SimpleNamespace(
                            explicit_scope=[node_id] if "洛必达" in kwargs["goal"] else []))
    monkeypatch.setattr(module, "_descendant_ids", lambda db, ids: ids)
    monkeypatch.setattr(module, "read_self_reports", lambda db, session_id: [])
    result = module.learning_evidence_query(
        ReadOnlyRecords(), None, session_id=UUID(int=3),
        ctx=SimpleNamespace(daily_plan_id=None, knowledge_node_ids=[node_id]),
        message="我全库的正确率，和洛必达法则这个知识点的正确率分别是多少？",
        query_type="learning_state", now=now)

    global_text, node_text = result["answer"].split("## 指定知识点统计")
    assert "客观已判定正确率：2/3" in global_text
    assert "独立作答正确率：1/2" in global_text
    assert "客观已判定正确率：1/2" in node_text
    assert "独立作答正确率：1/2" in node_text
    global_scope, node_scope = result["evidence"]["scope_results"]
    assert set(global_scope["attempt_ids"]) == {str(a.id) for a in attempts}
    assert set(node_scope["attempt_ids"]) == {str(a.id) for a in attempts[:2]}
    assert global_scope["attempt_summary"]["unknown"] == 1
    assert global_scope["attempt_summary"]["assisted_right"] == 1
    assert global_scope["time_window"] == node_scope["time_window"]
    assert global_scope["writes"] is node_scope["writes"] is False
