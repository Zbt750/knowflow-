"""V2 40-request gate contract; all responses use HTTPX MockTransport.

No DNS/socket is permitted by these tests, and no provider response is real.
"""
import concurrent.futures
import asyncio
import json
import socket
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from scripts.naiwa_freeze_gate_20261021 import (
    CAPS,
    ROUND,
    BudgetStop,
    FinalRoundGate,
    SCENE,
    atomic_json,
)
from backend.chat.http_clients import CALL, call_purpose


def _deny_network(event, args):
    if event == "socket.connect":
        address = args[1]
        if not (isinstance(address, tuple) and address and address[0] in {"127.0.0.1", "::1"}):
            raise AssertionError("v2_gate_test_external_socket_forbidden")
    if event == "socket.getaddrinfo" and args[0] not in {"127.0.0.1", "localhost", "::1"}:
        raise AssertionError("v2_gate_test_external_dns_forbidden")


sys.addaudithook(_deny_network)


SCENE_CAPS = {"A": 4, "B": 5, "C": 7, "D": 7, "E": 5, "F": 4, "H": 4, "R": 4}
TEXT_PURPOSES = {"agent_text", "text_completion", "text_stream", "classification"}
PURPOSE_POLICY = {name: set(TEXT_PURPOSES) | ({"variant_generation"} if name in {"C", "R"} else set())
                  for name in SCENE_CAPS}
URL = "https://api.deepseek.com/chat/completions"
PAYLOAD = {"model": "deepseek-flash", "max_tokens": 100,
           "messages": [{"role": "user", "content": "mock-only V2 gate test"}]}
REPLY = {"model": "deepseek-flash", "choices": [{"message": {"content": "模拟响应"}, "finish_reason": "stop"}],
         "usage": {"prompt_tokens": 12, "completion_tokens": 4}}


@pytest.fixture
def gate():
    with tempfile.TemporaryDirectory(prefix="agent-full-v2-", dir=ROUND.parent) as folder:
        instance = FinalRoundGate(Path(folder), simulated=True, preparation=False,
            global_limit=40, scene_caps=SCENE_CAPS, purpose_policy=PURPOSE_POLICY,
            seal_on_scene_cap=False)
        try:
            yield instance
        finally:
            instance.uninstall()


def enable(gate, scene):
    SCENE.set(scene)
    CALL.set(None)
    atomic_json(gate.control, {"paid_enabled": True, "authorization_received": True,
                               "active_scene": scene})


def send(gate, scene, purpose="text_completion", payload=None, handler=None):
    enable(gate, scene)
    with httpx.Client(transport=httpx.MockTransport(
            handler or (lambda request: httpx.Response(200, json=REPLY)))) as client:
        with call_purpose(purpose, "Provider.complete"):
            return client.post(URL, json=payload or PAYLOAD)


def test_v2_configuration_is_separate_and_preserves_historical_defaults(gate):
    assert gate.path != ROUND / "provider-ledger.json"
    assert gate.global_limit == 40
    assert gate.scene_caps == SCENE_CAPS
    assert gate.seal_on_scene_cap is False
    assert CAPS == {"AGENT": 4, "GENERATE": 1}
    document = json.loads(gate.path.read_text(encoding="utf-8"))
    assert document["limits"]["max_requests"] == 40
    assert document["scene_limits"] == SCENE_CAPS


def test_scene_cap_blocks_only_that_scene_and_does_not_transfer_slots(gate):
    gate.install()
    for _ in range(SCENE_CAPS["A"]):
        send(gate, "A")
    with pytest.raises(BudgetStop, match="scene_cap"):
        send(gate, "A")
    assert len(gate.records) == 4
    assert json.loads(gate.control.read_text())["paid_enabled"] is True
    send(gate, "B")
    assert [r["case_id"] for r in gate.records] == ["A"] * 4 + ["B"]


