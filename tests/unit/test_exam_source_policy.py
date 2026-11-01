import pytest
from backend.services.exam_source_policy import requests_original_exam
from backend.services.home_intent import resolve


@pytest.mark.parametrize('text',['给我找一道原版历年真题','找两道历年考研真题','有没有历史真题','不要改编题，只要原版真题','原版真题，给我一道'])
def test_original_exam_request_requires_adapted_source_consent(text):
    assert requests_original_exam(text)
    intent,trace=resolve(text,None,lambda:pytest.fail('no model needed for inventory policy'))
    assert intent.operation=='clarify' and '没有原版' in intent.question
    assert trace['model_calls']==0


@pytest.mark.parametrize('text',['找一道真题改编题','找历年真题的改编题','不要原版真题，找改编题','根据原题生成一道变式'])
def test_adapted_or_reference_request_is_not_claimed_as_original(text):
    assert not requests_original_exam(text)
