"""No external sockets. All HTTP responses are MockTransport test output."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

import httpx
import pytest

from scripts.naiwa_freeze_gate_20261021 import FinalRoundGate, SCENE, ROUND, BudgetStop, atomic_json


def deny_external(event, args):
    if event == 'socket.connect':
        a = args[1]
        if not isinstance(a, tuple) or a[0] not in {'127.0.0.1', '::1'}:
            raise AssertionError('test_external_socket_forbidden')
    if event == 'socket.getaddrinfo' and args[0] not in {'127.0.0.1', 'localhost', '::1'}:
        raise AssertionError('test_external_dns_forbidden')


sys.addaudithook(deny_external)
PAYLOAD = {'model': 'deepseek-flash', 'max_tokens': 100, 'messages': [{'role': 'user', 'content': 'zero network stub'}]}
REPLY = {'model': 'deepseek-flash', 'choices': [{'message': {'content': 'precise'}, 'finish_reason': 'stop'}],
         'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}
URL = 'https://api.deepseek.com/chat/completions'


@pytest.fixture
def gate():
    with tempfile.TemporaryDirectory(prefix='transport-test-', dir=ROUND.parent) as folder:
        instance = FinalRoundGate(Path(folder), simulated=True)
        try: yield instance
        finally: instance.uninstall()


def enable(gate, scene='AGENT'):
    SCENE.set(scene)
    from backend.chat.http_clients import CALL,server_call
    CALL.set(server_call('variant_generation' if scene=='GENERATE' else 'text_completion','Provider.complete'))
    atomic_json(gate.control, {'paid_enabled': True, 'authorization_received': True, 'active_scene': scene})


def post(gate, scene='AGENT', handler=None):
    enable(gate, scene)
    with httpx.Client(transport=httpx.MockTransport(handler or (lambda r: httpx.Response(200, json=REPLY)))) as client:
        return client.post(URL, json=PAYLOAD)


def test_closed_gate_never_reaches_transport(gate):
    gate.install()
    with httpx.Client(transport=httpx.MockTransport(lambda r: pytest.fail('must not dispatch'))) as client:
        with pytest.raises(BudgetStop): client.post(URL, json=PAYLOAD)
    assert len(gate.records) == 0


def test_preparation_cannot_be_enabled_by_control_file(gate):
    real = FinalRoundGate(gate.output, simulated=False, preparation=True)
    real.install(); enable(real)
    try:
        with pytest.raises(BudgetStop, match='phase1'):
            post(real, handler=lambda r: pytest.fail('no real transport'))
        assert real.records == []
    finally: real.uninstall()


def test_global5_scene4_and1_and_restart(gate):
    gate.install()
    for _ in range(4): post(gate)
    with pytest.raises(BudgetStop): post(gate)
    gate.uninstall()
    resumed = FinalRoundGate(gate.output, simulated=True)
    assert len(resumed.records) == 4
    resumed.install()
    try:
        post(resumed, 'GENERATE')
        with pytest.raises(BudgetStop): post(resumed, 'GENERATE')
        with pytest.raises(BudgetStop): post(resumed, 'AGENT')
        assert len(resumed.records) == 5
        assert [r['case_id'] for r in resumed.records] == ['AGENT']*4+['GENERATE']
    finally: resumed.uninstall()


def test_generation1_cannot_use_agent_slots(gate):
    gate.install(); post(gate, 'GENERATE')
    with pytest.raises(BudgetStop): post(gate, 'GENERATE')
    assert len(gate.records) == 1


@pytest.mark.parametrize('failure', ['timeout', 'network', 'unknown_usage', 'auth', 'stream_interrupted'])
def test_failure_retains_reservation_and_closes(gate, failure):
    def handler(request):
        if failure == 'timeout': raise httpx.ReadTimeout('stub', request=request)
        if failure == 'network': raise httpx.ConnectError('stub', request=request)
        if failure == 'stream_interrupted':
            class Broken(httpx.SyncByteStream):
                def __iter__(self):
                    yield b'data: {"choices":[]}\n\n'
                    raise httpx.RemoteProtocolError('stub interrupted')
            return httpx.Response(200, stream=Broken())
        return httpx.Response(401 if failure == 'auth' else 200, json={})
    gate.install()
    try: post(gate, handler=handler)
    except httpx.HTTPError: pass
    assert len(gate.records) == 1
    assert not json.loads(gate.control.read_text())['paid_enabled']
    resumed = FinalRoundGate(gate.output, simulated=True)
    assert len(resumed.records) == 1
    with pytest.raises(BudgetStop): post(gate)
    assert len(gate.records) == 1


def test_abandoned_stream_keeps_unknown_reservation(gate):
    gate.install(); enable(gate)
    class Unread(httpx.SyncByteStream):
        def __iter__(self): yield b'data: [DONE]\n\n'
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,stream=Unread()))) as client:
        with client.stream('POST', URL, json=PAYLOAD): pass
    assert len(gate.records) == 1
    assert gate.records[0]['state'] == 'ACTUAL_USAGE_UNKNOWN_RESERVATION_RETAINED'


def test_multithread_atomic_reservations(gate):
    gate.install()
    barrier = threading.Barrier(4)
    sent=[]
    def handler(request):
        sent.append(1); barrier.wait(timeout=10)
        return httpx.Response(200,json=REPLY)
    enable(gate)
    def work(_):
        SCENE.set('AGENT')
        from backend.chat.http_clients import CALL,server_call
        CALL.set(server_call('text_completion','Provider.complete'))
        try:
            with httpx.Client(transport=httpx.MockTransport(handler)) as client: client.post(URL,json=PAYLOAD)
            return 'sent'
        except BudgetStop: return 'blocked'
    with ThreadPoolExecutor(max_workers=12) as pool: results=list(pool.map(work, range(12)))
    assert results.count('sent') == len(sent) == len(gate.records) == 4
    assert results.count('blocked') == 8


def test_cross_process_lock_and_recovery(gate):
    enable(gate)
    code="""
