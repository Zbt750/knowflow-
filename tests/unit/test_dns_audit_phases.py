"""No external DNS/socket: real factories/audit logic, controlled OS substitutes."""
import asyncio,contextvars,json,socket,sys,threading,tempfile
from pathlib import Path
from types import SimpleNamespace
import httpx,pytest
from backend.chat import http_clients
from scripts.naiwa_freeze_gate_20261021 import FinalRoundGate,ROUND,SCENE,TICKET,atomic_json,BudgetStop

def deny_external(event,args):
    if event=='socket.getaddrinfo' and args[0] not in {'127.0.0.1','::1','localhost'}:raise AssertionError('test_external_dns_forbidden')
    if event=='socket.connect':
        address=args[1]
        if not isinstance(address,tuple) or address[0] not in {'127.0.0.1','::1'}:raise AssertionError('test_external_socket_forbidden')
sys.addaudithook(deny_external)
URL='https://api.deepseek.com/chat/completions'
PAYLOAD={'model':'deepseek-flash','max_tokens':100,'messages':[]}
REPLY={'choices':[{'message':{'content':'transport fixture only'},'finish_reason':'stop'}],'usage':{'prompt_tokens':1,'completion_tokens':1}}
SETTINGS=SimpleNamespace(app_env='test',active_database_url='postgresql://stub@127.0.0.1:63044/naiwa_experience_test')

@pytest.fixture
def gate(monkeypatch):
    monkeypatch.setattr(http_clients,'_isolated_direct',False)
    with tempfile.TemporaryDirectory(prefix='dns-zero-',dir=ROUND.parent) as folder:
        g=FinalRoundGate(Path(folder),simulated=True,preparation=False)
        atomic_json(g.control,{'paid_enabled':True,'authorization_received':True,'active_scene':'AGENT'})
        token=SCENE.set('AGENT')
        purpose=http_clients.CALL.set(http_clients.server_call('text_completion','Provider.complete'))
        try:yield g
        finally:g.uninstall();SCENE.reset(token);http_clients.CALL.reset(purpose)

