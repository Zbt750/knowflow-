"""Current read projections must not label withdrawn receipts as graduation."""
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from backend.mastery.enums import MasteryState
from backend.mastery.storage import evidence_to_storage
from backend.models.learning import KpState
from backend.services.policy_evidence_service import current_policy_snapshot
from tests.unit.test_policy_origin_semantics import confirmation, origin_policy


class MissingCurrentReceipts:
    def scalars(self, statement):
        return []

    def get(self, model, key):
        return None


def test_withdrawn_current_receipts_do_not_display_current_graduation_or_rewrite_history():
    state=KpState(kp_id=uuid4(),state="mastered",assessment_basis="objective_v1",
        evidence_window=[evidence_to_storage(confirmation(i)) for i in range(3)],
        manual_credit_count=0,manual_confirmed_at=None,node_self_grade=None,
        review_stage=0,next_review_at=datetime(2026,10,20,tzinfo=timezone.utc),
        mastered_at=datetime(2026,10,10,tzinfo=timezone.utc),pending_review_question_ids=[])
    original=deepcopy(state.evidence_window)
    projected=current_policy_snapshot(MissingCurrentReceipts(),state,origin_policy())
    assert projected.evidence_window==()
    assert projected.state is not MasteryState.MASTERED
    assert projected.mastered_at is None
    assert state.state=="mastered" and state.evidence_window==original
    assert state.mastered_at is not None
