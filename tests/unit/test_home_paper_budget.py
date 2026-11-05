from types import SimpleNamespace
import pytest
from backend.services.practice_service import cap_paper_minutes


def entries(*minutes):
    return [(None, SimpleNamespace(estimated_minutes=m), None, str(i), None) for i,m in enumerate(minutes)]


def test_whole_paper_cap_preserves_formal_order_and_never_fills_with_fake_work():
    values=entries(30,30,20)
    assert cap_paper_minutes(values,90)==values
    assert cap_paper_minutes(values,60)==values[:2]
    assert cap_paper_minutes(values,25)==values[2:]
    assert cap_paper_minutes(values,15)==[]


@pytest.mark.parametrize('minutes',[0,4,241])
def test_budget_contract_is_enforced(minutes):
    with pytest.raises(ValueError,match='invalid_budget_minutes'):
        cap_paper_minutes(entries(10),minutes)


def test_invalid_estimate_is_not_treated_as_free_question():
    with pytest.raises(ValueError,match='question_minutes_invalid'):
        cap_paper_minutes(entries(0),90)
