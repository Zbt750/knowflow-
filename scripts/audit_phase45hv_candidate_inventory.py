"""Reconcile the 2016-2025 local draft inventory with archived candidate maps.

This is a read-only metadata audit. It does not read PDFs' page text, mutate
the user's Desktop archive, or claim that an unmatched candidate was lost.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
QUESTION_FILE = re.compile(r"^Q\d+\.md$", re.IGNORECASE)
YEAR_INDEX_ROW = re.compile(r"(?m)^\|\s*第\s*(\d+)\s*题\s*\|")


def digest(path: Path) -> str:
    h = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def identity(row: dict) -> tuple[str, int, int] | None:
    try:
        subject = str(row.get("subject") or "").strip()
        year = int(row.get("year") or 0)
        number = int(row.get("question_number") or 0)
    except (TypeError, ValueError):
        return None
    if not subject or not 1900 < year < 2100 or number < 1:
        return None
    subject = "math2" if subject in {"数学二", "math2"} else "408" if subject == "408" else subject
    return subject, year, number


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-root", type=Path, required=True,
        help="本地逐题资料目录；只读，不会修改目录内容")
    parser.add_argument("--output", type=Path, required=True,
        help="私有审计输出，必须位于 storage/quality-audits 下")
    parser.add_argument("--exam-index-root", type=Path,
        help="可选的年度原卷与知识点索引目录；仅读取 README、文件名和索引行数")
    parser.add_argument("--hv-clone-owner", type=Path,
        help="可选的H-V隔离克隆owner.json；只读比对公共题库来源身份，不读取题面")
    args = parser.parse_args()
    archive = args.archive_root.resolve()
    output = args.output.resolve()
    if not archive.is_dir():
        raise ValueError("archive_root_not_found")
    if not output.is_relative_to(ROOT / "storage/quality-audits"):
        raise ValueError("private_output_required")
    if output.exists():
        raise ValueError("refuse_overwrite_existing_audit")

    by_subject_year: Counter = Counter()
    draft_paths = []
    for subject_dir in (archive / "逐题整理").iterdir():
        if not subject_dir.is_dir():
            continue
        for year_dir in subject_dir.iterdir():
            if not year_dir.is_dir() or not year_dir.name.isdigit():
                continue
            year = int(year_dir.name)
            for path in year_dir.iterdir():
                if path.is_file() and QUESTION_FILE.fullmatch(path.name):
                    key = ("math2" if subject_dir.name == "数学二" else "408", year)
                    by_subject_year[key] += 1
                    draft_paths.append(path)

    mapping_path = ROOT / "tmp/phase1_20261006/candidate_question_mapping.csv"
    inventory_path = ROOT / "tmp/phase1_20261006/candidate_inventory.csv"
    if not mapping_path.is_file() or not inventory_path.is_file():
        raise ValueError("frozen_phase1_inventory_missing")
    mapping = read_csv(mapping_path)
    inventory = read_csv(inventory_path)
    mapping_identities = [identity(row) for row in mapping]
    mapping_unique = {key for key in mapping_identities if key is not None}
    map_status = Counter(row.get("mapping_status", "") for row in mapping)
    subject_counts = Counter(row.get("subject", "") for row in mapping)
    year_counts = Counter(row.get("year", "") for row in mapping)
    inventory_question_rows = sum(row.get("asset_kind") == "personal_question_draft" for row in inventory)
    inventory_artifact_rows = len(inventory) - inventory_question_rows

    # The three pack files are versioned snapshots and may overlap. Count
    # records per snapshot plus their identity union; never sum them as a total.
    pack_runs = []
    packs_root = ROOT / "storage/question-intake"
    for folder in ("past-exam-import-20261005-155734", "past-exam-import-20261005-v2-160006",
                   "past-exam-import-20261005-v3-160318"):
        path = packs_root / folder / "question-pack.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("questions", [])
        ids = set()
        years = Counter()
        subjects = Counter()
        dupes = 0
        for row in rows:
            key = identity({"subject": row.get("source", {}).get("subject") if isinstance(row.get("source"), dict) else "",
                "year": row.get("source", {}).get("year") if isinstance(row.get("source"), dict) else "",
                "question_number": row.get("source", {}).get("question_number") if isinstance(row.get("source"), dict) else ""})
            if key is not None:
                if key in ids:
                    dupes += 1
                ids.add(key)
                subjects[key[0]] += 1
                years[str(key[1])] += 1
        pack_runs.append({"snapshot": folder, "record_count": len(rows), "identified_source_identity_count": len(ids),
            "within_snapshot_duplicate_identity_rows": dupes, "subject_counts": dict(subjects), "year_counts": dict(years)})
    pack_union = set()
    for folder in ("past-exam-import-20261005-155734", "past-exam-import-20261005-v2-160006",
                   "past-exam-import-20261005-v3-160318"):
        rows = json.loads((packs_root / folder / "question-pack.json").read_text(encoding="utf-8")).get("questions", [])
        for row in rows:
            source = row.get("source") if isinstance(row.get("source"), dict) else {}
            key = identity({"subject": source.get("subject"), "year": source.get("year"),
                "question_number": source.get("question_number")})
            if key is not None:
                pack_union.add(key)

    raw_pdfs = list((archive / "个人复习原卷").rglob("*.pdf"))
    pdf_subjects = Counter()
    pdf_years = Counter()
    for path in raw_pdfs:
        name = path.name
        match = re.search(r"(20\d{2})", name)
        if match:
            pdf_years[match.group(1)] += 1
        if "408" in name or "计算机" in name:
            pdf_subjects["408"] += 1
        elif "数学二" in name or "数学" in name:
            pdf_subjects["math2"] += 1
        else:
            pdf_subjects["other_or_unclassified"] += 1

    exam_index_audit = None
    annual_index_identities = set()
    annual_index_identity_counts = Counter()
    if args.exam_index_root is not None:
        exam_root = args.exam_index_root.resolve()
        if not exam_root.is_dir():
            raise ValueError("exam_index_root_not_found")
        index_rows = []
        pdf_rows = []
        index_hashes = {}
        for subject_dir in exam_root.iterdir():
            if not subject_dir.is_dir() or subject_dir.name not in {"数学", "408"}:
                continue
            subject = "math2" if subject_dir.name == "数学" else "408"
            for year_dir in subject_dir.iterdir():
                if not year_dir.is_dir() or not re.fullmatch(r"20\d{2}", year_dir.name):
                    continue
                year = int(year_dir.name)
                for path in year_dir.iterdir():
                    if not path.is_file():
                        continue
                    if path.name.startswith("年度知识点-") and path.suffix.lower() == ".md":
                        content = path.read_text(encoding="utf-8-sig")
                        numbers = [int(value) for value in YEAR_INDEX_ROW.findall(content)]
                        count = len(numbers)
                        for number in numbers:
                            key = (subject, year, number)
                            annual_index_identities.add(key)
                            annual_index_identity_counts[key] += 1
                        index_rows.append({"subject": subject, "year": year, "question_index_rows": count})
                        index_hashes[f"{subject_dir.name}/{year_dir.name}/{path.name}"] = digest(path)
                    elif path.suffix.lower() == ".pdf":
                        pdf_rows.append({"subject": subject, "year": year, "name": path.name,
                                         "bytes": path.stat().st_size, "sha256": digest(path)})
        per_subject = {}
        for subject in sorted({row["subject"] for row in index_rows}):
            selected = sorted((row for row in index_rows if row["subject"] == subject),
                              key=lambda row: row["year"])
            per_subject[subject] = {
                "year_index_files": len(selected),
                "indexed_question_rows": sum(row["question_index_rows"] for row in selected),
                "by_year": {str(row["year"]): row["question_index_rows"] for row in selected},
            }
        exam_index_audit = {
            "root_read_only": True,
            "scope_from_readme": "2010-2026 annual subject directories; labels are study indexes, not official exam tags",
            "index_file_count": len(index_rows),
            "indexed_question_rows": sum(row["question_index_rows"] for row in index_rows),
            "unique_subject_year_question_index_identities": len(annual_index_identities),
            "duplicate_subject_year_question_identity_rows": sum(count - 1 for count in annual_index_identity_counts.values()),
            "duplicate_subject_year_question_identities": [
                {"subject": key[0], "year": key[1], "question_number": key[2], "rows": count}
                for key, count in sorted(annual_index_identity_counts.items()) if count > 1
            ],
            "by_subject": per_subject,
            "pdf_count": len(pdf_rows),
            "pdf_by_subject": dict(Counter(row["subject"] for row in pdf_rows)),
            "pdf_by_subject_year": {f"{subject}:{year}": count for (subject, year), count in
                sorted(Counter((row["subject"], row["year"]) for row in pdf_rows).items())},
            "pdf_metadata_and_sha256": pdf_rows,
            "index_sha256": index_hashes,
            "question_index_rows_2016_2025": sum(row["question_index_rows"] for row in index_rows
                if 2016 <= row["year"] <= 2025),
            "not_a_transcription_completeness_or_answer_verification_claim": True,
        }

    database_identity_audit = None
    if args.hv_clone_owner is not None:
        owner_path = args.hv_clone_owner.resolve()
        quality_root = ROOT / "storage/quality-audits"
        if not owner_path.is_relative_to(quality_root) or owner_path.name != "owner.json":
            raise ValueError("hv_clone_owner_must_be_private_audit_owner_json")
        owner = json.loads(owner_path.read_text(encoding="utf-8"))
        database = owner.get("database")
        if (owner.get("port") != 59227 or owner.get("system_identifier") != "7694698872540080852"
                or not isinstance(database, str) or not database.startswith("phase45hv_")
                or not database.endswith("_test")):
            raise ValueError("hv_clone_owner_identity_not_expected_owned_test_cluster")
        from psycopg import connect
        from scripts import run_phase45i_agent_real as test_owner
        _, cluster, owned_port = test_owner.load_existing_owner()
        if owned_port != 59227:
            raise ValueError("hv_test_cluster_port_mismatch")
        started = test_owner.start_owned_database(cluster, owned_port)
        try:
            with connect(host="127.0.0.1", port=owned_port, user="postgres", dbname="postgres",
                         autocommit=True, connect_timeout=5) as server:
                system_id = str(server.execute("SELECT system_identifier FROM pg_control_system()").fetchone()[0])
            if system_id != "7694698872540080852":
                raise ValueError("hv_clone_system_identifier_mismatch")
            with connect(host="127.0.0.1", port=owned_port, user="postgres", dbname=database,
                         connect_timeout=5) as db:
                with db.transaction():
                    db.execute("SET TRANSACTION READ ONLY")
                    revision = db.execute("SELECT version_num FROM alembic_version").fetchone()[0]
                    if revision != owner.get("source_revision"):
                        raise ValueError("hv_clone_schema_revision_mismatch")
                    rows = db.execute("""
                        SELECT question_provenance, grading_config
                        FROM questions
                        WHERE bank_scope = 'public' AND generation_batch_id IS NULL
                    """).fetchall()
        finally:
            if started:
                stopped = test_owner.command([str(test_owner.PG_BIN / "pg_ctl.exe"), "-D", str(cluster),
                    "-m", "fast", "-w", "-t", "30", "stop"], timeout=40, check=False)
                if stopped.returncode != 0:
                    raise RuntimeError("owned_isolated_cluster_failed_to_stop_after_read_only_audit")
        bank_keys = set()
        bank_by_provenance = Counter()
        for provenance, grading_config in rows:
            config = grading_config if isinstance(grading_config, dict) else {}
            prov = config.get("provenance") if isinstance(config.get("provenance"), dict) else {}
            source = prov.get("source") if isinstance(prov.get("source"), dict) else {}
            key = identity(source)
            if key is not None:
                bank_keys.add(key)
                bank_by_provenance[str(provenance or "unknown")] += 1
        candidate_keys = {key for key in mapping_identities if key is not None}
        candidate_annual_overlap = candidate_keys & annual_index_identities
        annual_archive_year_identities = {key for key in annual_index_identities if 2016 <= key[1] <= 2025}
        candidate_not_in_annual_index = candidate_keys - annual_index_identities
        annual_archive_not_in_candidate = annual_archive_year_identities - candidate_keys
        overlap = candidate_keys & bank_keys
        annual_overlap = annual_index_identities & bank_keys
        db_outside_archive = bank_keys - candidate_keys
        by_pair = {}
        pairs = sorted({(key[0], key[1]) for key in candidate_keys | bank_keys})
        for subject, year in pairs:
            candidates_for_pair = {key for key in candidate_keys if key[0] == subject and key[1] == year}
            bank_for_pair = {key for key in bank_keys if key[0] == subject and key[1] == year}
            by_pair[f"{subject}:{year}"] = {
                "archive_candidate_identities": len(candidates_for_pair),
                "current_public_bank_source_identities": len(bank_for_pair),
                "identity_overlap": len(candidates_for_pair & bank_for_pair),
                "archive_identity_not_in_current_bank": len(candidates_for_pair - bank_for_pair),
                "current_bank_identity_not_in_archive": len(bank_for_pair - candidates_for_pair),
            }
        missing_statuses = Counter()
        for row, key in zip(mapping, mapping_identities):
            if key is not None and key not in bank_keys:
                missing_statuses[row.get("mapping_status", "")] += 1
        annual_by_pair = {}
        for subject, year in sorted({(key[0], key[1]) for key in annual_index_identities | bank_keys}):
            index_for_pair = {key for key in annual_index_identities if key[0] == subject and key[1] == year}
            bank_for_pair = {key for key in bank_keys if key[0] == subject and key[1] == year}
            annual_by_pair[f"{subject}:{year}"] = {
                "indexed_identities": len(index_for_pair),
                "current_public_bank_source_identities": len(bank_for_pair),
                "identity_overlap": len(index_for_pair & bank_for_pair),
                "indexed_identity_not_in_current_bank": len(index_for_pair - bank_for_pair),
                "current_bank_identity_not_in_index": len(bank_for_pair - index_for_pair),
            }
        database_identity_audit = {
            "read_only": True,
            "isolated_database": database,
            "port": 59227,
            "system_identifier": system_id,
            "schema_revision": revision,
            "public_question_rows_scanned_for_source_metadata": len(rows),
            "unique_current_public_exam_source_identities": len(bank_keys),
            "current_source_identity_rows_by_question_provenance": dict(bank_by_provenance),
            "archive_candidate_unique_identities": len(candidate_keys),
            "archive_candidates_matching_annual_index_identities": len(candidate_annual_overlap),
            "archive_candidate_identity_not_in_annual_index": len(candidate_not_in_annual_index),
            "annual_2016_2025_identity_not_in_draft_archive": len(annual_archive_not_in_candidate),
            "archive_index_identity_differences": {
                "candidate_not_in_index": [
                    {"subject": key[0], "year": key[1], "question_number": key[2]}
                    for key in sorted(candidate_not_in_annual_index)
                ],
                "index_not_in_candidate_2016_2025": [
                    {"subject": key[0], "year": key[1], "question_number": key[2]}
                    for key in sorted(annual_archive_not_in_candidate)
                ],
            },
            "candidate_to_database_identity_overlap": len(overlap),
            "archive_candidate_identities_absent_from_current_public_bank": len(candidate_keys - bank_keys),
            "database_identities_outside_2016_2025_archive": len(db_outside_archive),
            "absent_candidate_mapping_statuses": dict(missing_statuses),
            "by_subject_year": by_pair,
            "annual_index_unique_identities_2010_2026": len(annual_index_identities),
            "annual_index_to_database_identity_overlap": len(annual_overlap),
            "annual_index_identity_absent_from_current_public_bank": len(annual_index_identities - bank_keys),
            "database_identity_not_in_annual_index": len(bank_keys - annual_index_identities),
            "annual_index_by_subject_year": annual_by_pair,
            "interpretation": "source-identity difference only; an absent identity is not proof the source text was lost or the candidate is ready for import",
        }

    report = {
        "version": "phase45hv-candidate-inventory-audit-v3",
        "read_only": True,
        "archive_scope": "local user archive metadata; question content not copied to this report",
        "draft_question_files": len(draft_paths),
        "draft_question_files_by_subject_year": {f"{subject}:{year}": count
            for (subject, year), count in sorted(by_subject_year.items())},
        "candidate_mapping_rows": len(mapping),
        "candidate_mapping_unique_exam_identity_keys": len(mapping_unique),
        "candidate_mapping_rows_by_subject": dict(subject_counts),
        "candidate_mapping_rows_by_year": dict(year_counts),
        "candidate_mapping_status_counts": dict(map_status),
        "candidate_mapping_sha256": digest(mapping_path),
        "candidate_inventory_rows": len(inventory),
        "candidate_inventory_question_draft_rows": inventory_question_rows,
        "candidate_inventory_non_question_artifact_rows": inventory_artifact_rows,
        "candidate_inventory_sha256": digest(inventory_path),
        "question_pack_snapshots": pack_runs,
        "question_pack_union_identity_count": len(pack_union),
        "pack_snapshots_are_overlapping_versions_not_additive": True,
        "user_archive_raw_pdf_count": len(raw_pdfs),
        "user_archive_raw_pdf_counts_by_subject_filename": dict(pdf_subjects),
        "user_archive_raw_pdf_counts_by_year_filename": dict(pdf_years),
        "additional_annual_exam_index_archive": exam_index_audit,
        "current_public_bank_identity_comparison": database_identity_audit,
        "interpretation": {
            "not_exact_database_match": map_status.get("POSSIBLE", 0) + map_status.get("UNMATCHED", 0),
            "possible_match_is_not_proven_missing": True,
            "unmatched_is_not_proven_data_loss": True,
            "draft_files_are_not_equivalent_to_complete_verified_online_questions": True,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "draft_question_files_by_subject_year"},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
