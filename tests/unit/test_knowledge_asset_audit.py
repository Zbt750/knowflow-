from types import SimpleNamespace
from uuid import uuid4

from scripts.audit_knowledge_assets import lesson_structure, summarize_assets


def item(**values):
    return SimpleNamespace(**values)


def test_lesson_structure_checks_sections_not_just_file_presence():
    assert lesson_structure(None)["exists"] is False
    assert lesson_structure("# 标题\n正文")["worked_example"] is False
    complete = lesson_structure("# 标题\n## 概念讲解\n正文\n## 解题方法\n步骤\n## 原创例题\n例子")
    assert all(complete.values())


def test_asset_report_separates_answerable_questions_from_exam_references():
    first_id, second_id = uuid4(), uuid4()
    nodes = [
        item(id=first_id, code="math.topic", subject="考研数学", is_active=True, is_assessable=True, is_reference_only=False),
        item(id=second_id, code="cs408.topic", subject="408", is_active=True, is_assessable=True, is_reference_only=True),
    ]
    questions = [item(kp_id=first_id, question_type="single_choice", is_active=True)]
    refs = [
        item(knowledge_point_id=second_id, subject="408", year=2020, question_number=1, question_source_url=None, topic_source_url="https://example.test/source"),
        item(knowledge_point_id=second_id, subject="408", year=2020, question_number=1, question_source_url=None, topic_source_url=None),
    ]
    lessons = {"math.topic": "## 概念\n## 方法\n## 例题", "cs408.topic": "## 概念\n## 方法\n## 例题"}

    report = summarize_assets(nodes, questions, refs, expected={"math.topic", "cs408.topic", "missing"}, lesson_reader=lessons.get)

    assert report["missing_expected_codes"] == ["missing"]
    assert report["active_answerable_questions"] == 1
    assert report["exam_reference_bindings"] == 2
    assert report["distinct_exam_questions_global"] == 1
    assert report["assessable_with_only_exam_references"] == ["cs408.topic"]
    assert report["reference_bindings_without_any_url"] == 1
    assert report["subjects"]["408"]["nodes_with_answerable_questions"] == 0
    assert report["nodes"][0]["distinct_exam_questions"] == 1


def test_asset_report_surfaces_invalid_bindings_and_keeps_coverage_honest():
    leaf, parent, inactive = uuid4(), uuid4(), uuid4()
    nodes = [item(id=leaf, code="leaf", subject="math", is_active=True, is_assessable=True, is_reference_only=False),
             item(id=parent, code="parent", subject="math", is_active=True, is_assessable=False, is_reference_only=False),
             item(id=inactive, code="inactive", subject="math", is_active=False, is_assessable=True, is_reference_only=False)]
    questions = [item(kp_id=identifier, question_type="calculation", difficulty="basic", skill_tags=["换元"], is_active=True)
                 for identifier in (leaf, parent, inactive)]
    refs = [item(knowledge_point_id=inactive, subject="math", year=2024, question_number=1,
                 question_source_url="https://example.test", topic_source_url=None)]
    report = summarize_assets(nodes, questions, refs, expected={"leaf", "parent"}, lesson_reader=lambda _: None)
    assert report["active_questions_outside_active_nodes"] == 1
    assert report["active_questions_on_non_assessable_nodes"] == 1
    assert report["references_outside_active_nodes"] == 1
    assert report["relationship_correctness"] == "not_automatically_verified"
    assert report["nodes"][0]["question_difficulties"] == {"basic": 1}
    assert report["nodes"][0]["questions_without_skill_tags"] == 0
