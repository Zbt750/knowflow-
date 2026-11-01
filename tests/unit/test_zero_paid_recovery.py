import pytest
from backend.chat.service import _dedupe_general_prefix
from backend.services.generation_formula_consistency import power_series_conflict,answer_formula_conflict

def test_duplicate_prefix_only_at_start():
    p='## 通用知识参考\n\n以下为模型通用知识回答，本轮未检索系统资料。\n\n'
    assert _dedupe_general_prefix(p+p+'正文')==p+'正文'
    assert _dedupe_general_prefix('```\n'+p+p+'```')=='```\n'+p+p+'```'

def test_bare_final_and_explanation_formula_conflicts():
    stem=r'求 $\sum_{n=1}^{\infty}((n^2+1)/n)x^n$ 的和。'
    right=r'$S(x)=x/(1-x)^2-\ln(1-x)$'
    assert power_series_conflict(stem,right,'x/(1-x)^2',right)
    assert power_series_conflict(stem,right,r'x/(1-x)^2-\ln(1-x)',r'$S(x)=x/(1-x)$')
    assert not power_series_conflict(stem,right,r'x/(1-x)^2-\ln(1-x)',right)
    assert answer_formula_conflict(right,'x/(1-x)^2')
    assert not power_series_conflict('任意积分证明',right,'无法核验','无已解析公式')
