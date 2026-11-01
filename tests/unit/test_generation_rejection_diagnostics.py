import json
from types import SimpleNamespace
import pytest
from backend.chat.service import Provider
from backend.errors import AppError
from backend.services.question_generation import Budget, generate
from backend.services.generation_diagnostics import with_diagnostics
from backend.services.personal_question_service import result_message


def test_real_historical_failures_are_truncation_not_answer_rejection():
    # Actual redacted ledger metadata, not a reconstructed model answer.
    for output_limit in (1800, 3000):
        historical = {'status':'failed', 'question_ids':[], 'failures':[{'index':1,
            'reason':'OUTPUT_TRUNCATED', 'review_status':'OUTPUT_TRUNCATED', 'error_type':'AppError'}],
            'calls':[{'model':'deepseek-flash','max_output_tokens':output_limit,'usage':None}]}
        enriched = with_diagnostics(historical)
        assert enriched['diagnostics'][0]['code'] == 'personal_generation_output_truncated'
        assert enriched['diagnostics'][0]['stage'] == 'provider_response'
        assert '不是已判定答案错误' in result_message(historical)
        assert 'diagnostics' not in historical  # read enrichment does not rewrite DB


def test_real_provider_transport_truncation_keeps_usage_without_saving_text(monkeypatch):
    observed = []
    def post(url, **kwargs):
        observed.append(kwargs['json'])
        # Transport fixture. Metadata shape matches the actual failure; content
        # and usage below are synthetic, not the unavailable historical payload.
        return SimpleNamespace(raise_for_status=lambda:None, json=lambda:{
            'choices':[{'finish_reason':'length','message':{'content':'{"stem":"未完成',
                'reasoning_content':'DO_NOT_PERSIST_REASONING'}}],
            'usage':{'prompt_tokens':420,'completion_tokens':3000,'total_tokens':3420}})
    monkeypatch.setattr('backend.chat.service.httpx.post',post)
    provider = Provider(api_key='DO_NOT_PERSIST_KEY',base_url='https://api.deepseek.com',
        model='deepseek-flash',timeout=10,max_tokens=3000,structured_generation=True)
    budget = Budget(max_calls=1,max_output_tokens=3000)
    with pytest.raises(AppError) as error:
        generate(provider, {'node':{'code':'TEST_FIXTURE.series'},'question_type':'single_choice'},
                 budget,prompt_version='personal-general-authoring-v1')
    assert error.value.code == 'answer_truncated'
    assert len(observed) == 1
    assert observed[0]['thinking'] == {'type':'disabled'}
    assert observed[0]['response_format'] == {'type':'json_object'}
    assert 'reasoning_effort' not in observed[0] and observed[0]['max_tokens'] == 3000
    assert budget.records[0]['usage']['total_tokens'] == 3420
    assert budget.records[0]['finish_reason'] == 'length'
    assert budget.records[0]['reasoning_chars'] == len('DO_NOT_PERSIST_REASONING')
    assert 'DO_NOT_PERSIST' not in json.dumps(budget.records)


@pytest.mark.parametrize('failure,code',[
    ({'reason':'FORMAT_ERROR','issues':['answer_final_value_conflict']},'answer_conflict'),
    ({'reason':'FORMAT_ERROR','issues':['explanation_step_conflict']},'answer_conflict'),
    ({'reason':'FORMAT_ERROR','issues':['question_or_explanation_incomplete']},'content_incomplete'),
    ({'reason':'FORMAT_ERROR','issues':['invalid_json']},'format_invalid'),
    ({'reason':'requested_type_not_followed'},'type_mismatch'),
    ({'reason':'INSUFFICIENT_EVIDENCE','issues':['generated_statement_outside_requested_skill']},'scope_mismatch'),
    ({'reason':'UNSUPPORTED'},'verification_unavailable'),
    ({'reason':'PROVIDER_TIMEOUT'},'provider_timeout'),
    ({'reason':'BUDGET_STOPPED'},'budget_stopped'),
    ({'reason':'duplicate'},'duplicate'),
])
def test_stable_rejection_categories(failure,code):
    result = with_diagnostics({'question_ids':[],'failures':[failure]})
    assert result['diagnostics'][0]['code'] == 'personal_generation_' + code


