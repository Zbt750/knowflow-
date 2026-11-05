import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import sys

import httpx
import pytest

from backend.chat import http_clients
from backend.chat.service import Provider
from backend.errors import AppError
from backend.services.learning_task_service import _model_turn
from backend.services.model_failure import classify_model_failure
from scripts.naiwa_freeze_gate_20261021 import FinalRoundGate,ROUND,SCENE,atomic_json
from scripts.phase5_eval_meter import BudgetStop
from tests.unit.provider_http_test_support import configure_owned_test_provider_http

def no_external(event,args):
    if event=='socket.connect':
        a=args[1]
        if not isinstance(a,tuple) or a[0] not in {'127.0.0.1','::1'}:
            raise AssertionError('external test connection forbidden')
    if event=='socket.getaddrinfo' and args[0] not in {'127.0.0.1','::1','localhost'}:
        raise AssertionError('external test DNS forbidden')
sys.addaudithook(no_external)

SETTINGS=SimpleNamespace(app_env='test',active_database_url='postgresql+psycopg://stub@127.0.0.1:63044/naiwa_experience_test')

@pytest.fixture(autouse=True)
def default_policy(monkeypatch):
    monkeypatch.setattr(http_clients,'_isolated_direct',False)


def pools(client):
    pool=client._transport_for_url(httpx.URL('https://api.deepseek.com/chat/completions'))._pool
    return type(pool).__name__,pool._retries


def test_real_default_factory_inherits_proxy_then_isolation_does_not(monkeypatch):
    monkeypatch.setenv('HTTPS_PROXY','http://127.0.0.1:9');monkeypatch.delenv('NO_PROXY',raising=False)
    with http_clients.sync_client() as client:assert pools(client)[0]=='HTTPProxy'
    async def inspect_default():
        async with http_clients.async_client() as client:assert pools(client)[0]=='AsyncHTTPProxy'
    asyncio.run(inspect_default())
    configure_owned_test_provider_http()
    with http_clients.sync_client() as client:
        assert pools(client)==('ConnectionPool',0)
        assert client.trust_env is False and client.follow_redirects is False
    async def inspect_direct():
        async with http_clients.async_client() as client:
            assert pools(client)==('AsyncConnectionPool',0)
            assert client.trust_env is False and client.follow_redirects is False
    asyncio.run(inspect_direct())


@pytest.mark.parametrize('options',[{'trust_env':True},{'proxy':'http://127.0.0.1:9'},{'follow_redirects':True}])
def test_isolated_factory_refuses_overrides(options):
    configure_owned_test_provider_http()
    with pytest.raises(ValueError):http_clients.sync_client(**options)
    with pytest.raises(ValueError):http_clients.async_client(**options)


def test_policy_cannot_be_enabled_for_daily_database():
    with pytest.raises(ValueError):http_clients.configure_isolated_provider_http(SimpleNamespace(app_env='dev',active_database_url='postgresql://x@127.0.0.1:5433/kaoyan'))
    assert http_clients.policy()['scope']=='unchanged-daily-default'


def test_fresh_disposable_database_requires_verified_exact_identity(monkeypatch):
    monkeypatch.setenv('NAIWA_FRESH_TEST_DATABASE', '1')
    monkeypatch.setenv('NAIWA_ISOLATED_DATABASE', 'naiwa_math_gate_regression2_test')
    monkeypatch.setenv('NAIWA_ISOLATED_PG_PORT', '65014')
    monkeypatch.setenv('NAIWA_EXPECTED_CLUSTER_ID', 'fixture-cluster')
    monkeypatch.setenv('NAIWA_CLUSTER_ID', 'fixture-cluster')
    settings = SimpleNamespace(app_env='test',
        active_database_url='postgresql+psycopg://kaoyan_app:stub@127.0.0.1:65014/naiwa_math_gate_regression2_test')
    verified = {'cluster_id':'fixture-cluster', 'database':'naiwa_math_gate_regression2_test',
        'role':'kaoyan_app', 'host':'127.0.0.1', 'port':65014}

    # No verified live-DB identity means the provider gate remains closed.
    with pytest.raises(ValueError):
        http_clients.configure_isolated_provider_http(settings)
    http_clients.configure_isolated_provider_http(settings, verified_fresh_identity=verified)
    assert http_clients.policy()['trust_env'] is False
    assert http_clients.policy()['follow_redirects'] is False


