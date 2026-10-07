"""专题匹配与历史错配回归；结构检查不等于独立教学审核。"""
from scripts.lesson_content_catalog import TOPICS, topic_for
from backend.services.lesson_service import read_lesson


def test_aliases_are_unique_and_explicit():
    names = [name for topic in TOPICS for name in topic.names]
    assert len(names) == len(set(names))
    assert topic_for("一个尚未编写的排序专题") is None
    for topic in TOPICS:
        for name in topic.names:
            assert topic_for(name) is topic
        for section in ("概念", "例题", "易错"):
            assert section in topic.body
        assert "## 二、" in topic.body  # 定理适用条件或算法的分析/执行方法。


def test_improper_integral_no_longer_uses_series_example():
    text = read_lesson("math.exam.fd2f9e3739d9")
    assert text is not None
    assert "knowledge-lesson-quality:subject-textbook-draft-v3" in text
    assert "p>" in text or "p >" in text
    assert "主值" in text
    assert "无穷级数研究部分和" not in text


def test_shell_sort_has_increment_example_not_binary_search():
    text = read_lesson("cs408.ds.topic.1408569fd510")
    assert text is not None
    assert "希尔排序" in text and "不稳定" in text
    assert "9" in text and "增量" in text
    assert "二分查找" not in text


def test_remaining_generated_summaries_are_not_claimed_complete():
    from scripts.generate_knowledge_lessons import _all_nodes, LESSON_DIR
    for node in _all_nodes()[0]:
        text = (LESSON_DIR / f"{node['code']}.md").read_text(encoding="utf-8")
        if text.startswith("<!-- knowledge-node-lesson:v1;"):
            assert "章节背景摘要，非完整专题讲解" in text


def test_baseline_does_not_allow_overwriting_later_edits(tmp_path):
    import hashlib
    from scripts.generate_knowledge_lessons import matches_baseline
    path = tmp_path / "topic.md"
    path.write_text("已检查的生成正文", encoding="utf-8")
    baseline = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()}
    assert matches_baseline(path, baseline)
    path.write_text("用户后来补写的正文", encoding="utf-8")
    assert not matches_baseline(path, baseline)
    assert not matches_baseline(path, {})


def test_new_lessons_are_specific_and_still_drafts():
    for name in ("快速排序", "归并排序", "堆排序", "含参积分求导", "二次型"):
        topic = topic_for(name)
        assert topic is not None
        assert "## 三、例题与完整过程" in topic.body
    assert "Lomuto" in topic_for("快速排序").body
    assert "顺序主子式非负" in topic_for("二次型").body
    assert "a²+2a" in topic_for("含参积分求导").body


def test_authored_math_example_values():
    from fractions import Fraction as F
    # 旋转体体积系数；矩阵逆与矩阵幂例题独立算术复核。
    assert F(1, 3) - F(1, 5) == F(2, 15)
    a = ((F(1), F(2)), (F(0), F(3)))
    inv = ((F(1), F(-2, 3)), (F(0), F(1, 3)))
    product = tuple(tuple(sum(a[i][k] * inv[k][j] for k in range(2)) for j in range(2)) for i in range(2))
    assert product == ((1, 0), (0, 1))
    square = tuple(tuple(sum(a[i][k] * a[k][j] for k in range(2)) for j in range(2)) for i in range(2))
    assert square == ((1, 3**2 - 1), (0, 3**2))
