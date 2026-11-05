"""Offline deployment probes must not pretend frame count proves streaming."""
import json
from pathlib import Path

import pytest

from scripts import verify_docker_deploy as probe


class Response:
    def __init__(self, parts):
        self.parts = iter(parts)

    def read1(self, size):
        return next(self.parts, b"")


def test_frames_split_across_reads_and_utf8_are_preserved():
    data = 'event: meta\r\ndata: {}\r\n\r\nevent: delta\ndata: {"text":"数学"}\n\nevent: done\ndata: {}\n\n'.encode()
    split = data.index("数学".encode()) + 1
    events, chunks, reads, incomplete = probe.observe_sse(
        Response([data[:7], data[7:split], data[split:]]), clock=lambda: 1.0)
    assert events == {"meta": 1, "delta": 1, "done": 1}
    assert chunks == 3 and reads == [1.0] and not incomplete


def test_many_frames_in_one_packet_have_only_one_delta_read():
    data = b"event: delta\ndata: {}\n\n" * 20 + b"event: done\ndata: {}\n\n"
    events, chunks, reads, incomplete = probe.observe_sse(Response([data]), clock=lambda: 1.0)
    assert events["delta"] == 20 and chunks == 1 and len(reads) == 1
    assert not incomplete


def test_distinct_delta_reads_record_observed_times():
    clock = iter([1.0, 1.2])
    events, _, reads, incomplete = probe.observe_sse(Response([
        b"event: delta\ndata: {}\n\n", b"event: delta\ndata: {}\n\nevent: done\ndata: {}\n\n"]),
        clock=lambda: next(clock))
    assert events["done"] == 1 and reads == [1.0, 1.2] and not incomplete


def test_incomplete_frame_is_not_a_completed_response():
    events, _, _, incomplete = probe.observe_sse(Response([b"event: done\ndata: {}\n"]))
    assert "done" not in events and incomplete


def test_buffered_read_only_cannot_prove_progressive_delivery():
    with pytest.raises(ValueError, match="lacks read1"):
        probe.observe_sse(object())


def test_default_probe_never_calls_upstream_and_reports_skip(monkeypatch, capsys):
    state = {"deleted": False}

    def request(path, method="GET", **kwargs):
        if method == "DELETE":
            state["deleted"] = True
            return 204, b""
        if path == "/api/health":
            value = {"retrieval": "ready"}
        elif path == "/api/materials/m1":
            if state["deleted"]:
                return 404, b"{}"
            value = {"status": "ready", "chunk_count": 1}
        elif path == "/api/materials/search":
            value = {"hits": [{"material_id": "m1"}]}
        else:
            value = {"items": [] if state["deleted"] else [{"title": probe.TITLE}]}
        return 200, json.dumps(value).encode()

    monkeypatch.setattr(probe, "request", request)
    monkeypatch.setattr(probe, "upload", lambda: (201, b'{"material":{"id":"m1","status":"queued"}}'))
    monkeypatch.setattr(probe, "check_sse_streaming", lambda: pytest.fail("unexpected paid request"))
    assert probe.main([]) == 0
    assert "SSE未执行" in capsys.readouterr().out


@pytest.mark.parametrize("failure_path", ["/api/materials/m1", "/api/materials/search"])
def test_request_failure_still_deletes_only_created_material(monkeypatch, failure_path):
    deleted = []

    def request(path, method="GET", **kwargs):
        if method == "DELETE":
            deleted.append(path)
            return 204, b""
        if path == failure_path:
            raise TimeoutError("private diagnostic must not be printed")
        value = {"retrieval": "ready"} if path == "/api/health" else {"status": "ready", "items": [{"title": probe.TITLE}]}
        return 200, json.dumps(value).encode()

    monkeypatch.setattr(probe, "request", request)
    monkeypatch.setattr(probe, "upload", lambda: (201, b'{"material":{"id":"m1","status":"queued"}}'))
    assert probe.main([]) == 1
    assert deleted == ["/api/materials/m1"]


def test_failed_upload_never_deletes_existing_resources(monkeypatch):
    monkeypatch.setattr(probe, "request", lambda *a, **k: (200, b'{"retrieval":"ready"}'))
    monkeypatch.setattr(probe, "upload", lambda: (503, b"{}"))
    assert probe.main([]) == 1


def test_cleanup_failure_is_not_a_passing_probe(monkeypatch, capsys):
    def request(path, method="GET", **kwargs):
        if method == "DELETE":
            return 503, b"{}"
        if path == "/api/health":
            return 200, b'{"retrieval":"ready"}'
        raise TimeoutError()

    monkeypatch.setattr(probe, "request", request)
    monkeypatch.setattr(probe, "upload", lambda: (201, b'{"material":{"id":"m1","status":"queued"}}'))
    assert probe.main([]) == 1
    assert "清理失败 HTTP 503" in capsys.readouterr().out


def test_unauthenticated_compose_only_binds_loopback():
    root = Path(__file__).resolve().parents[2]
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
    assert '"127.0.0.1:${WEB_PORT:-8080}:80"' in compose
    assert '"${WEB_PORT:-8080}:80"' not in compose
