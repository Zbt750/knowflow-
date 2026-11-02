"""Shared model HTTP construction; daily defaults unchanged, isolation explicit."""
import httpx
import os
import contextvars
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
import inspect
import re

_isolated_direct = False
_CALL_SEAL=object()
CALL=contextvars.ContextVar('server_model_call_purpose',default=None)

@dataclass(frozen=True)
class _ServerCall:
    purpose:str
    entry:str
    seal:object

def server_call(purpose,entry):
    """Trusted Python call-site metadata, never read from HTTP headers/body."""
    allowed={'Provider.complete':{'text_completion','variant_generation'},
        'Provider.tool_turn':{'agent_text'},'Provider.stream':{'text_stream'},
        'Provider.classify_retrieval_intent':{'classification'},'vision_recognition':{'vision'}}
    if purpose not in allowed.get(entry,set()):raise ValueError('invalid_server_model_call')
    return _ServerCall(purpose,entry,_CALL_SEAL)

def current_call():
    value=CALL.get()
    return value if isinstance(value,_ServerCall) and value.seal is _CALL_SEAL else None

@contextmanager
def call_purpose(purpose,entry):
    token=CALL.set(server_call(purpose,entry))
    try:yield
    finally:CALL.reset(token)

def call_entry(kind):
    """Label the real service entry; does not change daily HTTP defaults."""
    def decorate(fn):
        entry='Provider.'+fn.__name__
        def purpose(self):
            if kind=='completion':
                outer=current_call()
                return 'variant_generation' if self.structured_generation or (outer and outer.purpose=='variant_generation') else 'text_completion'
            return kind
        if inspect.isasyncgenfunction(fn):
            @wraps(fn)
            async def stream(self,*args,**kwargs):
                with call_purpose(purpose(self),entry):
                    async for value in fn(self,*args,**kwargs):yield value
            return stream
        @wraps(fn)
        def invoke(self,*args,**kwargs):
            with call_purpose(purpose(self),entry):return fn(self,*args,**kwargs)
        return invoke
    return decorate


def configure_isolated_provider_http(settings, *, verified_fresh_identity=None):
    """Process-only opt-in, never an OS proxy or daily configuration change."""
    from sqlalchemy.engine import make_url
    url = make_url(str(settings.active_database_url))
    retained_port = int(os.environ.get('NAIWA_RETAINED_EXPERIENCE_PORT', '0') or 0)
    retained_database = os.environ.get('NAIWA_RETAINED_EXPERIENCE_DATABASE', '')
    retained_experience = bool(retained_port and retained_database) and (
        url.host, url.port, url.database) == ('127.0.0.1', retained_port, retained_database)
    fresh_test = False
    if verified_fresh_identity is not None:
        expected_cluster = os.environ.get('NAIWA_EXPECTED_CLUSTER_ID')
        expected_database = os.environ.get('NAIWA_ISOLATED_DATABASE', '')
        try:
            isolated_port = int(os.environ.get('NAIWA_ISOLATED_PG_PORT', '0'))
        except ValueError:
            isolated_port = 0
        database_name_isolated = (
            expected_database != 'naiwa_experience_test'
            and re.fullmatch(r'[a-z][a-z0-9_]*_test', expected_database) is not None
        )
        fresh_test = (
            settings.app_env == 'test'
            and os.environ.get('NAIWA_FRESH_TEST_DATABASE') == '1'
            and database_name_isolated
            and isolated_port > 18000 and isolated_port not in {5433, 63044}
            and os.environ.get('NAIWA_CLUSTER_ID') == expected_cluster
            and (url.host, url.port, url.database, url.username) ==
                ('127.0.0.1', isolated_port, expected_database, 'kaoyan_app')
            and isinstance(verified_fresh_identity, dict)
            and verified_fresh_identity.get('cluster_id') == expected_cluster
            and verified_fresh_identity.get('database') == expected_database
            and verified_fresh_identity.get('role') == 'kaoyan_app'
            and verified_fresh_identity.get('host') == '127.0.0.1'
            and verified_fresh_identity.get('port') == isolated_port
        )
    if settings.app_env != 'test' or not (retained_experience or fresh_test):
        raise ValueError('isolated_provider_http_requires_owned_experience_database')
    global _isolated_direct
    _isolated_direct = True


def policy():
    return {'scope': 'isolated-process-only' if _isolated_direct else 'unchanged-daily-default',
            'trust_env': False if _isolated_direct else None,
            'follow_redirects': False, 'httpx_transport_retries': 0}


def _options(options):
    if not _isolated_direct:
        return options
    if options.get('proxy') is not None or options.get('trust_env') is True or options.get('follow_redirects') is True:
        raise ValueError('isolated_provider_http_policy_override_refused')
    return {**options, 'trust_env': False, 'follow_redirects': False}


def sync_client(**options):
    return httpx.Client(**_options(options))


def async_client(**options):
    return httpx.AsyncClient(**_options(options))


def post(url, **options):
    # Preserve existing daily convenience-function behavior and test hooks.
    if not _isolated_direct:
        return httpx.post(url, **options)
    timeout = options.pop('timeout', 5.0)
    with sync_client(timeout=timeout) as client:
        return client.post(url, **options)
