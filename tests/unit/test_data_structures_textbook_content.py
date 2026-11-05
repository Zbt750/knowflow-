"""Coverage and independent algorithm-example checks for 408 data structures."""
from __future__ import annotations

from collections import deque

from scripts.data_structures_textbook_content import (
    DETAILS,
    QUALITY_MARKER,
    data_structure_nodes,
    render_pages,
)
from scripts.generate_knowledge_lessons import LESSON_DIR, _ensure_sections


def test_exact_tree_coverage_and_every_topic_has_a_worked_example() -> None:
    nodes = data_structure_nodes()
    pages = render_pages()
    assert len(nodes) == len(pages) == 57
    topic_names = {node["name"] for node in nodes if node["code"] != "cs408.ds"}
    assert topic_names == set(DETAILS)
    assert len(set(pages.values())) == len(pages)
    for filename, expected in pages.items():
        actual = (LESSON_DIR / filename).read_text(encoding="utf-8")
        assert actual == expected
        assert QUALITY_MARKER in actual
        assert "例题" in actual and "分析与逐步解答" in actual
        assert "专题汇总：" not in actual
        assert "题库" in actual
        assert len(actual) >= 500


def test_generator_preserves_authored_lessons_without_appending_reference_tables(tmp_path) -> None:
    lesson = next(iter(render_pages().values()))
    path = tmp_path / "data-structures.md"
    path.write_text(lesson, encoding="utf-8")
    assert not _ensure_sections(path, {}, [{"year": 2025}], {}, [])
    assert path.read_text(encoding="utf-8") == lesson


def test_postfix_queue_and_huffman_examples() -> None:
    stack: list[int] = []
    for token in ("2", "3", "1", "*", "+"):
        if token.isdigit():
            stack.append(int(token))
        elif token == "*":
            right, left = stack.pop(), stack.pop()
            stack.append(left * right)
        else:
            right, left = stack.pop(), stack.pop()
            stack.append(left + right)
    assert stack == [5]

    queue = deque()
    queue.extend(("A", "B", "C"))
    assert [queue.popleft(), queue.popleft()] == ["A", "B"]
    queue.append("D")
    assert list(queue) == ["C", "D"]

    weights = [1, 2, 3, 4]
    merge_cost = 0
    while len(weights) > 1:
        weights.sort()
        new_weight = weights.pop(0) + weights.pop(0)
        merge_cost += new_weight
        weights.append(new_weight)
    assert merge_cost == 19


def test_sorting_and_binary_search_examples() -> None:
    values = [5, 2, 4, 1]
    pivot = 4
    partitioned = [value for value in values if value < pivot] + [pivot] + [value for value in values if value > pivot]
    assert partitioned == [2, 1, 4, 5]
    assert sorted(partitioned) == [1, 2, 4, 5]

    merged: list[int] = []
    left, right = [1, 4], [2, 3]
    while left and right:
        merged.append(left.pop(0) if left[0] <= right[0] else right.pop(0))
    merged.extend(left or right)
    assert merged == [1, 2, 3, 4]

    ordered = [3, 7, 9, 13, 20, 24, 31]
    lo, hi, checked = 0, len(ordered) - 1, []
    while lo <= hi:
        mid = (lo + hi) // 2
        checked.append(ordered[mid])
        if ordered[mid] == 20:
            break
        if ordered[mid] < 20:
            lo = mid + 1
        else:
            hi = mid - 1
    assert checked == [13, 24, 20]

    prefix = []
    for index, char in enumerate("abab"):
        length = prefix[index - 1] if index else 0
        while length and char != "abab"[length]:
            length = prefix[length - 1]
        if index and char == "abab"[length]:
            length += 1
        prefix.append(length)
    assert prefix == [0, 0, 1, 2]

    dag = {"A": ["C"], "B": ["C"], "C": ["D"], "D": []}
    indegree = {vertex: 0 for vertex in dag}
    for targets in dag.values():
        for target in targets:
            indegree[target] += 1
    ready = deque(vertex for vertex, degree in indegree.items() if degree == 0)
    topo = []
    while ready:
        vertex = ready.popleft()
        topo.append(vertex)
        for target in dag[vertex]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    position = {vertex: index for index, vertex in enumerate(topo)}
    assert len(topo) == 4 and all(
        position[left] < position[right]
        for left, targets in dag.items()
        for right in targets
    )


