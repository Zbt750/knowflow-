"""Local maintainer review drafts; no database mutations or automatic approvals.

Draft statuses are workflow decisions, not new Question trust states. Export uses
the existing six-aspect review bridge and snapshot-bound upgrade contract.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4
import hashlib
import json

from sqlalchemy import select, text

from backend.models.learning import KnowledgePoint, Question
from backend.services.answer_grading import grade_final_answer
from backend.services.answer_verification import answer_version_sha256
from backend.services.golden_learning_slice import ASPECTS, digest
from backend.services.question_attestation import question_content_sha256
from backend.services.question_eligibility import question_eligibility
from backend.services.question_pack import PackQuestion, fingerprint
from backend.services.question_verification_upgrade import snapshot, validate_reviews
from scripts.prepare_real_slice_review import identity, prepare

FORMAT = "golden-human-review-draft-v1"
ORDER = ("source", "stem", "answer", "explanation", "mapping", "grading")
DEFAULT_IDS = (
    "d1691564-0c42-43c0-8ab2-b011fd88ac65",
    "2aa85cd9-baed-493d-b79b-f3174f6016c0",
    "ab961f2c-8e24-4068-9bfc-effc9ea876e9",
)
CONTENT_FIELDS = ("question_type", "stem", "options", "correct_answer", "explanation",
                  "question_role", "difficulty", "skill_tags", "estimated_minutes", "is_variant")
ISSUES = {
    "source": ("source_identity_and_locator", "source_rights_and_local_scope"),
    "stem": ("exact_transcription",),
    "answer": ("independent_answer_solution",),
    "explanation": ("derivation_conditions_and_steps",),
    "mapping": ("node_and_skill_mapping",),
    "grading": ("actual_grader_boundary_review",),
}


def read_json(path: Path):
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("Review input exceeds 16 MiB")
    return json.loads(path.read_text(encoding="utf-8"))


def material_index(package: dict | None, corrected: dict | None = None) -> dict:
    """Locators only; historical review status never becomes a human decision."""
    result = {}
    for q in (package or {}).get("questions", []):
        result[q["question_id"]] = {
            "path": q.get("declared_original_source_file"),
            "sha256": q.get("declared_original_source_sha256"),
            "locator": q.get("original_page_locator"),
        }
    if corrected:
        src = corrected["source"]
        result[corrected["question_id"]] = {
            "path": src["pdf_path"], "sha256": src["pdf_sha256"],
            "locator": f"PDF page {src['page']}, Q{src['question_number']}",
            "expected_answer_sha256": corrected["hashes"]["answer_version_sha256"],
        }
    return result


def source_file_check(material: dict) -> dict:
    path = material.get("path")
    if not path:
        return {"path": None, "status": "not_supplied", "actual_sha256": None}
    resolved = Path(path)
    if not resolved.is_file():
        return {"path": str(resolved), "status": "missing", "actual_sha256": None}
    with resolved.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    expected = material.get("sha256")
    return {"path": str(resolved), "status": "matched" if sha == expected else "changed",
            "actual_sha256": sha, "expected_sha256": expected}


def grader_probes(view: dict, method: str) -> dict:
    """Run the real bounded comparator with a transient harness config.

    verified=True here is a test precondition only; it never updates Question.
    """
    c = view["content"]
    if method == "single_choice":
        correct = c["correct_answer"].strip().upper()
        wrong = next((k for k in c["options"] if k != correct), None)
        invalid = "INVALID"
        while invalid in c["options"]:
            invalid += "X"
        cases = [("correct", None, correct, "right"), ("wrong", None, wrong, "wrong"),
                 ("blank", None, "", "unknown"), ("illegal", None, invalid, "unknown"),
                 ("case_and_spaces", None, f" {correct.lower()} ", "right"),
                 ("free_text_not_option", "an unsupported expression", None, "unknown")]
    elif method == "numeric_final":
        # Derive equivalents from the same real parser; no simulated grading.
        from backend.services.answer_grading import _numeric_value
        target = _numeric_value(c["correct_answer"])
        if target is None:
            raise ValueError("Reference cannot use numeric_final")
        cases = [("correct", c["correct_answer"], None, "right"),
                 ("equivalent_fraction", f"{target.numerator * 2}/{target.denominator * 2}", None, "right"),
                 ("equivalent_latex", rf"\frac{{{target.numerator * 2}}}{{{target.denominator * 2}}}", None, "right"),
                 ("wrong", str(target + 1), None, "wrong"),
                 ("blank", "", None, "unknown"), ("illegal", "1/0", None, "unknown"),
                 ("expression", "sqrt(1)", None, "unknown")]
        if target.denominator == 1:
            cases += [("equivalent_integer", str(target.numerator), None, "right"),
                      ("equivalent_decimal", f"{target.numerator}.0", None, "right"),
                      ("no_tolerance", f"{target.numerator}.000000001", None, "wrong")]
    else:
        raise ValueError("This review harness supports single_choice or numeric_final")
    results = []
    for label, raw, selected, expected in cases:
        actual = grade_final_answer(question_type=c["question_type"],
            config={"verified": True, "method": method}, answer=raw,
            selected_option=selected, expected=c["correct_answer"], options=c["options"])
        results.append({"case": label, "raw_answer": raw, "selected_option": selected,
                        "expected": expected, "actual": actual.result, "reason": actual.reason,
                        "method": actual.method, "passed": actual.result == expected})
    return {"harness_only": True, "grants_verified_grader": False, "method": method,
            "cases": results, "passed": all(r["passed"] for r in results)}


def load_views(db, ids, materials=None) -> list[dict]:
    """Caller must enter a read-only transaction. All values come from live rows."""
    result = []
    ids = list(ids)
    if not ids or len(ids) > 100 or len(ids) != len(set(ids)):
        raise ValueError("Choose 1..100 distinct Question IDs")
    for qid in ids:
        q = db.get(Question, UUID(str(qid)))
        if q is None:
            raise ValueError(f"Question missing: {qid}")
        node = db.get(KnowledgePoint, q.kp_id)
        config = deepcopy(q.grading_config or {})
        source = deepcopy(config.get("provenance", {}).get("source", {}))
        material = deepcopy((materials or {}).get(str(q.id), {}))
        problems = []
        if not node or not node.is_active or not node.is_assessable or not q.is_active:
            problems.append("inactive_or_unassessable")
        if (q.grading_mode != "self_assessed" or config.get("verified") is not False
                or config.get("method") is not None
                or config.get("provenance", {}).get("content_status") != "source_transcribed"):
            problems.append("not_unverified_transcription")
        file_check = source_file_check(material)
        if file_check["status"] in {"missing", "changed"}:
            problems.append("source_file_missing_or_changed")
        answer_sha = answer_version_sha256(q)
        if material.get("expected_answer_sha256") and material["expected_answer_sha256"] != answer_sha:
            problems.append("corrected_review_material_is_stale")
        view = {"question_id": str(q.id), "content": {k: deepcopy(getattr(q, k)) for k in CONTENT_FIELDS},
                "source": source, "node": {"id": str(q.kp_id), "code": node.code if node else None,
                    "name": node.name if node else None, "active": node.is_active if node else False,
                    "assessable": node.is_assessable if node else False,
                    "reference_only": node.is_reference_only if node else False},
                "snapshot": snapshot(q), "question_content_sha256": question_content_sha256(q),
                "answer_version_sha256": answer_sha, "snapshot_sha256": digest(snapshot(q)),
                "eligibility": question_eligibility(q, node).public_dict(),
                "material": material, "source_file": file_check, "hard_blockers": problems,
                "issues": [i for group in ISSUES.values() for i in group]}
        if source.get("year") == 2024 and source.get("question_number") == 7 and source.get("subject") in {"数学二", "math2"}:
            view["issues"].append("page_range_conflict_p2_vs_p2_3")
        if source.get("year") == 2017 and source.get("question_number") == 11 and source.get("subject") in {"数学二", "math2"}:
            view["issues"].append("combined_pdf_identity_not_official_authority")
        # This binds all displayed context, including source file and node details.
        view["binding_sha256"] = digest(view)
        result.append(view)
    return result


def new_draft(views: list[dict]) -> dict:
    return {"format": FORMAT, "session_id": str(uuid4()), "created_at": datetime.now(timezone.utc).isoformat(),
        "human_review_confirmed": False,
        "questions": [{"view": deepcopy(v), "proposal": None, "proposal_sha256": None,
            "reviews": {a: {"status": "PENDING", "note": ""} for a in ORDER},
            "resolutions": {i: "" for i in v["issues"]}, "probes": None} for v in views]}


def find_question(draft, qid):
    return next(q for q in draft["questions"] if q["view"]["question_id"] == qid)


def check_binding(draft, current_views):
    if draft.get("format") != FORMAT or draft.get("human_review_confirmed") is not False:
        raise ValueError("Invalid draft or false approval claim")
    current = {v["question_id"]: v for v in current_views}
    if len(current) != len(draft["questions"]) or len({q["view"]["question_id"] for q in draft["questions"]}) != len(current):
        raise ValueError("Draft Question identities changed")
    for row in draft["questions"]:
        v = row["view"]
        saved = {k: val for k, val in v.items() if k != "binding_sha256"}
        if (digest(saved) != v["binding_sha256"] or v["question_id"] not in current
                or current[v["question_id"]]["binding_sha256"] != v["binding_sha256"]):
            raise ValueError(f"Live content/snapshot/source drift; old signoff rejected: {v['question_id']}")
        if set(row["reviews"]) != ASPECTS or set(row["resolutions"]) != set(v["issues"]):
            raise ValueError("Review aspects/issues changed")
        if row["proposal"]:
            validate_proposal(row)


def validate_proposal(row):
    q = PackQuestion.model_validate(row["proposal"])
    view = row["view"]
    if fingerprint(q) != row["proposal_sha256"]:
        raise ValueError("Proposal changed; all old signoffs invalid")
    if any(getattr(q, k) != view["content"][k] for k in CONTENT_FIELDS) or q.kp_code != view["node"]["code"]:
        raise ValueError("Review CLI cannot correct Question content/mapping")
    old = view["source"]
    if any(getattr(q.source, k) != old.get(k) for k in ("year", "question_number", "subject", "source_type")):
        raise ValueError("Source exam identity changed")
    if q.source_id != identity({"subject": "408" if old.get("subject") == "408" else "math2",
                                "year": old.get("year"), "question_number": old.get("question_number")}):
        raise ValueError("Source ID changed")
    if (q.content_status != "reviewed" or q.answer_provenance != "human_verified"
            or q.answer_reliability != "verified" or q.answer_reference is not None):
        raise ValueError("Only explicit human-solution proposals supported")
    return q


def configure(row, *, reviewer, citation, rights_basis, answer_note, method, reviewed_on=None):
    if not reviewer or not reviewer.strip():
        raise ValueError("Real reviewer identity must be entered by the operator")
    if method not in {"single_choice", "numeric_final"}:
        raise ValueError("Supported review methods: single_choice or numeric_final")
    when = reviewed_on or date.today().isoformat()
    if date.fromisoformat(when) > date.today():
        raise ValueError("Review date cannot be in the future")
    view = row["view"]
    if view["hard_blockers"]:
        raise ValueError("Live/material blockers: " + ", ".join(view["hard_blockers"]))
    src = deepcopy(view["source"])
    src.update(citation=citation, rights_basis=rights_basis, reviewed_by=reviewer, reviewed_on=when)
    key = {"subject": "408" if src.get("subject") == "408" else "math2",
           "year": src.get("year"), "question_number": src.get("question_number")}
    proposed = PackQuestion.model_validate({**deepcopy(view["content"]), "source_id": identity(key),
        "kp_code": view["node"]["code"], "source": src, "grading_method": method,
        "content_status": "reviewed", "content_reviewed_by": reviewer, "content_reviewed_on": when,
        "answer_provenance": "human_verified", "answer_reliability": "verified",
        "answer_reviewed_by": reviewer, "answer_reviewed_on": when,
        "answer_review_method": "independent_human_solution", "answer_review_note": answer_note})
    # Freeze the fully serialized representation so optional-field presence is
    # identical when resumed or passed to the existing fingerprint contract.
    proposed = PackQuestion.model_validate(proposed.model_dump(mode="json"))
    new_sha = fingerprint(proposed)
    if row["proposal_sha256"] != new_sha:
        row["reviews"] = {a: {"status": "PENDING", "note": ""} for a in ORDER}
        row["resolutions"] = {i: "" for i in view["issues"]}
    row["proposal"], row["proposal_sha256"] = proposed.model_dump(mode="json"), new_sha
    row["probes"] = grader_probes(view, method)
    return new_sha


def record_review(row, aspect, status, note):
    if aspect not in ASPECTS or status not in {"VERIFIED", "REJECTED", "PENDING"}:
        raise ValueError("Explicit aspect and VERIFIED/REJECTED/PENDING required")
    if status != "PENDING" and len(note.strip()) < 5:
        raise ValueError("A specific explanation (at least 5 characters) is required")
    # Explicit rejected/pending decisions also belong to a real operator and
    # exact version; only initial unsigned defaults have no reviewer metadata.
    q = validate_proposal(row)
    if status == "VERIFIED":
        if aspect == "answer" and note != q.answer_review_note:
            raise ValueError("Answer review note must match frozen proposal; reconfigure before changing it")
        row["reviews"][aspect] = {"status": status, "reviewer_kind": "human", "reviewed_by": q.answer_reviewed_by,
            "reviewed_on": date.today().isoformat(), "content_sha256": fingerprint(q), "note": note}
        required_date = (q.source.reviewed_on if aspect == "source" else q.answer_reviewed_on)
        if aspect in {"source", "answer"} and row["reviews"][aspect]["reviewed_on"] != required_date.isoformat():
            row["reviews"][aspect] = {"status": "PENDING", "note": ""}
            raise ValueError("New review date differs from proposal; reconfigure and review again")
    else:
        row["reviews"][aspect] = {"status": status, "note": note.strip(),
            "reviewer_kind": "human", "reviewed_by": q.answer_reviewed_by,
            "reviewed_on": date.today().isoformat(), "content_sha256": fingerprint(q)}


def export_bundle(draft, current_views):
    check_binding(draft, current_views)
    candidates, rows, targets = [], [], {}
    for row in draft["questions"]:
        v = row["view"]
        if v["hard_blockers"] or any(r["status"] != "VERIFIED" for r in row["reviews"].values()):
            raise ValueError(f"Incomplete/blocked review: {v['question_id']}")
        q = validate_proposal(row)
        validate_reviews(q, row["reviews"])
        probes = grader_probes(v, q.grading_method)
        if not probes["passed"]:
            raise ValueError("Real grader boundary checks failed")
        if any(not isinstance(s, str) or len(s.strip()) < 5 for s in row["resolutions"].values()):
            raise ValueError("Every unresolved issue requires an explicit operator resolution")
        if "page_range_conflict_p2_vs_p2_3" in v["issues"]:
            import re
            if (q.source.citation == v["source"].get("citation")
                    or re.search(r"(?:第|pp?\.)\s*2\s*[-–—]\s*3", q.source.citation)):
                raise ValueError("Source page conflict remains in proposed citation; explicitly resolve the locator")
        candidate = {"subject": "408" if q.source.subject == "408" else "math2",
            "year": q.source.year, "question_number": q.source.question_number,
            "candidate_node_codes": [q.kp_code], "issues": list(v["issues"]),
            "question_id": v["question_id"], "binding_sha256": v["binding_sha256"],
            "question_content_sha256": v["question_content_sha256"],
            "answer_version_sha256": v["answer_version_sha256"], "snapshot_sha256": v["snapshot_sha256"]}
        candidates.append(candidate)
        rows.append({"candidate_id": q.source_id, "candidate_sha256": digest(candidate),
            "approved_question": q.model_dump(mode="json"), "approved_question_sha256": fingerprint(q),
            "reviews": deepcopy(row["reviews"]), "resolved_issues": deepcopy(row["resolutions"])})
        targets[q.source_id] = {"question_id": v["question_id"], "snapshot_sha256": v["snapshot_sha256"]}
    batch = {"version": "structured-real-slice-intake-v1", "questions": candidates}
    decisions = {"version": "real-slice-human-review-v1", "batch_sha256": digest(batch),
        "human_review_confirmed": True, "pack_id": "human-reviewed-" + draft["session_id"],
        "pack_version": "1", "questions": rows}
    pack = prepare(batch, decisions)
    return {"batch": batch, "decisions": decisions, "targets": targets,
            "pack": pack.model_dump(mode="json"), "database_written": False}


def private_directory(path: Path, root: Path) -> Path:
    resolved, base = path.resolve(), root.resolve()
    if not any(resolved.is_relative_to(base / folder) for folder in ("storage/answer-trust", "storage/question-intake")):
        raise ValueError("Keep exam/review artifacts in ignored private storage")
    return resolved


def save_revision(draft, directory: Path, root: Path) -> Path:
    directory = private_directory(directory, root)
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / f"draft-{draft['session_id']}-{uuid4().hex}.json"
    payload = {"draft": draft, "integrity_sha256": digest(draft)}
    with output.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
    return output


def restore(path: Path, current_views, root: Path):
    private_directory(path.parent, root)
    payload = read_json(path)
    if digest(payload["draft"]) != payload.get("integrity_sha256"):
        raise ValueError("Saved draft integrity mismatch")
    check_binding(payload["draft"], current_views)
    return payload["draft"]
