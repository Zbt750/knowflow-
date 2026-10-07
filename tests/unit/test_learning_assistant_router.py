from types import SimpleNamespace
from uuid import uuid4
import pytest
from backend.schemas.learning_assistant import StudyContext
from backend.services.assistant_router import route_message,assistance_action,answer_reliability_question
from backend.services.learning_qa_service import safe_hint
from backend.services.learning_assistant_service import present_planner_message


@pytest.mark.parametrize("text,capability,intent",[
    ("为什么这题不能用洛必达？","qa","qa"),("这一步哪里错了？","qa","qa"),
    ("给我一点提示","qa","qa"),("我还是不懂","qa","qa"),
    ("解释一下二叉树的性质","qa","qa"),("为什么奶蛙还给我安排这个？","qa","qa"),
    ("为什么这个知识点还没毕业？","qa","qa"),("给我安排三道这种题","planner","plan"),
    ("我还有30分钟，帮我安排一下","planner","plan"),("今天重点练积分","planner","plan"),
    ("给我补两道二叉树","planner","plan"),("把剩下的换简单一点","planner","modify"),
    ("哪些知识点现在有题？","planner","query"),("我今天应该先学什么？","planner","recommend"),
    ("这种题我总错，帮我练一下","planner","plan"),
    ("根据我今天实际学习记录，先读取学习状态，再检查库存。接下来应该练什么？","planner","recommend"),
])
def test_fixed_router_categories(text,capability,intent):
    decision=route_message(text,StudyContext(question_id=uuid4()))
    assert (decision.capability,decision.intent)==(capability,intent)


def test_active_task_changes_refinement_route_and_invalid_classifier_falls_back():
    assert route_message("少一点",StudyContext()).capability=="qa"
    assert route_message("少一点",StudyContext(),task={"status":"ready","committed":False}).capability=="planner"
    assert route_message("少一点",StudyContext(),task={"status":"ready","committed":True}).capability=="qa"
    assert route_message("帮我看看这个",StudyContext(),classifier=lambda *_:"APPLY_NOW").capability=="qa"
    assert route_message("请求",StudyContext(),classifier=lambda *_:"PLANNER_PLAN").write_risk


def test_assistance_is_not_inferred_from_ordinary_concept_or_graduation_question():
    for text in ("洛必达法则是什么？","为什么知识点没毕业？","题库有多少道？"):
        assert assistance_action(text,question_present=True) is None
    assert assistance_action("请提示下一步",question_present=True)=="hint_2"
    assert assistance_action("请看答案",question_present=False) is None


@pytest.mark.parametrize("text",["正确答案为 B。","所以选B。","最终结果是B","解答"*400])
def test_known_hint_leaks_are_blocked_before_delivery(text):
    hint,blocked=safe_hint(text,SimpleNamespace(correct_answer="B",question_type="single_choice"),"hint_1")
    assert blocked and "B" not in hint


def test_direction_hint_is_preserved():
    assert safe_hint("先检查未定式类型，再考虑适用条件。",SimpleNamespace(correct_answer="B",question_type="single_choice"),"hint_1")[1] is False


@pytest.mark.parametrize("message,action",[
    ("给我一点提示。","hint_1"),("再提示一点。","hint_2"),
    ("别告诉答案，给我一点提示。","hint_1"),("请提示下一步","hint_2"),
    ("我刚才第一次答错，看提示以后才答对，为什么还没毕业？",None),
    ("我已经看过答案了，为什么这次答对还不算独立掌握？",None),
    ("为什么这个知识点还没学完？",None),
    ("算法设计中的提示信息是什么意思？",None),
    ("我刚才看过提示才答对",None),
    ("结合我的提示使用记录解释掌握状态",None),
    ("我看过提示了，再提示一点。","hint_2"),
])
def test_current_assistance_request_is_distinct_from_history(message,action):
    assert assistance_action(message,question_present=True)==action

@pytest.mark.parametrize("message,expected",[
    ("这题答案一定对吗？",True),("这道题的答案是官方的吗？",True),
    ("请讲解当前题的关键思路与适用条件。参考答案尚未人工核验，请明确区分可靠结论和参考推导。",False),
])
def test_answer_reliability_notice_only_answers_a_current_reliability_question(message,expected):
    assert answer_reliability_question(message)==expected


def test_planner_presentation_removes_full_and_known_short_ids_without_changing_counts():
    question=uuid4();ctx=StudyContext(question_id=question)
    text=f"原题{str(question)[:8]}…已在今日卷；可补2道选择题。任务{uuid4()}。"
    visible=present_planner_message(text,SimpleNamespace(trace=[]),ctx)
    assert str(question)[:8] not in visible
    assert "2道选择题" in visible


@pytest.mark.parametrize("text",["正确答案为 **B**。","结论：选 **B**。","答案为 `B`。"])
def test_markdown_hint_leaks_are_blocked(text):
    _,blocked=safe_hint(text,SimpleNamespace(correct_answer="B",question_type="single_choice"),"hint_1")
    assert blocked
