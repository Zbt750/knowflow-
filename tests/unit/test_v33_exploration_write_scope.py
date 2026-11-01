from types import SimpleNamespace
from uuid import uuid4

import pytest

from scripts.naiwa_agent_full_v2_20261021 import (
    _practice_request_owned,
    compare_snapshot,
)


class _FakeDb:
    def __init__(self, row):
        self.row = row

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def get(self, _model, _row_id):
        return self.row


@pytest.mark.parametrize(
    "status,registered_scene,registered_purpose,source_matches,expected",
    [
        ("draft", "A", "qa", True, True),
        ("pending", "A", "qa", True, True),
        ("proposed", "A", "qa", True, True),
        ("accepted", "A", "qa", True, False),
        ("declined", "A", "qa", True, False),
        ("draft", "B", "qa", True, False),
        ("draft", "A", "study", True, False),
        ("draft", "A", "qa", False, False),
    ],
)
def test_decline_scope_requires_owned_live_qa_request(
    status, registered_scene, registered_purpose, source_matches, expected
):
    source_id = uuid4()
    other_id = uuid4()
    row = SimpleNamespace(
        id=uuid4(),
        status=status,
        source_conversation_id=source_id if source_matches else other_id,
    )
    factory = lambda: _FakeDb(row)
    registry = {
        "sessions": [
            {
                "session_id": str(source_id),
                "scene_created": registered_scene,
                "purpose": registered_purpose,
            }
        ]
    }

    assert _practice_request_owned(factory, str(row.id), registry, "A") is expected


def test_snapshot_comparison_protects_practice_request_rows():
    before = {"practice_requests": [{"id": "request-1", "status": "draft"}]}
    changed = {"practice_requests": [{"id": "request-1", "status": "accepted"}]}

    assert not compare_snapshot(before, changed)["preexisting_rows_preserved"]
    assert compare_snapshot(
        before, changed, mutable_practice_request_ids=["request-1"]
    )["preexisting_rows_preserved"]
