"""Stored test data only: CLI must hold READ ONLY and leave every row intact."""
from argparse import Namespace
from copy import deepcopy
from pathlib import Path
import json
from sqlalchemy import select,text
from backend.models.learning import Question
from scripts.review_golden_slice import fingerprints
from scripts.audit_question_quality import run
from tests.integration.test_learning_loop import session_factory,clean_database


def test_cli_reads_test_db_deterministically_and_preserves_all_tables(session_factory,clean_database,tmp_path,monkeypatch):
    import scripts.audit_question_quality as cli
    with session_factory() as db:
        q=db.scalar(select(Question).order_by(Question.id))
        qid=str(q.id)
        before=fingerprints(db)
    monkeypatch.setattr(cli,"safe_output",lambda path:path)
    monkeypatch.setattr(cli,"registry_from_existing",lambda:{})
    args=Namespace(output_dir=tmp_path/"run1",source_manifest=None,source_root=[],kp_code=None,
        question_id=[qid],candidates=None,limit=1,rule_version=cli.RULE_VERSION)
    a=run(args)
    assert a["database"].endswith("_test") and a["summary"]["real_inventory_audited"]==0
    assert a["summary"]["test_fixture_inventory_audited"]==1
    assert a["protection"]["before"]==a["protection"]["after"]==before
    assert a["summary"]["model_calls"]==a["summary"]["actually_activated"]==0
    original=(args.output_dir/"report.json").read_bytes()
    args.output_dir=tmp_path/"run2"
    b=run(args)
    assert a["decision_set_sha256"]==b["decision_set_sha256"]
    assert (tmp_path/"run1/report.json").read_bytes()==original
    with session_factory() as db:
        assert fingerprints(db)==before


def test_cli_rejects_missing_id_without_publishing_success(session_factory,clean_database,tmp_path,monkeypatch):
    import pytest
    import scripts.audit_question_quality as cli
    monkeypatch.setattr(cli,"safe_output",lambda path:path)
    monkeypatch.setattr(cli,"registry_from_existing",lambda:{})
    args=Namespace(output_dir=tmp_path/"unwritten",source_manifest=None,source_root=[],kp_code=None,
        question_id=["00000000-0000-4000-8000-000000000000"],candidates=None,limit=1,rule_version=cli.RULE_VERSION)
    with pytest.raises(ValueError,match="Unknown/inactive"):
        run(args)
    assert not args.output_dir.exists()
