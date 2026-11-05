"""Read-only inventory of the isolated H-X batch-15b checkpoint."""
from __future__ import annotations

import json
import csv
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from psycopg import connect
    from scripts import run_phase45i_agent_real as owner_api

    checkpoint = json.loads((ROOT / "storage/quality-audits/phase45hx-20261011/batch-15b/checkpoint.json")
        .read_text(encoding="utf-8"))
    if (checkpoint.get("status") != "BATCH_05_COMPLETE" or checkpoint.get("port") == 5433
            or checkpoint.get("system_identifier_expected") != "7694698872540080852"):
        raise RuntimeError("batch15b_isolated_checkpoint_guard_failed")
    database = checkpoint["clone"]["database"]
    _, cluster, port = owner_api.load_existing_owner()
    if port != checkpoint["port"] or port == 5433:
        raise RuntimeError("isolated_port_mismatch")
    started = owner_api.start_owned_database(cluster, port)
    try:
        with connect(host="127.0.0.1", port=port, user="postgres", dbname=database,
                     connect_timeout=5) as db:
            system_id = str(db.execute("SELECT system_identifier FROM pg_control_system()")
                .fetchone()[0])
            if system_id != checkpoint["system_identifier_expected"]:
                raise RuntimeError("isolated_system_identifier_mismatch")
            nodes = db.execute("""SELECT id, code, name, subject FROM knowledge_points
                WHERE is_active AND is_assessable ORDER BY subject, name""").fetchall()
            questions = db.execute("""SELECT id, kp_id, question_type, correct_answer, stem,
                grading_config, question_provenance, content_trust, answer_provenance,
                answer_reliability, auto_review_event_id, is_active, is_hidden,
                options, explanation, skill_tags, difficulty, question_role
                FROM questions WHERE bank_scope='public' AND generation_batch_id IS NULL""").fetchall()
            # This bounded slice is exactly 408 Q1-Q40 plus Math II Q1-Q10.
            wanted = {("408", 2017, number) for number in range(1, 41)} | {
                ("math2", 2017, number) for number in range(1, 11)}
            node_by_id = {row[0]: row for row in nodes}
            matched = []
            for row in questions:
                config = row[5] if isinstance(row[5], dict) else {}
                provenance = config.get("provenance", {}) if isinstance(config, dict) else {}
                source = provenance.get("source", {}) if isinstance(provenance, dict) else {}
                subject_text = str(source.get("subject", "")).lower()
                subject = "408" if "408" in subject_text else (
                    "math2" if "math" in subject_text or "数学" in subject_text else "")
                try:
                    identity = (subject, int(source.get("year")), int(source.get("question_number")))
                except (TypeError, ValueError):
                    continue
                if identity in wanted:
                    event_id = row[10]
                    node = node_by_id.get(row[1])
                    attempt_count = db.execute("SELECT count(*) FROM question_attempts WHERE question_id=%s", (row[0],)).fetchone()[0]
                    matched.append({"question_id": str(row[0]), "identity": identity,
                        "kp_code": node[1] if node else None, "kp_name": node[2] if node else None,
                        "question_type": row[2], "answer": row[3], "stem": row[4],
                        "options": row[13], "explanation": row[14], "skill_tags": row[15],
                        "difficulty": row[16], "question_role": row[17],
                        "question_provenance": row[6], "content_trust": row[7],
                        "answer_provenance": row[8], "answer_reliability": row[9],
                        "auto_review_current_pointer": str(event_id) if event_id else None,
                        "attempt_count": attempt_count,
                        "auto_review_event_id": str(event_id) if event_id else None})
            terms = ("系统调用", "多道", "文件", "inode", "硬链接", "DMA", "无线",
                "802", "IPv4", "IP地址", "子网", "TCP", "拥塞", "主存与控制存储器",
                "稀疏矩阵", "Huffman")
            selected_nodes = [{"id": str(row[0]), "code": row[1], "name": row[2], "subject": row[3]}
                for row in nodes if any(term.lower() in row[2].lower() for term in terms)]
            from backend.services.question_attestation import _subject
            mapping_path = ROOT / "tmp/phase1_20261006/candidate_question_mapping.csv"
            with mapping_path.open(encoding="utf-8-sig", newline="") as stream:
                mapping_rows = list(csv.DictReader(stream))
            old_unmatched = [row for row in mapping_rows if row.get("mapping_status") == "UNMATCHED"]
            # Include every DB identity, not only the bounded 2017 review slice.
            all_db_identities = set()
            for row in questions:
                config = row[5] if isinstance(row[5], dict) else {}
                provenance = config.get("provenance", {}) if isinstance(config, dict) else {}
                source = provenance.get("source", {}) if isinstance(provenance, dict) else {}
                try:
                    key = (_subject(source.get("subject", "")), int(source.get("year")),
                        int(source.get("question_number")))
                except (TypeError, ValueError):
                    continue
                if key[0] in {"408", "math2"}:
                    all_db_identities.add(key)
            mapping_present = [row for row in old_unmatched
                if (_subject(row.get("subject", "")), int(row["year"]), int(row["question_number"])) in all_db_identities]
            by_subject = {subject: {"csv_unmatched": sum(_subject(r.get("subject", "")) == subject for r in old_unmatched),
                "already_present_in_live_clone": sum(_subject(r.get("subject", "")) == subject for r in mapping_present),
                "still_absent_by_exam_identity": sum(_subject(r.get("subject", "")) == subject for r in old_unmatched)
                    - sum(_subject(r.get("subject", "")) == subject for r in mapping_present)}
                for subject in ("408", "math2")}
            csv_reconciliation = {"mapping_csv_rows": len(mapping_rows), "csv_unmatched_total": len(old_unmatched),
                "already_present_in_live_clone_total": len(mapping_present),
                "still_absent_by_exam_identity_total": len(old_unmatched) - len(mapping_present),
                "by_subject": by_subject}
            matched_summary = [{"identity": row["identity"], "question_id": row["question_id"],
                "kp_code": row["kp_code"], "question_type": row["question_type"],
                "provenance": row["question_provenance"], "content_trust": row["content_trust"],
                "answer_reliability": row["answer_reliability"],
                "has_current_auto_review": bool(row["auto_review_current_pointer"]),
                "attempt_count": row["attempt_count"]} for row in matched]
            report = {"status": "READ_ONLY_INVENTORY_PASS", "database": database,
                "port": port, "system_identifier": system_id, "public_questions": len(questions),
                "assessable_nodes": len(nodes), "selected_nodes": selected_nodes,
                "target_identity_total": len(wanted), "target_existing_total": len(matched),
                "candidate_csv_reconciliation": csv_reconciliation,
                "target_existing_questions": matched,
                "unmatched_target_identities": sorted([list(i) for i in wanted
                    - {tuple(row["identity"]) for row in matched}])}
            output_dir = ROOT / "storage/quality-audits/phase45hx-20261011/batch-16-preflight"
            output_file = output_dir / "2017-slice-inventory.json"
            if output_file.exists():
                raise RuntimeError("refuse_overwrite_existing_inventory_snapshot")
            output_dir.mkdir(parents=True, exist_ok=True)
            output_file.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            print(json.dumps({"status": report["status"], "database": database, "port": port,
                "system_identifier": system_id, "public_questions": len(questions),
                "assessable_nodes": len(nodes), "target_identity_total": len(wanted),
                "target_existing_total": len(matched), "target_missing_total": len(wanted)-len(matched),
                "candidate_csv_reconciliation": csv_reconciliation,
                "output": str(output_file.relative_to(ROOT))}, ensure_ascii=False, default=str))
    finally:
        if started:
            owner_api.command([str(owner_api.PG_BIN / "pg_ctl.exe"), "-D", str(cluster),
                "-m", "fast", "-w", "-t", "60", "stop"], timeout=75, check=False)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