import sys,json
from pathlib import Path
import httpx
from scripts.naiwa_freeze_gate_20261021 import FinalRoundGate,SCENE,BudgetStop
from backend.chat.http_clients import CALL,server_call
CALL.set(server_call('text_completion','Provider.complete'))
g=FinalRoundGate(Path(sys.argv[1]),simulated=True);SCENE.set('AGENT')
try:
 r=g.begin(httpx.Request('POST','https://api.deepseek.com/chat/completions',json={'model':'deepseek-flash','max_tokens':100,'messages':[]}))
 g.finish(r,json.dumps({'choices':[{'finish_reason':'stop'}],'usage':{'prompt_tokens':1,'completion_tokens':1}}).encode(),200)
 print('reserved')
except BudgetStop: print('blocked')
"""
    children=[subprocess.Popen([sys.executable,'-c',code,str(gate.output)],stdout=subprocess.PIPE,stderr=subprocess.PIPE) for _ in range(8)]
    outcomes=[]
    for child in children:
        stdout,stderr=child.communicate(timeout=30)
        assert child.returncode==0,stderr.decode(errors='replace')
        outcomes.append(stdout.decode().strip())
    resumed=FinalRoundGate(gate.output,simulated=True)
    assert len(resumed.records)==outcomes.count('reserved')==4
    assert outcomes.count('blocked')==4


def test_dead_process_unknown_send_never_freed(gate):
    enable(gate)
    code="""