def test_actual_async_factory_propagates_ticket_to_dns_executor(gate,monkeypatch):
    observations=[];main=threading.get_ident()
    def controlled_resolver(host,port,*args,**kwargs):
        observations.append({'ticket':TICKET.get() is not None,'worker':threading.get_ident()!=main})
        gate.socket_guard('socket.getaddrinfo',(host,port,0,0,0))
        return [(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',443))]
    monkeypatch.setattr(socket,'getaddrinfo',controlled_resolver)
    async def transport(self,request):
        addresses=await asyncio.get_running_loop().getaddrinfo('api.deepseek.com',443,type=socket.SOCK_STREAM)
        gate.socket_guard('socket.connect',(None,addresses[0][4]))
        return httpx.Response(200,json=REPLY)
    monkeypatch.setattr(httpx.AsyncHTTPTransport,'handle_async_request',transport)
    http_clients.configure_isolated_provider_http(SETTINGS);gate.install()
    async def run():
        async with http_clients.async_client() as client:return await client.post(URL,json=PAYLOAD)
    response=asyncio.run(run())
    assert response.status_code==200 and observations==[{'ticket':True,'worker':True}]

def test_plain_executor_does_not_implicitly_inherit_context():
    value=contextvars.ContextVar('zero-dns-proof',default=None)
    async def run():
        token=value.set('scoped-capability')
        try:
            plain=await asyncio.get_running_loop().run_in_executor(None,value.get)
            copied=await asyncio.get_running_loop().run_in_executor(None,contextvars.copy_context().run,value.get)
            return plain,copied
        finally:value.reset(token)
    assert asyncio.run(run())==(None,'scoped-capability')

@pytest.mark.parametrize('asynchronous',[False,True])
def test_real_httpcore_phases_with_controlled_network_backend(gate,monkeypatch,asynchronous):
    """Real HTTPX -> httpcore -> h11 -> stream.write, never an OS network."""
    from httpcore._backends.base import NetworkBackend,AsyncNetworkBackend,NetworkStream,AsyncNetworkStream
    writes=[];threads=[]
    payload=json.dumps(REPLY).encode()
    raw=b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: '+str(len(payload)).encode()+b'\r\nConnection: close\r\n\r\n'+payload
    def resolver(host,port,*a,**kw):
        threads.append({'thread':threading.get_ident(),'has_ticket':TICKET.get() is not None})
        return [(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',443))]
    monkeypatch.setattr(socket,'getaddrinfo',resolver)
    class Stream(NetworkStream):
        def __init__(self):self.data=raw
        def read(self,*a,**kw):v=self.data;self.data=b'';return v
        def write(self,data,*a,**kw):writes.append(bytes(data))
        def start_tls(self,*a,**kw):return self
        def close(self):pass
    class AStream(AsyncNetworkStream):
        def __init__(self):self.data=raw
        async def read(self,*a,**kw):v=self.data;self.data=b'';return v
        async def write(self,data,*a,**kw):writes.append(bytes(data))
        async def start_tls(self,*a,**kw):return self
        async def aclose(self):pass
    class Backend(NetworkBackend):
        def connect_tcp(self,host,port,**kw):
            addresses=socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)
            gate.socket_guard('socket.connect',(None,addresses[0][4]));return Stream()
    class ABackend(AsyncNetworkBackend):
        async def connect_tcp(self,host,port,**kw):
            addresses=await asyncio.get_running_loop().getaddrinfo(host.encode('ascii'),port,type=socket.SOCK_STREAM)
            gate.socket_guard('socket.connect',(None,addresses[0][4]));return AStream()
    http_clients.configure_isolated_provider_http(SETTINGS);gate.install()
    if asynchronous:
        async def run():
            async with http_clients.async_client() as client:
                client._transport._pool._network_backend=ABackend()
                return await client.post(URL,json=PAYLOAD)
        response=asyncio.run(run())
    else:
        with http_clients.sync_client() as client:
            client._transport._pool._network_backend=Backend()
            response=client.post(URL,json=PAYLOAD)
    assert response.json()==REPLY
    assert writes[0].startswith(b'POST /chat/completions HTTP/1.1')
    assert all(t['has_ticket'] for t in threads)
    stages=[e['stage'] for e in gate.records[0]['phase_events']]
    assert stages==['reservation_created','dns_attempted','connection_attempted','http_dispatch_attempted','http_response_received']
    assert all(e['simulated'] is True for e in gate.records[0]['phase_events'])
    assert gate.document['summary']['budget_reservations']==1
    assert gate.document['summary']['http_dispatch_attempts']==1
    if asynchronous:assert threads[0]['thread']!=threading.get_ident()
    out=Path('storage/quality-audits/naiwa-dns-audit-zero-20261021')
    if out.exists():(out/('phases-async.json' if asynchronous else 'phases-sync.json')).write_text(json.dumps(gate.records[0],indent=2),encoding='utf-8')

@pytest.mark.parametrize('host,port',[('evil.invalid',443),('api.deepseek.com',80),('api.deepseek.com.evil.invalid',443),
                                    (b'api.deepseek.com',80),('API.DEEPSEEK.COM',443)])
def test_wrong_dns_target_denied_before_substitute_resolver(gate,monkeypatch,host,port):
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:pytest.fail('must reject before resolver'))
    gate.install();record=gate.begin(httpx.Request('POST',URL,json=PAYLOAD));cap=gate.activate(record);token=TICKET.set(cap)
    try:
        with pytest.raises(BudgetStop,match='external_dns_closed'):socket.getaddrinfo(host,port)
        assert gate.records[0]['phase_events'][-1]['stage']=='dns_attempted'
        assert gate.records[0]['phase_events'][-1]['allowed'] is False
    finally:gate.capabilities.pop(cap,None);TICKET.reset(token)

@pytest.mark.parametrize('forged',[1,'request-id',object()])
def test_arbitrary_thread_or_numeric_ticket_cannot_authorize(gate,forged):
    token=TICKET.set(forged)
    try:
        with pytest.raises(BudgetStop,match='external_dns_closed'):gate.socket_guard('socket.getaddrinfo',('api.deepseek.com',443))
        with pytest.raises(BudgetStop):gate.socket_guard('socket.connect',(None,('93.184.216.34',443)))
    finally:TICKET.reset(token)

def test_copy_context_is_narrow_and_revoked_after_request(gate,monkeypatch):
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',443))])
    gate.install();record=gate.begin(httpx.Request('POST',URL,json=PAYLOAD));cap=gate.activate(record);token=TICKET.set(cap)
    try:
        context=contextvars.copy_context()
        socket.getaddrinfo('api.deepseek.com',443)
        gate.socket_guard('socket.connect',(None,('93.184.216.34',443)))
        for address in [('8.8.8.8',443),('93.184.216.34',80),('127.0.0.1',9999)]:
            with pytest.raises(BudgetStop):gate.socket_guard('socket.connect',(None,address))
        gate.capabilities.pop(cap)
        with pytest.raises(BudgetStop):context.run(gate.socket_guard,'socket.getaddrinfo',('api.deepseek.com',443))
    finally:gate.capabilities.pop(cap,None);TICKET.reset(token)

def test_manual_executor_without_propagation_still_denied(gate,monkeypatch):
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:pytest.fail('unscoped resolver invoked'))
    gate.install();record=gate.begin(httpx.Request('POST',URL,json=PAYLOAD));cap=gate.activate(record);token=TICKET.set(cap)
    async def run():
        with pytest.raises(BudgetStop,match='external_dns_closed'):
            await asyncio.get_running_loop().run_in_executor(None,socket.getaddrinfo,'api.deepseek.com',443)
    try:asyncio.run(run())
    finally:gate.capabilities.pop(cap,None);TICKET.reset(token)

@pytest.mark.parametrize('address',['127.0.0.1','10.0.0.5','169.254.169.254','::1'])
def test_dns_rebinding_private_addresses_rejected(gate,monkeypatch,address):
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(socket.AF_INET,socket.SOCK_STREAM,6,'',(address,443))])
    gate.install();record=gate.begin(httpx.Request('POST',URL,json=PAYLOAD));cap=gate.activate(record);token=TICKET.set(cap)
    try:
        with pytest.raises(BudgetStop,match='dns_result_not_public'):socket.getaddrinfo('api.deepseek.com',443)
        assert gate.capabilities[cap]['ips']==set()
    finally:gate.capabilities.pop(cap,None);TICKET.reset(token)

