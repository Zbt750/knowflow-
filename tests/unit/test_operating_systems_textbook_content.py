"""Coverage and hand-checkable examples for 408 operating-systems lessons."""
from __future__ import annotations

from collections import deque

from scripts.operating_systems_textbook_content import (
    DETAILS,
    QUALITY_MARKER,
    UNVERIFIED_NAME,
    operating_system_nodes,
    render_pages,
)
from scripts.generate_knowledge_lessons import LESSON_DIR, _ensure_sections


def test_exact_tree_coverage_and_topic_specific_examples() -> None:
    nodes = operating_system_nodes()
    pages = render_pages()
    assert len(nodes) == len(pages) == 42
    topic_nodes = [node for node in nodes if node["code"] != "cs408.os"]
    assert {node["name"] for node in topic_nodes} == set(DETAILS) | {UNVERIFIED_NAME}
    placeholder = next(node for node in topic_nodes if node["name"] == UNVERIFIED_NAME)
    assert placeholder["is_reference_only"] is True
    assert len(set(pages.values())) == len(pages)
    for filename, expected in pages.items():
        actual = (LESSON_DIR / filename).read_text(encoding="utf-8")
        assert actual == expected
        assert QUALITY_MARKER in actual
        assert "题库" in actual
        if filename.endswith("28afec2a802b.md"):
            assert "不是概念教材页" in actual
            assert "不虚构知识内容" in actual
        elif filename != "cs408.os.md":
            assert "例题" in actual and "分析与逐步解答" in actual
            assert len(actual) >= 600


def test_generator_preserves_authored_lesson_without_exam_reference_append(tmp_path) -> None:
    lesson = next(iter(render_pages().values()))
    path = tmp_path / "operating-systems.md"
    path.write_text(lesson, encoding="utf-8")
    assert not _ensure_sections(path, {}, [{"year": 2025}], {}, [])
    assert path.read_text(encoding="utf-8") == lesson


def test_scheduling_worked_examples() -> None:
    # Non-preemptive FCFS: A(0,5), B(2,2).
    fcfs = {"A": (5, 0), "B": (7, 3)}  # completion, waiting
    assert fcfs["A"][0] - 0 == 5
    assert fcfs["B"][0] - 2 == 5
    assert fcfs["B"][0] - 2 - 2 == fcfs["B"][1] == 3

    # RR q=2 with A(0,5), B(1,3), arrivals go to the ready queue.
    ready = deque([("A", 5)])
    time, complete, trace = 0, {}, []
    arrivals = [(1, "B", 3)]
    while ready or arrivals:
        if not ready:
            time = arrivals[0][0]
        while arrivals and arrivals[0][0] <= time:
            _, name, burst = arrivals.pop(0)
            ready.append((name, burst))
        name, remaining = ready.popleft()
        run = min(2, remaining)
        trace.append(name)
        time += run
        remaining -= run
        while arrivals and arrivals[0][0] <= time:
            _, arrived, burst = arrivals.pop(0)
            ready.append((arrived, burst))
        if remaining:
            ready.append((name, remaining))
        else:
            complete[name] = time
    assert trace == ["A", "B", "A", "B", "A"]
    assert complete == {"B": 7, "A": 8}


def test_page_memory_disk_and_buffer_examples() -> None:
    # Paging and segmentation address checks.
    page_size = 1024
    logical = 2500
    page, offset = divmod(logical, page_size)
    assert (page, offset, 7 * page_size + offset) == (2, 452, 7620)
    assert 120 < 800 and 5000 + 120 == 5120
    assert not 900 < 800

    # LRU: three frames, reference string 1,2,1,3,2,4 -> four faults.
    frames: list[int] = []
    recent: list[int] = []
    faults = 0
    for value in (1, 2, 1, 3, 2, 4):
        if value not in frames:
            faults += 1
            if len(frames) == 3:
                victim = recent.pop(0)
                frames.remove(victim)
            frames.append(value)
        if value in recent:
            recent.remove(value)
        recent.append(value)
    assert faults == 4 and set(frames) == {2, 3, 4}

    # Disk SSTF and two-buffer pipeline examples.
    head = 50
    total = 0
    pending = [82, 170, 43, 140, 24, 16, 190]
    order = []
    while pending:
        target = min(pending, key=lambda value: abs(value - head))
        total += abs(target - head)
        head = target
        order.append(target)
        pending.remove(target)
    assert order == [43, 24, 16, 82, 140, 170, 190] and total == 208
    assert 13 + 9 * 8 == 85


def test_semaphore_bitmap_and_deadlock_examples() -> None:
    empty, full, mutex = 2, 0, 1
    empty -= 1  # P(empty)
    mutex -= 1  # P(mutex)
    mutex += 1  # V(mutex)
    full += 1  # V(full)
    assert (empty, full, mutex) == (1, 1, 1)
    assert (2**20) // 8 == 2**17

    # With one instance per resource, this cycle is a deadlock.
    resource_graph = {"P1": "R2", "R2": "P2", "P2": "R1", "R1": "P1"}
    current = "P1"
    visited = []
    while current not in visited:
        visited.append(current)
        current = resource_graph[current]
    assert current == "P1"
