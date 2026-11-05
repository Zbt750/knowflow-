"""Count execution facts, never turn an unattempted slot into a rejected题."""
from collections import Counter
from backend.services.generation_diagnostics import diagnostic

LABELS = {
    'output_truncated':'模型输出截断，未取得完整题目',
    'format_invalid':'模型返回结构不符合要求，未保存',
    'content_incomplete':'题干、答案或解析不完整，未保存',
    'answer_conflict':'答案或解析校验不一致，未保存',
    'type_mismatch':'没有遵循已确认题型，未保存',
    'scope_mismatch':'不符合已确认知识范围，未保存',
    'difficulty_mismatch':'不符合已确认难度要求，未保存',
    'verification_unavailable':'现有独立校验无法确认通过，未保存为合格题',
    'duplicate':'与已有个人题重复，未重复保存',
    'reference_changed':'原题或知识点已变化，未保存',
    'provider_timeout':'模型请求超时，未取得题目',
    'provider_network':'模型网络请求失败，未取得题目',
    'provider_failed':'模型服务请求失败，未取得完整题目',
    'budget_stopped':'预算停止，未继续生成',
    'storage_forbidden':'保存权限检查失败，未确认保存',
    'processing_failed':'处理未完成，请读取状态确认',
    'quality_rejected':'内容未通过质量检查，未保存',
}


def with_outcomes(result):
    result=dict(result)
    requested=int(result.get('requested') or 0)
    saved=len(set(result.get('question_ids') or []))
    failures={f['index']:f for f in result.get('failures',[]) if isinstance(f.get('index'),int) and 1<=f['index']<=requested}
    details=Counter()
    for failure in failures.values():
        code=diagnostic(failure)['code'].removeprefix('personal_generation_')
        details[code]+=1
    # New batches track entered candidate slots. Legacy incomplete records are
    # labelled unknown; they are not silently treated as either failed or idle.
    entered=result.get('attempted_indices')
    if entered is not None:
        entered_count=len({i for i in entered if isinstance(i,int) and 1<=i<=requested})
        not_attempted=max(0,requested-entered_count)
        unknown=max(0,entered_count-saved-len(failures))
    else:
        not_attempted=None
        unknown=max(0,requested-saved-len(failures))
    # Entering a slot is not a physical request: validation or a budget guard
    # may stop it before Provider.complete. Each call record wraps one call.
    calls=result.get('calls')
    attempted=len(calls) if isinstance(calls,list) else None
    quality={'answer_conflict','type_mismatch','scope_mismatch','difficulty_mismatch','verification_unavailable','quality_rejected'}
    result['outcome_summary']={
        'requested_count':requested,'saved_count':saved,'failed_count':len(failures),
        'attempted_count':attempted,'not_attempted_count':not_attempted,'unresolved_count':unknown,
        'not_executed_count':not_attempted,
        'provider_calls':len(result.get('calls') or []),
        'network_failed_count':details.get('provider_network',0),
        'quality_rejected_count':sum(n for code,n in details.items() if code in quality),
        'response_failed_count':sum(n for code,n in details.items() if code in {'output_truncated','provider_timeout','provider_network','provider_failed','budget_stopped'}),
        'structure_rejected_count':sum(n for code,n in details.items() if code in {'format_invalid','content_incomplete'}),
        'failure_details':[{'code':'personal_generation_'+code,'count':count,'message':LABELS[code]} for code,count in details.items()]}
    return result
