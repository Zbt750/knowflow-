"""Apply explicit human declarations to a NEW golden asset, never to the DB.

No answer/source verification is performed here. The operator must complete a
real review before filling the declaration; models cannot attest as humans.
"""
import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.services.golden_learning_slice import ASPECTS, GoldenSlice, Review, digest


def review_template(asset: GoldenSlice):
    return {
        "asset_sha256": digest(asset.model_dump(mode="json")),
        "attest_human_review": False, "reviewer": "", "reviewed_on": "",
        "questions": [{"source_id": q.content.source_id, "content_sha256": q.content_hash(),
                       "aspects": {aspect: "" for aspect in sorted(ASPECTS)}} for q in asset.questions],
        "lessons": [{"kp_code": t.kp_code, "content_sha256": t.lesson_sha256, "note": ""} for t in asset.topics],
    }


def apply_review(asset: GoldenSlice, decisions: dict):
    if decisions.get("attest_human_review") is not True:
        raise ValueError("explicit human review declaration required")
    if decisions.get("asset_sha256") != digest(asset.model_dump(mode="json")):
        raise ValueError("review belongs to another asset version")
    reviewer = decisions.get("reviewer")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("real reviewer name required")
    reviewed_on = date.fromisoformat(decisions["reviewed_on"])
    data = asset.model_dump(mode="json")
    questions = {q.content.source_id: (i, q) for i, q in enumerate(asset.questions)}
    topics = {t.kp_code: (i, t) for i, t in enumerate(asset.topics)}
    seen = set()
    def stamp(sha, note):
        return Review(status="VERIFIED", reviewer_kind="human", reviewed_by=reviewer,
                      reviewed_on=reviewed_on, content_sha256=sha, note=note).model_dump(mode="json")
    for row in decisions.get("questions", []):
        key = row["source_id"]
        if key not in questions or key in seen:
            raise ValueError("unknown or duplicate question")
        seen.add(key)
        i, question = questions[key]
        if row["content_sha256"] != question.content_hash():
            raise ValueError("question content changed after review")
        aspects = row["aspects"]
        if not isinstance(aspects, dict) or not aspects or not set(aspects).issubset(ASPECTS):
            raise ValueError("invalid review aspects")
        # Each included aspect requires its own actual review note; no blank
        # defaults or bulk 'all approved' operation.
        for aspect, note in aspects.items():
            data["questions"][i]["reviews"][aspect] = stamp(question.content_hash(), note)
    seen = set()
    for row in decisions.get("lessons", []):
        key = row["kp_code"]
        if key not in topics or key in seen:
            raise ValueError("unknown or duplicate lesson")
        seen.add(key)
        i, topic = topics[key]
        # Verify the current bundled file, not just the asset's old hash.
        from backend.resources import bundled_path
        current = hashlib.sha256(bundled_path(f"seed/lessons/{key}.md").read_bytes()).hexdigest()
        if row["content_sha256"] != topic.lesson_sha256 or current != topic.lesson_sha256:
            raise ValueError("lesson content changed after review")
        data["topics"][i]["lesson_review"] = stamp(current, row["note"])
    if not decisions.get("questions") and not decisions.get("lessons"):
        raise ValueError("no review decisions supplied")
    return GoldenSlice.model_validate(data)


def read_json(path):
    if path.stat().st_size > 4 * 1024**2:
        raise ValueError("review input exceeds 4 MiB")
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("asset", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--template", action="store_true")
    mode.add_argument("--decisions", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asset = GoldenSlice.model_validate(read_json(args.asset))
    result = review_template(asset) if args.template else apply_review(asset, read_json(args.decisions)).model_dump(mode="json")
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print("Review file created; no database write. Human declarations are not automated certification.")


if __name__ == "__main__":
    main()
