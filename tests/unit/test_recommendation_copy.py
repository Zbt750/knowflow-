import pytest
from backend.services.recommendation_copy import recommendation_sentence


@pytest.mark.parametrize('text',['先阅读讲解','先阅读讲解。','先阅读讲解。。','先阅读讲解.'])
def test_recommendation_has_one_sentence_ending(text):
    assert recommendation_sentence(text)=='先阅读讲解。'


def test_sentence_preserves_values_and_existing_question():
    assert recommendation_sentence('预计0.5分钟')=='预计0.5分钟。'
    assert recommendation_sentence('是否继续？')=='是否继续？'
    assert recommendation_sentence('')==''
