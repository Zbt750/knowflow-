import pytest
from pydantic import ValidationError

from scripts.manage_answer_verification import VerificationManifest


def base(operation="verify"):
    entry = {
        "operation": operation,
        "question_id": "7e5d8f65-1514-4560-b487-66d9049a2d7a",
        "expected_answer_sha256": "a" * 64,
        "verifier": "local reviewer",
        "method": "manual comparison",
        "note": "Reviewed against the listed answer evidence.",
        "idempotency_key": "answer-review:case-1",
    }
    if operation == "verify":
        entry["verification_type"] = "human_verified"
    else:
        entry["expected_verification_event_id"] = "7e5d8f65-1514-4560-b487-66d9049a2d7a"
    return {"schema_version": "answer-verification-manifest-v1", "entries": [entry]}


def test_human_verified_manifest_requires_explicit_reviewer_method_note():
    manifest = VerificationManifest.model_validate(base())
    assert manifest.entries[0].verification_type == "human_verified"
    data = base()
    data["entries"][0]["note"] = "bad"
    with pytest.raises(ValidationError):
        VerificationManifest.model_validate(data)


def test_authoritative_reference_requires_allowlisted_source_metadata():
    data = base()
    data["entries"][0]["verification_type"] = "verified_reference"
    with pytest.raises(ValidationError, match="source_reference"):
        VerificationManifest.model_validate(data)
    data["entries"][0]["source_reference"] = {
        "kind": "forum_answer", "identifier": "x", "title": "untrusted", "locator": "url"}
    with pytest.raises(ValidationError):
        VerificationManifest.model_validate(data)
    data["entries"][0]["source_reference"] = {
        "kind": "official_answer_key", "identifier": "official-2025-q1",
        "title": "Answer key", "locator": "page 2 / question 1"}
    assert VerificationManifest.model_validate(data).entries[0].source_reference.kind == "official_answer_key"


def test_manifest_rejects_duplicate_question_mutations():
    data = base()
    data["entries"].append({**data["entries"][0], "idempotency_key": "second-operation"})
    with pytest.raises(ValidationError, match="one operation per question"):
        VerificationManifest.model_validate(data)
