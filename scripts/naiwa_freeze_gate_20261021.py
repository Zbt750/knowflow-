"""Isolated final-round transport gate. No CLI or authorization/enable command.

Every HTTPX physical transport dispatch is intercepted, below Client.send so
redirects/auth follow-ups cannot bypass it. Other socket clients fail closed.
Only this round's ledger is writable; all older budgets are irrelevant.
"""
import contextvars
import asyncio
import socket
import ipaddress
import hashlib
import json
import os
import sys
from pathlib import Path
import threading
import time
from uuid import uuid4

import httpx
from filelock import FileLock

from scripts.phase5_eval_meter import Meter, BudgetStop
from scripts.naiwa_transport_guards_20261021 import AuthorizationMutex,SyncWriteGuard,AsyncWriteGuard

ROOT = Path(__file__).resolve().parents[1]
ROUND = ROOT / 'storage/quality-audits/naiwa-freeze-preflight-20261021/round5'
SCENE = contextvars.ContextVar('naiwa_final_round_scene', default=None)
TICKET = contextvars.ContextVar('naiwa_final_round_physical_ticket', default=None)
CAPS = {'AGENT': 4, 'GENERATE': 1}
_PURPOSES = {'agent_text', 'text_completion', 'text_stream', 'classification', 'variant_generation'}
_DEFAULT_PURPOSE_POLICY = {
    'AGENT': {'agent_text', 'text_completion', 'text_stream', 'classification'},
    'GENERATE': {'variant_generation'},
}


def process_started(pid):
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        api.OpenProcess.restype = wintypes.HANDLE
        api.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        api.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = api.OpenProcess(0x1000, False, int(pid))
        if not handle: raise ProcessLookupError(pid)
        values = [wintypes.FILETIME() for _ in range(4)]
        try:
            exit_code = wintypes.DWORD()
            if not api.GetExitCodeProcess(handle, ctypes.byref(exit_code)) or exit_code.value != 259:
                raise ProcessLookupError(pid)
            if not api.GetProcessTimes(handle, *(ctypes.byref(v) for v in values)):
                raise ProcessLookupError(pid)
            return values[0].dwHighDateTime << 32 | values[0].dwLowDateTime
        finally: api.CloseHandle(handle)
    return Path(f'/proc/{int(pid)}/stat').read_text().split(') ', 1)[1].split()[19]


