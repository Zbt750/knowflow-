from dataclasses import replace
from datetime import datetime, timedelta, timezone
import pytest
from backend.mastery.learning_progress import ProgressAttempt, project_learning_progress

NOW = datetime(2026, 10, 8, tzinfo=timezone.utc)


def attempt(q="q1", result="right", **changes):
    fields = dict(question_id=q, practice_item_id="item-" + q, occurred_at=NOW, result=result,
        number=1, assisted=False, assistance_level="none", category="first_independent_correct",
        sequence_version="attempt-sequence-v1", history_unknown=False, content_identity=q,
        skill_tags=("conditions", "calculation"))
    fields.update(changes)
    return ProgressAttempt(**fields)


def project(rows, **kwargs):
    return project_learning_progress(rows, practice_count=kwargs.pop("practice_count", 3), **kwargs)


def test_practice_exists_without_strict_confirmation():
    p = project([attempt()])
    assert p.status == "PRACTICING" and p.distinct_question_count == 1
    assert "参考答案" in p.reliability_note and p.strict_graduation_unchanged


def test_same_item_correction_has_learning_but_needs_retest():
    p = project([attempt(result="wrong"), attempt(number=2, category="self_corrected")])
    assert p.status == "RETEST_RECOMMENDED" and p.distinct_question_count == 1
    assert p.observed_attempt_count == 2


@pytest.mark.parametrize("level", ["solution", "hint_1", "hint_2", "process_review"])
def test_assisted_success_is_not_independent(level):
    p = project([attempt(assisted=True, assistance_level=level)])
    assert p.status == "RETEST_RECOMMENDED" and p.assisted_correct_question_count == 1


def test_repeated_question_does_not_create_skill_or_distinct_credit():
    p = project([attempt(occurred_at=NOW+timedelta(days=i), reliable_current=True,
        strict_current_confirmation=True) for i in range(5)])
    assert p.status != "STABLE_PRACTICE" and p.distinct_question_count == 1


def test_reference_wrong_is_not_reliable_failure():
    p = project([attempt(result="wrong")])
    assert p.status == "PRACTICING" and p.reference_wrong_count == 1 and p.reliable_wrong_count == 0
    assert "不能确定" in p.reason


def test_reliable_wrong_needs_consolidation():
    assert project([attempt(result="wrong", reliable_current=True)]).status == "NEEDS_CONSOLIDATION"


@pytest.mark.parametrize("result", ["unknown", "unsupported"])
def test_unknown_is_not_wrong(result):
    p = project([attempt(result=result, assisted=None, assistance_level=None)])
    assert p.status == "PRACTICING" and p.unknown_count == 1 and p.reliable_wrong_count == 0


def test_legacy_missing_fields_does_not_infer_independence():
    p = project([attempt(q=f"q{i}", assisted=None, assistance_level=None,
        sequence_version=None, history_unknown=None) for i in range(5)])
    assert p.status == "PRACTICING"
    assert any("不能推断独立" in s for s in p.limitations)


def test_no_inventory_is_content_problem():
    p = project([], practice_count=0)
    assert p.status == "NOT_STARTED" and p.next_action == "read_lesson"
    assert any("不能据此判断你不会" in s for s in p.limitations)


def test_progress_across_distinct_reference_questions_is_observation_not_stable():
    p = project([attempt(result="wrong"), attempt("q2", occurred_at=NOW+timedelta(days=1)),
                 attempt("q3", occurred_at=NOW+timedelta(days=2))])
    assert p.status == "IMPROVING" and p.status != "STABLE_PRACTICE"
    assert "参考答案" in p.next_step


def test_stable_only_current_strict_receipts_with_diversity_and_delay():
    rows = [attempt(f"q{i}", occurred_at=NOW+timedelta(days=i), reliable_current=True,
        strict_current_confirmation=True) for i in range(3)]
    assert project(rows, required_tags=["conditions"]).status == "STABLE_PRACTICE"
    assert project(rows, history_truncated=True).status != "STABLE_PRACTICE"
    assert project(rows, required_tags=["not-covered"]).status != "STABLE_PRACTICE"
    assert project([replace(r, reliable_current=False) for r in rows]).status != "STABLE_PRACTICE"
    assert project([replace(r, content_identity="same") for r in rows]).status != "STABLE_PRACTICE"


def test_later_observed_independent_retest_does_not_keep_assistance_forever():
    rows = [attempt(assisted=True, assistance_level="solution"),
        attempt(practice_item_id="fresh-item", occurred_at=NOW+timedelta(days=1))]
    assert project(rows).status == "PRACTICING"


def test_reliable_wrong_has_priority_over_another_assisted_correct():
    assert project([attempt(result="wrong", reliable_current=True),
        attempt("q2", assisted=True, assistance_level="solution")]).status == "NEEDS_CONSOLIDATION"


def test_unsupported_retry_cannot_erase_prior_reliable_error():
    assert project([attempt(result="wrong", reliable_current=True),
        attempt(result="unknown", number=2)]).status == "NEEDS_CONSOLIDATION"
