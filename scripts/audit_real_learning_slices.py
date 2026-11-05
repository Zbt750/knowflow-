"""Offline intake audit for two real-content slices, not a verification certificate.

Uses an existing read-only supply report and versioned source pointers. Never
changes nodes, attempts, evidence, questions or review status.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SLICE_SCOPES = {
    "integral": {
        "primary": "math.exam.c431f98f817c",
        "related": ["math.exam.c023f0987a18", "math.exam.b8203539e400",
                    "math.exam.352fcf1392ad", "math.exam.fd2f9e3739d9"],
    },
    "binary_tree": {
        "primary": "cs408.ds.topic.1efaf3d00b50",
        "related": ["cs408.ds.topic.56a82ba8b1ba", "cs408.ds.topic.7efb7d5560e4",
                    "cs408.ds.topic.de07cf385c9a", "cs408.ds.topic.f32b740044c8"],
    },
}


def build_report(supply, references, root=ROOT):
    nodes = {n["code"]: n for n in supply["nodes"]}
    slices = []
    for name, scope in SLICE_SCOPES.items():
        codes = [scope["primary"], *scope["related"]]
        missing = sorted(set(codes) - set(nodes))
        if missing:
            raise ValueError(f"Slice nodes missing from supply snapshot: {missing}")
        pointers = {}
        for ref in references:
            code = ref["knowledge_point_code"]
            if code not in codes:
                continue
            key = (ref["subject"], ref["year"], ref["question_number"])
            record = pointers.setdefault(key, {"subject": key[0], "year": key[1], "question_number": key[2],
                "candidate_node_codes": set(), "source_urls": set()})
            record["candidate_node_codes"].add(code)
            if ref.get("question_source_url"):
                record["source_urls"].add(ref["question_source_url"])
        source_rows = [{**p, "candidate_node_codes": sorted(p["candidate_node_codes"]),
                        "source_urls": sorted(p["source_urls"])} for _, p in sorted(pointers.items())]
        node_rows = []
        for code in codes:
            n = nodes[code]
            lesson = root / "seed" / "lessons" / f"{code}.md"
            node_rows.append({"code": code, "name": n["name"], "path": n["path"],
                "relationship": "primary" if code == scope["primary"] else "related_not_alias",
                "online_questions": n["online"], "supported_grading_questions": n["automatic_grading"],
                "lesson_exists": lesson.is_file(),
                "lesson_sha256": hashlib.sha256(lesson.read_bytes()).hexdigest() if lesson.is_file() else None,
                "lesson_verification": "not_established_by_this_audit"})
        slices.append({"slice": name, "primary_code": scope["primary"], "nodes": node_rows,
            "unique_source_pointers": len(source_rows), "source_pointers": source_rows,
            "online_questions": sum(n["online_questions"] for n in node_rows),
            "supported_grading_questions": sum(n["supported_grading_questions"] for n in node_rows),
            "verified_question_count": None, "release_ready": False,
            "blockers": ["independent_content_answer_mapping_review_not_established",
                         "real_question_closed_loop_not_accepted"],
            "normalization": "scope_only_no_alias_merge_no_evidence_pooling"})
    return {"schema_version": "real-learning-slice-intake-v1", "supply_created_at": supply["created_at"],
        "slices": slices, "limits": ["source_pointers_are_not_online_questions",
            "related_nodes_are_not_equivalent_concepts", "no_database_or_model_calls",
            "generated_golden_fixtures_are_not_real_verified_content"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--supply", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Refuse to overwrite an earlier audit")
    from backend.services.exam_reference_service import build_exam_reference_seed
    raw = args.supply.read_bytes()
    report = build_report(json.loads(raw), build_exam_reference_seed()[1])
    report["supply_sha256"] = hashlib.sha256(raw).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps([{k: s[k] for k in ("slice", "unique_source_pointers", "online_questions",
        "supported_grading_questions", "release_ready")} for s in report["slices"]], indent=2))


if __name__ == "__main__":
    main()
