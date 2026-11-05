"""Regressions from actual DeepSeek/browser evidence, 2026-10-19."""
from pathlib import Path
import json
import pytest
from backend.services.assistant_router import post_graduation_review_query
from backend.services.generation_formula_consistency import answer_formula_conflict
from backend.services.personal_question_general import GeneralOutput


@pytest.mark.parametrize('text',[
    '我最近在复习高等数学的幂级数，但是总是容易把求导和积分弄混，你能给我讲清楚吗？',
    '为什么复习幂级数时要先求导？','我最近想巩固积分，你能举个例子吗？'])
def test_concept_help_is_not_post_graduation_status(text):
    assert not post_graduation_review_query(text)


@pytest.mark.parametrize('text',['已毕业的节点为什么提示复习？','哪些知识点需要复习？','查询毕业后复习状态',
    '我的行列式节点已经毕业了吗？之后复习做错会不会把原来的毕业取消？'])
def test_explicit_review_status_remains_supported(text):
    assert post_graduation_review_query(text)


def test_real_deepseek_inconsistent_answer_is_rejected():
    evidence=Path(__file__).parent/'fixtures/deepseek_series_conflict_20261019.json'
    output=json.loads(evidence.read_text(encoding='utf-8'))
    # Production parses the difficulty sidecar before GeneralOutput validation.
    output.pop('difficulty_assessment',None)
    with pytest.raises(ValueError,match='answer_final_value_conflict'):
        GeneralOutput.model_validate(output)


def test_symbolic_counterexample_only_rejects_proven_conflict():
    assert answer_formula_conflict(r'$S(x)=\frac{x}{(1-x)^2}$',r'$S(x)=\frac{x(1+x)}{(1-x)^3}$')
    assert not answer_formula_conflict(r'$S(x)=\frac{x}{(1-x)^2}$',r'$S(x)=\frac{x}{(1-x)^2}$')
    assert not answer_formula_conflict('分段函数，需要另作证明','无法可靠识别')
    assert not answer_formula_conflict('$S(x)=__import__("os")$','$S(x)=1$')


def test_same_wrong_answers_are_checked_against_series_statement_and_domain():
    from backend.services.generation_formula_consistency import power_series_conflict
    stem=r'设 $S(x)=\sum_{n=1}^{\infty}\frac{n^2+1}{n}x^{n}$，求收敛域与和函数。'
    wrong=r'$S(x)=\frac{x(1+x)}{(1-x)^3}-\ln(1-x)$'
    right=r'$S(x)=\frac{x}{(1-x)^2}-\ln(1-x)$'
    assert power_series_conflict(stem,wrong,wrong,'收敛域为 $(-1,1)$。')
    assert power_series_conflict(stem,right,right,'收敛域为 $[-1,1)$。')
    assert not power_series_conflict(stem,right,right,'收敛域为 $(-1,1)$。')
    assert not power_series_conflict('证明一个一般定理',wrong,wrong,'未知')
    assert not power_series_conflict(r'$\sum_{n=1}^{\infty}((n^6)^6)^6x^n$',wrong,wrong,'未知')
    # 第10次真实响应：两个错误答案相同，但题干要求 1+2/n。
    shifted=r'设幂级数 $\displaystyle\sum_{n=1}^{\infty}\frac{n+2}{n}\,x^{n}$。'
    bad=r'$S(x)=\frac{2x-x^2}{(1-x)^2}$'
    assert power_series_conflict(shifted,bad,bad,'收敛域为 $(-1,1)$')


def test_concept_explanation_preserves_output_without_changing_other_providers():
    from types import SimpleNamespace
    from backend.chat.service import Provider,_provider_for_answer
    provider=Provider(api_key='test',base_url='https://api.deepseek.com',model='deepseek-flash',timeout=1,max_tokens=4000)
    prepared=SimpleNamespace(retrieval_mode='general',generation_profile='normal',prompt=[{'role':'user','content':'我最近复习幂级数，总把求导和积分弄混，给我讲清楚吗？'}])
    scoped=_provider_for_answer(provider,prepared)
    assert scoped is not provider and scoped.max_tokens==4000
    assert scoped._request_options()=={'thinking':{'type':'disabled'}}
    assert provider._request_options()=={'reasoning_effort':'low'}
    prepared.prompt=[{'role':'user','content':'求极限，请讲解这道题'}]
    assert _provider_for_answer(provider,prepared) is provider


def test_real_http_deferred_provider_does_not_bypass_answer_policy(monkeypatch):
    from types import SimpleNamespace
    from backend.api.routes import chat
    from backend.chat.service import Provider,_provider_for_answer
    provider=Provider(api_key='test',base_url='https://api.deepseek.com',model='deepseek-flash',timeout=1,max_tokens=4000)
    monkeypatch.setattr(chat,'provider_from_settings',lambda settings:provider)
    deferred=chat._DeferredProvider(SimpleNamespace())
    assert deferred.resolved is None
    prepared=SimpleNamespace(retrieval_mode='general',generation_profile='normal',prompt=[{'role':'user','content':'我最近复习幂级数，总把求导和积分弄混，给我讲清楚吗？'}])
    scoped=_provider_for_answer(deferred,prepared)
    assert scoped._request_options()=={'thinking':{'type':'disabled'}}
    assert scoped.max_tokens==provider.max_tokens==4000
    prepared.retrieval_mode='hybrid'
    assert _provider_for_answer(provider,prepared) is provider


