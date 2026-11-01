"""Safe, stable model failure classification; never expose raw exception text."""
from dataclasses import dataclass
import httpx

MESSAGES = {
    'provider_authorization_revoked': '模型请求的写入授权已撤销或过期，已停止后续写入并保留占额；已尝试发送的字节无法撤回，未自动重试。',
    'provider_purpose_not_authorized': '本次模型用途未获授权，请求未发送，也未新增预算占额；未自动重试。',
    'provider_dns_policy_blocked': '模型域名解析被隔离网络审计拒绝，未取得模型回复；已保留占额并停止后续请求。请先检查DNS授权票据，未自动重试。',
    'provider_socket_policy_blocked': '模型连接被隔离网络审计拒绝，未取得模型回复；已保留占额并停止后续请求。请先核对连接授权，未自动重试。',
    'provider_proxy_policy_blocked': '模型请求被当前代理安全策略阻止，尚未发送。请先修复隔离环境的代理配置；没有创建或加入学习计划。',
    'provider_transport_retry_blocked': '模型请求的传输配置不符合禁止自动重试的要求，尚未发送；没有创建或加入学习计划。',
    'provider_scene_not_authorized': '本次模型操作尚未获得对应场景授权，请求未发送；没有创建或加入学习计划。',
    'provider_egress_closed': '当前真实模型出口已关闭，请求未发送；没有创建或加入学习计划。',
    'provider_request_policy_blocked': '模型请求不符合当前安全约束，尚未发送；请检查请求配置，没有创建或加入学习计划。',
    'provider_budget_exhausted': '本轮模型请求已达到授权的总量或场景预算上限，本次请求未发送；没有创建或加入学习计划。',
    'provider_request_state_unknown': '模型请求状态或计费信息尚无法确认，已停止后续请求并保留占额；请先核对记录，没有创建或加入学习计划。',
    'provider_network': '模型连接中断，具体网络原因尚未确定。已保留已读取的工具证据，没有创建或加入学习计划；未自动重试。',
    'provider_timeout': '模型请求超时，是否到达模型服务尚无法确定。已保留工具证据，没有创建或加入学习计划；未自动重试。',
    'provider_auth_failed': '模型授权失败，请检查密钥与模型权限。没有创建或加入学习计划；未自动重试。',
}
REASONS = {
    'authorization_revoked_before_write':'provider_authorization_revoked',
    'authorization_lock_busy':'provider_request_state_unknown',
    'model_purpose_not_authorized':'provider_purpose_not_authorized',
    'model_purpose_shape_mismatch':'provider_purpose_not_authorized',
    'transport_boundary_unverified':'provider_request_policy_blocked',
    'proxy_not_allowed': 'provider_proxy_policy_blocked',
    'transport_retries_not_allowed': 'provider_transport_retry_blocked',
    'hidden_transport_retries_or_proxy_not_allowed': 'provider_request_policy_blocked',
    'global_cap5': 'provider_budget_exhausted', 'scene_cap': 'provider_budget_exhausted',
    'authorized_budget_stop': 'provider_budget_exhausted',
    'scene_physical_request_cap': 'provider_budget_exhausted',
    'paid_exit_closed_or_scene_unapproved': 'provider_scene_not_authorized',
    'scene_not_authorized': 'provider_scene_not_authorized',
    'paid_exit_closed': 'provider_egress_closed',
    'phase1_real_model_exit_permanently_closed': 'provider_egress_closed',
    'single_request_token_bound': 'provider_request_policy_blocked',
    'destination_or_request_shape_not_allowed': 'provider_request_policy_blocked',
    'request_contract_invalid': 'provider_request_policy_blocked',
    'external_dns_closed': 'provider_dns_policy_blocked',
    'dns_result_not_public': 'provider_dns_policy_blocked', 'dns_result_empty': 'provider_dns_policy_blocked',
    'non_database_socket_closed': 'provider_socket_policy_blocked',
    'unfinished_send_state_unknown_reservation_retained':'provider_request_state_unknown',
    'finish_reason_unknown_reservation_retained':'provider_request_state_unknown',
    'usage_not_returned_stop_for_reconciliation':'provider_request_state_unknown',
    'response_accounting_unknown_reservation_retained':'provider_request_state_unknown',
    'ledger_identity_or_limits_invalid':'provider_request_state_unknown',
    'ledger_count_invalid':'provider_request_state_unknown',
}

@dataclass(frozen=True)
class ModelFailure:
    code: str
    reason: str
    stage: str = 'unknown'
    physical_request_attempts: int | None = None
    model_request_sent: bool | None = None
    budget_reservations: int | None = None
    http_dispatch_attempts: int | None = None
    phase_evidence: tuple = ()

    def public_dict(self):
        return {'code': self.code, 'reason': self.reason, 'stage': self.stage,
                'physical_request_attempts': self.physical_request_attempts,
                'model_request_sent': self.model_request_sent,'budget_reservations':self.budget_reservations,
                'http_dispatch_attempts':self.http_dispatch_attempts,'phase_evidence':list(self.phase_evidence)}


def classify_model_failure(exc):
    seen=set();chain=[];cause=exc;diagnostic={}
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause));chain.append(cause)
        value=(getattr(cause,'transport_diagnostic',None) or getattr(cause,'diagnostic',None)
            or (getattr(getattr(cause,'response',None),'extensions',{}) or {}).get('naiwa_transport'))
        if isinstance(value,dict) and value.get('source')=='final_round_gate':diagnostic=value
        cause=cause.__cause__ or cause.__context__
    attempts=diagnostic.get('physical_request_attempts')
    attempts=attempts if type(attempts) is int and 0<=attempts<=1 else None
    sent=diagnostic.get('model_request_sent')
    sent=sent if type(sent) is bool else None
    stage=diagnostic.get('stage')
    stages={'preflight_rejected','reservation_created','dns_attempted','connection_attempted',
            'http_dispatch_attempted','http_response_received','request_state_unknown'}
    stage=stage if stage in stages|{'pre_send','transport_attempted','response_headers_received'} else 'unknown'
    reservations=diagnostic.get('budget_reservations');reservations=reservations if type(reservations) is int and 0<=reservations<=1 else None
    dispatches=diagnostic.get('http_dispatch_attempts');dispatches=dispatches if type(dispatches) is int and 0<=dispatches<=1 else None
    evidence=tuple(s for s in diagnostic.get('phase_evidence',[]) if isinstance(s,str) and s in stages)
    def failure(code,reason):return ModelFailure(code,reason,stage,attempts,sent,reservations,dispatches,evidence)
    for error in chain:
        if type(error).__name__=='BudgetStop' and type(error).__module__.endswith('phase5_eval_meter'):
            raw=getattr(error,'reason',str(error))
            code=REASONS.get(raw,'provider_request_state_unknown')
            # Store only allowlisted tokens, never a proxy URL or exception text.
            return failure(code,raw if raw in REASONS else 'unreconciled_guard_stop')
    for error in chain:
        detail=getattr(error,'detail',None)
        if detail in MESSAGES:
            return failure(detail,detail)
        status=getattr(getattr(error,'response',None),'status_code',None)
        if status in {401,403} or (isinstance(detail,str) and detail.endswith((':http_401',':http_403'))):
            return failure('provider_auth_failed','authentication_failed')
        if isinstance(error,(TimeoutError,httpx.TimeoutException)):
            return failure('provider_timeout','timeout')
        if isinstance(error,(httpx.TransportError,OSError)):
            return failure('provider_network','network')
    return None
