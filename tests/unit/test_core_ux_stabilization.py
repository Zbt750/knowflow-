"""Offline contracts, not real-model answer-quality scores."""
from copy import deepcopy
import json
import pytest
from backend.schemas.learning_assistant import StudyContext
from backend.services.assistant_router import route_message
from backend.services.learning_task_context import pack_records, expand_records, compact_model_messages, compact_tool_result


@pytest.mark.parametrize("message", [
    "我现在可以练习的题目有哪些？哪些是历年真题，哪些是原创题？",
    "查询当前可练题目库存", "历年真题有多少道？", "原创题有几道？",
    "有哪些真题变式？", "真题改编有多少？", "查询定积分节点库存",
    "正式题与个人生成题有什么区别？", "这些题的来源是什么？",
])
def test_inventory_and_source_natural_language_uses_read_only_business_query(message):
    result = route_message(message, StudyContext(surface="study"))
    assert (result.capability, result.intent) == ("data_query", "inventory")


@pytest.mark.parametrize("message", [
    "解释这道数学题的解法", "接着上题，计算矩阵的行列式",
    "请分析资料中的这道题为什么不能直接换元", "这道题的选项有哪些错误？",
    "为什么这道原创题用中值定理？", "什么是真题变式？",
    "请解释定积分的换元方法", "根据引用资料分析本题条件",
])
def test_question_explanation_is_not_inventory(message):
    assert route_message(message, StudyContext(surface="study")).capability == "qa"


@pytest.mark.parametrize("message", [
    "Python async/await为什么存在？", "2027年408大纲有什么最新变化？",
    "我上传的PDF怎么解释？", "那上面你生成的题怎么做？讲解一下。",
    "接着上题，这个A的行列式、特征值，以及特征空间维数分别是多少？",
])
def test_source_or_explanation_does_not_consume_intent_model(message):
    def forbidden_classifier(*args):
        pytest.fail("A deterministic source or explanation question must not call the intent model")
    assert route_message(message, StudyContext(surface="study"), classifier=forbidden_classifier).capability == "qa"


def test_concept_explanation_does_not_reveal_unrelated_current_question():
    from backend.services.assistant_router import assistance_action
    assert assistance_action("解释洛必达法则的使用条件", question_present=True) is None
    assert assistance_action("解释这道题的解法", question_present=True) == "solution"
    assert assistance_action("我还是不懂", question_present=True) == "hint_2"


def test_formal_replacement_is_not_inventory_query():
    from backend.services.assistant_data_queries import classify_read_only_data_query
    assert classify_read_only_data_query("把剩下的题换简单一点") is None


def test_column_view_is_lossless_for_unseen_qualifications_versions_and_attempts():
    records = [{"question_id": str(i), "question_version": {"id": f"v{i}", "content_hash": str(i)*64},
        "source_category": ["exam_curated", "exam_variant", "personal_ai_practice"][i % 3],
        "question_trust": {"event_id": f"e{i}", "snapshot_hash": str(i+1)*64, "bank_scope": "public" if i % 3 != 2 else "personal"},
        "recent_attempts": [{"result": "right", "assisted": a, "version": f"v{i}"} for a in (False, True, None)],
        "budget_minutes": 20, "confirmation_required": True, "kp_id": "node-1"} for i in range(16)]
    original = {"questions": records, "practice_eligible_count": 31, "scope": ["node-1"]}
    encoded = pack_records(original)
    assert encoded["questions"]["$records"] == 16
    assert expand_records(encoded) == original
    assert len(json.dumps(encoded)) < len(json.dumps(original))
    assert original["questions"][0]["question_id"] == "0"


def test_column_view_preserves_missing_null_false_and_numeric_types():
    value = [{"value": x, "unchanged_long_field": "same"*30} for x in (None, False, 0, 0.0, "0")]
    mixed = [{"present": None}, {}, {"present": False}]
    for source in (value, mixed):
        assert json.dumps(expand_records(pack_records(source))) == json.dumps(source)
    trust = [{"question_trust": {"flag": v}} for v in (False, 0, 0.0)]
    compact = compact_tool_result({"questions": trust})
    assert "question_trust_defaults" not in compact


def test_all_tool_facts_recover_and_only_exact_same_snapshot_reuses_reference():
    first = {"questions": [{"id": str(i), "version": "v1", "assisted": True} for i in range(8)], "count": 45}
    changed = deepcopy(first); changed["questions"][0]["assisted"] = False
    messages = [{"role":"tool", "tool_call_id":str(i), "content":json.dumps(data)} for i,data in enumerate((first, first, changed))]
    original = deepcopy(messages)
    result = compact_model_messages(messages)
    assert json.loads(result[0]["content"]) == {"same_result_as_tool_call_id": "1"}
    assert expand_records(json.loads(result[1]["content"])) == first
    assert expand_records(json.loads(result[2]["content"])) == changed
    assert messages == original


@pytest.mark.parametrize('text',['给我安排1道这种题','给我安排一道这种题','帮我规划两道这样的题'])
def test_explicit_question_workload_is_not_swallowed_by_readonly_inventory(text):
    from backend.services.assistant_data_queries import classify_read_only_data_query
    assert classify_read_only_data_query(text) is None