def test_graph_examples_for_bfs_dijkstra_and_spanning_trees() -> None:
    graph = {"A": ["B", "C"], "B": ["A", "D"], "C": ["A", "D"], "D": ["B", "C"]}
    queue = deque(["A"])
    seen = {"A"}
    order = []
    while queue:
        vertex = queue.popleft()
        order.append(vertex)
        for neighbor in graph[vertex]:
            if neighbor not in seen:
                seen.add(neighbor)
                queue.append(neighbor)
    assert order == ["A", "B", "C", "D"]

    distances = {"S": 0, "A": 4, "B": 1, "C": float("inf")}
    edges = {"S": [("A", 4), ("B", 1)], "A": [("C", 1)], "B": [("A", 2), ("C", 5)], "C": []}
    unsettled = set(distances)
    while unsettled:
        current = min(unsettled, key=distances.__getitem__)
        unsettled.remove(current)
        for neighbor, weight in edges[current]:
            if neighbor in unsettled:
                distances[neighbor] = min(distances[neighbor], distances[current] + weight)
    assert distances == {"S": 0, "A": 3, "B": 1, "C": 4}

    # Prim chooses a minimum crossing edge; Kruskal rejects the edge that closes a cycle.
    weighted = [(1, "A", "B"), (2, "B", "C"), (3, "A", "C")]
    connected = {"A"}
    prim_cost = 0
    while len(connected) < 3:
        weight, left, right = min(edge for edge in weighted if (edge[1] in connected) != (edge[2] in connected))
        connected.update((left, right))
        prim_cost += weight
    parent = {vertex: vertex for vertex in "ABC"}
    def find(vertex):
        while parent[vertex] != vertex:
            vertex = parent[vertex]
        return vertex
    kruskal_cost = 0
    for weight, left, right in weighted:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[left_root] = right_root
            kruskal_cost += weight
    assert prim_cost == kruskal_cost == 3


def test_tree_array_hash_and_address_calculations() -> None:
    leaves, two_child_nodes, one_child_nodes = 4, 3, 2
    assert leaves == two_child_nodes + 1
    assert leaves + two_child_nodes + one_child_nodes == 9
    assert 10 - 3 == 7  # edges in a forest: n - number_of_trees
    assert 2 * 4 == 8 and 2 * 4 + 1 == 9  # one-based complete-tree children
    assert ((2 - 1) * 5 + (3 - 0)) * 4 + 1000 == 1032
    # Symmetric 4x4 matrix, lower-triangle row order, zero-based storage index.
    lower_triangle_index = lambda row, column: max(row, column) * (max(row, column) + 1) // 2 + min(row, column)
    assert lower_triangle_index(3, 1) == lower_triangle_index(1, 3) == 7

    slots = [None] * 7
    for key in (10, 17, 24):
        index = key % 7
        while slots[index] is not None:
            index = (index + 1) % 7
        slots[index] = key
    assert slots[3:6] == [10, 17, 24]

    # Circular queue: front is first element, rear is the next free slot.
    queue_slots = [None] * 5
    front = rear = 0
    for value in ("A", "B", "C"):
        queue_slots[rear] = value
        rear = (rear + 1) % len(queue_slots)
    removed = []
    for _ in range(2):
        removed.append(queue_slots[front])
        front = (front + 1) % len(queue_slots)
    for value in ("D", "E"):
        queue_slots[rear] = value
        rear = (rear + 1) % len(queue_slots)
    logical_queue = [queue_slots[(front + offset) % 5] for offset in range((rear - front) % 5)]
    assert removed == ["A", "B"] and logical_queue == ["C", "D", "E"]
    assert (rear + 1) % 5 != front


def test_traversal_reconstruction_and_avl_rotation_examples() -> None:
    preorder, inorder = "ABDECFG", "DBEAFCG"
    def build(pre, ino):
        if not pre:
            return None
        root = pre[0]
        split = ino.index(root)
        return root, build(pre[1:1 + split], ino[:split]), build(pre[1 + split:], ino[split + 1:])
    tree = build(preorder, inorder)
    def postorder(node):
        return "" if node is None else postorder(node[1]) + postorder(node[2]) + node[0]
    assert postorder(tree) == "DEBFGCA"

    # LL insertion 3,2,1 followed by one right rotation.
    unbalanced = (3, (2, (1, None, None), None), None)
    left_root = unbalanced[1]
    rotated = (left_root[0], left_root[1], (unbalanced[0], left_root[2], unbalanced[2]))
    assert rotated == (2, (1, None, None), (3, None, None))
