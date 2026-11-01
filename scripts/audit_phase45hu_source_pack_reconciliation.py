"""Reconcile private exam-pack versions against a frozen H-S public-bank export.

The report stores identities and differing field names, never question text.
It proves local source-pack inventory reconciliation only, not scan fidelity,
answer correctness, licensing, or public redistribution rights.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def save_new(directory: Path, value: object) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "report.json").write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def identity(subject, year, question_number, canonical_subject):
    if subject is None or year is None or question_number is None:
        return None
    return (canonical_subject(str(subject)), str(year), str(question_number))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bank-export", type=Path,
        default=ROOT / "storage/quality-audits/phase45hs-20261010/formal-bank-export.json")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if not output.is_relative_to(ROOT / "storage/quality-audits"):
        raise ValueError("private_audit_output_required")
    if output.exists():
        raise ValueError("output_exists_refuse_overwrite")

    from backend.services.question_attestation import _subject
    from scripts.run_question_repair_pilot import local_pack_registry

    registry, rejected_files = local_pack_registry(ROOT)
    pack_by_identity = defaultdict(list)
    for pack_key, entries in registry.items():
        for entry in entries:
            question = entry["question"]
            source = question.source
            if str(source.source_type) != "exam":
                continue
            key = identity(source.subject, source.year, source.question_number, _subject)
            if key is not None:
                pack_by_identity[key].append({
                    "pack_key": pack_key,
                    "pack_id": entry["pack_id"],
                    "pack_version": entry["pack_version"],
                    "file": Path(entry["path"]).resolve().relative_to(ROOT / "storage/question-intake").as_posix(),
                    "fingerprint": entry["fingerprint"],
                    "content": {field: getattr(question, field, None) for field in
                        ("question_type", "stem", "options", "correct_answer", "explanation", "kp_code")},
                })

    exported = json.loads(args.bank_export.read_text(encoding="utf-8"))
    question_rows = exported["questions"]
    bank_by_identity = defaultdict(list)
    no_identity_rows = []
    for row in question_rows:
        provenance = (row.get("grading_config") or {}).get("provenance") or {}
        source = provenance.get("source") or {}
        key = identity(source.get("subject"), source.get("year"), source.get("question_number"), _subject)
        if key is None or source.get("source_type") != "exam":
            no_identity_rows.append(row.get("id"))
            continue
        bank_by_identity[key].append(row)

    pack_keys, bank_keys = set(pack_by_identity), set(bank_by_identity)
    exact_reference_count = 0
    current_diffs = Counter()
    for rows in bank_by_identity.values():
        for row in rows:
            provenance = (row.get("grading_config") or {}).get("provenance") or {}
            matches = {item["fingerprint"]: item for item in registry.get(provenance.get("key"), [])
                if item["fingerprint"] == provenance.get("sha256")}
            if len(matches) != 1:
                continue
            exact_reference_count += 1
            pack = next(iter(matches.values()))["question"]
            differences = [field for field in
                ("question_type", "stem", "options", "correct_answer", "explanation")
                if row.get(field) != getattr(pack, field, None)]
            current_diffs["+".join(differences) if differences else "exact"] += 1

    version_variants = Counter()
    changed_fields_by_identity = Counter()
    variant_examples = []
    for key, entries in pack_by_identity.items():
        content_payloads = {
            json.dumps(entry["content"], sort_keys=True, ensure_ascii=False, default=str)
            for entry in entries
        }
        fingerprints = {entry["fingerprint"] for entry in entries}
        version_variants[f"rows={len(entries)};fingerprints={len(fingerprints)};content_variants={len(content_payloads)}"] += 1
        if len(content_payloads) > 1:
            fields = [field for field in ("question_type", "stem", "options", "correct_answer", "explanation", "kp_code")
                if len({json.dumps(entry["content"].get(field), sort_keys=True, ensure_ascii=False, default=str)
                    for entry in entries}) > 1]
            changed_fields_by_identity.update(fields)
            if len(variant_examples) < 100:
                variant_examples.append({"identity": list(key), "records": len(entries),
                    "distinct_fingerprints": len(fingerprints), "distinct_content_versions": len(content_payloads),
                    "fields_differing_across_pack_versions": fields,
                    "pack_versions": sorted({f"{entry['pack_id']}@{entry['pack_version']}" for entry in entries})})

    report = {
        "version": "phase45hu-source-pack-reconciliation-v1",
        "source_pack_directory": "storage/question-intake",
        "bank_export": args.bank_export.resolve().relative_to(ROOT).as_posix(),
        "bank_export_sha256": sha256(args.bank_export.read_bytes()).hexdigest(),
        "rejected_source_files": len(rejected_files),
        "local_pack_rows": sum(len(items) for items in registry.values()),
        "local_pack_source_keys": len(registry),
        "pack_unique_exam_identities": len(pack_keys),
        "pack_duplicate_identity_groups": sum(len(rows) > 1 for rows in pack_by_identity.values()),
        "pack_extra_rows_over_unique_identities": sum(len(rows) for rows in pack_by_identity.values()) - len(pack_keys),
        "pack_version_shape_distribution": dict(version_variants),
        "pack_identities_with_multiple_content_versions": sum(
            count for shape, count in version_variants.items() if int(shape.rsplit("content_variants=", 1)[1]) > 1),
        "pack_changed_field_occurrences_across_versions": dict(changed_fields_by_identity),
        "bank_question_rows": len(question_rows),
        "bank_rows_with_exam_identity": sum(len(rows) for rows in bank_by_identity.values()),
        "bank_unique_exam_identities": len(bank_keys),
        "bank_duplicate_exam_identity_groups": sum(len(rows) > 1 for rows in bank_by_identity.values()),
        "bank_rows_without_exam_identity": len(no_identity_rows),
        "pack_and_bank_identity_overlap": len(pack_keys & bank_keys),
        "pack_only_identities": [list(key) for key in sorted(pack_keys - bank_keys)],
        "bank_only_identities": [list(key) for key in sorted(bank_keys - pack_keys)],
        "bank_rows_with_exact_source_pack_key_and_fingerprint": exact_reference_count,
        # The bank input is the frozen H-S export, not a live database read.
        # Name this honestly so consumers do not interpret it as post-H-S state.
        "frozen_export_content_comparison_to_exact_referenced_pack": dict(current_diffs),
        "version_difference_examples_no_question_text": variant_examples,
        "limits": [
            "A source-pack identity match is not proof that the transcription is verbatim to a scan.",
            "Pack-version differences are retained as version evidence and are not imported as new questions.",
            "This reconciliation does not authenticate answers, rights, or public redistribution permission.",
            "No database connection or write was performed.",
        ],
    }
    save_new(output, report)
    print(json.dumps({key: report[key] for key in (
        "version", "local_pack_rows", "pack_unique_exam_identities", "pack_duplicate_identity_groups",
        "pack_identities_with_multiple_content_versions", "bank_question_rows", "bank_unique_exam_identities",
        "bank_duplicate_exam_identity_groups", "pack_and_bank_identity_overlap", "pack_only_identities",
        "bank_only_identities", "bank_rows_with_exact_source_pack_key_and_fingerprint",
        "frozen_export_content_comparison_to_exact_referenced_pack", "rejected_source_files")}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
