"""Read-only coverage report for the project's versioned knowledge assets.

Structural checks do not certify syllabus completeness, source copyright, or
the mathematical correctness of a lesson/question relationship.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from backend.config import get_settings
from backend.db import create_db_engine, create_session_factory
from backend.models.learning import ExamQuestionReference, KnowledgePoint, Question
from backend.services.exam_reference_service import build_exam_reference_seed
from backend.services.lesson_service import read_lesson


def expected_codes() -> set[str]:
    syllabus = json.loads((ROOT / "seed/syllabus.json").read_text(encoding="utf-8"))
    codes: set[str] = set()

    def walk(rows: list[dict[str, Any]]) -> None:
        for row in rows:
            codes.add(row["code"])
            walk(row.get("children", []))

    walk(syllabus["nodes"])
    exam_nodes, _ = build_exam_reference_seed()
    codes.update(row["code"] for row in exam_nodes)
    return codes


def lesson_structure(text: str | None) -> dict[str, bool]:
    if not text:
        return {"exists": False, "concept": False, "method_or_conditions": False, "worked_example": False}
    headings = re.findall(r"(?m)^#{1,3}\s+(.+)$", text)
    return {
        "exists": True,
        "concept": any("概念" in heading or "知识点地图" in heading for heading in headings),
        "method_or_conditions": any(any(term in heading for term in (
            "方法", "条件", "判别", "步骤", "思路", "性质", "公式", "检查", "为什么", "讲解",
        )) for heading in headings),
        "worked_example": any("例题" in heading for heading in headings),
    }


def summarize_assets(
    nodes: list[KnowledgePoint], questions: list[Question], references: list[ExamQuestionReference],
    *, expected: set[str], lesson_reader=read_lesson,
) -> dict[str, Any]:
    active = [node for node in nodes if node.is_active]
    active_ids = {node.id for node in active}
    assessable_ids = {node.id for node in active if node.is_assessable}
    questions_by_node: dict[Any, list[Question]] = defaultdict(list)
    refs_by_node: dict[Any, list[ExamQuestionReference]] = defaultdict(list)
    for question in questions:
        if question.is_active:
            questions_by_node[question.kp_id].append(question)
    for ref in references:
        refs_by_node[ref.knowledge_point_id].append(ref)
    node_rows = []
    for node in sorted(active, key=lambda item: item.code):
        lesson = lesson_structure(lesson_reader(node.code))
        node_questions = questions_by_node[node.id]
        node_refs = refs_by_node[node.id]
        unique_refs = {(ref.subject, ref.year, ref.question_number) for ref in node_refs}
        types = Counter(question.question_type for question in node_questions)
        node_rows.append({
            "code": node.code,
            "subject": node.subject,
            "assessable": node.is_assessable,
            "reference_only": node.is_reference_only,
            "lesson": lesson,
            "answerable_questions": len(node_questions),
            "question_types": dict(sorted(types.items())),
            "question_difficulties": dict(sorted(Counter(getattr(q, "difficulty", "unknown") for q in node_questions).items())),
            "questions_without_skill_tags": sum(not getattr(q, "skill_tags", None) for q in node_questions),
            "exam_reference_bindings": len(node_refs),
            "distinct_exam_questions": len(unique_refs),
            "reference_years": sorted({ref.year for ref in node_refs}),
            "references_without_any_url": sum(not ref.question_source_url and not ref.topic_source_url for ref in node_refs),
        })
    leaves = [row for row in node_rows if row["assessable"]]
    subject_summary = {}
    for subject in sorted({row["subject"] for row in node_rows}):
        subject_rows = [row for row in leaves if row["subject"] == subject]
        subject_summary[subject] = {
            "assessable_nodes": len(subject_rows),
            "nodes_with_answerable_questions": sum(row["answerable_questions"] > 0 for row in subject_rows),
            "reference_only_nodes": sum(row["reference_only"] for row in subject_rows),
            "nodes_with_references": sum(row["exam_reference_bindings"] > 0 for row in subject_rows),
        }
    db_codes = {node.code for node in active}
    return {
        "scope": "active_nodes_vs_seed_syllabus_and_annual_index",
        "expected_node_count": len(expected),
        "active_node_count": len(active),
        "missing_expected_codes": sorted(expected - db_codes),
        "extra_active_codes": sorted(db_codes - expected),
        "lesson_files_missing": [row["code"] for row in node_rows if not row["lesson"]["exists"]],
        "lesson_structure_gaps": [row["code"] for row in leaves if row["lesson"]["exists"] and not all(row["lesson"].values())],
        "assessable_without_question_or_reference": [row["code"] for row in leaves if not row["answerable_questions"] and not row["exam_reference_bindings"]],
        "assessable_with_only_exam_references": [row["code"] for row in leaves if not row["answerable_questions"] and row["exam_reference_bindings"]],
        "active_answerable_questions": sum(row["answerable_questions"] for row in node_rows),
        "active_questions_outside_active_nodes": sum(q.is_active and q.kp_id not in active_ids for q in questions),
        "active_questions_on_non_assessable_nodes": sum(q.is_active and q.kp_id in active_ids and q.kp_id not in assessable_ids for q in questions),
        "references_outside_active_nodes": sum(ref.knowledge_point_id not in active_ids for ref in references),
        "relationship_correctness": "not_automatically_verified",
        "exam_reference_bindings": len(references),
        "distinct_exam_questions_global": len({(ref.subject, ref.year, ref.question_number) for ref in references}),
        "reference_bindings_without_any_url": sum(not ref.question_source_url and not ref.topic_source_url for ref in references),
        "subjects": subject_summary,
        "nodes": node_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optional JSON report path; no database writes")
    args = parser.parse_args()
    engine = create_db_engine(str(get_settings().active_database_url))
    try:
        with create_session_factory(engine)() as db:
            report = summarize_assets(
                list(db.scalars(select(KnowledgePoint))),
                list(db.scalars(select(Question))),
                list(db.scalars(select(ExamQuestionReference))),
                expected=expected_codes(),
            )
    finally:
        engine.dispose()
    report["created_at"] = datetime.now(timezone.utc).isoformat()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {key: value for key, value in report.items() if key not in {"nodes", "created_at"}}
    summary = {key: (len(value) if isinstance(value, list) else value) for key, value in summary.items()}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
