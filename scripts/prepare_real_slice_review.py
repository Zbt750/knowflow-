"""Bridge real-text intake to existing reviewed packs after explicit human review.

No automatic approval, no database writes. Review strings are maintainer
attestations, not authentication or an independent certificate of correctness.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.services.golden_learning_slice import ASPECTS, Review, digest
from backend.services.question_pack import PackQuestion, QuestionPack, fingerprint


def identity(q):
    return f"{q['subject']}-{q['year']}-q{q['question_number']:03d}"


def template(batch):
    return {"version": "real-slice-human-review-v1", "batch_sha256": digest(batch),
        "human_review_confirmed": False, "pack_id": "real-slice-reviewed", "pack_version": "1",
        "questions": [{"candidate_id": identity(q), "candidate_sha256": digest(q),
            "approved_question": None, "approved_question_sha256": None,
            "reviews": {aspect: {"status": "UNVERIFIED"} for aspect in sorted(ASPECTS)},
            "resolved_issues": {issue: "" for issue in q["issues"]}} for q in batch["questions"]],
        "instructions": "Keep only actually reviewed questions. Fill complete PackQuestion, its fingerprint, six exact-hash human reviews and individual issue resolution notes. Never let an AI attest as human."}


def prepare(batch, decisions):
    if batch.get("version") != "structured-real-slice-intake-v1":
        raise ValueError("Unsupported intake version")
    if decisions.get("version") != "real-slice-human-review-v1" or decisions.get("human_review_confirmed") is not True:
        raise ValueError("Explicit actual human review is required; templates and AI reviews cannot approve")
    if decisions.get("batch_sha256") != digest(batch):
        raise ValueError("Intake batch changed after review")
    indexed = {}
    for q in batch["questions"]:
        key = identity(q)
        if key in indexed:
            raise ValueError("Duplicate candidate identity")
        indexed[key] = q
    approved, seen = [], set()
    for row in decisions.get("questions", []):
        key = row["candidate_id"]
        if key not in indexed or key in seen:
            raise ValueError("Unknown or duplicate reviewed candidate")
        seen.add(key)
        candidate = indexed[key]
        if row.get("candidate_sha256") != digest(candidate):
            raise ValueError("Candidate changed after review")
        question = PackQuestion.model_validate(row["approved_question"])
        sha = fingerprint(question)
        if row.get("approved_question_sha256") != sha:
            raise ValueError("Approved content changed after review")
        if question.content_status != "reviewed" or question.source.source_type != "exam":
            raise ValueError("Only completely reviewed real exam questions may be exported")
        source = question.source
        if (question.source_id != key or source.year != candidate["year"]
                or source.question_number != candidate["question_number"]
                or source.subject not in ({"408"} if candidate["subject"] == "408" else {"math2", "数学二"})):
            raise ValueError("Reviewed question identity differs from candidate")
        if question.kp_code not in candidate["candidate_node_codes"]:
            raise ValueError("New node mapping requires a new audited intake, not silent remapping")
        reviews = row.get("reviews", {})
        if set(reviews) != ASPECTS:
            raise ValueError("All six review aspects are required")
        for value in reviews.values():
            review = Review.model_validate(value)
            if review.status != "VERIFIED" or review.content_sha256 != sha:
                raise ValueError("Six human reviews must bind exact approved content")
        if question.answer_reviewed_by != reviews["answer"]["reviewed_by"] or source.reviewed_by != reviews["source"]["reviewed_by"]:
            raise ValueError("Source/answer reviewers differ from attestations")
        if source.reviewed_on.isoformat() != reviews["source"]["reviewed_on"]:
            raise ValueError("Source review date differs from attestation")
        resolutions = row.get("resolved_issues", {})
        if set(resolutions) != set(candidate["issues"]) or any(not isinstance(v, str) or len(v.strip()) < 5 for v in resolutions.values()):
            raise ValueError("Every original issue needs a specific review resolution")
        approved.append(question)
    return QuestionPack(pack_id=decisions["pack_id"], version=decisions["pack_version"], questions=approved)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch", type=Path)
    parser.add_argument("--decisions", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not any(output.is_relative_to(ROOT / folder) for folder in ("storage", "eval/reports")):
        parser.error("Question text/reviews must remain in local ignored directories")
    if output.exists():
        parser.error("Refuse to overwrite previous review or pack")
    if args.batch.stat().st_size > 12 * 1024 * 1024 or args.decisions and args.decisions.stat().st_size > 12 * 1024 * 1024:
        parser.error("Review input exceeds bounded size")
    batch = json.loads(args.batch.read_text(encoding="utf-8"))
    result = (prepare(batch, json.loads(args.decisions.read_text(encoding="utf-8"))).model_dump(mode="json")
              if args.decisions else template(batch))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Prepared reviewed pack; database untouched." if args.decisions else "Prepared UNVERIFIED template; no approval or database writes.")


if __name__ == "__main__":
    main()
