"""Independent acceptance assertions; failures are retained, never xfail/skip.

All sends terminate in MockTransport or memory streams. No OS resolver/network.
"""
import asyncio,json,socket,os
from pathlib import Path
import httpx,pytest
from tests.unit.test_dns_audit_phases import gate,SETTINGS,PAYLOAD,REPLY,URL
from backend.chat import http_clients
from scripts.naiwa_freeze_gate_20261021 import TICKET,BudgetStop
from tests.unit.provider_http_test_support import configure_owned_test_provider_http
OUT=Path('storage/quality-audits/naiwa-dns-independent-review-20261021')

def evidence(name,value):
    if OUT.exists():(OUT/(name+'.json')).write_text(json.dumps(value,indent=2,default=str),encoding='utf-8')

@pytest.mark.parametrize('address',['224.0.0.1','239.1.1.1','ff02::1'])
def test_dns_multicast_must_be_rejected_before_connect(gate,monkeypatch,address):
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(socket.AF_INET,socket.SOCK_STREAM,6,'',(address,443))])
    gate.install();record=gate.begin(httpx.Request('POST',URL,json=PAYLOAD));cap=gate.activate(record);token=TICKET.set(cap)
    blocked=False
    try:
        try:
            socket.getaddrinfo('api.deepseek.com',443)
            gate.socket_guard('socket.connect',(None,(address,443)))
        except BudgetStop:blocked=True
        evidence('multicast-'+address.replace(':','_'),{'address':address,'blocked':blocked,
            'approved_ips':sorted(gate.capabilities[cap]['ips']),'record':gate.records[0],
            'simulation':True,'os_dns_connections':0})
        assert blocked,'multicast DNS answer and connect authorization were accepted'
        assert address not in gate.capabilities[cap]['ips']
    finally:gate.capabilities.pop(cap,None);TICKET.reset(token)

@pytest.mark.parametrize('asynchronous',[False,True])
def test_unapproved_visual_payload_cannot_borrow_agent_scene(gate,monkeypatch,asynchronous):
    seen=[]
    def handler(request):seen.append(json.loads(request.content));return httpx.Response(200,json=REPLY)
    mock=httpx.MockTransport(handler)
    monkeypatch.setattr(httpx.HTTPTransport,'handle_request',lambda self,r:mock.handle_request(r))
    async def async_handler(self,r):return await mock.handle_async_request(r)
    monkeypatch.setattr(httpx.AsyncHTTPTransport,'handle_async_request',async_handler)
    configure_owned_test_provider_http();gate.install()
    payload={**PAYLOAD,'messages':[{'role':'user','content':[{'type':'text','text':'review visual path'},
        {'type':'image_url','image_url':{'url':'data:image/png;base64,dGVzdA=='}}]}]}
    blocked=False
    try:
        if asynchronous:
            async def run():
                async with http_clients.async_client() as client:return await client.post(URL,json=payload)
            asyncio.run(run())
        else:
            with http_clients.sync_client() as client:client.post(URL,json=payload)
    except BudgetStop:blocked=True
    evidence('visual-'+str(asynchronous),{'blocked':blocked,'mock_dispatches':len(seen),
        'reservations':len(gate.records),'records':gate.records,'simulation':True,'external_requests':0})
    assert blocked and not seen,'unapproved vision payload reached shared model transport using AGENT scope'
    assert gate.records==[],'unapproved request must not consume an authorized text request slot'

@pytest.mark.parametrize('revocation',['closed','expired'])
def test_revoked_ticket_must_block_before_http_headers(gate,monkeypatch,revocation):
    from httpcore._backends.base import NetworkBackend,NetworkStream
    writes=[];raw=json.dumps(REPLY).encode()
    response=b'HTTP/1.1 200 OK\r\nContent-Length: '+str(len(raw)).encode()+b'\r\nConnection: close\r\n\r\n'+raw
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',443))])
    class MemoryStream(NetworkStream):
        def __init__(self):self.data=response
        def read(self,*a,**k):value=self.data;self.data=b'';return value
        def write(self,data,*a,**k):writes.append(bytes(data))
        def close(self):pass
        def start_tls(self,*a,**k):
            # Controlled boundary after approved DNS/TCP, before real httpcore
            # starts serializing/writing request headers. No actual TLS occurs.
            if revocation=='closed':gate.seal('independent_review_closed_before_http_write')
            else:gate.capabilities[TICKET.get()]['expires']=0
            return self
    class MemoryBackend(NetworkBackend):
        def connect_tcp(self,host,port,**kw):
            addresses=socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)
            gate.socket_guard('socket.connect',(None,addresses[0][4]));return MemoryStream()
    configure_owned_test_provider_http();gate.install();blocked=False
    with http_clients.sync_client() as client:
        client._transport._pool._network_backend=MemoryBackend()
        try:client.post(URL,json=PAYLOAD)
        except BudgetStop:blocked=True
    evidence('revoked-'+revocation,{'blocked':blocked,'memory_write_count':len(writes),
        'first_memory_write':writes[0].decode(errors='replace') if writes else None,
        'records':gate.records,'simulation':True,'real_dns_tls_http_requests':0})
    assert blocked and not writes,'closed/expired authorization still reached HTTP request serialization/write'

def test_ticket_from_other_process_identity_is_denied(gate):
    record=gate.begin(httpx.Request('POST',URL,json=PAYLOAD));cap=gate.activate(record);token=TICKET.set(cap)
    try:
        gate.capabilities[cap]['pid']=os.getpid()+1
        assert gate.active_ticket() is None
        with pytest.raises(BudgetStop):gate.socket_guard('socket.getaddrinfo',('api.deepseek.com',443))
        with pytest.raises(BudgetStop):gate.socket_guard('socket.connect',(None,('93.184.216.34',443)))
    finally:gate.capabilities.pop(cap,None);TICKET.reset(token)