def test_reserved_dns_refusal_is_not_http_sent(gate,monkeypatch):
    from backend.services.model_failure import classify_model_failure
    async def transport(self,request):
        gate.socket_guard('socket.getaddrinfo',('evil.invalid',443))
        pytest.fail('no HTTP response')
    monkeypatch.setattr(httpx.AsyncHTTPTransport,'handle_async_request',transport)
    http_clients.configure_isolated_provider_http(SETTINGS);gate.install()
    async def run():
        async with http_clients.async_client() as client:
            with pytest.raises(BudgetStop) as caught:await client.post(URL,json=PAYLOAD)
            return caught.value
    error=asyncio.run(run());failure=classify_model_failure(error)
    assert failure.code=='provider_dns_policy_blocked' and failure.stage=='dns_attempted'
    assert failure.model_request_sent is False and failure.physical_request_attempts==0
    assert failure.budget_reservations==1 and failure.http_dispatch_attempts==0
    row=gate.records[0];assert row['http_status'] is None and not row.get('usage') and not row.get('finish_reason')
    assert len(gate.records)==1 and gate.document['summary']['http_dispatch_attempts']==0
    assert not json.loads(gate.control.read_text())['paid_enabled']
    resumed=FinalRoundGate(gate.output,simulated=True,preparation=False)
    assert len(resumed.records)==1
    out=Path('storage/quality-audits/naiwa-dns-audit-zero-20261021')
    if out.exists():(out/'dns-refusal-after-reservation.json').write_text(json.dumps({'diagnostic':failure.public_dict(),'record':row},indent=2),encoding='utf-8')

@pytest.mark.parametrize('event,args,code',[('socket.getaddrinfo',('evil.invalid',443),'provider_dns_policy_blocked'),
        ('socket.connect',(None,('93.184.216.34',443)),'provider_socket_policy_blocked')])
def test_policy_failures_not_budget_or_egress(gate,event,args,code):
    from backend.services.model_failure import classify_model_failure,MESSAGES
    with pytest.raises(BudgetStop) as caught:gate.socket_guard(event,args)
    failure=classify_model_failure(caught.value)
    assert failure.code==code and '预算' not in MESSAGES[code] and '出口已关闭' not in MESSAGES[code]
    assert failure.physical_request_attempts==0 and failure.stage in {'dns_attempted','connection_attempted'}
    assert failure.budget_reservations==0 # actual audit callback, no request reservation

