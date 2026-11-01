from copy import deepcopy
import json
from pathlib import Path
import pytest
from backend.services.generation_formula_consistency import (
    bounded_calculus_check, power_series_conflict,
    selected_option_conflicts_nonfinite_final,
)
from backend.services.personal_question_general import GeneralOutput

BAD_STEM = r'求极限 $\lim_{x\to0}\frac{e^x-1-x-\frac{x^2}{2}}{x-\ln(1+x)}$。'
GOOD_STEM = r'求极限 $\lim_{x\to0}\frac{e^x-1-x}{x^2}$。'

def output(stem=GOOD_STEM, value='1/2'):
    return dict(stem=stem,question_type='calculation',options=None,correct_answer=value,final_value=value,
                explanation='利用泰勒展开并消去相同阶的小量，原极限为 $'+value+'$。',steps=[])

@pytest.mark.parametrize('stem,expected',[(GOOD_STEM,'1/2'),
    (r'求 $\lim_{x\to0}\frac{\sin x}{x}$。','1'),
    (r'已知 $f(x)=3*x^2+2*x$，求 f\x27(0)。'.replace(r'\x27',"'"),'2'),
    (r'求 $\int_0^1 x^2 dx$。','1/3')])
def test_supported_fragment_does_not_claim_whole_question_proof(stem,expected):
    result=bounded_calculus_check(stem,expected,expected,'完整解析仅作参考。')
    assert result['status']=='CONSISTENT_FRAGMENT',result
    assert result['expected']==expected and result['whole_question_verified'] is False

@pytest.mark.parametrize('value',['1','1/2','2','3'])
def test_consistently_wrong_answer_fields_still_rejected_from_stem(value):
    with pytest.raises(ValueError,match='statement_answer_conflict'):
        GeneralOutput.model_validate(output(BAD_STEM,value))

def test_all_numeric_options_missing_true_answer():
    value=output(BAD_STEM,'1');value.update(question_type='single_choice',options=dict(A='1',B='2',C='3',D='1/2'),correct_answer='A')
    with pytest.raises(ValueError,match='options_missing_mathematical_answer'):
        GeneralOutput.model_validate(value)

def test_supported_choice_requires_one_unique_option_and_the_selected_label():
    options={'A':'0','B':'1','C':'2','D':'3'}
    checked=bounded_calculus_check(BAD_STEM,'0','0','原极限为 $0$。',options,selected_option='A')
    assert checked['status']=='CONSISTENT_FRAGMENT'
    assert checked['option_check']=={'status':'PASS','matching_option':'A'}
    wrong_label=bounded_calculus_check(BAD_STEM,'1','1','原极限为 $1$。',options,selected_option='B')
    assert wrong_label['status']=='CONFLICT'
    assert wrong_label['issue']=='selected_option_conflicts_with_mathematical_answer'
    duplicate_value=bounded_calculus_check(BAD_STEM,'0','0','原极限为 $0$。',
        {'A':'0','B':'0.0','C':'1','D':'2'},selected_option='A')
    assert duplicate_value['status']=='CONFLICT'
    assert duplicate_value['issue']=='multiple_options_match_mathematical_answer'

def test_unparseable_choice_set_is_unknown_not_consistent_or_trusted():
    options={'A':'0','B':'1','C':'2','D':'无法确定'}
    checked=bounded_calculus_check(BAD_STEM,'0','0','原极限为 $0$。',options,selected_option='A')
    assert checked['status']=='UNKNOWN'
    assert checked['reason']=='option_outside_bounded_constant_scope'
    assert checked['whole_question_verified'] is False
    candidate=output(BAD_STEM,'0')
    candidate.update(question_type='single_choice',options=options,correct_answer='A')
    parsed=GeneralOutput.model_validate(candidate)
    assert parsed.correct_answer=='A'  # structurally usable only; admission stays reference-only

def test_original_m02_choice_failure_cannot_be_marked_consistent():
    options={'A':'1','B':'2','C':'3','D':'1/2'}
    checked=bounded_calculus_check(BAD_STEM,'1','1/2','答案选 A，最终结果为 $1/2$。',
        options,selected_option='A')
    assert checked['status']=='CONFLICT'


