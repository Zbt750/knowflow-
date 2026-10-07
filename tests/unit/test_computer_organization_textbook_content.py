"""Coverage and numerical checks for 408 computer-organization lessons."""
from __future__ import annotations

from scripts.computer_organization_textbook_content import (
    DETAILS,
    QUALITY_MARKER,
    computer_organization_nodes,
    render_pages,
)
from scripts.generate_knowledge_lessons import LESSON_DIR, _ensure_sections


def test_exact_tree_coverage_and_every_topic_has_a_specific_worked_example() -> None:
    nodes = computer_organization_nodes()
    pages = render_pages()
    assert len(nodes) == len(pages) == 32
    topic_names = {node["name"] for node in nodes if node["code"] != "cs408.co"}
    assert topic_names == set(DETAILS)
    assert len(set(pages.values())) == len(pages)
    for filename, expected in pages.items():
        actual = (LESSON_DIR / filename).read_text(encoding="utf-8")
        assert actual == expected
        assert QUALITY_MARKER in actual
        assert "例题" in actual and "分析与逐步解答" in actual
        assert "专题汇总：" not in actual
        assert "题库" in actual
        assert len(actual) >= 600


def test_generator_preserves_authored_lesson_without_appending_exam_index(tmp_path) -> None:
    lesson = next(iter(render_pages().values()))
    path = tmp_path / "computer-organization.md"
    path.write_text(lesson, encoding="utf-8")
    assert not _ensure_sections(path, {}, [{"year": 2025}], {}, [])
    assert path.read_text(encoding="utf-8") == lesson


def test_numeric_examples_and_address_field_decomposition() -> None:
    # Signed 8-bit overflow example: 100 + 40 wraps to -116.
    wrapped = (100 + 40) & 0xFF
    signed = wrapped - 0x100 if wrapped & 0x80 else wrapped
    assert wrapped == 0b10001100 and signed == -116
    assert not (-128 <= 100 + 40 <= 127)

    # Single precision fields for 5.5: sign 0, biased exponent 129, fraction 011... .
    assert 2 + 127 == 129
    assert f"{129:08b}" == "10000001"
    assert "011" + "0" * 20 == "01100000000000000000000"

    # 16-bit byte address / 1 KiB direct-mapped cache / 16-byte block.
    offset_bits = 16 .bit_length() - 1
    line_count = 1024 // 16
    index_bits = line_count.bit_length() - 1
    assert (offset_bits, index_bits, 16 - offset_bits - index_bits) == (4, 6, 6)

    # 4 KiB paging preserves the low 12-bit offset.
    virtual = 0x12345
    physical = (0x2A << 12) | (virtual & 0xFFF)
    assert physical == 0x2A345


def test_performance_dma_and_multiprocessor_examples() -> None:
    old_time = 2_000_000_000 * 1.5 / 3_000_000_000
    new_time = 2_000_000_000 * 1.2 / 3_000_000_000
    assert old_time == 1 and new_time == 0.8
    assert round(old_time / new_time, 2) == 1.25
    assert 4096 // 4 == 1024
    assert 7200 and abs((60 / 7200 * 1000) / 2 - 4.1666666667) < 1e-8
