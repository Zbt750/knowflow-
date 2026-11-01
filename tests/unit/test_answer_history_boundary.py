from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from backend.services.answer_submission_service import _scoped_question_history, MAX_PREVIOUS_QUESTION_RECORDS

NOW = datetime(2036, 10, 13, tzinfo=timezone.utc)

def attempt(hash_value, days, *, tracked=True, **overrides):
    receipt = {"question_content_sha256":hash_value,"version":5,
        "grading_input_version":"bounded-final-input-v2","sequence_version":"attempt-sequence-v1",
        "assisted":False,"assistance_level":"none","result":"right"} if tracked else {"question_content_sha256":hash_value}
    receipt.update(overrides)
    return SimpleNamespace(grading_evidence=receipt,objective_result="right",submitted_at=NOW+timedelta(days=days))

def test_first_current_version_retest_keeps_unknown_history():
    old=attempt("old",-2,tracked=False)
    compatible,unknown,excluded=_scoped_question_history([old],"current")
    assert compatible==[] and unknown and excluded==0

def test_later_tracked_attempt_establishes_future_context_without_upgrading_old():
    old=attempt("old",-2,tracked=False)
    fresh=attempt("current",-1,sequence_category="independent_correct_history_unknown")
    original=old.grading_evidence.copy()
    compatible,unknown,excluded=_scoped_question_history([fresh,old],"current")
    assert compatible==[fresh] and not unknown and excluded==1
    assert old.grading_evidence==original

@pytest.mark.parametrize("changes",[
    {"version":3},{"grading_input_version":None},{"sequence_version":None},
    {"assisted":None},{"assistance_level":"unrecorded"},{"result":"wrong"},
])
def test_incomplete_or_inconsistent_current_receipt_does_not_clear_unknown(changes):
    current=attempt("current",-1,**changes);old=attempt("old",-2,tracked=False)
    assert _scoped_question_history([current,old],"current")[1] is True

def test_same_timestamp_does_not_invent_an_ordered_boundary():
    current=attempt("current",-1);old=attempt("old",-1,tracked=False)
    assert _scoped_question_history([current,old],"current")[1] is True

def test_newer_incompatible_attempt_blocks_an_older_anchor():
    old=attempt("old",0,tracked=False);current=attempt("current",-1)
    assert _scoped_question_history([old,current],"current")[1] is True

def test_bounded_history_overflow_remains_conservative():
    rows=[attempt("current",-i) for i in range(MAX_PREVIOUS_QUESTION_RECORDS+1)]
    assert _scoped_question_history(rows,"current")[1] is True

def test_ordinary_compatible_history_keeps_existing_behavior():
    current=attempt("current",-1)
    compatible,unknown,excluded=_scoped_question_history([current],"current")
    assert compatible==[current] and not unknown and excluded==0
