from copy import deepcopy
from uuid import uuid4

from backend.schemas.knowledge import NodeAttemptView


def test_node_history_does_not_export_private_grading_audit():
    evidence = {"assisted": True, "assistance_level": "solution", "attempt_number": 2,
        "sequence_category": "solution_assisted_correct", "grading_config": {
            "verification_revisions": [{"before": "PRIVATE SNAPSHOT"}]},
        "reference_answer": "PRIVATE ANSWER KEY", "previous_mastery_snapshot": {"internal": "PRIVATE"}}
    before = deepcopy(evidence)
    view = NodeAttemptView(id=uuid4(), question_id=uuid4(), question_stem="SYNTHETIC QUESTION",
        self_grade=None, objective_result="right", result_state="consolidating", reason_code="test",
        submitted_at="2026-10-03T00:00:00+00:00", grading_evidence=evidence)
    assert view.grading_evidence == {"assisted": True, "assistance_level": "solution", "attempt_number": 2,
        "sequence_category": "solution_assisted_correct"}
    assert evidence == before
    assert "PRIVATE" not in view.model_dump_json()
