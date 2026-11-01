"""TEST_FIXTURE supply combinations, never actual learner receipts."""
from types import SimpleNamespace
from uuid import uuid4
from backend.mastery.policy import MasteryPolicy
from backend.services.public_bank_supply import supply_for_node
import backend.services.public_bank_supply as module

def q(kind='single_choice',origin='real_exam',tags=('skill',),source=1,stem=None):
    return SimpleNamespace(id=uuid4(),bank_scope='public',generation_batch_id=None,is_active=True,is_hidden=False,
        question_type=kind,question_provenance=origin,skill_tags=list(tags),is_variant=False,
        stem=stem or 'TEST_FIXTURE '+str(uuid4()),options=None,
        grading_config={'provenance':{'source':{'subject':'math2','year':2024,'question_number':source}}})
def node():return SimpleNamespace(id=uuid4(),code='TEST_FIXTURE',name='合成节点',subject='math2')
def qualify(monkeypatch):monkeypatch.setattr(module,'question_eligibility',lambda q,n:SimpleNamespace(practice_eligible=True,evidence_capability='verified_objective',blocking_reasons=()))
def test_type_quotas_deduplicate_same_source_but_ignore_origin(monkeypatch):
    qualify(monkeypatch)
    p=MasteryPolicy(policy_version=2,min_confirmations=1,min_real_questions=1,required_variant_count=0,
        required_question_types={'single_choice':1,'fill_blank':1},required_question_origins={'real_exam':1})
    assert supply_for_node([q(source=1),q(kind='fill_blank',source=1)],node(),p)['status']=='INSUFFICIENT'
    practice_a=q(origin='trusted_practice',source=1)
    practice_b=q(kind='fill_blank',origin='trusted_practice',source=2)
    assert supply_for_node([practice_a,practice_b],node(),p)['status']=='CONDITIONAL_FUTURE_SUBMISSIONS'
def test_duplicate_text_source_and_personal_never_inflate(monkeypatch):
    qualify(monkeypatch)
    a=q(source=1,stem='same');b=q(source=2,stem='same');c=q(source=3)
    c.bank_scope='personal'
    p=MasteryPolicy(policy_version=2,min_confirmations=2,min_real_questions=2,required_variant_count=0)
    r=supply_for_node([a,b,c],node(),p)
    assert r['strict_independent_source_groups']==1 and r['status']=='INSUFFICIENT'
def test_skill_and_variant_gaps_are_reported_without_origin_blocker(monkeypatch):
    qualify(monkeypatch)
    p=MasteryPolicy(policy_version=2,required_variant_count=1,required_skill_tags=frozenset({'different'}),required_question_origins={'real_exam':3})
    r=supply_for_node([q(origin='trusted_practice')],node(),p)
    assert 'SKILL_SHORTAGE:different' in r['blocking_reasons']
    assert not any(reason.startswith('ORIGIN_SHORTAGE:') for reason in r['blocking_reasons'])
    assert not r['learner_graduated'] and not r['evidence_written']
