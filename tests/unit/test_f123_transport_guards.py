"""F123 regression: controlled memory only, external audit hook inherited."""
import asyncio,json,socket,threading
import httpx,pytest
from tests.unit.test_dns_audit_phases import gate,SETTINGS,PAYLOAD,REPLY,URL
from backend.chat import http_clients
from scripts.naiwa_freeze_gate_20261021 import TICKET,SCENE,BudgetStop,atomic_json
from scripts.naiwa_transport_guards_20261021 import SyncWriteGuard,AsyncWriteGuard
from tests.unit.provider_http_test_support import configure_owned_test_provider_http

@pytest.mark.parametrize('address',['0.0.0.0','127.0.0.1','10.1.2.3','169.254.1.1','100.64.0.1','240.0.0.1',
    '224.0.0.1','239.1.1.1','::','::1','fe80::1','fc00::1','ff02::1','::ffff:93.184.216.34','::ffff:127.0.0.1'])
def test_address_policy_rejects_non_unicast(gate,address):
    assert gate.allowed_address(address) is None

def test_mixed_dns_answers_are_atomic(gate,monkeypatch):
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(2,1,6,'',(a,443)) for a in ['93.184.216.34','224.0.0.1']])
    gate.install();r=gate.begin(httpx.Request('POST',URL,json=PAYLOAD));cap=gate.activate(r);tok=TICKET.set(cap)
    try:
        with pytest.raises(BudgetStop):socket.getaddrinfo('api.deepseek.com',443)
        assert not gate.capabilities[cap]['ips']
    finally:TICKET.reset(tok)

@pytest.mark.parametrize('forged',[None,{'purpose':'agent_text','entry':'Provider.tool_turn'},http_clients._ServerCall('agent_text','Provider.tool_turn',object())])
def test_untrusted_purpose_denied_before_reservation(gate,forged):
    token=http_clients.CALL.set(forged)
    try:
        with pytest.raises(BudgetStop):gate.begin(httpx.Request('POST',URL,json=PAYLOAD,headers={'X-Purpose':'agent_text'}))
        assert gate.records==[]
    finally:http_clients.CALL.reset(token)

def test_vision_service_cannot_borrow_text_context(gate):
    with http_clients.call_purpose('vision','vision_recognition'):
        with pytest.raises(BudgetStop):gate.begin(httpx.Request('POST',URL,json=PAYLOAD))
    assert gate.records==[]

@pytest.mark.parametrize('scene',['AGENT','GENERATE'])
def test_visual_shape_cannot_borrow_either_scene(gate,scene):
    atomic_json(gate.control,{'paid_enabled':True,'authorization_received':True,'active_scene':scene})
    tok=SCENE.set(scene)
    purpose='variant_generation' if scene=='GENERATE' else 'text_completion'
    p={**PAYLOAD,'messages':[{'role':'user','content':[{'type':'image_url','image_url':{'url':'data:mock'}}]}]}
    try:
        with http_clients.call_purpose(purpose,'Provider.complete'):
            with pytest.raises(BudgetStop):gate.begin(httpx.Request('POST',URL,json=p))
        assert gate.records==[]
    finally:SCENE.reset(tok)

def test_unknown_server_entry_cannot_issue_purpose():
    with pytest.raises(ValueError):http_clients.server_call('agent_text','user_supplied_entry')

def test_actual_vision_entry_overrides_inherited_agent(gate,monkeypatch):
    from types import SimpleNamespace
    from backend.services import vision_recognition_service as vision
    seen=[]
    effective=SimpleNamespace(llm_model='deepseek-flash',llm_max_output_tokens=100,
        llm_timeout_seconds=5,llm_base_url='https://api.deepseek.com',
        llm_api_key=SimpleNamespace(get_secret_value=lambda:'TEST-NOT-A-KEY'))
    monkeypatch.setattr(vision,'effective_vision_settings',lambda s:effective)
    monkeypatch.setattr(vision,'normalized_image',lambda data:b'CONTROLLED-TEST-IMAGE')
    async def transport(self,request):seen.append(request);return httpx.Response(200,json=REPLY)
    monkeypatch.setattr(httpx.AsyncHTTPTransport,'handle_async_request',transport)
    configure_owned_test_provider_http();gate.install()
    with http_clients.call_purpose('agent_text','Provider.tool_turn'):
        with pytest.raises(BudgetStop):asyncio.run(vision.recognize_work(SETTINGS,b'test'))
    assert seen==[] and gate.records==[]

def test_plain_text_image_word_is_not_blacklisted(gate):
    p={**PAYLOAD,'messages':[{'role':'user','content':'Explain the literal image_url field as text.'}]}
    assert gate.begin(httpx.Request('POST',URL,json=p))

