"""Offline, fact-level checklist for fixed synthetic multi-chunk QA cases.

This is a coverage aid, not a replacement for RAGAS or claim-level citation
verification. Only fact identifiers and boolean checks are printed.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHECKLIST = ROOT / "eval/dataset/multichunk_fact_checklist_v1.json"


def audit_fact(answer: str, blocks: list[dict[str, Any]], fact: dict[str, Any]) -> dict[str, Any]:
    source_checks = []
    for source in fact["sources"]:
        matching = [block for block in blocks
                    if block.get("material_title") == source["material_title"]
                    and any(term in str(block.get("context", "")) for term in source["evidence_any"])]
        source_checks.append({
            "evidence_present": bool(matching),
            "source_cited_somewhere": any(
                re.search(r"\[" + re.escape(str(block["label"])) + r"\]", answer)
                for block in matching if block.get("label")
            ),
        })
    answer_present = any(term in answer for term in fact["answer_any"])
    return {
        "fact_id": fact["id"],
        "answer_present": answer_present,
        "evidence_present": all(item["evidence_present"] for item in source_checks),
        "sources_cited_somewhere": all(item["source_cited_somewhere"] for item in source_checks),
        "source_checks": source_checks,
    }


def audit_report(report: dict[str, Any], checklist: dict[str, Any]) -> dict[str, Any]:
    checked = []
    for row in report.get("cases", []):
        facts = checklist["cases"].get(row.get("case_id"))
        if facts is None:
            continue
        snapshot = row.get("actual_evidence")
        if not isinstance(snapshot, dict) or not isinstance(row.get("answer"), str):
            checked.append({"case_id": row.get("case_id"), "status": "unavailable", "facts": []})
            continue
        blocks = snapshot.get("blocks")
        if not isinstance(blocks, list):
            checked.append({"case_id": row.get("case_id"), "status": "unavailable", "facts": []})
            continue
        results = [audit_fact(row["answer"], blocks, fact) for fact in facts]
        checked.append({"case_id": row.get("case_id"), "status": "checked", "facts": results})
    return {"checklist_version": checklist["version"], "cases": checked}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path, help="Explicit local report JSON paths")
    parser.add_argument("--checklist", type=Path, default=DEFAULT_CHECKLIST)
    args = parser.parse_args()
    checklist = json.loads(args.checklist.read_text(encoding="utf-8"))
    outputs = []
    for path in args.reports:
        report = json.loads(path.read_text(encoding="utf-8"))
        outputs.append({"report": path.name, **audit_report(report, checklist)})
    print(json.dumps(outputs, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
