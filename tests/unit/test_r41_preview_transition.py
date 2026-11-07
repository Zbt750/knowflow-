from types import SimpleNamespace
from uuid import uuid4
import pytest
from backend.services import home_recommendation_service as service
from backend.services.home_public_view import public_preview


def test_current_allocated_leaves_expose_transition_consent_without_original_recommendations(monkeypatch):
    parent, leaf, other = uuid4(), uuid4(), uuid4()
    result = {'draft': {'selected_kp_ids': [str(parent)], 'allocation_kp_ids': [str(leaf)], 'questions': []},
              'context': {'system_recommendations': []}, 'receipt': None}
    monkeypatch.setattr(service, 'view', lambda row: result)
    def policies(db, ids, *, include_missing):
        assert ids == [leaf] and include_missing
        return {leaf: SimpleNamespace(graduation_binding_pending=True)}, None
    monkeypatch.setattr('backend.services.study_read_context.policies_for_nodes', policies)
    shown = public_preview(service._preview_view(object(), object()))
    assert shown['context']['required_graduation_set_transition_ids'] == [str(leaf)]
    assert str(parent) not in shown['context']['required_graduation_set_transition_ids']
    assert str(other) not in shown['context']['required_graduation_set_transition_ids']
    assert shown['draft']['questions'] == []


@pytest.mark.parametrize('receipt,draft', [({'plan_id': 'already-created'}, {'selected_kp_ids': []}), (None, None)])
def test_committed_or_empty_preview_does_not_request_new_transition(monkeypatch, receipt, draft):
    monkeypatch.setattr(service, 'view', lambda row: {'receipt': receipt, 'draft': draft, 'context': {}})
    def forbidden(*args, **kwargs):
        raise AssertionError('No policy read needed without an uncommitted draft')
    monkeypatch.setattr('backend.services.study_read_context.policies_for_nodes', forbidden)
    assert service._preview_view(object(), object())['context']['required_graduation_set_transition_ids'] == []

def test_public_system_skips_only_private_evidence_work(monkeypatch):
    from datetime import datetime, timezone
    from backend.services.home_public_view import public_system
    node = uuid4()
    recommendation = SimpleNamespace(kp_id=node, model_dump=lambda **kwargs: {'kp_id': str(node), 'name': 'actual-topic'})
    monkeypatch.setattr(service, '_home_inventory', lambda *args: {'practice_eligible_count': 3})
    monkeypatch.setattr(service, '_paper', lambda *args, **kwargs: {'selected_kp_ids': [str(node)], 'questions': [], 'total_minutes': 0})
    called=[]
    tool = SimpleNamespace(nodes=set(), get_learning_state=lambda *args: called.append(node) or {'states': [{'private': 'diagnostic'}]})
    monkeypatch.setattr(service, '_tools', lambda *args: tool)
    db = SimpleNamespace(scalars=lambda *args: [])
    now=datetime(2026,11,7,tzinfo=timezone.utc)
    rich=service.read_system(db,[recommendation],now)
    assert called == [node] and rich['evidence']['states']
    called.clear()
    fast=service.read_system(db,[recommendation],now,include_evidence=False)
    assert called == [] and fast['evidence']['states'] == []
    assert public_system(rich) == public_system(fast)


def test_difficulty_receipt_exposes_only_count_never_private_references():
    value={'difficulty_changes':[{'old_question_id':'private-old','new_question_id':'private-new'},
                                 {'old_question_version_id':'private-version','stem':'private-stem'}]}
    wire=public_preview(value)
    assert wire == {'difficulty_change_count':2}
