"""Allowlisted generation diagnostics; no raw responses or exception strings."""

TRANSPORT_HINTS = {
    'dns_resolution_failed': '模型域名解析失败。请检查 DNS 或代理的域名解析设置后，主动重新请求。',
    'tls_certificate_failed': '模型连接的证书验证失败。请检查系统时间、证书和代理证书配置后，主动重新请求。',
    'tls_handshake_failed': '模型连接的 TLS 握手失败。请检查网络或代理配置后，主动重新请求。',
    'connection_refused': '模型连接被拒绝。请检查服务地址和代理是否可用后，主动重新请求。',
    'connection_reset': '模型连接中途断开。请检查网络后，主动重新请求。',
    'proxy_error': '模型请求的代理连接失败。请检查代理配置后，主动重新请求。',
}


def provider_failure_details(exc):
    """Retain transport evidence from typed causes, never exception messages.

    HTTPX wraps DNS/TLS/socket errors. Walking that bounded chain keeps their
    distinct causes without leaking a proxy URL, upstream response or API key.
    An absent cause is unknown; it is never diagnosed from a generic AppError.
    """
    import socket
    import ssl
    import httpx
    from backend.chat.call_trace import safe_failure_reason

    reason = safe_failure_reason(getattr(exc, 'detail', None))
    cause = None
    visited = set()
    current = exc
    for _ in range(8):
        if current is None or id(current) in visited:
            break
        visited.add(id(current))
        if reason == 'unknown' and isinstance(current, (httpx.TransportError, TimeoutError)):
            candidate = safe_failure_reason('complete:' + type(current).__name__)
            if candidate != 'unknown': reason = candidate
        if isinstance(current, socket.gaierror): cause = 'dns_resolution_failed'
        elif isinstance(current, ssl.SSLCertVerificationError): cause = 'tls_certificate_failed'
        elif isinstance(current, ssl.SSLError) and cause is None: cause = 'tls_handshake_failed'
        elif isinstance(current, ConnectionRefusedError) and cause is None: cause = 'connection_refused'
        elif isinstance(current, ConnectionResetError) and cause is None: cause = 'connection_reset'
        elif isinstance(current, httpx.ProxyError) and cause is None: cause = 'proxy_error'
        current = current.__cause__ or current.__context__
    details = {'failure_reason': reason}
    if cause: details['network_cause'] = cause
    return details

MESSAGES = {
    "difficulty_mismatch": ("difficulty_check", "生成题的变化或模型自评与所需难度不一致，未保存。可以重新提出请求；本次没有自动重试。"),
    "output_truncated": ("provider_response", "模型输出达到长度上限，题目尚未完整返回，不是已判定答案错误。未保存题目，也没有自动重试。"),
    "format_invalid": ("response_parse", "模型返回格式异常，无法读取完整题目；未保存。可重新提出一次出题请求。"),
    "content_incomplete": ("content_check", "模型题干、答案或解析不完整，未保存。可重新提出出题请求。"),
    "answer_conflict": ("answer_check", "答案、解析或计算步骤校验不一致，未保存；不能直接采用本次答案。"),
    "type_mismatch": ("content_check", "模型没有遵循已确认的题型，未保存。请重新确认题型后提出新请求。"),
    "scope_mismatch": ("content_check", "题目不符合已确认的知识范围，未保存。请检查原题与知识点是否匹配。"),
    "verification_unavailable": ("answer_check", "该题的独立校验暂不能给出通过结论，未保存为合格题。可选择其他题型。"),
    "reference_changed": ("save_check", "参考原题或知识点已发生变化，未保存。请重新选择原题与知识点。"),
    "duplicate": ("save_check", "生成内容与已有个人题重复，未重复保存。可从对应知识节点查看已有题。"),
    "storage_forbidden": ("save_question", "题目保存权限不足，未确认保存成功。请联系管理员检查应用角色权限。"),
    "provider_timeout": ("provider_request", "模型请求超时，没有自动重试。请稍后重新提出请求。"),
    "provider_network": ("provider_request", "模型服务连接失败，没有自动重试。请检查网络后重新提出请求。"),
    "budget_stopped": ("budget_check", "出题请求触及调用或Token预算，已停止；未自动增加预算或重试。"),
    "provider_failed": ("provider_request", "模型请求未完成，没有自动重试。请检查模型配置或服务状态。"),
    "quality_rejected": ("quality_check", "生成内容未达到现有质量检查要求，未保存。可重新提出出题请求。"),
    "processing_failed": ("generation_processing", "出题处理未完成；请读取批次状态确认已保存内容，不要重复提交同一请求。"),
}


