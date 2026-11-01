"""Bounded repair planning using existing pack/quality services, never production writes."""
from collections import Counter
from pathlib import Path
import hashlib
import json
from backend.services.question_pack import PackQuestion, fingerprint
from backend.services.question_attestation import assess_source_attestation, question_content_sha256, _subject
from backend.services.question_quality import audit_question, audit_teaching_question
from backend.services.question_eligibility import legacy_question_eligibility
from backend.services.golden_learning_slice import digest
from backend.services.question_verification_upgrade import snapshot

VERSION = "question-blocker-repair-v1"


def restore_pack_binding(db,q,node,plan,registry,identities):
    """Only fresh marked _test namespaces; never modify origin/answer/content."""
    import re
    from sqlalchemy import text,select
    from backend.models.learning import QuestionSourceAttestation,Question
    from backend.services.question_attestation import create_source_attestation_record
    database=db.scalar(text("SELECT current_database()")); schema=db.scalar(text("SELECT current_schema()"))
    marker=db.scalar(text("SELECT obj_description(oid,'pg_namespace') FROM pg_namespace WHERE nspname=:schema"),{"schema":schema})
    if not database.endswith("_test") or not re.fullmatch(r"question_repair_[0-9a-f]{16}",schema or "") or marker!="kaoyan-question-repair:v1":
        raise ValueError("Repair writes require a marked private question_repair schema in _test database")
    if db.scalar(text("SHOW search_path"))!=schema:
        raise ValueError("Repair namespace must not fall back to public")
    q=db.scalar(select(Question).where(Question.id==q.id).with_for_update().execution_options(populate_existing=True))
    if q.bank_scope!='public' or q.generation_batch_id:
        raise ValueError('Personal questions are not public repair subjects')
    if str(q.id)!=plan["question_id"]: raise ValueError("Wrong repair subject")
    link=exact_pack_link(q,node,registry,identities)
    if not link or not link["usable"] or link!=plan.get("pack_link"):
        raise ValueError("Pack proof missing, changed or not unique; no repair")
    current=digest(snapshot(q))
    assessment=link["assessment"]
    key=assessment["attestation_key"]
    if (q.source_attestation_key==key and q.source_attestation_sha256==question_content_sha256(q)
            and q.content_trust=="source_attested" and q.source_status=="traceable"):
        expected_after={**plan["before_snapshot"],"source_attestation_key":key,
            "source_attestation_sha256":assessment["question_content_sha256"],"content_trust":"source_attested","source_status":"traceable"}
        if current!=digest(expected_after): raise ValueError("Repair replay snapshot drift")
        return {"status":"NOOP","question_id":str(q.id),"after_snapshot_sha256":current}
    if current!=plan["before_snapshot_sha256"]:
        raise ValueError("Question snapshot drift; do not repair")
    before=snapshot(q)
    from backend.services.answer_verification import answer_version_sha256
    before_answer_sha=answer_version_sha256(q)
    q.source_attestation_key=key; q.source_attestation_sha256=assessment["question_content_sha256"]
    q.content_trust="source_attested"; q.source_status="traceable"
    # Reuse existing machine attestation model, not a new human/trust event.
    from backend.services.question_attestation import SourceAttestationAssessment
    typed=SourceAttestationAssessment(status=assessment["status"],attestation_key=key,
        question_content_sha256=assessment["question_content_sha256"],source_content_sha256=assessment["source_content_sha256"],
        source_identity=assessment["source_identity"],source_locator=assessment["source_locator"],
        mapping_type=assessment["mapping_type"],issues=tuple(assessment["issues"]))
    if db.scalar(select(QuestionSourceAttestation).where(QuestionSourceAttestation.attestation_key==key)) is None:
        db.add(create_source_attestation_record(question=q,assessment=typed,candidate_id=link["candidate_id"],
            pack_id=link["pack_id"],pack_version=link["pack_version"],candidate_archive_sha256=link["file_sha256"],
            attestation_source="b3_isolated_exact_pack_restore_not_human_review"))
    db.flush()
    return {"status":"APPLIED_IN_ISOLATION","question_id":str(q.id),"before":before,"after":snapshot(q),
        "after_snapshot_sha256":digest(snapshot(q)),"source_record_key":key,"evidence":link,
        "before_content_sha256":plan["content_sha256"],"after_content_sha256":question_content_sha256(q),
        "before_answer_version_sha256":before_answer_sha,"after_answer_version_sha256":answer_version_sha256(q),
        "changed_fields":["source_attestation_key","source_attestation_sha256","content_trust","source_status"],
        "answer_changed":False,"origin_changed":False,"human_verification_created":False}


def local_pack_registry(root):
    registry={}; rejected=[]
    for path in sorted((root/"storage/question-intake").rglob("*.json")):
        if path.stat().st_size>16*1024*1024: continue
        try:
            payload=path.read_bytes()
            raw=json.loads(payload.decode("utf-8"))
            if not isinstance(raw,dict) or not raw.get("pack_id") or not isinstance(raw.get("questions"),list): continue
            file_sha=hashlib.sha256(payload).hexdigest()
            for row in raw["questions"]:
                try: pack=PackQuestion.model_validate(row)
                except Exception: continue  # Old/invalid packages are not silently repaired.
                key=f"{raw['pack_id']}:{pack.source_id}"
                registry.setdefault(key,[]).append({"path":str(path.resolve()),"file_sha256":file_sha,
                    "pack_id":raw["pack_id"],"pack_version":str(raw.get("version","")),
                    "question":pack,"fingerprint":fingerprint(pack)})
        except (OSError,ValueError): rejected.append(str(path))
    return registry,rejected


