"""Coverage and independent arithmetic checks for the linear-algebra lessons."""
from __future__ import annotations

import sympy as sp

from scripts.generate_knowledge_lessons import LESSON_DIR, _ensure_sections
from scripts.linear_algebra_textbook_content import (
    DETAILS,
    GUIDES,
    QUALITY_MARKER,
    linear_algebra_nodes,
    render_pages,
)


def test_exact_tree_coverage_and_topic_specific_textbook_pages() -> None:
    nodes = linear_algebra_nodes()
    pages = render_pages()
    assert len(nodes) == 27
    assert len(pages) == len(nodes)
    assert len(set(pages.values())) == len(pages)
    parent_codes = {node.get("parent_code") for node in nodes}
    guide_codes = {node["code"] for node in nodes if node["code"] in parent_codes}
    leaf_codes = {node["code"] for node in nodes} - guide_codes
    assert guide_codes == set(GUIDES)
    assert leaf_codes == set(DETAILS)

    for filename, expected in pages.items():
        actual = (LESSON_DIR / filename).read_text(encoding="utf-8")
        assert actual == expected
        assert QUALITY_MARKER in actual
        assert "例题" in actual and "逐步解答" in actual
        assert "历年真题练习入口" not in actual
        assert "专题汇总：" not in actual
        assert "题库" in actual
        assert len(actual) >= 500


def test_generator_preserves_authored_pages_without_exam_reference_append(tmp_path) -> None:
    lesson = next(iter(render_pages().values()))
    path = tmp_path / "linear-algebra.md"
    path.write_text(lesson, encoding="utf-8")
    assert not _ensure_sections(path, {}, [{"year": 2025}], {}, [])
    assert path.read_text(encoding="utf-8") == lesson


def test_representative_matrix_algebra_is_correct() -> None:
    a = sp.Matrix([[2, 1], [0, 3]])
    p = sp.Matrix([[1, 1], [0, 1]])
    d = sp.diag(2, 3)
    assert p.inv() * a * p == d
    assert p * d**5 * p.inv() == sp.Matrix([[32, 211], [0, 243]])


def test_determinant_and_adjugate_examples_are_correct() -> None:
    a = sp.Matrix([[1, 2, 0], [3, 0, 1], [0, 1, 2]])
    assert a.det() == -13
    b = sp.Matrix([[1, 2], [3, 4]])
    assert b.det() == -2
    assert b.adjugate() / b.det() == b.inv()


def test_linear_system_vector_and_rank_examples_are_correct() -> None:
    a = sp.Matrix([[1, 1, 1], [1, -1, 1]])
    b = sp.Matrix([1, 0])
    system_solution = tuple(next(iter(sp.linsolve((a, b)))))
    assert a * sp.Matrix(system_solution) == b

    vectors = [sp.Matrix([1, 0, 1]), sp.Matrix([0, 1, 1]), sp.Matrix([1, 1, 2])]
    assert vectors[2] == vectors[0] + vectors[1]
    assert sp.Matrix.hstack(*vectors).rank() == 2

    rank_example = sp.Matrix([[1, 2, 3], [2, 4, 6], [1, 1, 1]])
    assert rank_example.rank() == 2


def test_quadratic_form_permutation_and_nilpotent_examples_are_correct() -> None:
    q = sp.Matrix([[2, 2], [2, 5]])
    assert q.det() == 6 and q[:1, :1].det() == 2
    x, y = sp.symbols("x y", real=True)
    assert sp.expand((sp.Matrix([x, y]).T * q * sp.Matrix([x, y]))[0] - (2*x**2 + 4*x*y + 5*y**2)) == 0
    assert sp.expand(2*(x+y)**2 + 3*y**2 - (2*x**2 + 4*x*y + 5*y**2)) == 0

    matrix_a = sp.Matrix([[1, 1], [2, 2]])
    matrix_x = sp.Matrix([[1, 2], [0, 0]])
    matrix_b = sp.Matrix([[1, 2], [2, 4]])
    assert matrix_a * matrix_x == matrix_b

    p = sp.Matrix([[0, 1, 0], [1, 0, 0], [0, 0, 1]])
    assert p**2 == sp.eye(3) and p.det() == -1
    n = sp.Matrix([[0, 1, 0], [0, 0, 1], [0, 0, 0]])
    assert n**3 == sp.zeros(3) and n**2 != sp.zeros(3)
