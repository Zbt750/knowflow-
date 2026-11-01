import pytest
from backend.services.personal_generation_intent import explicitly_generate, _preferences


@pytest.mark.parametrize("message", [
    "帮我生成一道难度更大的类似题。", "这道题不错，再出一道同类型的。",
    "基于这道题给我出一道变式题。", "再来一道难一点的练习题。",
    "帮我出一道类似的题。", "这题我会了，换一道更有挑战性的。",
    "这道题我觉得还不错，帮我生成一道比它难一点的类似题。",
    "根据我刚才发的题目，再出一道综合性更强的题。",
    "请编写一道矩阵计算题", "再给我两道同类练习",
])
def test_explicit_generation_without_requiring_polite_prefix(message):
    assert explicitly_generate(message)


@pytest.mark.parametrize("message", [
    "根据当前洛必达知识点，给我出一道稍难的极限题，要求答案与解析一致；不确定的内容标明未核验，不加入今日学习。",
    "请生成一道幂级数单选题，正确选项必须出现在选项中，并附上答案和解析。",
])
def test_answer_consistency_constraints_do_not_cancel_explicit_question_generation(message):
    assert explicitly_generate(message)


@pytest.mark.parametrize("message", [
    "解释这道题", "帮我检查这道题的解题思路", "给我讲一下编码理论",
    "题库里有多少题", "出题功能怎么用", "解释出题过程", "不要生成新题，解释原题",
    "给我生成这道题的解答", "这道题为什么会生成两个解",
])
def test_explanations_and_inventory_are_not_generation(message):
    assert not explicitly_generate(message)


def test_increased_difficulty_is_not_silently_basic():
    assert _preferences("再来一道难一点的练习题")[0] == "improved"
    assert _preferences("再出一道综合性更强的题")[0] == "comprehensive"


def test_generated_text_with_json_control_character_damage_is_rejected():
    from backend.services.question_generation import Output
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="generated_text_encoding_damaged"):
        Output(stem="求和公式 "+"\x0c"+"rac{x}{1-x}", question_type="calculation", correct_answer="x",
            explanation="这是包含损坏公式的解析，不应作为有效题保存。", final_value="x")
