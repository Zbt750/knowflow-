"""Synthetic TEST_FIXTURE bounds and compatibility; no real signoff."""
from copy import deepcopy
from collections import Counter
from types import SimpleNamespace
import json
import pytest
from tests.unit.test_question_attestation import attested_fixture,PACK_ID,PACK_VERSION,ARCHIVE_SHA
from backend.services.question_attestation import assess_source_attestation
from backend.services.quality_verifiers import verify_problem
from scripts.run_question_repair_pilot import choose_pilot,isolated_factory
from backend.services.question_repair import identity_counts


def test_optional_null_source_origin_does_not_invalidate_legacy_exact_snapshot():
    q,node,pack,row,_=attested_fixture()
    q.grading_config["provenance"]["source"].pop("content_origin")
    result=assess_source_attestation(question=q,node=node,pack_question=pack,pack_id=PACK_ID,
        pack_version=PACK_VERSION,candidate_archive_sha256=ARCHIVE_SHA,candidate_map_row=row)
    assert result.status=="source_attested"
    q.grading_config["provenance"]["source"]["content_origin"]="AI_GENERATED"
    result=assess_source_attestation(question=q,node=node,pack_question=pack,pack_id=PACK_ID,
        pack_version=PACK_VERSION,candidate_archive_sha256=ARCHIVE_SHA,candidate_map_row=row)
    assert "database_source_snapshot_mismatch" in result.issues


@pytest.mark.parametrize("stem,options,answer",[
    ("下列数中不能由 IEEE754 二进制浮点格式精确表示的是？",{"A":"1.2","B":"1.25","C":"2.0","D":"2.5"},"A"),
    ("32 位补码所能表示的整数范围是（ ）。",{"A":"−2^32 ～ 2^31−1","B":"−2^31 ～ 2^31−1","C":"−2^32 ～ 2^32−1","D":"−2^31 ～ 2^32−1"},"B"),
    ("假设 8 位字长计算机中，带符号整数 x、y 的补码分别为 `[x]补=A3H`、`[y]补=75H`，通过补码加减运算器得到 x−y 的值及 OF 标志分别为：",{"A":"24，0","B":"24，1","C":"46，0","D":"46，1"},"D"),
])
def test_bounded_cs_entire_statement_unique_key(stem,options,answer):
    q=SimpleNamespace(stem=stem,options=options,correct_answer=answer,question_type="single_choice")
    result=verify_problem(q)
    assert result["status"]=="PASS" and result["matching_options"]==[answer]
    q.correct_answer=next(k for k in options if k!=answer)
    assert verify_problem(q)["status"]=="FAIL"
    q.stem += "另要求说明其他情形。"
    assert verify_problem(q)["status"]=="NOT_APPLICABLE"


def test_ieee_multiple_nonbinary_values_fail_not_select_first():
    q=SimpleNamespace(stem="下列数中不能由IEEE754二进制浮点格式精确表示的是？",question_type="single_choice",
        options={"A":"1.2","B":"1.3","C":"2","D":"3"},correct_answer="A")
    assert verify_problem(q)["reason"]=="non_unique_correct_option"


@pytest.mark.parametrize("stem,answer",[
    (r"已知 $f(x)=x^2(e^x-1)$，求 $f^{(5)}(1)$。",r"$31e$"),
    (r"$f(x,y)$ 可微，且 $df(0,0)=\pi dx+3dy,g(x)=f(\ln x,\sin \pi x)$，计算 $g'(1)=\underline{\quad\quad\quad\quad}$.",r"$-2\pi$"),
    (r"设 $\int_1^{+\infty}\frac{a}{x(2x+a)}\,dx=\ln2$，则 $a=$____。","2"),
])
def test_bounded_math_derived_from_statement_not_question_id(stem,answer):
    q=SimpleNamespace(stem=stem,correct_answer=answer,question_type="fill_blank",options=None)
    assert verify_problem(q)["status"]=="PASS"
    q.correct_answer="0"
    assert verify_problem(q)["status"]=="FAIL"
    q.stem += "再求其他参数。"
    assert verify_problem(q)["status"]=="NOT_APPLICABLE"


def test_ieee_precision_outside_bound_is_unknown():
    q=SimpleNamespace(stem="下列数中不能由IEEE754二进制浮点格式精确表示的是？",question_type="single_choice",
        options={"A":"1.2","B":"x","C":"2","D":"3"},correct_answer="A")
    assert verify_problem(q)["status"]=="UNKNOWN"


def test_isolation_rejects_development_or_remote_target_before_connecting():
    for url in ("postgresql+psycopg://u:p@127.0.0.1/kaoyan", "postgresql+psycopg://u:p@remote/kaoyan_test"):
        with pytest.raises(ValueError,match="local _test"):
            with isolated_factory(url): pass


def test_pilot_deterministic_retains_risks_and_process_candidates():
    rows=[]
    for i in range(40):
        rows.append({"question_id":str(i),"subject":"408" if i%2 else "考研数学",
            "category":"ABCD"[i%4],"automatic_answer_proof_available":i<4,
            "pack_link":{"usable":True},"production_eligibility":{"practice_eligible":False}})
    a=choose_pilot({"questions":rows}); b=choose_pilot({"questions":deepcopy(rows)})
    assert a==b and len(a)==30 and {r["category"] for r in a}==set("ABCD")
    assert {r["subject"] for r in a}=={"408","考研数学"}


def test_subject_aliases_cannot_hide_duplicate_exam_identity():
    rows=[SimpleNamespace(grading_config={"provenance":{"source":{"subject":s,"year":2020,"question_number":1}}}) for s in ("数学二","math2")]
    assert identity_counts(rows)[("math2",2020,1)]==2


def test_changed_frozen_bundle_rejected_before_database_connection(tmp_path,monkeypatch):
    from argparse import Namespace
    import scripts.run_question_repair_pilot as cli
    from backend.services.golden_learning_slice import digest
    monkeypatch.setattr(cli,"safe_output",lambda path:path)
    folder=tmp_path/"source"; folder.mkdir()
    (folder/"report.json").write_text(json.dumps({"inventory_snapshot_sha256":digest({"questions":[]})}),encoding="utf-8")
    (folder/"inventory-snapshot.json").write_text(json.dumps({"questions":["tampered TEST_FIXTURE"]}),encoding="utf-8")
    with pytest.raises(ValueError,match="snapshot hash mismatch"):
        cli.run(Namespace(output_dir=tmp_path/"output",diagnosis=folder,question_id=None))
    assert not (tmp_path/"output").exists()