def diagnostic(failure):
    reason = failure.get('reason', '')
    issues = set(failure.get('issues') or [])
    uncertainties = set(failure.get('uncertainties') or [])
    code = 'quality_rejected'
    if reason == 'DIFFICULTY_MISMATCH': code = 'difficulty_mismatch'
    elif reason == 'OUTPUT_TRUNCATED': code = 'output_truncated'
    elif reason == 'duplicate': code = 'duplicate'
    elif reason in {'node_or_verifier_drift', 'parent_content_drift'}: code = 'reference_changed'
    elif reason == 'requested_type_not_followed': code = 'type_mismatch'
    elif 'generated_statement_outside_requested_skill' in issues: code = 'scope_mismatch'
    elif reason == 'CONFIRMED_WRONG' or issues.intersection({'answer_final_value_conflict', 'statement_answer_conflict', 'explanation_step_conflict', 'independent_answer_conflict', 'explanation_final_value_conflict', 'independent_explanation_claim_conflict'}): code = 'answer_conflict'
    elif issues.intersection({'question_or_explanation_incomplete', 'answer_missing', 'stem_missing', 'explanation_missing'}) or any(i.startswith('incomplete_question_structure') for i in issues): code = 'content_incomplete'
    elif reason == 'FORMAT_ERROR': code = 'format_invalid'
    elif reason == 'UNSUPPORTED' or 'independent_verifier_unsupported' in uncertainties: code = 'verification_unavailable'
    elif reason == 'BUDGET_STOPPED': code = 'budget_stopped'
    elif reason == 'PROVIDER_TIMEOUT': code = 'provider_timeout'
    elif reason == 'PROVIDER_NETWORK': code = 'provider_network'
    elif reason == 'PROVIDER_FAILED': code = 'provider_failed'
    elif reason == 'STORAGE_FORBIDDEN': code = 'storage_forbidden'
    elif reason == 'PROCESSING_FAILED': code = 'processing_failed'
    stage, message = MESSAGES[code]
    cause = failure.get('network_cause')
    if code == 'provider_network' and cause in TRANSPORT_HINTS:
        message = TRANSPORT_HINTS[cause] + '本次没有自动重试，未取得题目。'
    result = {'index': failure.get('index'), 'code': 'personal_generation_' + code,
              'stage': stage, 'message': message}
    if cause in TRANSPORT_HINTS: result['network_cause'] = cause
    # Only admit the same allowlisted vocabulary used at the HTTP boundary.
    from backend.chat.call_trace import safe_failure_reason
    reason = failure.get('failure_reason', '')
    if isinstance(reason, str) and reason.startswith('network_') and safe_failure_reason('complete:' + reason[8:]) == reason:
        result['failure_reason'] = reason
    return result


def with_diagnostics(result):
    """Also interpret existing ledger results at read time, without rewriting them."""
    if not isinstance(result, dict): return result
    failures = list(result.get('failures') or [])
    if not failures and not result.get('question_ids'):
        error = result.get('provider_error')
        reason = ('PROVIDER_TIMEOUT' if error in {'TimeoutError', 'ReadTimeout', 'ConnectTimeout'} else
                  'FORMAT_ERROR' if error in {'JSONDecodeError', 'ValidationError', 'GeneratedFormatError'} else
                  'STORAGE_FORBIDDEN' if result.get('processing_error') == 'storage_permission_denied' else
                  'PROCESSING_FAILED' if result.get('processing_error') else 'PROVIDER_FAILED' if error else '')
        if reason: failures.append({'reason': reason})
    return {**result, 'diagnostics': [diagnostic(f) for f in failures]}