@pytest.mark.parametrize('followup',[
    '我还是不懂，能不能换一种方式讲',
    '换个角度解释一下，刚才的概念我没明白',
    '能不能换一种说法讲？',
    '那为什么有些极限不能直接用？',
    '你给我举一个容易用错的例子。',
    '洛必达法则什么时候可以用？',
])
def test_concept_followup_preserves_body_budget(followup):
    from types import SimpleNamespace
    from backend.chat.service import Provider,_provider_for_answer
    provider=Provider(api_key='test',base_url='https://api.deepseek.com',model='deepseek-flash',timeout=1,max_tokens=4000)
    prepared=SimpleNamespace(retrieval_mode='general',generation_profile='normal',prompt=[
        {'role':'user','content':'给我讲清楚幂级数求导和积分的区别'},
        {'role':'assistant','content':'下面从几何级数举例。'},
        {'role':'user','content':followup}])
    scoped=_provider_for_answer(provider,prepared)
    assert scoped._request_options()=={'thinking':{'type':'disabled'}}
    assert scoped.max_tokens==provider.max_tokens==4000


def test_followup_does_not_disable_thinking_for_prior_complex_problem():
    from types import SimpleNamespace
    from backend.chat.service import Provider,_provider_for_answer
    provider=Provider(api_key='test',base_url='https://api.deepseek.com',model='deepseek-flash',timeout=1,max_tokens=4000)
    prepared=SimpleNamespace(retrieval_mode='general',generation_profile='normal',prompt=[
        {'role':'user','content':'证明这个函数级数逐项求导后仍一致收敛'},
        {'role':'user','content':'我还是不懂，能不能换一种方式讲'}])
    assert _provider_for_answer(provider,prepared) is provider


def test_lhopital_simplified_followup_keeps_both_indeterminate_forms_and_conditions():
    from types import SimpleNamespace
    from backend.chat.service import _general_prompt, _answer_style_instruction
    history = [
        SimpleNamespace(role="user", content="洛必达法则什么时候可以用？", status="completed"),
        SimpleNamespace(role="assistant", content="要检查未定式和可导条件。", status="completed"),
    ]
    prompt = _general_prompt("我还是不太懂，换一种简单方式讲。", history)
    system = prompt[0]["content"]
    assert "0/0或∞/∞" in system
    assert "去心邻域内分子、分母可导" in system
    assert "分母导数不为0" in system
    assert "导数之比的极限存在" in system
    assert "不能据此断言原极限不存在" in system
    assert "通常控制在3至6个短句" in _answer_style_instruction("换一种简单方式讲")
    assert prompt[-1] == {"role": "user", "content": "我还是不太懂，换一种简单方式讲。"}


def test_latex_parenthesis_and_display_delimiters_do_not_hide_conflicts():
    from backend.services.generation_formula_consistency import power_series_conflict
    left=r'\(S(x)=\frac{x}{(1-x)^2}\)'
    right=r'\[S(x)=\frac{x(1+x)}{(1-x)^3}\]'
    assert answer_formula_conflict(left,right)
    stem=r'设 \(S(x)=\sum_{n=1}^{\infty}nx^n\)，求收敛域与和函数。'
    assert power_series_conflict(stem,right,right,r'收敛域为 \([-1,1)\)。')
    assert not power_series_conflict(stem,left,left,r'收敛域为 \((-1,1)\)。')


def test_integrated_series_is_not_misread_as_the_original_sum():
    from backend.services.generation_formula_consistency import power_series_conflict
    stem=r'将 $\sum_{n=1}^{\infty}x^n$ 从0到x逐项积分，记积分结果为S(x)。'
    answer=r'$S(x)=-x-\ln(1-x)$'
    # 本求和反证器不支持这个积分任务，应保留未知，而不是错误拒绝。
    assert not power_series_conflict(stem,answer,answer,'只在开区间讨论。')


def test_real_deepseek_product_integral_limit_conflict_is_detected_but_unknown_is_not_certified():
    from backend.services.generation_formula_consistency import product_integral_limit_conflict
    stem = r"设 $f(x)$ 在 $x=0$ 的某邻域内二阶可导，且 $f(0)=0$，$f'(0)=1$，$f''(0)=2$。求极限 $\lim_{x\to 0}\dfrac{x f(x)-\int_0^x f(t)\,dt}{x^3}$ 的值。"
    assert product_integral_limit_conflict(stem, r"$\dfrac{2}{3}$")
    assert not product_integral_limit_conflict(stem, "不存在")
    unsupported = r"$\lim_{x\to0}\dfrac{x f(x)-\int_0^x f(t)dt}{x^4}$"
    assert not product_integral_limit_conflict(unsupported, r"$\dfrac{2}{3}$")