import sys,httpx
from pathlib import Path
from scripts.naiwa_freeze_gate_20261021 import FinalRoundGate,SCENE
from backend.chat.http_clients import CALL,server_call
CALL.set(server_call('text_completion','Provider.complete'))
g=FinalRoundGate(Path(sys.argv[1]),simulated=True);SCENE.set('AGENT')
g.begin(httpx.Request('POST','https://api.deepseek.com/chat/completions',json={'model':'deepseek-flash','max_tokens':100,'messages':[]}))
"""
    subprocess.run([sys.executable,'-c',code,str(gate.output)],check=True,timeout=30)
    resumed=FinalRoundGate(gate.output,simulated=True)
    assert len(resumed.records)==1 and 'unknown' in resumed.stop_reason
    resumed.install()
    try:
        with pytest.raises(BudgetStop):post(resumed)
        assert len(resumed.records)==1
    finally:resumed.uninstall()


def test_real_provider_complete_classifier_stream_tools_and_generation_share(gate,monkeypatch):
    from backend.chat.service import Provider
    def handler(request):
        payload=json.loads(request.content)
        if payload.get('stream'):
            data={'choices':[{'delta':{'content':'中文公式'},'finish_reason':'stop'}],'usage':REPLY['usage']}
            return httpx.Response(200,content=('data: '+json.dumps(data)+'\n\ndata: [DONE]\n\n').encode())
        return httpx.Response(200,json=REPLY)
    transport=httpx.MockTransport(handler)
    monkeypatch.setattr(httpx.Client,'_transport_for_url',lambda self,url:transport)
    monkeypatch.setattr(httpx.AsyncClient,'_transport_for_url',lambda self,url:transport)
    provider=Provider(api_key='not-real',base_url='https://api.deepseek.com',model='deepseek-flash',timeout=5,max_tokens=100,stream_include_usage=True)
    gate.install();enable(gate)
    provider.complete([{'role':'user','content':'stub'}])
    assert provider.classify_retrieval_intent('stub')=='precise'
    async def stream():return ''.join([v async for v in provider.stream([{'role':'user','content':'stub'}])])
    assert asyncio.run(stream())=='中文公式'
    provider.tool_turn([{'role':'user','content':'tool followup'}],[],timeout=5)
    enable(gate,'GENERATE')
    provider.structured_generation=True
    provider.complete([{'role':'user','content':'generation stub'}])
    assert len(gate.records)==5
    assert sum(r['stage']=='classifier' for r in gate.records)==1
    assert all(r.get('usage') for r in gate.records)


def test_async_parallel_streaming_cap(gate):
    gate.install(); enable(gate)
    sent=[]
    async def handler(request):
        sent.append(1);await asyncio.sleep(.02)
        return httpx.Response(200,json=REPLY)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            async def call():
                try:await client.post(URL,json=PAYLOAD);return True
                except BudgetStop:return False
            return await asyncio.gather(*(call() for _ in range(9)))
    assert sum(asyncio.run(run()))==len(sent)==4


def test_legacy_send_wrappers_cannot_bypass_lower_gate(gate,monkeypatch):
    original=httpx.Client.send
    # Old 19/5/7 wrappers all patch Client.send, above the new interception point.
    for _ in range(3):
        before=original
        def wrapper(self,request,*args,_before=before,**kwargs):return _before(self,request,*args,**kwargs)
        original=wrapper
    monkeypatch.setattr(httpx.Client,'send',original)
    gate.install()
    with httpx.Client(transport=httpx.MockTransport(lambda r:pytest.fail('bypass'))) as client:
        with pytest.raises(BudgetStop):client.post(URL,json=PAYLOAD)
    assert gate.records==[]


def test_retries_proxy_redirects_and_alternate_models_block(gate):
    gate.install();enable(gate)
    with httpx.Client(transport=httpx.HTTPTransport(retries=2)) as client:
        with pytest.raises(BudgetStop,match='retries'):client.post(URL,json=PAYLOAD)
    assert gate.records==[]
    enable(gate)
    with httpx.Client(transport=httpx.MockTransport(lambda r:pytest.fail('other model'))) as client:
        with pytest.raises(BudgetStop):client.post(URL,json={**PAYLOAD,'model':'other'})
    assert gate.records==[]


def test_socket_guard_blocks_nonmodel_and_raw_bypasses(gate):
    for address in [('192.0.2.1',443),('127.0.0.1',8000),('127.0.0.1',5433),('127.0.0.1',63045)]:
        with pytest.raises(BudgetStop):gate.socket_guard('socket.connect',(None,address))
    with pytest.raises(BudgetStop):gate.socket_guard('socket.getaddrinfo',('api.deepseek.com',443))
    gate.socket_guard('socket.connect',(None,('127.0.0.1',63044)))


def test_constructor_preserves_existing_ledger_bytes(gate):
    before=gate.path.read_bytes()
    FinalRoundGate(gate.output,simulated=True)
    assert gate.path.read_bytes()==before


def test_older_ledger_directory_is_rejected():
    with pytest.raises(ValueError):FinalRoundGate(Path('storage/quality-audits/naiwa-real-20261020'))


@pytest.mark.parametrize('asynchronous',[False,True])
def test_chunked_sse_usage_is_counted_once(gate,asynchronous):
    data=('data: '+json.dumps(REPLY)+'\n\ndata: [DONE]\n\n').encode()
    class Sync(httpx.SyncByteStream):
        def __iter__(self):
            for index in range(0,len(data),7):yield data[index:index+7]
    class Async(httpx.AsyncByteStream):
        async def __aiter__(self):
            for index in range(0,len(data),7):yield data[index:index+7]
    gate.install();enable(gate)
    if asynchronous:
        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,stream=Async()))) as client:
                async with client.stream('POST',URL,json=PAYLOAD) as response:assert await response.aread()==data
        asyncio.run(run())
    else:
        with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,stream=Sync()))) as client:
            with client.stream('POST',URL,json=PAYLOAD) as response:assert response.read()==data
    assert len(gate.records)==1 and gate.records[0]['usage']==REPLY['usage']


def test_actual_network_transport_is_blocked_before_any_dispatch(gate):
    gate.install()
    # HTTPTransport, not MockTransport. The closed gate must prevent invoking it.
    with httpx.Client(transport=httpx.HTTPTransport(retries=0),trust_env=False) as client:
        with pytest.raises(BudgetStop,match='closed'):client.post(URL,json=PAYLOAD)
    assert gate.records==[]


def test_automatic_provider_retry_is_rejected_before_count(gate,monkeypatch):
    from backend.chat.service import Provider
    from backend.errors import AppError
    from scripts.naiwa_freeze_gate_20261021 import disable_provider_retries
    class IsolatedProvider(Provider):pass
    disable_provider_retries(IsolatedProvider)
    provider=IsolatedProvider(api_key='stub',base_url='https://api.deepseek.com',model='deepseek-flash',timeout=1,max_tokens=100)
    gate.install();enable(gate)
    with pytest.raises(AppError) as result:provider.complete([],attempt=2)
    assert result.value.retryable is False and gate.records==[]


def test_redirect_does_not_hide_second_physical_request(gate):
    gate.install();enable(gate)
    sent=[]
    def handler(request):
        sent.append(request.url.path)
        return httpx.Response(307,headers={'location':'https://example.invalid/redirect'})
    with httpx.Client(transport=httpx.MockTransport(handler),follow_redirects=True) as client:
        with pytest.raises(BudgetStop):client.post(URL,json=PAYLOAD)
    assert sent==['/chat/completions'] and len(gate.records)==1


def test_alternative_local_provider_cannot_bypass(gate):
    gate.install();enable(gate)
    with httpx.Client(transport=httpx.MockTransport(lambda r:pytest.fail('local provider bypass'))) as client:
        with pytest.raises(BudgetStop):client.post('http://127.0.0.1:9/chat/completions',json=PAYLOAD)
    assert gate.records==[]


def test_missing_finish_reason_stops_next_dispatch(gate):
    gate.install()
    post(gate,handler=lambda r:httpx.Response(200,json={'usage':REPLY['usage']}))
    assert len(gate.records)==1 and 'finish_reason_unknown' in gate.stop_reason
    with pytest.raises(BudgetStop):post(gate)


def test_windows_asyncio_ipc_does_not_open_model_egress(gate):
    code="""
