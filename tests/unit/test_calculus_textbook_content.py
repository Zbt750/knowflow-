"""高数批次结构与独立算术检查；不声称替代人工教材审核。"""
import pytest
import sympy as s

from scripts.calculus_textbook_content import calculus_nodes, render_pages, QUALITY_MARKER
from scripts.generate_knowledge_lessons import LESSON_DIR, _ensure_sections


def test_exact_subject_coverage_and_published_content():
    nodes = calculus_nodes()
    assert len(nodes) == 75
    parents = {node.get('parent_code') for node in nodes}
    assert sum(node['code'] in parents for node in nodes) == 8
    pages = render_pages()
    for name, expected in pages.items():
        assert (LESSON_DIR / name).read_text(encoding='utf-8') == expected
        assert QUALITY_MARKER in expected
        assert '例题' in expected and ('解答' in expected or '贯通' in expected)
        assert '历年真题练习入口' not in expected
        assert '章节背景摘要，非完整专题讲解' not in expected
        assert len(expected) >= 500
    assert len(set(pages.values())) == 75


def test_generator_preserves_textbook_without_references(tmp_path):
    text = next(iter(render_pages().values()))
    path = tmp_path / 'lesson.md'
    path.write_text(text, encoding='utf-8')
    assert not _ensure_sections(path, {}, [{'year': 2025}], {}, [])
    assert path.read_text(encoding='utf-8') == text


x, y = s.symbols('x y', real=True)

@pytest.mark.parametrize('actual, expected', [
    (s.limit((s.sqrt(1+x)-1)/x, x, 0), s.Rational(1,2)),
    (s.limit((s.tan(x)-x)/x**3, x, 0), s.Rational(1,3)),
    (s.limit((s.asin(x)-s.atan(x))/x**3, x, 0), s.Rational(1,2)),
    (s.integrate(x*s.exp(x**2), (x,0,1)), (s.E-1)/2),
    (s.integrate(x*s.exp(x), (x,0,1)), 1),
    (s.integrate(x-x**2, (x,0,1)), s.Rational(1,6)),
    (s.integrate(x**2-x**4, (x,0,1)), s.Rational(2,15)),
    (s.integrate(x**2, (x,0,2))/2, s.Rational(4,3)),
    (s.integrate(s.integrate(x+y, (y,0,x)), (x,0,1)), s.Rational(1,2)),
    (s.integrate(s.integrate(x+2*y,(y,0,1)), (x,0,2)), 4),
    (s.integrate(s.integrate(x,(y,0,x)), (x,0,1)), s.Rational(1,3)),
    (s.integrate(s.integrate(y,(y,0,x)), (x,0,1)), s.Rational(1,6)),
    (s.diff((1-x)*s.exp(x),x,2)-2*s.diff((1-x)*s.exp(x),x)+(1-x)*s.exp(x), 0),
    (s.diff(x*s.exp(x)/2,x,2)-x*s.exp(x)/2, s.exp(x)),
    (s.diff(-s.log(1-x),x,2)-s.diff(-s.log(1-x),x)**2, 0),
    (s.det(s.Matrix([[2,2],[2,6]])),8),
])
def test_worked_example_values_and_ode_substitution(actual, expected):
    assert s.simplify(actual-expected) == 0
