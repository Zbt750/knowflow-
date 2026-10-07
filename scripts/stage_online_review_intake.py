"""Turn exact saved online snapshots into UNVERIFIED review intake, no DB writes."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.services.golden_learning_slice import digest
from scripts.prepare_real_slice_review import template
from scripts.upgrade_reviewed_transcriptions import local_output, read_json


def build_intake(worksheet):
    if worksheet.get("version") != "real-slice-derivation-worksheet-v1":
        raise ValueError("Unsupported worksheet")
    questions, seen = [], set()
    for row in worksheet.get("online_integral_review", {}).get("questions", []):
        record = row["record"]
        if row.get("record_sha256") != digest(record):
            raise ValueError("Online snapshot changed since worksheet")
        config = record.get("grading_config") or {}
        source = config.get("provenance", {}).get("source", {})
        if (config.get("verified") is not False or source.get("subject") not in {"math2", "数学二"}
                or source.get("source_type") != "exam"):
            raise ValueError("Only unverified math2 exam snapshots supported")
        year, number = source.get("year"), source.get("question_number")
        if (type(year) is not int or type(number) is not int or not 2000 <= year <= 2100 or not 1 <= number <= 200):
            raise ValueError("Invalid source identity")
        key = f"math2-{year}-q{number:03d}"
        if key != row["candidate_id"] or key in seen:
            raise ValueError("Mismatched or duplicate online identity")
        seen.add(key)
        questions.append({"subject": "math2", "year": year, "question_number": number,
            "raw_text": record["stem"], "options": record.get("options"),
            "question_type": record.get("question_type"), "candidate_node_codes": [record["kp_code"]],
            "online_question_id": record["id"], "saved_record_sha256": digest(record),
            "saved_record": record, "prior_source_declaration": source,
            "unverified_reference_answer": record.get("correct_answer"),
            "ai_derivation_draft": row.get("ai_derivation"),
            "issues": ["source_comparison_pending", "rights_scope_review_pending", "answer_review_pending",
                       "explanation_review_pending", "mapping_review_pending", "grading_boundary_review_pending"],
            "content_status": "UNVERIFIED", "can_import": False, "verified": False})
    if not questions:
        raise ValueError("No saved online integral snapshots")
    return {"version": "structured-real-slice-intake-v1", "origin": "saved_online_snapshot_not_new_db_audit",
        "worksheet_sha256": digest(worksheet), "questions": questions}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("worksheet", type=Path)
    parser.add_argument("--batch-output", type=Path, required=True)
    parser.add_argument("--decisions-output", type=Path, required=True)
    args = parser.parse_args()
    first, second = local_output(args.batch_output), local_output(args.decisions_output)
    if first == second:
        parser.error("Batch and decisions need distinct paths")
    batch = build_intake(read_json(args.worksheet))
    for path, value in ((first, batch), (second, template(batch))):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
    print(f"Prepared {len(batch['questions'])} UNVERIFIED online review rows; no human signatures or database writes")


if __name__ == "__main__":
    main()
