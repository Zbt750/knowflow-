import pytest
from backend.schemas.learning_assistant import StudyContext
from backend.services.assistant_router import route_message


@pytest.mark.parametrize('text', [
    '请说明函数极限的含义，作为普通知识讲解，不安排练习。',
    '讲讲定积分，不选题。',
    '解释连续性，不加入今日卷。',
    '请说明函数极限，不生成题目。',
])
def test_negated_operations_do_not_prevent_ordinary_explanation(text):
    route = route_message(text, StudyContext(surface='chat'))
    assert route.capability == 'qa'
    assert route.intent == 'qa'
    assert route.write_risk is False
