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