@pytest.mark.parametrize('database', ['naiwa_experience_test', 'naiwa_differentiated_r12', 'public'])
def test_fresh_database_policy_rejects_retained_or_unmarked_database_names(monkeypatch, database):
    monkeypatch.setenv('NAIWA_FRESH_TEST_DATABASE', '1')
    monkeypatch.setenv('NAIWA_ISOLATED_DATABASE', database)
    monkeypatch.setenv('NAIWA_ISOLATED_PG_PORT', '65014')
    monkeypatch.setenv('NAIWA_EXPECTED_CLUSTER_ID', 'fixture-cluster')
    monkeypatch.setenv('NAIWA_CLUSTER_ID', 'fixture-cluster')
    settings = SimpleNamespace(app_env='test',
        active_database_url=f'postgresql+psycopg://kaoyan_app:stub@127.0.0.1:65014/{database}')
    verified = {'cluster_id':'fixture-cluster', 'database':database,
        'role':'kaoyan_app', 'host':'127.0.0.1', 'port':65014}
    with pytest.raises(ValueError):
        http_clients.configure_isolated_provider_http(settings, verified_fresh_identity=verified)
    assert http_clients.policy()['scope']=='unchanged-daily-default'


@pytest.mark.parametrize('field,value', [
    ('cluster_id','other-cluster'), ('database','naiwa_experience_test'),
    ('role','postgres'), ('host','0.0.0.0'), ('port',5433),
])
def test_fresh_disposable_database_rejects_mismatched_identity(monkeypatch, field, value):
    monkeypatch.setenv('NAIWA_FRESH_TEST_DATABASE', '1')
    monkeypatch.setenv('NAIWA_ISOLATED_DATABASE', 'naiwa_differentiated_test')
    monkeypatch.setenv('NAIWA_ISOLATED_PG_PORT', '64124')
    monkeypatch.setenv('NAIWA_EXPECTED_CLUSTER_ID', 'fixture-cluster')
    monkeypatch.setenv('NAIWA_CLUSTER_ID', 'fixture-cluster')
    settings = SimpleNamespace(app_env='test',
        active_database_url='postgresql+psycopg://kaoyan_app:stub@127.0.0.1:64124/naiwa_differentiated_test')
    verified = {'cluster_id':'fixture-cluster', 'database':'naiwa_differentiated_test',
        'role':'kaoyan_app', 'host':'127.0.0.1', 'port':64124}
    verified[field] = value
    with pytest.raises(ValueError):
        http_clients.configure_isolated_provider_http(settings, verified_fresh_identity=verified)


def test_fresh_disposable_database_rejects_daily_target_even_with_fresh_marker(monkeypatch):
    monkeypatch.setenv('NAIWA_FRESH_TEST_DATABASE', '1')
    monkeypatch.setenv('NAIWA_ISOLATED_DATABASE', 'naiwa_differentiated_test')
    monkeypatch.setenv('NAIWA_ISOLATED_PG_PORT', '64124')
    monkeypatch.setenv('NAIWA_EXPECTED_CLUSTER_ID', 'fixture-cluster')
    monkeypatch.setenv('NAIWA_CLUSTER_ID', 'fixture-cluster')
    settings = SimpleNamespace(app_env='test',
        active_database_url='postgresql+psycopg://kaoyan_app:stub@127.0.0.1:5433/kaoyan')
    verified = {'cluster_id':'fixture-cluster', 'database':'naiwa_differentiated_test',
        'role':'kaoyan_app', 'host':'127.0.0.1', 'port':64124}
    with pytest.raises(ValueError):
        http_clients.configure_isolated_provider_http(settings, verified_fresh_identity=verified)
    assert http_clients.policy()['scope']=='unchanged-daily-default'


def test_daily_sync_convenience_path_unchanged(monkeypatch):
    calls=[]
    monkeypatch.setattr(httpx,'post',lambda *a,**k:calls.append(k) or 'daily-path')
    assert http_clients.post('https://example.invalid',timeout=1)=='daily-path'
    assert calls==[{'timeout':1}]