def exact_pack_link(q,node,registry,identity_counts):
    provenance=(q.grading_config or {}).get("provenance",{})
    candidates=[p for p in registry.get(provenance.get("key"),[]) if p["fingerprint"]==provenance.get("sha256")]
    # Multiple copies with identical payload are one link; different payloads never guessed.
    candidates={p["fingerprint"]:p for p in candidates}
    if len(candidates)!=1: return None
    p=next(iter(candidates.values())); pack=p["question"]
    source=pack.source
    identity=(_subject(source.subject),source.year,source.question_number)
    if identity_counts[identity]!=1: return None
    cid=f"{source.subject}:{source.year}:Q{source.question_number}"
    assessment=assess_source_attestation(question=q,node=node,pack_question=pack,
        pack_id=p["pack_id"],pack_version=p["pack_version"],candidate_archive_sha256=p["file_sha256"],
        candidate_map_row={"candidate_id":cid,"candidate_path":p["path"],"mapping_status":"EXACT",
            "match_count":1,"matched_question_ids":json.dumps([str(q.id)])})
    return {"path":p["path"],"file_sha256":p["file_sha256"],"pack_id":p["pack_id"],
        "pack_version":p["pack_version"],"candidate_id":cid,"source_content_sha256":p["fingerprint"],
        "assessment":assessment.public_dict(),"usable":assessment.status=="source_attested"}


def identity_counts(rows):
    return Counter((_subject((q.grading_config or {}).get("provenance",{}).get("source",{}).get("subject")),
        (q.grading_config or {}).get("provenance",{}).get("source",{}).get("year"),
        (q.grading_config or {}).get("provenance",{}).get("source",{}).get("question_number")) for q in rows)


def diagnose(q,node,*,runs,registry,identities,duplicate):
    baseline=legacy_question_eligibility(q,node)
    audit=audit_question(q,node,source_check={"status":"UNKNOWN","reason":"full_source_not_reaudited_in_inventory_scan"},
        runs=runs,duplicate=duplicate)
    teaching=audit_teaching_question(q,node,old_audit=audit)
    link=exact_pack_link(q,node,registry,identities)
    labels=set(baseline.blocking_reasons)
    if not baseline.answer_verification_current and not baseline.answer_attestation_current:
        labels.add("answer_reliability_insufficient")
    if link and any(i.startswith("knowledge_mapping_code_mismatch") for i in link["assessment"]["issues"]):
        labels.add("mapping_version_mismatch")
    labels.update("quality:"+v["reason"] for v in audit["stages"].values() if v["status"]=="FAIL")
    if "figure_or_table_asset_not_embedded" in audit["stages"]["structure"].get("issues",[]): labels.add("required_figure_missing")
    if not baseline.source_attestation_current: labels.add("current_source_binding_missing")
    if baseline.answer_attestation_current and audit["stages"]["independent_answer"]["status"]!="PASS": labels.add("only_ai_consistency")
    if q.source_attestation_key and not baseline.source_attestation_current: labels.add("content_version_drift")
    if q.content_trust=="needs_review" and (q.grading_config or {}).get("content_revisions") and not baseline.source_attestation_current:
        labels.add("content_version_drift")
    if audit["stages"]["uniqueness"]["status"]=="UNKNOWN": labels.add("answer_uniqueness_unresolved")
    if audit["stages"]["answer_consistency"]["status"]=="FAIL": labels.add("solver_conflict_not_proven_answer_error")
    if teaching["material_error"]: category="D"; action="isolate_material_issue"
    elif teaching["primary_use"]=="REFERENCE_ONLY": category="C"; action="reference_learning_only"
    elif q.question_type in {"proof","discussion","subjective","program"} and link and link["usable"]:
        category="C"; action="source_link_then_reference_support_review_not_auto_admit"
    elif link and link["usable"] and not baseline.source_attestation_current:
        category="A"; action="restore_exact_pack_source_and_mapping_binding"
    elif audit["stages"]["answer_consistency"]["status"]=="FAIL": category="D"; action="independent_conflict_review"
    else: category="B"; action="bounded_independent_verification_or_defer"
    priority=("required_figure_missing","quality:structure_incomplete","content_version_drift",
        "current_source_binding_missing","answer_provenance_unknown","answer_uniqueness_unresolved",
        "grading_or_practice_mode_unsupported","question_provenance_unknown")
    primary=next((p for p in priority if p in labels),next(iter(sorted(labels)),"other_rule"))
    return {"question_id":str(q.id),"kp_id":str(q.kp_id),"node_code":node.code if node else None,
        "node_name":node.name if node else None,"subject":node.subject if node else None,
        "before_snapshot":snapshot(q),"before_snapshot_sha256":digest(snapshot(q)),"content_sha256":question_content_sha256(q),
        "production_eligibility":baseline.public_dict(),"teaching_quality":teaching,
        "primary_blocker":primary,"blocker_labels":sorted(labels),"category":category,"action":action,
        "pack_link":link,"independent_answer":audit["stages"]["independent_answer"],
        "known_material_error":teaching["material_error"],"manual_risk_candidate":teaching["manual_review_candidate"],
        "structure":audit["stages"]["structure"],"grader":audit["stages"]["grading"],
        "automatic_answer_proof_available":audit["stages"]["independent_answer"]["status"]=="PASS"}
