"""Repair one source transcription and admit one exact CRC exam variant.

All writes use the completed owned H-X snapshot as a new _test clone. The
ambiguous original CRC question remains unchanged. No learner/policy writes.
"""
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_phase45hx_batch01 import all_table_fingerprints, run_logged, save
from scripts.run_phase45hx_batch02 import inventory, PORT, SYSTEM_ID, REVISION, PROTECTED

SOURCE = ROOT / "storage/quality-audits/phase45hx-20261010/batch-13"
OUT = ROOT / "storage/quality-audits/phase45hx-20261010/batch-14"
INTAKE = ROOT / "storage/question-intake/phase45hx-20261010/huffman-source-correction-v1.json"
HUFFMAN_ID = UUID("4aa0fb9f-b1ee-4e67-a150-161969fbd00b")
CRC_ID = UUID("7d912016-f746-4c3c-be5e-e335103773f1")
OLD_BITS = "010001100100101011110101"
CORRECT_BITS = "0100011001001011110101"
ASSETS = {
    "huffman": (Path("C:/Users/ZBT/Desktop/考研知识点/408/2017/2017年计算机408统考真题.pdf"),
        "16f9c9afac663bc64e4057fe666d4563091349f71ba4113c26f58a66ea449883"),
    "crc": (Path("C:/Users/ZBT/Desktop/考研知识点/408/2023/2023年计算机408统考真题.pdf"),
        "e168bc9aa4663316ec3c5dd7051a060e08c4f708ff7ef0c555c41ff34f8a7433"),
}


