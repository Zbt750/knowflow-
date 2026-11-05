from types import SimpleNamespace
from uuid import uuid4
import pytest
from backend.schemas.learning_assistant import StudyContext
from backend.services.assistant_router import route_message,assistance_action,answer_reliability_question
from backend.services.learning_qa_service import safe_hint, final_answer_disclosed
from backend.services.learning_assistant_service import (
    present_planner_message, _requests_question_reference,
    _may_classify_data_query, _may_continue_generation,
)
from backend.services.personal_generation_intent import explicitly_generate
from backend.services.assistant_data_queries import classify_read_only_data_query


@pytest.mark.parametrize('text',[
    '从题库找两道洛必达法则的题，不要加入今日卷',
    '从现有题库选一道隐函数题，先不创建计划',
])
def test_explicit_bank_lookup_respects_withheld_write_consent(text):
    route=route_message(text,StudyContext())
    assert route.capability=='data_query' and route.intent=='find'
    assert not route.write_risk


@pytest.mark.parametrize('text',['不许给我生成两道洛必达法则题','不准生成一道隐函数练习题'])
def test_prohibited_authoring_never_requests_generation(text):
    assert explicitly_generate(text) is False


@pytest.mark.parametrize("text,capability,intent",[
    ("为什么这题不能用洛必达？","qa","qa"),("这一步哪里错了？","qa","qa"),
    ("给我一点提示","qa","qa"),("我还是不懂","qa","qa"),
    ("解释一下二叉树的性质","qa","qa"),("为什么奶蛙还给我安排这个？","qa","qa"),
    ("为什么这个知识点还没毕业？","qa","qa"),("给我安排三道这种题","planner","plan"),
    ("我还有30分钟，帮我安排一下","planner","plan"),("今天重点练积分","planner","plan"),
    ("给我补两道二叉树","planner","plan"),("把剩下的换简单一点","planner","modify"),
    ("哪些知识点现在有题？","data_query","inventory"),("我今天应该先学什么？","planner","recommend"),
    ("这种题我总错，帮我练一下","planner","plan"),
    ("根据我今天实际学习记录，先读取学习状态，再检查库存。接下来应该练什么？","planner","recommend"),
    ("接着上题，这个A的行列式、特征值，以及特征空间维数分别是多少？","qa","qa"),
    ("请根据二叉树题在提示后答对的真实记录推荐后续练习，说明这和独立答对有什么区别。","planner","recommend"),
    ("请根据二叉树题看了解析后答对的记录安排后续复测。","planner","plan"),
    ("请联网查询2027最新大纲","qa","qa"),
    ("题库里有多少道可练题？","data_query","inventory"),
    ("你好，我第一次使用奶蛙。你能具体帮我做什么？我主要复习考研数学和408；你能看我的题库、结合学习记录给建议、讲题或帮我安排练习吗？安排之前需要我确认吗？","qa","qa"),
    ("奶蛙支持哪些学习功能？","qa","qa"),
    ("你能帮我做什么？","qa","qa"),
    ("帮我安排一道洛必达题。","planner","plan"),
    ("我今天只有90分钟，根据我最近的错题和薄弱知识点安排数学二复习。先给出建议，未经我确认不要创建或追加今日学习。","planner","recommend"),
    ("根据洛必达复习安排一下，先给我建议，不要创建计划。","planner","recommend"),
])
def test_fixed_router_categories(text,capability,intent):
    decision=route_message(text,StudyContext(question_id=uuid4()))
    assert (decision.capability,decision.intent)==(capability,intent)


def test_capability_inquiry_does_not_authorize_practice_or_plan_writes():
    text=("你好，我第一次使用奶蛙。你能具体帮我做什么？我主要复习考研数学和408；"
          "你能看我的题库、结合学习记录给建议、讲题或帮我安排练习吗？安排之前需要我确认吗？")
    decision=route_message(text,StudyContext(question_id=uuid4()))
    assert decision.reason=="assistant_capability_inquiry"
    assert decision.capability=="qa" and decision.intent=="qa"
    assert decision.write_risk is False