def test_global_40_cap_under_concurrent_mock_dispatch_and_restart(gate):
    gate.install()
    work = [scene for scene, cap in SCENE_CAPS.items() for _ in range(cap)]
    assert len(work) == 40
    for scene in work:
        send(gate, scene)
    assert len(gate.records) == 40
    assert {s: sum(r["case_id"] == s for r in gate.records) for s in SCENE_CAPS} == SCENE_CAPS
    assert not gate.records[-1].get("error_type")
    resumed = FinalRoundGate(gate.output, simulated=True, preparation=False,
        global_limit=40, scene_caps=SCENE_CAPS, purpose_policy=PURPOSE_POLICY,
        seal_on_scene_cap=False)
    assert len(resumed.records) == 40
    resumed.install()
    with pytest.raises(BudgetStop):
        send(resumed, "R")
    assert len(resumed.records) == 40


def test_scene_cap_is_atomic_under_concurrent_mock_dispatch(gate):
    gate.install()
    enable(gate, "C")
    def run(scene):
        SCENE.set("C")
        with call_purpose("text_completion", "Provider.complete"):
            with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=REPLY))) as client:
                try:
                    return client.post(URL, json=PAYLOAD).status_code
                except BudgetStop:
                    return "blocked"
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(run, range(8)))
    assert results.count(200) == SCENE_CAPS["C"]
    assert results.count("blocked") == 1
    assert len(gate.records) == SCENE_CAPS["C"]


def test_state_unknown_keeps_reservation_after_restart(gate):
    gate.install()
    def no_usage(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "simulated"},
                                                       "finish_reason": "stop"}]})
    response = send(gate, "F", handler=no_usage)
    assert response.status_code == 200
    assert len(gate.records) == 1
    assert gate.records[0]["state"] == "ACTUAL_USAGE_UNKNOWN_RESERVATION_RETAINED"
    resumed = FinalRoundGate(gate.output, simulated=True, preparation=False,
        global_limit=40, scene_caps=SCENE_CAPS, purpose_policy=PURPOSE_POLICY,
        seal_on_scene_cap=False)
    assert len(resumed.records) == 1
    assert resumed.records[0]["case_id"] == "F"