def test_actual_provider_all_factories_mock_low_transport_share_gate(monkeypatch):
    configure_owned_test_provider_http()
    monkeypatch.setenv('HTTPS_PROXY','http://127.0.0.1:9')
    seen=[]
    usage={'prompt_tokens':10,'completion_tokens':5}
    def handler(request):
        p=json.loads(request.content);seen.append(p)
        if p.get('stream'):
            body={'choices':[{'delta':{'content':'中文'},'finish_reason':'stop'}],'usage':usage}
            return httpx.Response(200,content=('data: '+json.dumps(body)+'\n\ndata: [DONE]\n\n').encode())
        return httpx.Response(200,json={'choices':[{'message':{'content':'precise'},'finish_reason':'stop'}],'usage':usage})
    mock=httpx.MockTransport(handler)
    # Leave actual Client construction, proxy selection and gate intact. Only
    # the final transport handler is substituted, so no external socket exists.
    monkeypatch.setattr(httpx.HTTPTransport,'handle_request',lambda self,request:mock.handle_request(request))
    async def asynchronous(self,request):return await mock.handle_async_request(request)
    monkeypatch.setattr(httpx.AsyncHTTPTransport,'handle_async_request',asynchronous)
    with tempfile.TemporaryDirectory(prefix='real-factory-',dir=ROUND.parent) as folder:
        gate=FinalRoundGate(Path(folder),simulated=True);gate.install()
        def enable(scene):
            http_clients.CALL.set(http_clients.server_call('variant_generation' if scene=='GENERATE' else 'text_completion','Provider.complete'))
            SCENE.set(scene);atomic_json(gate.control,{'paid_enabled':True,'authorization_received':True,'active_scene':scene})
        provider=Provider(api_key='stub-only',base_url='https://api.deepseek.com',model='deepseek-flash',timeout=2,max_tokens=100,stream_include_usage=True)
        try:
            enable('AGENT')
            provider.complete([{'role':'user','content':'fixture'}])
            assert provider.classify_retrieval_intent('fixture')=='precise'
            async def stream():assert ''.join([v async for v in provider.stream([])])=='中文'
            asyncio.run(stream())
            response=provider.tool_turn([],[],timeout=2)
            assert response['transport_diagnostic']['physical_request_attempts']==1
            enable('GENERATE');provider.complete([])
            assert len(gate.records)==len(seen)==5
            assert gate.document['scene_counts']=={'AGENT':4,'GENERATE':1}
            assert all(r['state']=='COMPLETED_USAGE_OBSERVED' for r in gate.records)
        finally:gate.uninstall()


@pytest.mark.parametrize('reason,code',[
    ('proxy_not_allowed','provider_proxy_policy_blocked'),('transport_retries_not_allowed','provider_transport_retry_blocked'),
    ('global_cap5','provider_budget_exhausted'),('scene_cap','provider_budget_exhausted'),
    ('paid_exit_closed_or_scene_unapproved','provider_scene_not_authorized'),
    ('phase1_real_model_exit_permanently_closed','provider_egress_closed'),
    ('unfinished_send_state_unknown_reservation_retained','provider_request_state_unknown'),
    ('secret-proxy://user:password@host','provider_request_state_unknown')])
def test_precise_guard_attribution_is_safe(reason,code):
    class Fault:
        model='fixed-zero-network'
        def tool_turn(self,*args,**kwargs):
            try:raise BudgetStop(reason,diagnostic={'source':'final_round_gate','stage':'pre_send','physical_request_attempts':0,'model_request_sent':False})
            except BudgetStop as error:raise AppError('generation_failed',retryable=True) from error
    calls=[]
    with pytest.raises(AppError) as result:_model_turn(Fault(),[],calls,turn=1,timeout=2)
    assert result.value.detail==code and result.value.retryable is False
    assert calls[0]['error_code']==code and calls[0]['physical_request_attempts']==0
    assert calls[0]['failure']['model_request_sent'] is False
    assert 'password' not in json.dumps(calls)


@pytest.mark.parametrize('error,code',[
    (httpx.ConnectError('private-proxy credential'),'provider_network'),
    (httpx.ReadTimeout('private URL'),'provider_timeout'),
    (httpx.HTTPStatusError('private key',request=httpx.Request('POST','https://example.invalid'),response=httpx.Response(401)),'provider_auth_failed')])
def test_network_timeout_auth_are_not_budget(error,code):
    try:
        try:raise error
        except Exception as cause:raise AppError('generation_failed',retryable=True) from cause
    except AppError as wrapped:failure=classify_model_failure(wrapped)
    assert failure.code==code and failure.physical_request_attempts is None
    assert 'private' not in json.dumps(failure.public_dict())