def test_capability_inquiry_cannot_be_overridden_by_data_or_stale_generation_context():
    text="你能帮我做什么？比如你能查看我的题库有多少道数学二题，能不能查我做过的错题？"
    decision=route_message(text,StudyContext())
    assert decision.reason=="assistant_capability_inquiry"
    assert not _may_classify_data_query(decision,qa_action="auto",generation_requested=False)
    assert not _may_continue_generation(decision,mode="builtin",qa_action="auto",
        generation_requested=False,generation_continuation=True)
    explicit=route_message("题库里有多少道数学二可练题？",StudyContext())
    assert _may_classify_data_query(explicit,qa_action="auto",generation_requested=False)
    assert not _may_continue_generation(explicit,mode="builtin",qa_action="auto",
        generation_requested=False,generation_continuation=False)


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


@pytest.mark.parametrize("text", [
    "结论：选 **A**。", "最终答案为 `B`。", "所以选 _C_。",
])
def test_markdown_formatting_does_not_hide_disclosed_final_answer(text):
    assert final_answer_disclosed(text)


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


@pytest.mark.parametrize("message,expected",[
    ("今天想练IEEE754浮点表示，请读取记录和题库；如果没有可练题，说明库存问题并推荐可用讲解，不自动出新题。",False),
    ("请根据定点数编码先错、后来独立做对的记录安排后续练习。",False),
    ("今天继续练页面置换，先读取最近错误，不要自动生成新题。",False),
    ("帮我生成三道二叉树练习题",True),
    ("给我生成5道这个知识点的练习题",True),
    ("请出题",True),
    ("出一道新题",True),
    ("出一道新题的功能怎么用？",False),
])
def test_generation_intent_requires_an_explicit_unnegated_new_question_request(message,expected):
    assert explicitly_generate(message) is expected


@pytest.mark.parametrize("message", [
    "那上面你生成的题怎么做？讲解一下。",
    "刚才生成的练习题答案和解析是什么？",
    "讲解一下你生成的题的解题思路。",
])
def test_explaining_a_saved_generated_question_is_not_a_new_generation(message):
    assert explicitly_generate(message) is False
    assert assistance_action(message, question_present=True) == "solution"


@pytest.mark.parametrize("message", [
    "基于你刚生成的题，再出一道更难的变式题。",
    "这题讲完后请再生成一道练习题。",
])
def test_explicit_new_generation_after_question_explanation_remains_generation(message):
    assert explicitly_generate(message) is True


@pytest.mark.parametrize("message,expected", [
    ("那你看看我库里面有多少道这样的题。", "inventory"),
    ("我做过洛必达法则的题吗？", "history"),
    ("帮我找一道现成的洛必达法则题。", "find"),
    ("今天的学习卷还有几道题没做？", "today_detail"),
    ("哪个知识点最近比较薄弱？", "learning_state"),
])
def test_read_only_learning_data_queries_are_classified(message, expected):
    assert classify_read_only_data_query(message) == expected


@pytest.mark.parametrize("message", [
    "洛必达法则是什么？",
    "这道题怎么做？",
    "请讲解题目中的洛必达法则。",
    "帮我生成一道洛必达法则的练习题。",
])
def test_knowledge_explanation_and_generation_are_not_misrouted_to_inventory(message):
    assert classify_read_only_data_query(message) is None


@pytest.mark.parametrize("message,has_current_question,expected", [
    ("我还是不懂，接着刚才的例子再解释一次。", False, False),
    ("我还是不懂，换个简单方式讲刚才说的概念。", False, False),
    ("那刚才那道题怎么做？", False, False),
    ("请讲解你刚生成的练习题。", False, True),
    ("刚才生成的那道题能再说一下吗？", False, True),
    ("这个题的答案和解析是什么？", False, False),
    ("这个题的答案和解析是什么？", True, True),
    ("接着上面的例题，为什么要先求导？", False, False),
])
def test_question_reference_short_circuit_requires_an_explicit_question_reference(message, has_current_question, expected):
    assert _requests_question_reference(message, has_current_question=has_current_question) is expected


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
