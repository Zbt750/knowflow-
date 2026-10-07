"""Coverage and hand-checkable numerical examples for 408 computer networks."""
from __future__ import annotations

import math

from scripts.computer_networks_textbook_content import (
    DETAILS,
    QUALITY_MARKER,
    computer_network_nodes,
    render_pages,
)
from scripts.generate_knowledge_lessons import LESSON_DIR, _ensure_sections


def test_exact_tree_coverage_and_each_topic_has_a_worked_example() -> None:
    nodes = computer_network_nodes()
    pages = render_pages()
    assert len(nodes) == len(pages) == 40
    topic_nodes = [node for node in nodes if node["code"] != "cs408.cn"]
    assert {node["name"] for node in topic_nodes} == set(DETAILS)
    assert all(node["is_reference_only"] for node in topic_nodes)
    assert len(set(pages.values())) == len(pages)
    for filename, expected in pages.items():
        actual = (LESSON_DIR / filename).read_text(encoding="utf-8")
        assert actual == expected
        assert QUALITY_MARKER in actual
        assert "题库" in actual
        if filename != "cs408.cn.md":
            assert "例题" in actual and "分析与逐步解答" in actual
            assert len(actual) >= 600


def test_generator_preserves_authored_lesson_without_exam_reference_append(tmp_path) -> None:
    lesson = next(iter(render_pages().values()))
    path = tmp_path / "computer-networks.md"
    path.write_text(lesson, encoding="utf-8")
    assert not _ensure_sections(path, {}, [{"year": 2025}], {}, [])
    assert path.read_text(encoding="utf-8") == lesson


def test_network_delay_window_and_cidr_examples() -> None:
    frame_bits = 1500 * 8
    serialization_seconds = frame_bits / 100_000_000
    assert math.isclose(serialization_seconds, 0.00012)
    assert 100_000_000 * 0.04 == 4_000_000

    address = [192, 168, 10, 77]
    prefix = 26
    block_size = 2 ** (32 - prefix)
    host_part = address[3] % block_size
    network_last = address[3] - host_part
    broadcast_last = network_last + block_size - 1
    assert (network_last, broadcast_last) == (64, 127)
    assert block_size - 2 == 62


def test_ipv4_fragmentation_and_transport_windows() -> None:
    total_length, header_length, mtu = 4000, 20, 1500
    max_payload = mtu - header_length
    original_payload = total_length - header_length
    fragment_payloads = [max_payload, max_payload, original_payload - 2 * max_payload]
    assert fragment_payloads == [1480, 1480, 1020]
    assert [0, 1480 // 8, 2960 // 8] == [0, 185, 370]
    assert all(size % 8 == 0 for size in fragment_payloads[:-1])

    assert 2**3 == 8 and 2 ** (3 - 1) == 4  # SR max window
    assert 2**3 - 1 == 7  # GBN max window
    assert 1000 + 500 == 1500  # cumulative ACK still expects first missing byte


def test_routing_crc_channel_and_stop_wait_examples() -> None:
    graph = {
        "S": {"A": 2, "B": 5},
        "A": {"S": 2, "B": 1, "T": 5},
        "B": {"S": 5, "A": 1, "T": 2},
        "T": {"A": 5, "B": 2},
    }
    dist = {node: math.inf for node in graph}
    dist["S"] = 0
    previous = {}
    unsettled = set(graph)
    while unsettled:
        node = min(unsettled, key=dist.__getitem__)
        unsettled.remove(node)
        for neighbor, weight in graph[node].items():
            if neighbor in unsettled and dist[node] + weight < dist[neighbor]:
                dist[neighbor] = dist[node] + weight
                previous[neighbor] = node
    assert dist["T"] == 5
    assert previous["T"] == "B" and previous["B"] == "A" and previous["A"] == "S"

    data, generator = "1101000", "1011"
    remainder = list(map(int, data))
    divisor = list(map(int, generator))
    for index in range(len(data) - len(generator) + 1):
        if remainder[index]:
            for offset, bit in enumerate(divisor):
                remainder[index + offset] ^= bit
    crc = "".join(map(str, remainder[-(len(generator) - 1):]))
    assert crc == "001"
    codeword = "1101" + crc
    verification = list(map(int, codeword))
    for index in range(len(codeword) - len(generator) + 1):
        if verification[index]:
            for offset, bit in enumerate(divisor):
                verification[index + offset] ^= bit
    assert verification[-(len(generator) - 1):] == [0, 0, 0]

    utilization = 1 / (1 + 2 * 20)
    assert math.isclose(utilization, 1 / 41)
