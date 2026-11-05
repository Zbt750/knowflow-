from types import SimpleNamespace
import pytest
from backend.errors import AppError
from backend.services.paper_adjustment_service import protection_state, require_removable, _signature


def item(**changes):
    return SimpleNamespace(id='one',question_version_id='v1',removed_at=None,
                           completed_at=None,answer_revealed_at=None,**changes)


@pytest.mark.parametrize('kinds,attempt,expected',[
    (set(),False,'planned'),({'viewed'},False,'viewed'),({'started'},False,'started'),
    ({'skipped'},False,'skipped'),({'viewed'},True,'submitted'),
])
def test_existing_activity_and_attempt_facts_determine_protection(kinds,attempt,expected):
    assert protection_state(item(),kinds,attempt)==expected


@pytest.mark.parametrize('state',['started','submitted','completed','skipped','removed'])
def test_history_bearing_states_cannot_be_removed_even_after_confirmation(state):
    with pytest.raises(AppError): require_removable(state,viewed_confirmed=True)


def test_viewed_item_requires_explicit_second_confirmation():
    with pytest.raises(AppError):require_removable('viewed')
    require_removable('viewed',viewed_confirmed=True)
    require_removable('planned')


def test_new_version_invalidates_paper_snapshot():
    first=item(); before=_signature([first]);first.question_version_id='v2'
    assert _signature([first])!=before


def test_completion_and_removal_override_older_view_events():
    from datetime import datetime, timezone
    row=item();row.completed_at=datetime.now(timezone.utc)
    assert protection_state(row,{'viewed'},True)=='completed'
    row.removed_at=row.completed_at
    assert protection_state(row,{'viewed'},True)=='removed'


def test_history_foreign_key_restricts_physical_item_deletion():
    from backend.models.learning import QuestionAttempt
    foreign_key=next(iter(QuestionAttempt.__table__.c.practice_item_id.foreign_keys))
    assert foreign_key.ondelete=='RESTRICT'


def test_view_confirmation_must_be_a_boolean_not_a_text_command():
    from backend.schemas.paper_adjustment import PaperAdjustmentConfirmation
    from pydantic import ValidationError
    from uuid import uuid4
    with pytest.raises(ValidationError):
        PaperAdjustmentConfirmation(session_id=uuid4(),draft_version='a'*64,confirm_viewed='yes')