@pytest.mark.parametrize('error,code',[(httpx.ReadTimeout('fixture'),'provider_timeout'),
    (httpx.ConnectError('fixture'),'provider_network')])
def test_unknown_transport_state_never_invents_sent_usage_or_status(gate,error,code):
    from backend.services.model_failure import classify_model_failure
    def handler(request):raise error
    gate.install()
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPError) as caught:client.post(URL,json=PAYLOAD)
    failure=classify_model_failure(caught.value)
    assert failure.code==code and failure.stage=='request_state_unknown'
    assert failure.model_request_sent is None and failure.physical_request_attempts is None
    row=gate.records[0]
    assert row['budget_reservations']==1 and row['transport_handler_attempts']==1
    assert row['http_dispatch_attempts']==0 and row['http_status'] is None
    assert not row.get('usage') and not row.get('finish_reason')
    assert row['transport_diagnostic']['model_request_sent'] is None
    assert not json.loads(gate.control.read_text())['paid_enabled']

def test_preflight_rejection_has_no_reservation_or_http_dispatch(gate):
    from backend.services.model_failure import classify_model_failure
    atomic_json(gate.control,{'paid_enabled':False})
    gate.install()
    with httpx.Client(transport=httpx.MockTransport(lambda r:pytest.fail('closed dispatch'))) as client:
        with pytest.raises(BudgetStop) as caught:client.post(URL,json=PAYLOAD)
    failure=classify_model_failure(caught.value)
    assert failure.code=='provider_egress_closed' and failure.stage=='preflight_rejected'
    assert failure.budget_reservations==0 and failure.http_dispatch_attempts==0
    assert failure.model_request_sent is False and gate.records==[]

def test_dns_diagnostic_flows_through_agent_and_sse_without_db_writes(gate,monkeypatch):
    from backend.services.model_failure import MESSAGES
    from backend.services.learning_task_service import _model_turn
    from backend.errors import AppError
    from backend.services.learning_assistant_service import encode_sse
    def handler(request):gate.socket_guard('socket.getaddrinfo',('wrong.invalid',443))
    class Provider:
        model='zero-network-diagnostic'
        def tool_turn(self,*a,**kw):
            with httpx.Client(transport=httpx.MockTransport(handler)) as client:client.post(URL,json=PAYLOAD)
    gate.install();calls=[]
    with pytest.raises(AppError) as caught:_model_turn(Provider(),[],calls,turn=1,timeout=3)
    assert caught.value.detail=='provider_dns_policy_blocked' and caught.value.retryable is False
    failure=calls[0]['failure'];assert failure['budget_reservations']==1 and failure['physical_request_attempts']==0
    frame=encode_sse('error',{'code':caught.value.detail,'message':MESSAGES[caught.value.detail],
        'retryable':False,'model_failure':failure})
    if isinstance(frame,bytes):frame=frame.decode('utf-8')
    assert 'event: error' in frame and 'provider_dns_policy_blocked' in frame
    assert '预算上限' not in frame and '出口已关闭' not in frame

def test_expired_wrong_scene_and_other_gate_capabilities_are_not_accepted(gate):
    record=gate.begin(httpx.Request('POST',URL,json=PAYLOAD));cap=gate.activate(record);token=TICKET.set(cap)
    try:
        gate.capabilities[cap]['expires']=0
        with pytest.raises(BudgetStop):gate.socket_guard('socket.getaddrinfo',('api.deepseek.com',443))
        gate.capabilities[cap]['expires']=float('inf')
        scene=SCENE.set('GENERATE')
        try:
            with pytest.raises(BudgetStop):gate.socket_guard('socket.getaddrinfo',('api.deepseek.com',443))
        finally:SCENE.reset(scene)
        with tempfile.TemporaryDirectory(dir=ROUND.parent) as folder:
            other=FinalRoundGate(Path(folder),simulated=True,preparation=False)
            atomic_json(other.control,{'paid_enabled':True,'authorization_received':True,'active_scene':'AGENT'})
            with pytest.raises(BudgetStop):other.socket_guard('socket.getaddrinfo',('api.deepseek.com',443))
    finally:gate.capabilities.pop(cap,None);TICKET.reset(token)

