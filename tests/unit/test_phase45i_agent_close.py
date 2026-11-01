"""Unseen parameters and counterexamples for C7 lossless parsing and audit."""
import json
from copy import deepcopy
from uuid import uuid4
import pytest
from backend.models.learning import KnowledgePoint
from backend.services.question_generation import C7Output,parse_generated_output,assess_output
from backend.services.quality_verifiers import verify_problem
from backend.services.phase45i_quality_verifiers import verify_narrative_claims
from tests.unit.test_phase45i_quality_verifiers import q


def wire(**changes):
    body=dict(stem='计算定积分：∫_0^1 (6x^2+2) dx = ____。',question_type='fill_blank',options=None,
        correct_answer=4,explanation='原函数为2x^3+2x。上下限代入得到4。',final_value=4,
        steps=[{'expression':'2+2','value':4}])
    body.update(changes);return json.dumps(body,ensure_ascii=False)


def test_lossless_c7_numeric_fields_and_code_fence_do_not_change_content():
    out,changes=parse_generated_output('```json\n'+wire()+'\n```',compatibility=True,model_class=C7Output)
    assert out.correct_answer==out.final_value=='4'
    assert out.stem==json.loads(wire())['stem'] and len(changes)==4
    with pytest.raises(Exception):parse_generated_output(wire(),model_class=C7Output)


@pytest.mark.parametrize('raw',[wire(correct_answer=True),wire()[:-1],wire(options=['4','3','2','1']),
    wire(correct_answer=None),wire(explanation=''),wire(extra='do not silently remove')])
def test_normalization_never_guesses_missing_or_invalid_fields(raw):
    with pytest.raises(Exception):parse_generated_output(raw,compatibility=True,model_class=C7Output)


def test_decimal_conversion_preserves_wire_precision():
    raw=wire().replace('"final_value": 4','"final_value": 0.123456789012345678901')
    out,_=parse_generated_output(raw,compatibility=True,model_class=C7Output)
    assert out.final_value=='0.123456789012345678901'


@pytest.mark.parametrize(('stem','answer'),[
    ("已知函数f(x)=2*x^3-4*x+1，求f'(t)的值，其中t=-3。",'50'),
    ('计算定积分：∫_{-2}^{3} (2*x+3) dx = ______。','20'),
    (r'计算极限：\\lim_{x\\to 0}\\frac{e^{7 x}-1-7 x}{x^2}=____。','49/2')])
def test_new_parameters_and_equivalent_bounded_statement_formats(stem,answer):
    assert verify_problem(q(stem,answer))['status']=='PASS'
    assert verify_problem(q(stem,'999'))['status']=='FAIL'


def test_improper_integral_complete_iff_options_are_exactly_verified():
    stem='关于含参数p的反常积分I(p)=∫_e^{+∞}dx/[x(ln x)^p]，下列结论正确的是（）。'
    options={'A':'当且仅当p>1时收敛','B':'当且仅当p=1时收敛','C':'当且仅当0≤p<1时收敛','D':'仅当p<0时收敛'}
    assert verify_problem(q(stem,'A',kind='single_choice',options=options))['status']=='PASS'
    bad={**options,'B':options['A']}
    assert verify_problem(q(stem,'A',kind='single_choice',options=bad))['status']=='FAIL'
    bad={**options,'B':'当且仅当sin(p)>0时收敛'}
    assert verify_problem(q(stem,'A',kind='single_choice',options=bad))['status']=='UNKNOWN'


def test_correct_final_answer_does_not_justify_wrong_primitive():
    question=q('计算定积分：∫_0^1 (6x^2+2) dx = ____。','4')
    question.explanation='原函数 F(x)=3x^3+2x。代入得到4。'
    assert verify_narrative_claims(question,verify_problem(question))['status']=='FAIL'


@pytest.mark.parametrize(('stem','answer','explanation'),[
    ('计算定积分：∫_0^1 (6x^2+2) dx = ____。','4','原函数为3x^3+2x。最终结果为4。'),
    (r'计算极限：\lim_{x\to 0}\frac{e^{4x}-1-4x}{x^2}=____。','8',r'e^{4x}=1+4x+7x^2+o(x^2)，最后极限为8。'),
    ('一棵完全二叉树共有100个结点，则其叶子结点数为（）。','50','叶子结点数为n+floor(n/2)，结果为50。')])
def test_correct_answers_do_not_hide_wrong_key_reasoning(stem,answer,explanation):
    question=q(stem,answer);question.explanation=explanation
    assert verify_problem(question)['status']=='PASS'
    assert verify_narrative_claims(question,verify_problem(question))['status']=='FAIL'


def test_unsupported_narrative_is_withheld_even_with_correct_answer():
    node=KnowledgePoint(id=uuid4(),code='math.exam.c431f98f817c',name='定积分的计算',subject='考研数学',
        is_active=True,is_assessable=True,is_reference_only=False)
    output=C7Output.model_validate(json.loads(wire(correct_answer='4',final_value='4',steps=[],explanation='凭感觉这个答案应该是四。')))
    result=assess_output(output,node,request_id='TEST_FIXTURE missing reasoning',mode='original',family='power_integral',
        trace={'prompt_version':'question-generation-c7-v1'})
    assert result['status']!='AUTO_PASS' and 'explanation_key_claim_not_independently_verified' in result['uncertainties']


def test_unverified_final_conflict_is_not_confirmed_model_error():
    node=KnowledgePoint(id=uuid4(),code='math.exam.fd2f9e3739d9',name='反常积分的计算与敛散性',
        subject='考研数学',is_active=True,is_assessable=True,is_reference_only=False)
    out=C7Output(stem='某未知条件的反常积分判断，选择正确结论。',question_type='single_choice',
        options={'A':'p>1','B':'p≤1','C':'p=1','D':'p<0'},correct_answer='A',
        final_value='B',explanation='当前条件不足以独立验证，保留待审阅。')
    result=assess_output(out,node,request_id='TEST_FIXTURE unknown',mode='original',family='improper_integral_parameter')
    assert result['review_status']!='CONFIRMED_WRONG' and result['status']!='AUTO_PASS'