def atomic_json(path, value):
    temporary = path.with_name(path.name + f'.{os.getpid()}.{threading.get_ident()}.tmp')
    with temporary.open('w', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


class FinalRoundGate(Meter):
    def __init__(self, output=ROUND, *, simulated=False, preparation=True,
                 global_limit=5, scene_caps=None, purpose_policy=None,
                 seal_on_scene_cap=True):
        output = Path(output).resolve()
        allowed = ROUND.parent.resolve()
        if not output.is_relative_to(allowed):
            raise ValueError('final_round_may_not_write_older_ledgers')
        if type(global_limit) is not int or not 0 < global_limit <= 40:
            raise ValueError('invalid_final_round_global_limit')
        selected_caps = dict(CAPS if scene_caps is None else scene_caps)
        if (type(seal_on_scene_cap) is not bool or not selected_caps
                or any(not isinstance(name, str) or not name.isupper()
                or type(cap) is not int or cap <= 0 for name, cap in selected_caps.items())
                or sum(selected_caps.values()) < global_limit):
            raise ValueError('invalid_final_round_scene_limits')
        selected_policy = {name: set(values) for name, values in
                           (_DEFAULT_PURPOSE_POLICY if purpose_policy is None else purpose_policy).items()}
        if (set(selected_policy) != set(selected_caps)
                or any(not values or not values <= _PURPOSES for values in selected_policy.values())):
            raise ValueError('invalid_final_round_purpose_policy')
        # The historical round5 ledger is immutable and permanently remains on
        # its original limits. A larger authorization must use a distinct path.
        if output == ROUND.resolve() and (global_limit != 5 or selected_caps != CAPS
                or selected_policy != _DEFAULT_PURPOSE_POLICY or not seal_on_scene_cap):
            raise ValueError('historical_round5_configuration_is_immutable')
        output.mkdir(parents=True, exist_ok=True)
        super().__init__(output, max_requests=global_limit)
        self.global_limit = global_limit
        self.scene_caps = selected_caps
        self.purpose_policy = selected_policy
        self.seal_on_scene_cap = bool(seal_on_scene_cap)
        self.simulated, self.preparation = simulated, preparation
        self.path = output / 'provider-ledger.json'
        self.control = output / 'control.json'
        self.disk_lock = FileLock(str(output / 'physical-send.lock'), timeout=10)
        self.authorization=AuthorizationMutex(output/'authorization-write.lock')
        self.installed = False
        self.before_send = None
        # Request capabilities are object identities owned by this gate/process,
        # not integer tickets that an arbitrary thread can synthesize.
        self.capabilities = {}
        with self.authorization.hold(), self.lock, self.disk_lock:
            if not self.path.exists():
                self.document = {'limits': {'max_requests': self.global_limit},
                                 'scene_limits': self.scene_caps,
                                 'purpose_policy': {name: sorted(values) for name, values in self.purpose_policy.items()},
                                 'seal_on_scene_cap': self.seal_on_scene_cap,
                                 'requests': [], 'stop_reason': None}
                self.flush()
            self.reload()
            if not self.control.exists():
                self.seal('authorization_not_received')
            # Never reset a ledger, including one interrupted during an actual send.
            orphaned = [r for r in self.records if not r.get('finished') and not self.owner_alive(r)]
            if orphaned:
                self.stop_reason = 'unfinished_send_state_unknown_reservation_retained'
                self.flush()
                self.seal(self.stop_reason)

    @staticmethod
    def owner_alive(record):
        try:
            return process_started(record['owner_pid']) == record['owner_started']
        except (KeyError, OSError):
            return False

    def reload(self):
        self.document = json.loads(self.path.read_text(encoding='utf-8'))
        if (self.document['limits']['max_requests'] != self.global_limit
                or self.document['scene_limits'] != self.scene_caps
                or self.document.get('purpose_policy', {name: sorted(values) for name, values in
                    _DEFAULT_PURPOSE_POLICY.items()}) !=
                    {name: sorted(values) for name, values in self.purpose_policy.items()}
                or self.document.get('seal_on_scene_cap', True) != self.seal_on_scene_cap):
            raise BudgetStop('ledger_identity_or_limits_invalid')
        self.records = self.document['requests']
        self.stop_reason = self.document.get('stop_reason')
        if (len(self.records) > self.global_limit or [r['number'] for r in self.records] != list(range(1, len(self.records)+1))
                or any(r.get('case_id') not in self.scene_caps for r in self.records)
                or any(sum(r['case_id'] == s for r in self.records) > cap for s, cap in self.scene_caps.items())):
            # Pure validation: do not acquire an authorization lock while a
            # caller holds a ledger lock. Invalid ledgers refuse every send.
            raise BudgetStop('ledger_count_invalid')

    def flush(self):
        self.document.update(requests=self.records, stop_reason=self.stop_reason,
            scene_counts={s: sum(r['case_id'] == s for r in self.records) for s in self.scene_caps},
            summary=self.summary())
        self.document['summary'].update(budget_reservations=len(self.records),
            legacy_actual_requests_semantics='budget_reservations_not_confirmed_http_sends',
            http_dispatch_attempts=sum(any(e['stage']=='http_dispatch_attempted' for e in r.get('phase_events',[])) for r in self.records),
            http_responses_received=sum(any(e['stage']=='http_response_received' for e in r.get('phase_events',[])) for r in self.records))
        atomic_json(self.path, self.document)

    def seal(self, reason):
        with self.authorization.hold():
            atomic_json(self.control, {'paid_enabled': False, 'authorization_received': False,
                'active_scene': None, 'reason': reason, 'time': time.time()})

    async def aseal(self,reason):
        async with self.authorization.ahold():self.seal(reason)

    def refusal(self, reason):
        """Proven pre-dispatch refusal; keep the reason separate from budget use."""
        diagnostic={'source':'final_round_gate','stage':'preflight_rejected',
                    'physical_request_attempts':0,'model_request_sent':False,'budget_reservations':0,
                    'transport_handler_attempts':0,'http_dispatch_attempts':0}
        import re
        safe_reason=reason if isinstance(reason,str) and re.fullmatch('[a-z0-9_]{1,100}',reason) else 'unknown_guard_stop'
        with self.lock:
            with (self.output/'blocked-before-send.jsonl').open('a',encoding='utf-8') as log:
                log.write(json.dumps({'reason':safe_reason,**diagnostic,'time':time.time()})+'\n')
        return BudgetStop(safe_reason,diagnostic=diagnostic)

    def begin(self, request):
        with self.authorization.hold(), self.lock, self.disk_lock:
            self.reload()
            state = json.loads(self.control.read_text(encoding='utf-8'))
            scene = SCENE.get()
            if self.preparation and not self.simulated:
                raise self.refusal('phase1_real_model_exit_permanently_closed')
            if not (state.get('paid_enabled') and state.get('authorization_received')):
                raise self.refusal('paid_exit_closed')
            if not (scene in self.scene_caps and state.get('active_scene') == scene):
                raise self.refusal('scene_not_authorized')
            if self.stop_reason:
                raise self.refusal(self.stop_reason)
            if len(self.records) >= self.global_limit:
                reason = 'global_cap5' if self.global_limit == 5 else 'authorized_budget_stop'
                self.seal(reason); raise self.refusal(reason)
            if sum(r['case_id'] == scene for r in self.records) >= self.scene_caps[scene]:
                if self.seal_on_scene_cap:
                    self.seal('scene_cap')
                raise self.refusal('scene_cap')
            # A new process must not ignore an earlier process's ambiguous send.
            if any(not r.get('finished') and not self.owner_alive(r) for r in self.records):
                self.stop_reason = 'unfinished_send_state_unknown_reservation_retained'
                self.flush(); self.seal(self.stop_reason); raise BudgetStop(self.stop_reason)
            if (request.method != 'POST' or request.url.scheme != 'https'
                    or request.url.host != 'api.deepseek.com' or (request.url.port or 443) != 443
                    or request.url.path != '/chat/completions'):
                self.seal('destination_or_request_shape_not_allowed')
                raise self.refusal('destination_or_request_shape_not_allowed')
            try:
                payload = json.loads(request.content)
                assert payload['model'] == 'deepseek-flash'
                assert type(payload['max_tokens']) is int and 0 < payload['max_tokens'] <= 8000
                assert len(request.content) <= 62000
            except (ValueError, KeyError, AssertionError):
                self.seal('request_contract_invalid'); raise self.refusal('request_contract_invalid')
            from backend.chat.http_clients import current_call
            purpose=current_call()
            if purpose is None or purpose.purpose not in self.purpose_policy[scene]:
                raise self.refusal('model_purpose_not_authorized')
            if not self.text_request_shape(payload):
                raise self.refusal('model_purpose_shape_mismatch')
            if self.before_send:
                try: self.before_send(scene, request)
                except BaseException:
                    self.seal('pre_send_integrity_failed'); raise
            record = {'number': len(self.records)+1, 'case_id': scene, 'stage':
                'classifier' if payload['max_tokens'] == 48 else scene.lower(),
                'state': 'RESERVED_BEFORE_SEND', 'request_model': payload['model'],
                'request': payload, 'request_sha256': hashlib.sha256(request.content).hexdigest(),
                'request_bytes': len(request.content), 'input_reservation': len(request.content)+2048,
                'output_limit': payload['max_tokens'], 'output_reservation': 8000,
                'conservative_cny': float((len(request.content)+2048)*self.input_cost_per_token+8000*self.output_cost_per_token),
                'started_at': time.time(), 'started_monotonic': time.monotonic(),
                'owner_pid': os.getpid(), 'owner_started': process_started(os.getpid())}
            record.update(request_id=str(uuid4()), scene_id=scene,
                client='httpx physical single request', method=request.method,
                endpoint=str(request.url), retries=0,
                purpose=purpose.purpose,service_entry=purpose.entry,
                budget_reservations=1,transport_handler_attempts=0,http_dispatch_attempts=0,
                phase_events=[{'stage':'reservation_created','time':time.time(),'simulated':self.simulated}])
            self.records.append(record)
            self.flush()  # fsync + atomic rename BEFORE any physical transport dispatch.
            return record

    def phase(self, number, stage, **evidence):
        assert stage in {'dns_attempted','connection_attempted','http_dispatch_attempted',
                         'http_response_received','request_state_unknown'}
        with self.lock, self.disk_lock:
            self.reload()
            row=next(r for r in self.records if r['number']==number)
            row.setdefault('phase_events',[]).append({'stage':stage,'time':time.time(),
                'simulated':self.simulated,**evidence})
            row['http_dispatch_attempts']=int(any(e['stage']=='http_dispatch_attempted' for e in row['phase_events']))
            self.flush()

    def transport_entered(self,record):
        with self.lock,self.disk_lock:
            self.reload();row=next(r for r in self.records if r['number']==record['number'])
            row['transport_handler_attempts']=1
            self.flush()

    def activate(self, record):
        capability=object()
        self.capabilities[capability]={'number':record['number'],'scene':record['case_id'],
            'request_id':record['request_id'],'pid':os.getpid(),'expires':time.monotonic()+300,'ips':set()}
        return capability

    def owned_ticket(self):
        cap=TICKET.get()
        try:value=self.capabilities.get(cap)
        except TypeError:return None
        return value if value and value['pid']==os.getpid() else None

    def active_ticket(self):
        value=self.owned_ticket()
        if not value or value['expires']<time.monotonic():return None
        row=next((r for r in self.records if r['number']==value['number']),None)
        if not row or row.get('finished') or row.get('request_id')!=value['request_id']:return None
        state=json.loads(self.control.read_text(encoding='utf-8'))
        if ((self.preparation and not self.simulated) or not state.get('paid_enabled')
                or not state.get('authorization_received') or state.get('active_scene')!=value['scene']
                or SCENE.get()!=value['scene']):return None
        return value

    @staticmethod
    def text_request_shape(payload):
        keys={'model','messages','max_tokens','temperature','stream','stream_options','tools','tool_choice',
              'thinking','reasoning_effort','response_format'}
        if set(payload)-keys or not isinstance(payload.get('messages'),list):return False
        for message in payload['messages']:
            if not isinstance(message,dict) or set(message)-{'role','content','name','tool_call_id','tool_calls','function_call','refusal'}:return False
            content=message.get('content')
            if isinstance(content,list):
                if any(not isinstance(p,dict) or set(p)!={'type','text'} or p['type']!='text' or not isinstance(p['text'],str) for p in content):return False
            elif content is not None and not isinstance(content,str):return False
        return True

    @staticmethod
    def allowed_address(raw):
        try:address=ipaddress.ip_address(raw)
        except ValueError:return None
        # Mapped IPv6 is refused as a representation, not canonicalised into a
        # different sockaddr that might escape the reviewed connect identity.
        if isinstance(address,ipaddress.IPv6Address) and address.ipv4_mapped is not None:return None
        if (not address.is_global or address.is_multicast or address.is_unspecified or address.is_loopback
                or address.is_link_local or address.is_private or address.is_reserved):return None
        return str(address)

    def authorize_write(self):
        with self.lock,self.disk_lock:self.reload()
        value=self.active_ticket()
        if not value:
            owned=self.owned_ticket()
            diag={'source':'final_round_gate','stage':'preflight_rejected','write_rejected':True,
                  'budget_reservations':1 if owned else 0,'physical_request_attempts':0,
                  'model_request_sent':False,'http_dispatch_attempts':0}
            raise BudgetStop('authorization_revoked_before_write',diagnostic=diag)
        return next(r for r in self.records if r['number']==value['number'])

    def mark_write(self,record,size):
        with self.lock,self.disk_lock:
            self.reload();row=next(r for r in self.records if r['number']==record['number'])
            row['write_calls_attempted']=row.get('write_calls_attempted',0)+1
            row['write_bytes_attempted']=row.get('write_bytes_attempted',0)+size
            first=not row.get('http_dispatch_attempts')
            if first:row.setdefault('phase_events',[]).append({'stage':'http_dispatch_attempted','time':time.time(),
                'simulated':self.simulated,'evidence':'guarded_stream_write','bytes_requested':size})
            row['http_dispatch_attempts']=1;self.flush()

    @staticmethod
    def dns_host(host):
        if isinstance(host,bytes):
            try:host=host.decode('ascii')
            except UnicodeDecodeError:return None
        return host if isinstance(host,str) else None

    def diagnostic(self, record, *, rejected=False):
        with self.lock,self.disk_lock:
            self.reload();row=next(r for r in self.records if r['number']==record['number'])
            stages=[e['stage'] for e in row.get('phase_events',[])]
        dispatched='http_dispatch_attempted' in stages
        response='http_response_received' in stages
        return {'source':'final_round_gate','stage':stages[-1] if stages else 'request_state_unknown',
            'physical_request_attempts':1 if dispatched or response else 0 if rejected else None,
            'model_request_sent':True if response and not self.simulated else False if rejected and not dispatched else None,
            'request_id':record['request_id'],'simulated':self.simulated,'budget_reservations':1,
            'transport_handler_attempts':1,'http_dispatch_attempts':int(dispatched),'phase_evidence':stages}

    def audit_error(self,reason,stage):
        """Evidence from the audit callback/result check, never exception-name inference."""
        ticket=self.owned_ticket()
        diagnostic={'source':'final_round_gate','stage':stage,'audit_rejected':True,
            'physical_request_attempts':0,'model_request_sent':False,
            'budget_reservations':1 if ticket else 0,'http_dispatch_attempts':0,
            'phase_evidence':[stage]}
        return BudgetStop(reason,diagnostic=diagnostic)

    def failed_transport(self,record,error):
        evidence=getattr(error,'diagnostic',None)
        rejected=bool(isinstance(evidence,dict) and evidence.get('source')=='final_round_gate'
            and (evidence.get('audit_rejected') is True or evidence.get('write_rejected') is True))
        if rejected:
            with self.lock,self.disk_lock:
                self.reload();row=next(r for r in self.records if r['number']==record['number'])
                latest=row['phase_events'][-1]['stage']
            if evidence.get('audit_rejected') and latest!=evidence['stage']:
                self.phase(record['number'],evidence['stage'],allowed=False,evidence='audit_refusal_propagated')
        else:self.phase(record['number'],'request_state_unknown',evidence='exception_without_delivery_proof')
        error.transport_diagnostic=self.diagnostic(record,rejected=rejected)
        self.finish(record,error=error)

    def finish(self, record, *args, **kwargs):
        with self.authorization.hold(), self.lock, self.disk_lock:
            self.reload()
            current = next(r for r in self.records if r['number'] == record['number'])
            if current.get('finished'):
                return
            try:
                super().finish(current, *args, **kwargs)
            except BaseException:
                self.stop_reason = 'response_accounting_unknown_reservation_retained'
                self.flush(); self.seal(self.stop_reason)
                raise
            error=kwargs.get('error')
            if error is not None:
                diagnostic=getattr(error,'transport_diagnostic',None)
                if isinstance(diagnostic,dict) and diagnostic.get('source')=='final_round_gate':
                    current['transport_diagnostic']=diagnostic
            if current.get('error_type') or (current.get('http_status') or 599) >= 400:
                self.stop_reason = 'network_or_provider_error_reservation_retained'
            if current.get('http_status') == 200 and not current.get('finish_reason'):
                self.stop_reason = 'finish_reason_unknown_reservation_retained'
            if self.stop_reason:
                self.seal(self.stop_reason)
            elif len(self.records) >= self.global_limit:
                self.seal('global_cap5' if self.global_limit == 5 else 'authorized_budget_stop')
            elif (self.seal_on_scene_cap and
                  sum(r['case_id'] == current['case_id'] for r in self.records) >= self.scene_caps[current['case_id']]):
                self.seal('scene_cap')
            self.flush()

    def _provider_error_records(self):
        # Isolation gate only: pending concurrent reservations are not errors.
        return [r for r in self.records if r.get('finished')]

    async def afinish(self,*args,**kwargs):
        async with self.authorization.ahold():self.finish(*args,**kwargs)

    async def afailed_transport(self,*args,**kwargs):
        async with self.authorization.ahold():self.failed_transport(*args,**kwargs)

    def consumer_stream_closed(self, record, data, status, encoding=None):
        """A consumer may stop at [DONE] before the raw iterator reaches EOF.

        GeneratorExit is lifecycle evidence, not a network failure. Only a
        captured terminal SSE marker together with parsed usage and finish_reason
        proves a complete response. An earlier close remains unknown and sealed.
        """
        self.finish(record, data, status, encoding=encoding)
        with self.lock, self.disk_lock:
            self.reload()
            row=next(r for r in self.records if r['number']==record['number'])
            terminal=any(line.strip()=='data: [DONE]' for line in row.get('response_text','').splitlines())
            complete=bool(terminal and row.get('state')=='COMPLETED_USAGE_OBSERVED'
                and row.get('finish_reason') and isinstance(row.get('usage'),dict))
            if complete:
                row['consumer_closed_after_terminal']=True
                self.flush()
                return True
        self.phase(record['number'],'request_state_unknown',evidence='consumer_closed_before_terminal_usage')
        return False

    async def aconsumer_stream_closed(self,*args,**kwargs):
        async with self.authorization.ahold():return self.consumer_stream_closed(*args,**kwargs)

    def socket_guard(self, event, args):
        """Independent fail-closed guard for requests/urllib/raw sockets too."""
        if event == 'socket.connect':
            address = args[1]
            if isinstance(address, tuple) and len(address) >= 2 and address[0] in {'127.0.0.1', '::1'} and address[1] == 63044:
                return
            # Windows asyncio creates a private local socketpair for event-loop
            # wake-up IPC (tool_turn uses asyncio.run). This is not HTTP egress.
            # Permit only the actual stdlib _make_self_pipe stack, never an
            # arbitrary localhost Provider, database or application connection.
            if isinstance(address, tuple) and address[0] in {'127.0.0.1', '::1'}:
                frame = sys._getframe(1)
                stdlib = (Path(sys.base_prefix)/'Lib/asyncio').resolve()
                while frame:
                    if frame.f_code.co_name == '_make_self_pipe' and Path(frame.f_code.co_filename).resolve().is_relative_to(stdlib):
                        return
                    frame = frame.f_back
            ticket=self.active_ticket()
            allowed=bool(ticket and isinstance(address,tuple) and len(address)>=2
                and address[1]==443 and address[0] in ticket['ips'])
            owned=self.owned_ticket()
            if owned:self.phase(owned['number'],'connection_attempted',allowed=allowed,evidence='socket_audit')
            if allowed:return
            raise self.audit_error('non_database_socket_closed','connection_attempted')
        if event == 'socket.getaddrinfo':
            host=self.dns_host(args[0]);port=args[1]
            if host in {'127.0.0.1', 'localhost', '::1'}:
                return
            ticket=self.active_ticket()
            allowed=bool(ticket and host=='api.deepseek.com' and port==443)
            owned=self.owned_ticket()
            if owned:self.phase(owned['number'],'dns_attempted',allowed=allowed,evidence='socket_audit')
            if allowed:return
            raise self.audit_error('external_dns_closed','dns_attempted')

    def install(self):
        if self.installed:
            return
        gate = self
        self.sync_original = httpx.Client._send_single_request
        self.async_original = httpx.AsyncClient._send_single_request

        # Only a currently registered request's exact allowlisted DNS job gains
        # its copied context. Other executor jobs/threads remain unauthorised.
        self.resolver_original=socket.getaddrinfo
        self.loop_resolver_original=asyncio.BaseEventLoop.getaddrinfo
        def resolve(host,port,*args,**kwargs):
            ticket=gate.active_ticket()
            # Audit before entering even a substituted resolver; native Python
            # also raises the same event before the OS resolver is invoked.
            gate.socket_guard('socket.getaddrinfo',(host,port,0,0,0))
            values=gate.resolver_original(host,port,*args,**kwargs)
            if ticket and gate.dns_host(host)=='api.deepseek.com' and port==443:
                ips=set()
                for value in values:
                    address=gate.allowed_address(value[4][0])
                    if address is None:raise gate.audit_error('dns_result_not_public','dns_attempted')
                    ips.add(address)
                if not ips:raise gate.audit_error('dns_result_empty','dns_attempted')
                ticket['ips'].update(ips)
            return values
        async def loop_resolve(loop,host,port,*,family=0,type=0,proto=0,flags=0):
            if gate.active_ticket() and gate.dns_host(host)=='api.deepseek.com' and port==443:
                ctx=contextvars.copy_context()
                return await loop.run_in_executor(None,ctx.run,
                    lambda:resolve(host,port,family=family,type=type,proto=proto,flags=flags))
            return await gate.loop_resolver_original(loop,host,port,family=family,type=type,proto=proto,flags=flags)
        socket.getaddrinfo=resolve
        asyncio.BaseEventLoop.getaddrinfo=loop_resolve

        def add_trace(request, record, asynchronous=False):
            previous=request.extensions.get('trace')
            def observe(name):
                if name in {'http11.send_request_headers.started','http2.send_request_headers.started'}:
                    with gate.lock,gate.disk_lock:
                        gate.reload();row=next(r for r in gate.records if r['number']==record['number'])
                        row['httpcore_headers_path_entered']=True;gate.flush()
            if asynchronous:
                async def trace(name,info):
                    observe(name)
                    if previous:await previous(name,info)
            else:
                def trace(name,info):
                    observe(name)
                    if previous:previous(name,info)
            request.extensions['trace']=trace

        def check_transport(client, request):
            # Hard-closed preparation never reaches any transport, regardless
            # of whether its pool metadata can be inspected.
            if gate.preparation and not gate.simulated:
                raise gate.refusal('phase1_real_model_exit_permanently_closed')
            transport = client._transport_for_url(request.url)
            pool = getattr(transport, '_pool', None)
            reason = ('transport_retries_not_allowed' if pool and getattr(pool,'_retries',0)!=0 else
                      'proxy_not_allowed' if pool and 'Proxy' in type(pool).__name__ else
                      'transport_boundary_unverified' if (pool and getattr(pool,'_http2',False)) or (pool is None and not gate.simulated) else None)
            if reason:
                gate.seal(reason)
                raise gate.refusal(reason)

        class SyncBody(httpx.SyncByteStream):
            def __init__(self, original, record, response):
                self.original, self.record, self.response, self.data = original, record, response, bytearray()
                self.exhausted = self.failed = False
            def __iter__(self):
                try:
                    for chunk in self.original:
                        self.data.extend(chunk); yield chunk
                except BaseException as error:
                    if isinstance(error,GeneratorExit):
                        raise
                    self.failed = True
                    gate.phase(self.record['number'],'request_state_unknown',evidence='stream_interrupted_usage_unknown')
                    error.transport_diagnostic=gate.diagnostic(self.record)
                    gate.finish(self.record, bytes(self.data), self.response.status_code, error=error,
                        encoding=self.response.headers.get('content-encoding')); raise
                else:
                    self.exhausted = True
                    gate.finish(self.record, bytes(self.data), self.response.status_code,
                        encoding=self.response.headers.get('content-encoding'))
            def close(self):
                try: self.original.close()
                finally:
                    finalize = gate.finish if self.exhausted or self.failed else gate.consumer_stream_closed
                    finalize(self.record, bytes(self.data), self.response.status_code,
                        encoding=self.response.headers.get('content-encoding'))

        class AsyncBody(httpx.AsyncByteStream):
            def __init__(self, original, record, response):
                self.original, self.record, self.response, self.data = original, record, response, bytearray()
                self.exhausted = self.failed = False
            async def __aiter__(self):
                try:
                    async for chunk in self.original:
                        self.data.extend(chunk); yield chunk
                except BaseException as error:
                    if isinstance(error,GeneratorExit):
                        # Response.aclose owns finalization. Starting another
                        # async lock job during loop async-generator shutdown
                        # can leave an unawaited owner and a locked file.
                        raise
                    self.failed = True
                    gate.phase(self.record['number'],'request_state_unknown',evidence='stream_interrupted_usage_unknown')
                    error.transport_diagnostic=gate.diagnostic(self.record)
                    await gate.afinish(self.record, bytes(self.data), self.response.status_code, error=error,
                        encoding=self.response.headers.get('content-encoding')); raise
                else:
                    self.exhausted = True
                    await gate.afinish(self.record, bytes(self.data), self.response.status_code,
                        encoding=self.response.headers.get('content-encoding'))
            async def aclose(self):
                try: await self.original.aclose()
                finally:
                    finalize = gate.afinish if self.exhausted or self.failed else gate.aconsumer_stream_closed
                    await finalize(self.record, bytes(self.data), self.response.status_code,
                        encoding=self.response.headers.get('content-encoding'))

        def sync(client, request):
            check_transport(client, request)
            record = gate.begin(request)
            cap=gate.activate(record);token = TICKET.set(cap)
            add_trace(request,record)
            try:
                gate.transport_entered(record)
                response = gate.sync_original(client, request)
                gate.phase(record['number'],'http_response_received',evidence='httpx_response_object')
                response.extensions['naiwa_transport']=gate.diagnostic(record)
                if response.is_stream_consumed:
                    gate.finish(record, response.content, response.status_code)
                else:
                    response.stream = SyncBody(response.stream, record, response)
                return response
            except BaseException as error:
                gate.failed_transport(record,error);raise
            finally:
                gate.capabilities.pop(cap,None);TICKET.reset(token)

        async def asynchronous(client, request):
            async with gate.authorization.ahold():
                check_transport(client, request)
                record = gate.begin(request)
            cap=gate.activate(record);token = TICKET.set(cap)
            add_trace(request,record,asynchronous=True)
            try:
                gate.transport_entered(record)
                response = await gate.async_original(client, request)
                gate.phase(record['number'],'http_response_received',evidence='httpx_response_object')
                response.extensions['naiwa_transport']=gate.diagnostic(record)
                if response.is_stream_consumed:
                    await gate.afinish(record, response.content, response.status_code)
                else:
                    response.stream = AsyncBody(response.stream, record, response)
                return response
            except BaseException as error:
                await gate.afailed_transport(record,error);raise
            finally:
                gate.capabilities.pop(cap,None);TICKET.reset(token)

        httpx.Client._send_single_request = sync
        httpx.AsyncClient._send_single_request = asynchronous
        from httpcore._sync.http11 import HTTP11Connection
        from httpcore._async.http11 import AsyncHTTP11Connection
        self.sync_event_original=HTTP11Connection._send_event
        self.async_event_original=AsyncHTTP11Connection._send_event
        def send_event(connection,event,timeout):
            if not isinstance(connection._network_stream,SyncWriteGuard):
                connection._network_stream=SyncWriteGuard(gate,connection._network_stream)
            return gate.sync_event_original(connection,event,timeout=timeout)
        async def async_send_event(connection,event,timeout):
            if not isinstance(connection._network_stream,AsyncWriteGuard):
                connection._network_stream=AsyncWriteGuard(gate,connection._network_stream)
            return await gate.async_event_original(connection,event,timeout=timeout)
        HTTP11Connection._send_event=send_event
        AsyncHTTP11Connection._send_event=async_send_event
        self.installed = True

    def uninstall(self):
        if self.installed:
            httpx.Client._send_single_request = self.sync_original
            httpx.AsyncClient._send_single_request = self.async_original
            socket.getaddrinfo=self.resolver_original
            asyncio.BaseEventLoop.getaddrinfo=self.loop_resolver_original
            from httpcore._sync.http11 import HTTP11Connection
            from httpcore._async.http11 import AsyncHTTP11Connection
            HTTP11Connection._send_event=self.sync_event_original
            AsyncHTTP11Connection._send_event=self.async_event_original
            self.installed = False


def disable_provider_retries(provider_class):
    """Acceptance-only: keep application-level failure retries from charging."""
    if getattr(provider_class, '_final_round_no_retry', False):
        return
    from backend.errors import AppError
    complete, stream, tool = provider_class.complete, provider_class.stream, provider_class.tool_turn

    def once_complete(self, messages, *, attempt=1):
        if attempt != 1:
            raise AppError('generation_failed', detail='final_round_automatic_retry_disabled', retryable=False)
        try: return complete(self, messages, attempt=1)
        except AppError as error:
            error.retryable = False; raise

    async def once_stream(self, messages, *, attempt=1):
        if attempt != 1:
            raise AppError('generation_failed', detail='final_round_automatic_retry_disabled', retryable=False)
        try:
            async for chunk in stream(self, messages, attempt=1): yield chunk
        except AppError as error:
            error.retryable = False; raise

    def once_tool(self, *args, **kwargs):
        try: return tool(self, *args, **kwargs)
        except AppError as error:
            error.retryable = False; raise

    provider_class.complete, provider_class.stream, provider_class.tool_turn = once_complete, once_stream, once_tool
    provider_class._final_round_no_retry = True
