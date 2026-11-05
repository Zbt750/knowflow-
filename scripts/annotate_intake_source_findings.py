"""Carry hash-bound AI source findings into a NEW unverified intake. No DB/model calls."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.services.golden_learning_slice import digest
from scripts.prepare_real_slice_review import identity


def annotate(batch, findings):
    if batch.get("version") != "structured-real-slice-intake-v1":
        raise ValueError("Unsupported intake")
    if (findings.get("version") != "ai-source-findings-v1"
            or findings.get("batch_sha256") != digest(batch)
            or findings.get("human_review_confirmed") is not False):
        raise ValueError("Stale findings or invalid review declaration")
    result = deepcopy(batch)
    indexed = {}
    for row in result["questions"]:
        key = identity(row)
        if key in indexed:
            raise ValueError("Duplicate intake identity")
        indexed[key] = row
    seen = set()
    for finding in findings["questions"]:
        key = finding["candidate_id"]
        if key not in indexed or key in seen:
            raise ValueError("Unknown or duplicate finding")
        seen.add(key)
        row = indexed[key]
        if finding.get("candidate_sha256") != digest(row):
            raise ValueError("Finding differs from candidate content")
        if (row.get("content_status") != "UNVERIFIED" or row.get("verified") is not False
                or row.get("can_import") is not False):
            raise ValueError("Only unverified intake may be annotated")
        issues = finding.get("issues")
        if (not isinstance(issues, list) or not issues or len(issues) != len(set(issues))
                or any(not isinstance(i, str) or not i.strip() for i in issues)
                or not isinstance(finding.get("note"), str) or len(finding["note"].strip()) < 10):
            raise ValueError("Explicit unique issues and source note required")
        proposal = finding.get("proposed_primary_kp_code")
        if proposal is not None and (not isinstance(proposal, str) or not proposal.strip()):
            raise ValueError("Invalid mapping proposal")
        withdrawals = finding.get("withdrawn_issues", [])
        # Retract only an AI's unsupported subject inference, never a rights,
        # authenticity, mapping or human-review requirement.
        if (not isinstance(withdrawals, list) or len(withdrawals) != len(set(withdrawals))
                or any(i != "local_source_subject_edition_conflict" or i not in row["issues"]
                       for i in withdrawals)
                or set(withdrawals) & set(issues)):
            raise ValueError("Only an existing unsupported subject inference can be withdrawn")
        row["issues"] = sorted((set(row["issues"]) - set(withdrawals)) | set(issues))
        if row.get("source_findings"):
            row.setdefault("source_findings_history", []).append(deepcopy(row["source_findings"]))
        row["source_findings"] = deepcopy(finding)
        row["source_findings"]["status"] = "AI_REVIEWED_PENDING_HUMAN"
        # A proposal is not a primary mapping or an equivalence declaration.
        # Human review may select it in a new hash-bound batch, never transfer evidence.
        if proposal and proposal not in row["candidate_node_codes"]:
            row["candidate_node_codes"].append(proposal)
    result["previous_batch_sha256"] = digest(batch)
    result["source_findings_sha256"] = digest(findings)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch", type=Path)
    parser.add_argument("--findings", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to((ROOT / "storage/question-intake").resolve()):
        parser.error("Use a new ignored intake path")
    if any(p.stat().st_size > 12 * 1024 * 1024 for p in (args.batch, args.findings)):
        parser.error("Bounded input exceeded")
    result = annotate(json.loads(args.batch.read_text(encoding="utf-8")),
                      json.loads(args.findings.read_text(encoding="utf-8")))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(f"New UNVERIFIED intake: {len(result['questions'])} candidates; DB untouched; approved 0")


if __name__ == "__main__":
    main()
