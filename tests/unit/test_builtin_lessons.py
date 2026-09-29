"""系统知识讲解的文件覆盖与路径安全性。"""

from __future__ import annotations

import json
from pathlib import Path

from backend.services.lesson_service import lesson_file, read_lesson
from backend.services.exam_reference_service import build_exam_reference_seed

ROOT = Path(__file__).resolve().parents[2]


def _all_codes(nodes: list[dict]) -> list[tuple[str, bool]]:
    result: list[tuple[str, bool]] = []
    for node in nodes:
        result.append((node["code"], bool(node["is_assessable"])))
        result.extend(_all_codes(node.get("children", [])))
    return result


def test_every_seed_node_has_matching_lesson() -> None:
    syllabus = json.loads((ROOT / "seed" / "syllabus.json").read_text(encoding="utf-8"))
    for code, assessable in _all_codes(syllabus["nodes"]):
        content = read_lesson(code)
        assert content is not None, code
        assert content.startswith(f"<!-- kp:{code} -->"), code
        assert content.count("# ") >= 1, code
        if assessable:
            assert "例题" in content, code
            assert "错" in content, code


def test_every_exam_reference_node_has_lesson_and_real_question_index() -> None:
    nodes, references = build_exam_reference_seed()
    refs_by_code: dict[str, list[dict]] = {}
    for reference in references:
        refs_by_code.setdefault(reference["knowledge_point_code"], []).append(reference)

    for node in nodes:
        code = node["code"]
        content = read_lesson(code)
        assert content is not None, code
        assert "概念" in content or "知识点地图" in content, code
        assert "例题" in content, code
        if refs_by_code.get(code):
            assert "历年真题练习入口" in content, code
            assert str(refs_by_code[code][0]["year"]) in content, code
        if f"<!-- knowledge-node-lesson:v1; code={code} -->" in content:
            # 新生成页的“练习”入口是真题索引，不另外伪造一套模拟练习。
            assert "## 五、练习题" not in content, code
            assert "### 自测练习" not in content, code
            assert "包含：本课程相关知识链" not in content, code


def test_lesson_file_rejects_path_traversal() -> None:
    for code in ("../secrets", "a/b", r"a\b", "", "A"):
        assert lesson_file(code) is None
        assert read_lesson(code) is None