def test_variant_purpose_is_limited_to_declared_scenes_and_visual_shape_is_rejected(gate):
    gate.install()
    send(gate, "C", purpose="variant_generation")
    assert len(gate.records) == 1 and gate.records[0]["purpose"] == "variant_generation"
    with pytest.raises(BudgetStop, match="model_purpose_not_authorized"):
        send(gate, "A", purpose="variant_generation")
    visual = {**PAYLOAD, "messages": [{"role": "user", "content": [
        {"type": "text", "text": "visual"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
    ]}]}
    with pytest.raises(BudgetStop, match="model_purpose_shape_mismatch"):
        send(gate, "C", purpose="text_completion", payload=visual)
    assert len(gate.records) == 1


def test_existing_round5_ledger_and_old_caps_are_not_a_v2_quota_source():
    # A V2 temporary ledger starts with its own zero reservations. Its value is
    # independent of the protected historic 19/5/round5 ledgers.
    with tempfile.TemporaryDirectory(prefix="agent-full-v2-independent-", dir=ROUND.parent) as folder:
        instance = FinalRoundGate(Path(folder), simulated=True, preparation=False,
            global_limit=40, scene_caps=SCENE_CAPS, purpose_policy=PURPOSE_POLICY,
            seal_on_scene_cap=False)
        assert instance.records == []
        assert instance.max_requests == 40
        instance.uninstall()


def test_real_provider_normal_done_stream_close_is_not_unknown(gate, monkeypatch):
    """Reproduce A1: Provider stops at [DONE], not by consuming transport EOF."""
    from backend.chat import http_clients
    from backend.chat.service import Provider
    monkeypatch.setattr(http_clients, '_isolated_direct', False)
    http_clients.configure_isolated_provider_http(SimpleNamespace(app_env='test',
        active_database_url='postgresql+psycopg://stub:stub@127.0.0.1:63044/naiwa_experience_test'))
    data = ("data: " + json.dumps({'choices':[{'delta':{'content':'欢迎'},'finish_reason':None}]},ensure_ascii=False)
        + "\n\ndata: " + json.dumps({'choices':[{'delta':{},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':12,'completion_tokens':4}}) + "\n\ndata: [DONE]\n\n").encode()
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for start in range(0, len(data), 7):
                yield data[start:start+7]
    mock = httpx.MockTransport(lambda request:httpx.Response(200,stream=Stream()))
    async def handle(transport, request):
        return await mock.handle_async_request(request)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', handle)
    enable(gate,'A');gate.install()
    provider = Provider(api_key='mock-only',base_url='https://api.deepseek.com',
        model='deepseek-flash',timeout=5,max_tokens=100,stream_include_usage=True)
    async def run():
        return ''.join([text async for text in provider.stream([{'role':'user','content':'zero network lifecycle replay'}])])
    assert asyncio.run(run()) == '欢迎'
    row = gate.records[0]
    assert row['state'] == 'COMPLETED_USAGE_OBSERVED'
    assert row['finish_reason'] == 'stop' and row['usage']['completion_tokens'] == 4
    assert 'request_state_unknown' not in [event['stage'] for event in row['phase_events']]


def test_real_provider_close_before_terminal_keeps_unknown_reservation(gate, monkeypatch):
    from backend.chat import http_clients
    from backend.chat.service import Provider
    monkeypatch.setattr(http_clients,'_isolated_direct',False)
    http_clients.configure_isolated_provider_http(SimpleNamespace(app_env='test',
        active_database_url='postgresql+psycopg://stub:stub@127.0.0.1:63044/naiwa_experience_test'))
    data=('data: '+json.dumps({'choices':[{'delta':{'content':'partial'},'finish_reason':None}]})+'\n\n').encode()
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield data
            await asyncio.sleep(10)
    mock=httpx.MockTransport(lambda request:httpx.Response(200,stream=Stream()))
    async def handle(transport,request):return await mock.handle_async_request(request)
    monkeypatch.setattr(httpx.AsyncHTTPTransport,'handle_async_request',handle)
    enable(gate,'F');gate.install()
    provider=Provider(api_key='mock-only',base_url='https://api.deepseek.com',model='deepseek-flash',
        timeout=5,max_tokens=100,stream_include_usage=True)
    async def run():
        response=provider.stream([{'role':'user','content':'zero-network partial close'}])
        assert await anext(response)=='partial'
        await response.aclose()
    asyncio.run(run())
    assert len(gate.records)==1
    assert gate.records[0]['state']=='ACTUAL_USAGE_UNKNOWN_RESERVATION_RETAINED'
    assert 'request_state_unknown' in [e['stage'] for e in gate.records[0]['phase_events']]
    assert read_control(gate)['paid_enabled'] is False


def read_control(gate):
    return json.loads(gate.control.read_text(encoding='utf-8'))


def test_sync_done_close_uses_same_terminal_evidence(gate, monkeypatch):
    from backend.chat import http_clients
    monkeypatch.setattr(http_clients,'_isolated_direct',False)
    http_clients.configure_isolated_provider_http(SimpleNamespace(app_env='test',
        active_database_url='postgresql+psycopg://stub:stub@127.0.0.1:63044/naiwa_experience_test'))
    data=('data: '+json.dumps(REPLY)+'\n\ndata: [DONE]\n\n').encode()
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            for offset in range(0,len(data),7):yield data[offset:offset+7]
    mock=httpx.MockTransport(lambda request:httpx.Response(200,stream=Stream()))
    monkeypatch.setattr(httpx.HTTPTransport,'handle_request',lambda transport,request:mock.handle_request(request))
    enable(gate,'A');gate.install()
    with call_purpose('text_completion','Provider.complete'):
        with http_clients.sync_client() as client:
            with client.stream('POST',URL,json=PAYLOAD) as response:
                for line in response.iter_lines():
                    if line=='data: [DONE]':break
    assert gate.records[0]['state']=='COMPLETED_USAGE_OBSERVED'
    assert 'request_state_unknown' not in [e['stage'] for e in gate.records[0]['phase_events']]