@pytest.mark.parametrize('asynchronous',[False,True])
@pytest.mark.parametrize('revoke',['closed','expired','valid'])
def test_real_httpcore_memory_tls_boundary(gate,monkeypatch,asynchronous,revoke):
    from httpcore._backends.base import NetworkBackend,NetworkStream,AsyncNetworkBackend,AsyncNetworkStream
    writes=[];body=json.dumps(REPLY).encode()
    raw=b'HTTP/1.1 200 OK\r\nContent-Length: '+str(len(body)).encode()+b'\r\nConnection: close\r\n\r\n'+body
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(2,1,6,'',('93.184.216.34',443))])
    def revoke_now():
        if revoke=='closed':gate.seal('controlled_tls_close')
        elif revoke=='expired':gate.capabilities[TICKET.get()]['expires']=0
    class S(NetworkStream):
        def __init__(self):self.data=raw
        def read(self,*a,**k):v=self.data;self.data=b'';return v
        def write(self,b,*a,**k):writes.append(bytes(b))
        def start_tls(self,*a,**k):revoke_now();return self
        def close(self):pass
        def get_extra_info(self,n):return None
    class A(AsyncNetworkStream):
        def __init__(self):self.data=raw
        async def read(self,*a,**k):v=self.data;self.data=b'';return v
        async def write(self,b,*a,**k):writes.append(bytes(b))
        async def start_tls(self,*a,**k):revoke_now();return self
        async def aclose(self):pass
        def get_extra_info(self,n):return None
    def connect(host,port):
        rows=socket.getaddrinfo(host,port);gate.socket_guard('socket.connect',(None,rows[0][4]))
    class B(NetworkBackend):
        def connect_tcp(self,host,port,**k):connect(host,port);return S()
    class AB(AsyncNetworkBackend):
        async def connect_tcp(self,host,port,**k):connect(host,port);return A()
    configure_owned_test_provider_http();gate.install()
    def sync():
        with http_clients.sync_client() as c:
            c._transport._pool._network_backend=B();return c.post(URL,json=PAYLOAD)
    async def arun():
        async with http_clients.async_client() as c:
            c._transport._pool._network_backend=AB();return await c.post(URL,json=PAYLOAD)
    if revoke=='valid':assert (asyncio.run(arun()) if asynchronous else sync()).status_code==200 and writes
    else:
        with pytest.raises(BudgetStop):asyncio.run(arun()) if asynchronous else sync()
        assert writes==[]

def test_sync_write_and_revoke_are_serialized(gate):
    record=gate.begin(httpx.Request('POST',URL,json=PAYLOAD));cap=gate.activate(record)
    started=threading.Event();release=threading.Event();closed=threading.Event();writes=[];errors=[]
    class S:
        def write(self,b,timeout=None):started.set();assert release.wait(1);writes.append(b)
    def writer():
        tok=TICKET.set(cap);scene=SCENE.set('AGENT')
        try:SyncWriteGuard(gate,S()).write(b'headers')
        except BaseException as e:errors.append(e)
        finally:TICKET.reset(tok);SCENE.reset(scene)
    def closer():gate.seal('concurrent_close');closed.set()
    t=threading.Thread(target=writer);t.start();assert started.wait(1)
    c=threading.Thread(target=closer);c.start();assert not closed.wait(.05)
    release.set();t.join(2);c.join(2);assert not errors and closed.is_set() and writes==[b'headers']
    tok=TICKET.set(cap)
    try:
        with pytest.raises(BudgetStop):SyncWriteGuard(gate,S()).write(b'next')
        assert writes==[b'headers']
    finally:TICKET.reset(tok)

def test_async_write_close_has_no_event_loop_deadlock(gate):
    r=gate.begin(httpx.Request('POST',URL,json=PAYLOAD));cap=gate.activate(r)
    async def run():
        started=asyncio.Event();release=asyncio.Event();writes=[]
        class S:
            async def write(self,b,timeout=None):started.set();await release.wait();writes.append(b)
        async def writer():
            tok=TICKET.set(cap)
            try:await AsyncWriteGuard(gate,S()).write(b'headers')
            finally:TICKET.reset(tok)
        t=asyncio.create_task(writer());await started.wait();close=asyncio.create_task(gate.aseal('async_close'))
        await asyncio.sleep(.03);assert not close.done();release.set();await t;await close
        assert writes==[b'headers']
    asyncio.run(asyncio.wait_for(run(),3))

@pytest.mark.parametrize('asynchronous',[False,True])
def test_pool_reuse_cannot_reuse_previous_write_authorization(gate,monkeypatch,asynchronous):
    from httpcore._backends.base import NetworkBackend,NetworkStream,AsyncNetworkBackend,AsyncNetworkStream
    writes=[];connections=[];body=json.dumps(REPLY).encode()
    raw=b'HTTP/1.1 200 OK\r\nContent-Length: '+str(len(body)).encode()+b'\r\n\r\n'+body
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(2,1,6,'',('93.184.216.34',443))])
    class S(NetworkStream):
        def read(self,*a,**k):return raw
        def write(self,b,*a,**k):writes.append(bytes(b))
        def start_tls(self,*a,**k):return self
        def close(self):pass
        def get_extra_info(self,n):return None
    class A(AsyncNetworkStream):
        async def read(self,*a,**k):return raw
        async def write(self,b,*a,**k):writes.append(bytes(b))
        async def start_tls(self,*a,**k):return self
        async def aclose(self):pass
        def get_extra_info(self,n):return None
    class B(NetworkBackend):
        def connect_tcp(self,*a,**k):connections.append(1);return S()
    class AB(AsyncNetworkBackend):
        async def connect_tcp(self,*a,**k):connections.append(1);return A()
    def trace(name,info):
        if name=='http11.send_request_headers.started':gate.seal('pooled_second_request_revoked')
    async def atrace(name,info):
        if name=='http11.send_request_headers.started':await gate.aseal('pooled_second_request_revoked')
    configure_owned_test_provider_http();gate.install()
    async def arun():
        async with http_clients.async_client() as c:
            c._transport._pool._network_backend=AB()
            assert (await c.post(URL,json=PAYLOAD)).status_code==200
            before=len(writes)
            with pytest.raises(BudgetStop):await c.post(URL,json=PAYLOAD,extensions={'trace':atrace})
            assert len(writes)==before
    if asynchronous:asyncio.run(arun())
    else:
        with http_clients.sync_client() as c:
            c._transport._pool._network_backend=B();assert c.post(URL,json=PAYLOAD).status_code==200
            before=len(writes)
            with pytest.raises(BudgetStop):c.post(URL,json=PAYLOAD,extensions={'trace':trace})
            assert len(writes)==before
    assert connections==[1], 'second request must actually reuse first connection'
