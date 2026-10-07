"""Replay observable answer checks against saved ACTUAL contexts, without LLM calls.

The sidecar contains hashes and flags only: it neither copies private evidence nor
rewrites the source report, original answers, RAGAS scores, or human review.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.chat.answer_contract import VERSION, audit_answer_contract


def replay_report(report):
    rows = []
    for case in report.get("cases", []):
        snapshot = case.get("actual_evidence")
        answer = case.get("answer")
        if not isinstance(snapshot, dict) or not isinstance(answer, str):
            rows.append({"case_id": case.get("case_id"), "status": "unavailable",
                         "reason": "actual_snapshot_or_full_answer_missing"})
            continue
        review = audit_answer_contract(str(case.get("question", "")), answer,
                                       snapshot.get("blocks", []))
        rows.append({"case_id": case.get("case_id"),
                     "answer_sha256": hashlib.sha256(answer.encode("utf-8")).hexdigest(),
                     "snapshot_version": snapshot.get("version"),
                     "evidence_sha256": snapshot.get("evidence_sha256"),
                     **review})
    return {"audit_version": VERSION, "external_calls": 0,
            "source_report_modified": False, "original_metrics_modified": False,
            "semantic_correctness_proven": False,
            "manual_review_required": True,
            "summary": {
                "cases": len(rows),
                "flagged": sum(bool(row.get("issues")) for row in rows),
                "unobserved": sum(row.get("status") == "unobserved" for row in rows),
                "unavailable": sum(row.get("status") == "unavailable" for row in rows),
            }, "cases": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path, required=True,
                        help="New sidecar path; refuses overwrite")
    args = parser.parse_args()
    raw = args.report.read_bytes()
    result = replay_report(json.loads(raw.decode("utf-8")))
    result["source_report_sha256"] = hashlib.sha256(raw).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