def test_generation_policy_does_not_change_regular_qa_or_other_providers():
    qa = Provider(api_key='test',base_url='https://api.deepseek.com',model='deepseek-flash',timeout=1,max_tokens=3000)
    assert qa._request_options() == {'reasoning_effort':'low'}
    other = Provider(api_key='test',base_url='https://other.invalid',model='deepseek-flash',timeout=1,max_tokens=3000,structured_generation=True)
    assert other._request_options() == {}


@pytest.mark.parametrize('kind,reason,cause,status',[
    ('dns','network_ConnectError','dns_resolution_failed','PROVIDER_NETWORK'),
    ('tls','network_ConnectError','tls_certificate_failed','PROVIDER_NETWORK'),
    ('proxy','network_ProxyError','proxy_error','PROVIDER_NETWORK'),
    ('reset','network_ReadError','connection_reset','PROVIDER_NETWORK'),
    ('timeout','network_ReadTimeout',None,'PROVIDER_TIMEOUT'),
])
def test_transport_causes_are_distinct_safe_and_preserved_in_physical_call_ledger(monkeypatch,kind,reason,cause,status):
    import socket
    import ssl
    import httpx
    from backend.services.personal_question_service import _generation_failure_status
    from backend.services.generation_diagnostics import provider_failure_details
    root={'dns':socket.gaierror(-2,'SECRET_DNS'),
        'tls':ssl.SSLCertVerificationError('SECRET_TLS'),
        'reset':ConnectionResetError('SECRET_RESET')}.get(kind)
    transport={'proxy':httpx.ProxyError,'timeout':httpx.ReadTimeout,'reset':httpx.ReadError}.get(kind,httpx.ConnectError)
    def post(*args,**kwargs):
        raise transport('SECRET_UPSTREAM_OR_KEY') from root
    monkeypatch.setattr('backend.chat.service.httpx.post',post)
    provider=Provider(api_key='SECRET_KEY',base_url='https://api.deepseek.com',model='deepseek-flash',timeout=1,max_tokens=3000)
    budget=Budget(max_calls=1,max_output_tokens=3000)
    with pytest.raises(AppError) as raised:
        generate(provider,{'node':{'code':'TEST_FIXTURE.network'}},budget,prompt_version='personal-general-authoring-v1')
    details=provider_failure_details(raised.value)
    assert details['failure_reason']==reason and details.get('network_cause')==cause
    assert _generation_failure_status(raised.value)==status
    assert budget.calls==len(budget.records)==1 and budget.records[0]['failure_reason']==reason
    diagnostic=with_diagnostics({'failures':[{'index':1,'reason':status,**details}]})['diagnostics'][0]
    assert diagnostic['stage']=='provider_request' and diagnostic.get('network_cause')==cause
    assert 'SECRET' not in json.dumps([details,budget.records,diagnostic])


def test_historical_network_failure_is_not_relabelled_as_quality_or_guessed_dns():
    from backend.services.generation_outcomes import with_outcomes
    # Redacted real 9d4555ad... ledger: one request, no recorded lower-level cause.
    result=with_outcomes(with_diagnostics({'requested':3,'status':'failed','question_ids':[],
        'attempted_indices':[1],'calls':[{'error_type':'AppError','elapsed_ms':7597.953}],
        'failures':[{'index':1,'reason':'PROVIDER_NETWORK','error_type':'AppError'}]}))
    summary=result['outcome_summary']
    assert summary['attempted_count']==summary['network_failed_count']==1
    assert summary['quality_rejected_count']==0 and summary['not_executed_count']==2
    assert 'network_cause' not in result['diagnostics'][0]
