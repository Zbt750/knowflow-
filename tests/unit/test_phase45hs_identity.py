"""Deterministic identities, never a semantic-search deletion heuristic."""
from uuid import uuid4
from backend.models.learning import Question
from backend.services.question_identity import verified_identity,duplicate_findings,historical_identity
from backend.services.phase45hs_verifiers import exact_number

def integral(upper=2, kind='fill_blank', scope='personal'):
    return Question(id=uuid4(),kp_id=uuid4(),stem=f'计算定积分：∫_0^{upper} x dx = ____。',
        question_type=kind,correct_answer=str(upper*upper//2) if kind=='fill_blank' else 'B',
        options=None if kind=='fill_blank' else {'A':'1','B':'2','C':'3','D':'4'},bank_scope=scope)

def test_cross_format_identity_and_valuable_variant():
    a=integral();b=integral(kind='single_choice');c=integral(4)
    assert verified_identity(a) is not None
    assert verified_identity(a)==verified_identity(b)
    assert verified_identity(a)!=verified_identity(c)
    assert duplicate_findings(a,[b])['matches']
    assert not duplicate_findings(a,[c])['matches']

def test_banks_are_separate_and_hidden_rows_still_block_duplicate():
    a=integral();b=integral(scope='public');c=integral();c.is_hidden=True;c.is_active=False
    assert not duplicate_findings(a,[b])['matches']
    assert duplicate_findings(a,[c])['matches']

def test_same_answer_is_not_identity():
    a=integral();b=integral();b.stem='计算定积分：∫_0^1 4x dx = ____。'
    assert verified_identity(a)!=verified_identity(b)

def test_exam_identity_accepts_computer_408_paper_title_aliases():
    from types import SimpleNamespace
    def source(subject):
        return SimpleNamespace(is_variant=False,grading_config={"provenance":{"source":{
            "source_type":"exam","subject":subject,"year":2026,"question_number":2}}})
    assert historical_identity(source("408")) == ("408",2026,2)
    assert historical_identity(source("计算机学科专业基础（408）")) == ("408",2026,2)

def test_binary_scale_rejects_malformed_and_unbounded_expression():
    assert exact_number('2^(-126)') is not None
    for value in ('2^(-126','2^-126)','2^999','__import__("os")','1/0'):
        assert exact_number(value) is None

def test_review_v5_and_legacy_v4_receipts_remain_content_admission_not_relaxed_graduation():
    from tests.unit.test_policy_origin_semantics import confirmation,check
    def automatic(index,version='public-question-auto-review-v7',**extra):
        return confirmation(index,facts_change={'answer_provenance':'auto_verified','question_content_trust':'auto_verified',
            'answer_verification_event_id':None,'auto_review_event_id':str(uuid4()),'auto_review_version':version,
            'auto_review_snapshot_sha256':'a'*64,**extra})
    assert check([automatic(i) for i in range(3)])==(True,'graduated')
    assert check([automatic(i,version='public-question-auto-review-v5') for i in range(3)])==(True,'graduated')
    assert check([automatic(i,version='public-question-auto-review-v4') for i in range(3)])==(True,'graduated')
    assert check([automatic(0),automatic(1),automatic(2,version='unknown-v99')])==(False,'insufficient_confirmed_evidence')
    assert check([automatic(0),automatic(1),automatic(2,bank_scope='personal')])==(False,'insufficient_confirmed_evidence')
    assert check([automatic(0),automatic(1),automatic(2,assisted=True,assistance_level='solution')])==(False,'insufficient_confirmed_evidence')
    assert check([automatic(0),automatic(1)])==(False,'insufficient_confirmed_evidence')