import sys,asyncio
from pathlib import Path
from scripts.naiwa_freeze_gate_20261021 import FinalRoundGate,BudgetStop
gate=FinalRoundGate(Path(sys.argv[1]),simulated=True)
sys.addaudithook(gate.socket_guard)
loop=asyncio.new_event_loop();loop.close()
try:sys.audit('socket.connect',None,('192.0.2.1',443))
except BudgetStop:pass
else:raise AssertionError('external socket not blocked')
assert gate.records==[]
"""
    subprocess.run([sys.executable,'-c',code,str(gate.output)],check=True,timeout=30)


@pytest.mark.parametrize('asynchronous',[False,True])
def test_proxy_refusal_before_physical_dispatch(gate,monkeypatch,asynchronous):
    def forbidden(*args,**kwargs):pytest.fail('proxy transport must not be invoked')
    async def async_forbidden(*args,**kwargs):pytest.fail('async proxy transport must not be invoked')
    monkeypatch.setattr(httpx.HTTPTransport,'handle_request',forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport,'handle_async_request',async_forbidden)
    gate.install();enable(gate)
    if asynchronous:
        async def run():
            async with httpx.AsyncClient(proxy='http://127.0.0.1:9',trust_env=False) as client:
                with pytest.raises(BudgetStop,match='proxy_not_allowed'):await client.post(URL,json=PAYLOAD)
        asyncio.run(run())
    else:
        with httpx.Client(proxy='http://127.0.0.1:9',trust_env=False) as client:
            with pytest.raises(BudgetStop,match='proxy_not_allowed'):client.post(URL,json=PAYLOAD)
    assert gate.records==[]
