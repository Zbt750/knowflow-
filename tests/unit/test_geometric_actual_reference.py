"""Actual saved sample; deterministic checks do not certify arbitrary AI questions."""
from fractions import Fraction
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from backend.services.personal_question_general import GeneralOutput, assess_general_output


def test_actual_saved_geometric_answer_and_reference_only_admission():
    sample=json.loads(Path('tests/fixtures/geometric_actual_reference_20261024.json').read_text(encoding='utf-8'))
    # Independently derive the mathematical conclusion, not the model's self-check.
    assert Fraction(1,2)/(1-Fraction(1,2))==1
    assert Fraction(3,2)>1
    assert Fraction(3,2)**100>1  # terms cannot approach zero
    assert sample['correct_answer']=='B'
    output=GeneralOutput.model_validate({**{k:sample[k] for k in ('stem','options','correct_answer','explanation','final_value')},
        'question_type':'single_choice','steps':[]})
    node=SimpleNamespace(id=UUID('32a29e1e-8ae3-41fc-9322-43f727596819'),code=sample['node_code'],
        name='等比级数的敛散性与求和',subject='考研数学',is_active=True,is_assessable=True)
    result=assess_general_output(output,node,request_id='offline-regression-actual-geometric-20261024',
        trace={'mode':'offline_actual_saved_sample'},difficulty='basic')
    assert result['status']=='REFERENCE_SAVED'
    question=result['question']
    assert question.bank_scope=='personal' and question.grading_mode=='self_assessed'
    assert question.grading_config['verified'] is False
    assert question.grading_config['generation']['answer_independently_verified'] is False
    assert question.grading_config['generation']['review_status']=='STRUCTURE_CHECKED_REFERENCE_ONLY'
