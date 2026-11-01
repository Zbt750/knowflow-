import pytest
from backend.services.assistant_data_queries import classify_read_only_data_query, _subject_from_message


@pytest.mark.parametrize("message, expected", [
    ("我题库里有多少道数学二的可练题？", "inventory"),
    ("那其中洛必达法则的题有多少道？", "inventory"),
    ("洛必达法则有多少道题？", "inventory"),
    ("其中多少道是真题？", "inventory"),
    ("其中哪些是真题？", "inventory"),
    ("这些题我做过几道？", "history"),
    ("那里面我做错过哪些？", "history"),
    ("那些题我答错过哪几道？", "history"),
    ("请解释洛必达法则的使用条件", None),
    ("检查这些题的解题思路", None),
    ("为什么这些题要用洛必达法则？", None),
    ("这道题有哪些解法？", None),
    ("帮我生成一道洛必达法则的题", None),
    ("我今天只有90分钟，根据我最近的错题和薄弱知识点安排数学二复习。先给出建议，未经我确认不要创建或追加今日学习。", None),
    ("根据我的作答记录和薄弱知识点规划30分钟复习，不要执行", None),
    ("哪些知识点薄弱需要复习？", "learning_state"),
])
def test_followup_count_and_explanation_are_distinct(message, expected):
    assert classify_read_only_data_query(message) == expected


@pytest.mark.parametrize("message, expected", [("数学二可练题", "考研数学"), ("数二题库", "考研数学"),
    ("408题库", "408"), ("洛必达法则", None)])
def test_subject_aliases_do_not_silently_become_global(message, expected):
    assert _subject_from_message(message) == expected


def test_evidence_based_advice_reaches_planner_without_auto_apply():
    from backend.services.assistant_router import route_message
    from backend.schemas.learning_assistant import StudyContext
    message = "我今天只有90分钟，根据我最近的错题和薄弱知识点安排数学二复习。先给出建议，未经我确认不要创建或追加今日学习。"
    route = route_message(message, StudyContext(surface="study"))
    assert route.capability == "planner"
    assert route.intent != "modify"
