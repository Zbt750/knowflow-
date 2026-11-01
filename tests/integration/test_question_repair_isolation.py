"""Fresh marked schema, synthetic fixture, not the development public schema."""
from pathlib import Path
from copy import deepcopy
from collections import Counter
import hashlib
import json
import pytest
from sqlalchemy import select
from backend.models.learning import Question,KnowledgePoint,QuestionSourceAttestation
from backend.services.question_pack import QuestionPack,fingerprint
from backend.services.question_repair import local_pack_registry,exact_pack_link,restore_pack_binding
from backend.services.golden_learning_slice import digest
from backend.services.question_verification_upgrade import snapshot
from scripts.run_question_repair_pilot import isolated_factory
from tests.unit.test_question_attestation import attested_fixture,PACK_ID


def test_guarded_restore_noop_drift_and_public_rejection(test_database_url,tmp_path):
    q,node,pack,row,_=attested_fixture()
    raw={"pack_id":PACK_ID,"version":"test-v1","questions":[pack.model_dump(mode="json",exclude_unset=True)]}
    # Private test fixture on disk, never a real review package.
    folder=tmp_path/"storage/question-intake"; folder.mkdir(parents=True)
    path=folder/"test-pack.json"; path.write_text(json.dumps(raw),encoding="utf-8")
    registry,_=local_pack_registry(tmp_path)
    identities=Counter({("math2",pack.source.year,pack.source.question_number):1})
    with isolated_factory(test_database_url) as (factory,schema):
        with factory.begin() as db:
            db.add(node); db.flush(); db.add(q); db.flush()
            plan={"question_id":str(q.id),"before_snapshot":snapshot(q),"before_snapshot_sha256":digest(snapshot(q)),
                "content_sha256":__import__("backend.services.question_attestation",fromlist=["question_content_sha256"]).question_content_sha256(q),
                "pack_link":exact_pack_link(q,node,registry,identities)}
            before=deepcopy((q.stem,q.options,q.correct_answer,q.explanation,q.question_provenance))
            result=restore_pack_binding(db,q,node,plan,registry,identities)
            assert result["status"]=="APPLIED_IN_ISOLATION"
            assert restore_pack_binding(db,q,node,plan,registry,identities)["status"]=="NOOP"
            assert (q.stem,q.options,q.correct_answer,q.explanation,q.question_provenance)==before
            assert db.scalar(select(QuestionSourceAttestation)).attestation_source=="b3_isolated_exact_pack_restore_not_human_review"
        with factory.begin() as db:
            saved=db.get(Question,q.id)
            saved.correct_answer="B"; db.flush()
            with pytest.raises(ValueError,match="Pack proof|snapshot drift"):
                restore_pack_binding(db,saved,db.get(KnowledgePoint,node.id),plan,registry,identities)
        with factory() as db:
            from sqlalchemy import text
            db.execute(text("SET search_path=public"))
            with pytest.raises(ValueError,match="marked private"):
                restore_pack_binding(db,q,node,plan,registry,identities)
