from __future__ import annotations

import sys

import pytest

from scripts import run_isolated_chat_ragas as isolated_ragas


def test_orphan_cleanup_only_drops_dead_local_eval_schemas(monkeypatch) -> None:
    class Result:
        def all(self):
            return [
                ("ragas_chat_1111111111111111", "kaoyan-isolated-ragas:v1:test-host:101"),
                ("ragas_chat_2222222222222222", "kaoyan-isolated-ragas:v1:test-host:202"),
                ("ragas_chat_3333333333333333", "kaoyan-isolated-ragas:v1:other-host:303"),
                ("ragas_chat_4444444444444444", None),
                ("not_a_ragas_schema", "kaoyan-isolated-ragas:v1:test-host:404"),
            ]

    class Connection:
        dropped: list[str]

        def __init__(self) -> None:
            self.dropped = []

        def exec_driver_sql(self, statement: str):
            if statement.startswith("SELECT"):
                return Result()
            self.dropped.append(statement)
            return None

    monkeypatch.setattr(isolated_ragas.socket, "gethostname", lambda: "test-host")
    monkeypatch.setattr(isolated_ragas, "_pid_is_running", lambda pid: pid == 101)
    connection = Connection()

    removed = isolated_ragas._cleanup_orphaned_eval_schemas(connection)

    assert removed == ["ragas_chat_2222222222222222"]
    assert connection.dropped == ['DROP SCHEMA "ragas_chat_2222222222222222" CASCADE']


def test_cross_file_budget_selects_only_one_question() -> None:
    assert isolated_ragas._case_selection(cross_file_budget=6000, file_focus_v4=False) == (("cross-file",), 1)
    assert isolated_ragas._case_selection(cross_file_budget=None, file_focus_v4=True) == (("file-exact", "file-alias", "cross-file"), 4)


@pytest.mark.parametrize("arguments", [
    ["--cross-file-budget", "6000", "--limit", "1"],
    ["--baseline-v3-1", "--cross-file-budget", "6000", "--limit", "3"],
    ["--baseline-v3-1", "--cross-file-budget", "6000", "--limit", "1", "--file-focus-v4"],
])
def test_cross_file_budget_rejects_unbounded_or_mixed_modes_before_database(monkeypatch, arguments) -> None:
    monkeypatch.setattr(sys, "argv", ["run_isolated_chat_ragas.py", *arguments])
    with pytest.raises(SystemExit) as raised:
        isolated_ragas.main()
    assert raised.value.code == 2