def test_real_deepseek_finite_choice_conflicting_with_divergent_limit_is_rejected():
    # Exact contradiction class from the 2026-10-24 real generation response:
    # the explanation/final_value conclude divergence, but correct_answer=A
    # selects the finite value 1/2. This is a contradiction check, not a proof
    # that the model's limit derivation is itself correct.
    options = {
        'A': r'\(\dfrac12\)', 'B': r'\(1\)',
        'C': r'\(\dfrac13\)', 'D': r'\(\dfrac23\)',
    }
    final_value = '按所给条件计算，原极限不存在（发散）；题设不足以得到一个有限值，故无正确选项。'
    assert selected_option_conflicts_nonfinite_final(options['A'], final_value)
    candidate = output(GOOD_STEM, '1/2')
    candidate.update(question_type='single_choice', options=options, correct_answer='A', final_value=final_value)
    with pytest.raises(ValueError, match='selected_option_conflicts_with_nonfinite_final_value'):
        GeneralOutput.model_validate(candidate)


def test_nonfinite_guard_does_not_reject_negative_or_non_numeric_option_claims():
    assert not selected_option_conflicts_nonfinite_final('1/2', '该极限不发散，存在有限值。')
    assert not selected_option_conflicts_nonfinite_final('不存在', '原极限不存在（发散）。')

def test_correct_candidate_not_rejected_and_explanation_contradiction_rejected():
    assert GeneralOutput.model_validate(output(BAD_STEM,'0')).final_value=='0'
    value=output(BAD_STEM,'0');value['explanation']='用泰勒法计算，原极限为 $1$。与答案矛盾。'
    with pytest.raises(ValueError,match='statement_explanation_conclusion_conflict'):
        GeneralOutput.model_validate(value)

@pytest.mark.parametrize('stem',[r'证明任意满足条件的函数都收敛。',
    r'求 $\lim_{x\to0}\exp(1/x)$。', r'求 $\lim_{x\to0}\sqrt{x}$。',
    r'求 $\lim_{x\to1}\frac{\ln x}{x-1}$。',
    r'求 $\lim_{x\to0}__import__("os")$。'])
def test_unsupported_remains_unknown(stem):
    assert bounded_calculus_check(stem,'1','1','没有独立验证。')['status']=='UNKNOWN'

def test_original_real_failure_replay_is_immutable_and_rejected():
    source=Path('storage/quality-audits/naiwa-real-retest-20261020-budget7/provider-ledger.json')
    ledger=json.loads(source.read_text(encoding='utf-8'))
    record=next(r for r in ledger['requests'] if r['case_id']=='GENERATE')
    from backend.services.question_generation import parse_generated_output, GeneratedFormatError
    with pytest.raises((ValueError,GeneratedFormatError)):
        parse_generated_output(json.loads(record['response_text'])['choices'][0]['message']['content'],compatibility=True,model_class=GeneralOutput)
    assert json.loads(source.read_text(encoding='utf-8'))==ledger

@pytest.mark.parametrize('domain,conflict',[
    ('[-1,1)',False),  # sum x^n/n converges at -1 but not at 1
    ('(-1,1)',True),
    ('[-1,1]',True),
    ('(-1,1]',True),
])
def test_power_series_laurent_family_checks_each_unit_endpoint(domain,conflict):
    stem=r'设幂级数 $S(x)=\sum_{n=1}^{\infty}\frac{1}{n}x^{n}$，求收敛域与和函数。'
    correct=r'$S(x)=-\ln(1-x)$'
    result=power_series_conflict(stem,correct,correct,f'收敛域为 ${domain}$。')
    assert result is conflict

def test_power_series_polynomial_coefficients_exclude_both_unit_endpoints():
    stem=r'设 $S(x)=\sum_{n=1}^{\infty}(n+\frac{1}{n})x^{n}$，求收敛域与和函数。'
    correct=r'$S(x)=\frac{x}{(1-x)^2}-\ln(1-x)$'
    assert not power_series_conflict(stem,correct,correct,'收敛域为 $(-1,1)$。')
    assert power_series_conflict(stem,correct,correct,'收敛域为 $[-1,1)$。')

def test_power_series_accepts_bounded_tex_single_token_fraction_shorthand():
    stem=r'设 $S(x)=\sum_{n=1}^{\infty}\frac1n x^{n}$，求收敛域与和函数。'
    correct=r'$S(x)=-\ln(1-x)$'
    assert not power_series_conflict(stem,correct,correct,'收敛域为 $[-1,1)$。')
    assert power_series_conflict(stem,correct,correct,'收敛域为 $(-1,1)$。')