def test_parallel_dns_tasks_keep_distinct_request_capabilities(gate,monkeypatch):
    def resolver(host,port,*a,**kw):
        ticket=gate.active_ticket();assert ticket
        return [(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.'+str(30+ticket['number']),443))]
    monkeypatch.setattr(socket,'getaddrinfo',resolver)
    async def handler(self,request):
        value=await asyncio.get_running_loop().getaddrinfo('api.deepseek.com',443,type=socket.SOCK_STREAM)
        await asyncio.sleep(0)
        address=value[0][4];gate.socket_guard('socket.connect',(None,address))
        other=('93.184.216.32' if address[0].endswith('.31') else '93.184.216.31',443)
        with pytest.raises(BudgetStop):gate.socket_guard('socket.connect',(None,other))
        return httpx.Response(200,json=REPLY)
    monkeypatch.setattr(httpx.AsyncHTTPTransport,'handle_async_request',handler)
    http_clients.configure_isolated_provider_http(SETTINGS);gate.install()
    async def one():
        async with http_clients.async_client() as client:return await client.post(URL,json=PAYLOAD)
    async def both():return await asyncio.gather(one(),one())
    assert all(r.status_code==200 for r in asyncio.run(both()))
    assert len(gate.records)==2 and gate.capabilities=={}
    for row in gate.records:
        assert [e['allowed'] for e in row['phase_events'] if e['stage']=='connection_attempted']==[True,False]

def test_http_status_exception_retains_response_phase_evidence(gate):
    from backend.services.model_failure import classify_model_failure
    gate.install()
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(401,json={}))) as client:
        response=client.post(URL,json=PAYLOAD)
        with pytest.raises(httpx.HTTPStatusError) as caught:response.raise_for_status()
    failure=classify_model_failure(caught.value)
    assert failure.code=='provider_auth_failed' and failure.stage=='http_response_received'
    assert failure.budget_reservations==1 and failure.physical_request_attempts==1

def test_actual_audit_hook_blocks_real_external_dns_and_socket_without_os_dispatch(gate):
    """Separate process installs actual sys.audit guard before OS operations."""
    import subprocess
    code='''
import socket,sys
from pathlib import Path
from scripts.naiwa_freeze_gate_20261021 import FinalRoundGate,BudgetStop
gate=FinalRoundGate(Path(sys.argv[1]),simulated=True,preparation=True)
sys.addaudithook(gate.socket_guard)
def absolute_backstop(event,args):
    if event in {'socket.getaddrinfo','socket.connect'}:
        raise AssertionError('independent test backstop: never reach OS network')
sys.addaudithook(absolute_backstop)
for action in [lambda:socket.getaddrinfo('unapproved.invalid',443),lambda:socket.socket().connect(('192.0.2.1',443))]:
    try:action()
    except BudgetStop:pass
    else:raise AssertionError('OS operation was not blocked')
assert gate.records==[]
print('blocked by actual Python audit before OS DNS/connect')
'''
    subprocess.run([sys.executable,'-c',code,str(gate.output)],check=True,timeout=15)

def test_exception_name_alone_does_not_prove_pre_http_dns_refusal(gate):
    def handler(request):raise BudgetStop('external_dns_closed') # no actual audit callback
    gate.install()
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(BudgetStop) as caught:client.post(URL,json=PAYLOAD)
    diagnostic=caught.value.transport_diagnostic
    assert diagnostic['stage']=='request_state_unknown'
    assert diagnostic['model_request_sent'] is None and diagnostic['physical_request_attempts'] is None
    assert diagnostic['budget_reservations']==1

def test_finished_reservation_cannot_keep_dns_capability(gate):
    record=gate.begin(httpx.Request('POST',URL,json=PAYLOAD));cap=gate.activate(record);token=TICKET.set(cap)
    try:
        gate.finish(record,json.dumps(REPLY).encode(),200)
        assert gate.active_ticket() is None
        with pytest.raises(BudgetStop):gate.socket_guard('socket.getaddrinfo',('api.deepseek.com',443))
    finally:gate.capabilities.pop(cap,None);TICKET.reset(token)
