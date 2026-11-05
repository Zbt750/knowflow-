"""No external DNS/socket permitted. Real factory, MockTransport, temporary ledger."""
import asyncio
import concurrent.futures
import json
import sys
from pathlib import Path
import httpx
import pytest
from backend.chat.http_clients import call_purpose, sync_client, async_client
from scripts.naiwa_freeze_gate_20261021 import SCENE, ROUND, atomic_json, BudgetStop
from scripts.naiwa_v3_runtime_20261022 import V3Gate, LEGACY_CAPS, PURPOSE_POLICY


def deny_network(event,args):
    # Windows ProactorEventLoop builds its wakeup socketpair on loopback.
    # This test-only guard forbids EXTERNAL connections/DNS, not that local IPC.
    if event=='socket.connect' and not (isinstance(args[1],tuple) and args[1][0] in {'127.0.0.1','::1'}):
        raise AssertionError('V3_ZERO_NETWORK_EXTERNAL_SOCKET')
    if event=='socket.getaddrinfo' and args[0] not in {'127.0.0.1','::1','localhost'}:
        raise AssertionError('V3_ZERO_NETWORK_EXTERNAL_DNS')
sys.addaudithook(deny_network)

URL='https://api.deepseek.com/chat/completions'
PAYLOAD={'model':'deepseek-flash','max_tokens':100,'messages':[{'role':'user','content':'SIMULATED ONLY'}]}
REPLY={'choices':[{'message':{'content':'SIMULATED ONLY'},'finish_reason':'stop'}],
       'usage':{'prompt_tokens':5,'completion_tokens':3}}


def make(path):
    return V3Gate(path,simulated=True,preparation=False,global_limit=40,
        scene_caps=LEGACY_CAPS,purpose_policy=PURPOSE_POLICY,seal_on_scene_cap=False)


@pytest.fixture
def gate():
    import tempfile
    with tempfile.TemporaryDirectory(dir=ROUND.parent,prefix='v3-zero-') as name:
        g=make(Path(name))
        try:yield g
        finally:g.uninstall()


def enable(g,scene):
    SCENE.set(scene)
    atomic_json(g.control,{'paid_enabled':True,'authorization_received':True,'active_scene':scene})


def send(g,scene,handler=None):
    SCENE.set(scene)
    with sync_client(transport=httpx.MockTransport(handler or (lambda r:httpx.Response(200,json=REPLY)))) as c:
        with call_purpose('text_completion','Provider.complete'):
            return c.post(URL,json=PAYLOAD)


def test_a3_is_stricter_without_rewriting_existing_a4_schema(gate):
    gate.install();enable(gate,'A')
    for _ in range(3):assert send(gate,'A').status_code==200
    with pytest.raises(BudgetStop,match='v3_a_scene_cap3'):send(gate,'A')
    assert len(gate.records)==3
    assert json.loads(gate.path.read_text())['scene_limits']['A']==4


def test_restart_recovers_existing_a_usage_and_never_resets(gate):
    gate.install();enable(gate,'A');send(gate,'A');gate.uninstall()
    resumed=make(gate.path.parent)
    try:
        resumed.install();enable(resumed,'A');send(resumed,'A');send(resumed,'A')
        with pytest.raises(BudgetStop,match='v3_a_scene_cap3'):send(resumed,'A')
        assert len(resumed.records)==3
    finally:resumed.uninstall()


def test_concurrent_a_reservations_cannot_cross_three(gate):
    gate.install();enable(gate,'A')
    def worker(_):
        try:send(gate,'A');return True
        except BudgetStop:return False
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        results=list(pool.map(worker,range(9)))
    assert sum(results)==3 and len(gate.records)==3


def test_global40_including_inherited_usage(gate):
    gate.install()
    for scene,count in LEGACY_CAPS.items():
        enable(gate,scene)
        for _ in range(min(count,3) if scene=='A' else count):send(gate,scene)
    assert len(gate.records)==39  # stricter A3 never transfers its unused slot
    enable(gate,'B')
    with pytest.raises(BudgetStop):send(gate,'B')
    assert len(gate.records)==39


def test_timeout_retains_slot_and_blocks_reopening(gate):
    gate.install();enable(gate,'A')
    def failure(r):raise httpx.ReadTimeout('SIMULATED',request=r)
    with pytest.raises(httpx.ReadTimeout):send(gate,'A',failure)
    assert len(gate.records)==1 and gate.stop_reason
    enable(gate,'A')
    with pytest.raises(BudgetStop):send(gate,'A')
    assert len(gate.records)==1


def test_closed_exit_does_not_dispatch_or_reserve(gate):
    gate.install();SCENE.set('A');calls=[]
    with pytest.raises(BudgetStop):send(gate,'A',lambda r:calls.append(r))
    assert calls==[] and gate.records==[]


def test_sync_and_async_share_same_ledger_and_A_limit(gate):
    gate.install();enable(gate,'A');send(gate,'A')
    async def work():
        SCENE.set('A')
        async with async_client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=REPLY))) as c:
            with call_purpose('text_completion','Provider.complete'):
                await c.post(URL,json=PAYLOAD);await c.post(URL,json=PAYLOAD)
                with pytest.raises(BudgetStop,match='v3_a_scene_cap3'):await c.post(URL,json=PAYLOAD)
    asyncio.run(work())
    assert len(gate.records)==3
