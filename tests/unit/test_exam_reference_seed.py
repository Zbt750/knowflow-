from __future__ import annotations

import json
from pathlib import Path

from backend.services.exam_reference_service import build_exam_reference_seed


def _syllabus_codes() -> set[str]:
    path = Path(__file__).resolve().parents[2] / "seed" / "syllabus.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    codes: set[str] = set()

    def walk(nodes: list[dict]) -> None:
        for node in nodes:
            codes.add(node["code"])
            walk(node.get("children", []))

    walk(payload["nodes"])
    return codes


def test_exam_reference_seed_covers_all_bundled_years_without_question_text() -> None:
    nodes, references = build_exam_reference_seed()
    node_codes = {node["code"] for node in nodes}

    assert {"cs408", "cs408.ds", "cs408.co", "cs408.os", "cs408.cn"} <= node_codes
    assert {"math.calculus", "math.linear-algebra"} <= {
        node["parent_code"] for node in nodes if node["parent_code"]
    }
    assert len([node for node in nodes if node["is_reference_only"]]) >= 200
    assert len(references) >= 1400
    assert {(row["subject"], row["year"]) for row in references} == {
        (subject, year)
        for subject in ("数学二", "408")
        for year in range(2010, 2027)
    }
    assert {
        row["knowledge_point_code"] for row in references
    } <= node_codes | _syllabus_codes()
    assert all("stem" not in row and "answer" not in row for row in references)


def test_exam_reference_seed_preserves_408_source_links_and_2019_q46_conflict() -> None:
    _nodes, references = build_exam_reference_seed()
    q1 = next(
        row
        for row in references
        if row["subject"] == "408" and row["year"] == 2010 and row["question_number"] == 1
    )
    assert q1["question_source_url"] == "https://www.codebrick.tech/exam-408/q/ds/2010/01"
    assert q1["topic_source_url"] == "https://www.codebrick.tech/exam-408/"

    q46_codes = {
        row["knowledge_point_code"]
        for row in references
        if row["subject"] == "408" and row["year"] == 2019 and row["question_number"] == 46
        and ".topic." in row["knowledge_point_code"]
    }
    assert len(q46_codes) == 2


def test_exam_reference_seed_builds_deduplicated_topic_family_views() -> None:
    nodes, references = build_exam_reference_seed()
    nodes_by_code = {node["code"]: node for node in nodes}
    refs_by_code: dict[str, list[dict]] = {}
    for reference in references:
        refs_by_code.setdefault(reference["knowledge_point_code"], []).append(reference)

    math_multivariable = "math.family.calculus-multivariable"
    ds_sorting = "cs408.ds.family.sorting"
    cn_network = "cs408.cn.family.network-layer"
    for code in (math_multivariable, ds_sorting, cn_network):
        assert code in nodes_by_code
        assert nodes_by_code[code]["is_reference_only"] is True
        rows = refs_by_code[code]
        assert len(rows) > 10
        assert len({(row["subject"], row["year"], row["question_number"]) for row in rows}) == len(rows)
        assert all(row["source_topic_label"] for row in rows)

    math_question_ids = {
        (row["year"], row["question_number"])
        for row in refs_by_code[math_multivariable]
    }
    assert {(2013, 21), (2026, 7), (2026, 17)} <= math_question_ids

    sorting_question_ids = {
        (row["year"], row["question_number"])
        for row in refs_by_code[ds_sorting]
    }
    assert {(2010, 11), (2016, 43), (2026, 9), (2026, 10), (2026, 11)} <= sorting_question_ids

    network_question_ids = {
        (row["year"], row["question_number"])
        for row in refs_by_code[cn_network]
    }
    transport_question_ids = {
        (row["year"], row["question_number"])
        for row in refs_by_code["cs408.cn.family.transport-layer"]
    }
    assert (2010, 36) in network_question_ids
    assert (2010, 36) not in transport_question_ids