def main():
    prior = json.loads((SOURCE / "checkpoint.json").read_text(encoding="utf-8"))
    backup = json.loads((SOURCE / "final-checkpoint/report.json").read_text(encoding="utf-8"))
    dump = ROOT / backup["backup"]["path"]
    name = prior.get("clone", {}).get("database")
    if (prior.get("status") != "BATCH_03_COMPLETE" or prior.get("port") != PORT or PORT == 5433
            or not isinstance(name, str) or not name.startswith("phase45hx_") or not name.endswith("_test")
            or backup.get("status") != "ISOLATED_BANK_CHECKPOINT_RESTORE_PASS"
            or sha256(dump.read_bytes()).hexdigest() != backup["backup"]["sha256"]):
        raise RuntimeError("completed_restored_checkpoint_required")
    for path, digest in ASSETS.values():
        if sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError("source_pdf_changed")
    if OUT.exists() and any(OUT.iterdir()):
        raise RuntimeError("refuse_overwrite_batch")
    OUT.mkdir(parents=True, exist_ok=True)
    from scripts import run_phase45i_agent_real as owner
    _, cluster, port = owner.load_existing_owner()
    if port != PORT:
        raise RuntimeError("owned_port_mismatch")
    for key in list(os.environ):
        if key.upper().startswith("PG"):
            os.environ.pop(key)
    owner.OUT_DIR = OUT / "postgres-runtime"
    owner.OUT_DIR.mkdir()
    started = owner.start_owned_database(cluster, PORT)
    from psycopg import connect, sql
    from sqlalchemy import create_engine, select, text
    from backend.db import create_session_factory
    from backend.models.learning import Question, KnowledgePoint
    from backend.services.question_pack import QuestionPack, fingerprint
    from backend.services.question_repair import local_pack_registry
    from backend.services.question_verification_upgrade import snapshot
    from backend.services.question_answer_revision import revise_transcription_content
    from backend.services.golden_learning_slice import digest
    from backend.services.auto_question_review import (prepare_exam_curated_repair, qualify_public_question,
        question_snapshot_sha256, bind_solver_rendered_generation_explanation)
    from backend.services.question_generation import Output, assess_output
    from backend.services.phase45hs_verifiers import normalize, value
    from backend.services.quality_verifiers import verify_problem
    from backend.services.question_attestation import question_content_sha256
    from scripts.audit_phase45h_completion_archive import source_pack_evidence
    result = {"phase": "4.5H-X-batch-04", "status": "STARTED", "port": PORT,
        "system_identifier_expected": SYSTEM_ID, "paid_model_calls": 0, "development_5433_touched": False}
    clone = "phase45hx_" + uuid4().hex[:12] + "_test"
    test_name = "phase45hxtest_" + uuid4().hex[:10] + "_test"
    tests_created = False
    engine = None
    try:
        with connect(host="127.0.0.1", port=PORT, user="postgres", dbname="postgres", autocommit=True, connect_timeout=5) as server:
            if str(server.execute("SELECT system_identifier FROM pg_control_system()").fetchone()[0]) != SYSTEM_ID:
                raise RuntimeError("system_identifier_changed")
            if server.execute("SELECT count(*) FROM pg_stat_activity WHERE datname=%s", (name,)).fetchone()[0]:
                raise RuntimeError("source_has_active_sessions")
            server.execute(sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(sql.Identifier(clone), sql.Identifier(name)))
            server.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(sql.Identifier(test_name)))
        tests_created = True
        engine = create_engine(f"postgresql+psycopg://postgres@127.0.0.1:{PORT}/{clone}")
        with engine.connect() as connection:
            before = all_table_fingerprints(connection)
            if before != backup["source_fingerprints"] or connection.scalar(text("SELECT version_num FROM alembic_version")) != REVISION:
                raise RuntimeError("clone_not_identical_to_verified_backup")
        result["clone"] = {"database": clone, "revision_after": REVISION}
        result["backup_before"] = backup["backup"]
        test_out = OUT / "pytest-offline"
        test_out.mkdir()
        url = f"postgresql+psycopg://postgres@127.0.0.1:{PORT}/{test_name}"
        env = {**os.environ, "APP_ENV": "test", "TEST_DATABASE_URL": url, "DATABASE_URL": url,
            "KAOYAN_OWNED_TEST_PORT": str(PORT), "PHASE45I_CLOSE_OFFLINE": "1", "PHASE45I_CLOSE_OUTPUT": str(test_out),
            "LLM_API_KEY": "", "LLM_MODEL": "offline", "LLM_BASE_URL": "http://127.0.0.1:9",
            "PYTHONIOENCODING": "utf-8", "UPLOAD_DIR": str(test_out / "uploads"), "CHROMA_DIR": str(test_out / "chroma"),
            "MODEL_SETTINGS_PATH": str(test_out / "settings.bin")}
        files = ["tests/unit/test_phase45hx_crc_verifier.py", "tests/unit/test_phase45hx_math_verifiers.py",
            "tests/unit/test_phase45hx_recovery.py", "tests/unit/test_phase45hs_identity.py",
            "tests/unit/test_phase45i_quality_verifiers.py", "tests/unit/test_question_generation.py",
            "tests/unit/test_question_repair.py", "tests/integration/test_auto_question_review.py",
            "tests/integration/test_phase45hx_recovery.py", "tests/integration/test_phase45hw_graduation.py",
            "tests/integration/test_question_pack_import.py", "tests/integration/test_phase45hs_duplicates.py",
            "tests/integration/test_personal_question_bank.py", "tests/integration/test_agent_learning_journey.py",
            "tests/integration/test_learning_loop.py"]
        rc = run_logged([sys.executable, "-m", "pytest", *files, "-q", "-x", "-o", "addopts=",
            "-o", "faulthandler_timeout=120", "--basetemp", str(test_out / "pytest-tmp")], test_out / "pytest.log", env=env, timeout=1800)
        result["tests"] = {"exit_code": rc, "files": files, "log": str((test_out / "pytest.log").relative_to(ROOT))}
        if rc:
            raise RuntimeError("tests_failed_no_content_write")
        factory = create_session_factory(engine)
        registry, _ = local_pack_registry(ROOT)
        with factory() as db:
            huffman = db.get(Question, HUFFMAN_ID)
            node = db.get(KnowledgePoint, huffman.kp_id)
            if huffman.stem.count(OLD_BITS) != 1 or huffman.correct_answer != "D":
                raise RuntimeError("huffman_live_content_differs_from_native_preview")
            provenance = huffman.grading_config["provenance"]
            entries = [item for item in registry[provenance["key"]] if item["fingerprint"] == provenance["sha256"]]
            if not entries:
                raise RuntimeError("old_huffman_pack_missing")
            entry = entries[0]
            raw = entry["question"].model_dump(mode="json")
            raw["stem"] = huffman.stem.replace(OLD_BITS, CORRECT_BITS)
            corrected_pack = QuestionPack.model_validate({"pack_id": entry["pack_id"], "version": "hx-huffman-source-v1", "questions": [raw]})
            if INTAKE.exists():
                if json.loads(INTAKE.read_text(encoding="utf-8")) != corrected_pack.model_dump(mode="json"):
                    raise RuntimeError("existing_correction_pack_conflicts")
            else:
                save(INTAKE, corrected_pack.model_dump(mode="json"))
            new_fingerprint = fingerprint(corrected_pack.questions[0])
            expected = digest(snapshot(huffman))
            correction_args = dict(basis="原卷2017第1页放大核对：编码串22位；旧草稿多转录两位。只改编码串，答案D、码表、选项和节点保持。PDF SHA=" + ASSETS["huffman"][1],
                proposed_source_pack_sha256=new_fingerprint, proposed_pack_version=corrected_pack.version)
            preview = revise_transcription_content(db, HUFFMAN_ID, expected, {"stem": raw["stem"]}, **correction_args, apply=False)
            if not preview["corrected"]:
                raise RuntimeError("huffman_correction_preview_not_changed")
            applied = revise_transcription_content(db, HUFFMAN_ID, expected, {"stem": raw["stem"]}, **correction_args, apply=True)
            registry, _ = local_pack_registry(ROOT)
            source = source_pack_evidence(huffman, registry, node)
            if source is None:
                raise RuntimeError("corrected_huffman_source_not_bound")
            repair = prepare_exam_curated_repair(huffman, node, source)
            db.flush()
            source = source_pack_evidence(huffman, registry, node)
            sha = question_snapshot_sha256(huffman)
            event, reviewed = qualify_public_question(db, question_id=huffman.id, node_id=node.id,
                expected_snapshot_sha256=sha, idempotency_key=f"hx-huffman-corrected:{huffman.id}:{sha}", source_evidence=source)
            if event is None:
                result["huffman_blocked"] = reviewed
                raise RuntimeError("corrected_huffman_not_qualified")
            result["huffman"] = {"question_id": str(huffman.id), "correction_preview": preview, "correction_apply": applied,
                "repair": repair, "review": reviewed, "new_question_rows": 0}
            db.commit()
        with factory() as db:
            parent = db.get(Question, CRC_ID)
            node = db.get(KnowledgePoint, parent.kp_id)
            crc_before = snapshot(parent)
            parent_source = source_pack_evidence(parent, registry, node)
            if parent_source is None or parent.question_provenance != "real_exam" or parent.source_status != "traceable":
                raise RuntimeError("crc_parent_source_required")
            parsed = re.search(r'G=([01]{3,17})', normalize(parent.stem))
            if not parsed:
                raise RuntimeError("crc_generator_not_recoverable")
            stem = f"采用生成多项式 G={parsed[1]} 的 CRC 校验。以下收到的完整码字中，除以 G 后余数为零（即通过 CRC 检测）的是（）。"
            options = {key: value(raw) for key, raw in parent.options.items()}
            draft = SimpleNamespace(stem=stem, options=options, question_type="single_choice", correct_answer="")
            calculation = verify_problem(draft)
            derived = calculation.get("derived_answer")
            if not derived or len(calculation.get("matching_options", [])) != 1:
                raise RuntimeError("crc_independent_derivation_not_unique")
            output = Output(stem=stem, question_type="single_choice", options=options, correct_answer=derived,
                explanation="按GF(2)模2除法逐项检查接收码字的余数，唯一全0余数的选项通过检测；检测通过不能保证物理传输绝无错误。",
                final_value=options[derived], steps=[])
            candidate = assess_output(output, node, request_id="phase45hx-crc-detection-variant-2023q37-v1",
                mode="adapted", family="crc_received_zero_remainder", parent=parent, difficulty="medium",
                trace={"mode": "codex_offline", "model": "codex_development_authoring", "model_calls": 0,
                    "prompt_version": "codex-crc-detection-variant-v1"})
            if candidate["status"] != "AUTO_PASS":
                result["crc_generation_blocked"] = {"errors": candidate["errors"], "uncertainties": candidate["uncertainties"]}
                raise RuntimeError("crc_generation_quality_gate_failed")
            q = candidate["question"]
            q.bank_scope = "public"
            bind_solver_rendered_generation_explanation(q, q.grading_config["generation"]["independent_verification"])
            db.add(q)
            db.flush()
            evidence = {"status": "TRACEABLE", "method": "exam_variant_lineage_v1", "parent_question_id": str(parent.id),
                "parent_snapshot_sha256": question_snapshot_sha256(parent), "question_content_sha256": question_content_sha256(q),
                "parent_source_evidence": parent_source,
                "transformation_summary": "保留原生成多项式及四个接收码字，改变求解目标为CRC零余数检测，消除‘能保证未发生传输错误’的过强结论；原题原文保留。",
                "uncertainties": ["变式不声称是逐字原题；原卷真实性及公开再分发许可未独立认证"]}
            sha = question_snapshot_sha256(q)
            event, reviewed = qualify_public_question(db, question_id=q.id, node_id=node.id,
                expected_snapshot_sha256=sha, idempotency_key=f"hx-crc-variant:{q.id}:{sha}", source_evidence=evidence)
            if event is None:
                result["crc_qualification_blocked"] = reviewed
                raise RuntimeError("crc_variant_formal_quality_gate_failed")
            if snapshot(parent) != crc_before:
                raise RuntimeError("original_crc_question_changed")
            result["crc_variant"] = {"question_id": str(q.id), "parent_id": str(parent.id),
                "review": reviewed, "source_evidence": evidence, "original_unchanged": True,
                "generation_status": candidate["status"], "new_question_rows": 1}
            db.commit()
        with factory() as db:
            result["after_inventory"] = inventory(db)
            after = all_table_fingerprints(db.connection())
            result["protected_history"] = {"before": {key: before[key] for key in PROTECTED},
                "after": {key: after[key] for key in PROTECTED}, "unchanged": all(before[key] == after[key] for key in PROTECTED)}
            if not result["protected_history"]["unchanged"]:
                raise RuntimeError("protected_history_or_policy_changed")
        result["status"] = "BATCH_04_COMPLETE"
        result["code_sha256"] = {path: sha256((ROOT / path).read_bytes()).hexdigest() for path in (
            "backend/services/quality_verifiers.py", "backend/services/phase45hs_verifiers.py",
            "backend/services/phase45hx_crc_verifier.py", "backend/services/question_generation.py",
            "backend/services/auto_question_review.py", "scripts/run_phase45hx_batch04.py")}
        save(OUT / "checkpoint.json", result)
        print(json.dumps({"status": result["status"], "clone": result["clone"],
            "huffman_repaired": True, "crc_variant_added": True,
            "inventory": {key: value for key, value in result["after_inventory"].items() if key != "candidates"},
            "protected_history_unchanged": True}, ensure_ascii=False), flush=True)
        return 0
    except Exception as exc:
        result.update(status="BLOCKED_EXCEPTION", error_type=type(exc).__name__, error=str(exc)[:500])
        save(OUT / "checkpoint.json", result)
        print(json.dumps({key: result.get(key) for key in ("status", "error_type", "error")}, ensure_ascii=False), flush=True)
        return 1
    finally:
        if engine is not None:
            engine.dispose()
        if tests_created:
            with connect(host="127.0.0.1", port=PORT, user="postgres", dbname="postgres", autocommit=True, connect_timeout=5) as server:
                if not server.execute("SELECT count(*) FROM pg_stat_activity WHERE datname=%s", (test_name,)).fetchone()[0]:
                    server.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(test_name)))
        if started:
            owner.command([str(owner.PG_BIN / "pg_ctl.exe"), "-D", str(cluster), "-m", "fast", "-w", "-t", "60", "stop"], timeout=75, check=False)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
