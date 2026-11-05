"""Compose a bundled node lesson with the EXISTING read/validate plan tools.

No generated substitute questions, automatic plan writes or model/tool loops.
The ordinary confirmation transaction remains the only append authority.
"""
from datetime import datetime
from time import perf_counter
from uuid import UUID
from backend.errors import AppError
from backend.models.learning_task import LearningTask
from backend.services.learning_task_tools import TaskTools
from backend.services.learning_task_service import get_task, _validated_plan_summary


def build_explained_plan(factory, *, handoff, now: datetime):
    """Read/validate a preview without creating a task, plan or practice item."""
    tools=TaskTools(factory,budget_minutes=handoff.available_minutes,now=now,
        goal=handoff.user_problem,handoff=handoff.model_dump(mode='json'))
    ids=sorted(tools.explicit_scope or handoff.target_knowledge_node_ids,key=str)
    import re
    validated_conversation=handoff.constraints.get('scope_origin') in {
        'latest_validated_qa_context','same_session_explicit_scope','same_session_query_scope'}
    bound_reference = (handoff.constraints.get('scope_origin') in {'current_study_context','current_task_draft'}
        and bool(re.search(r'(?:这种|这样的|同类)(?:的)?(?:题|练习)',handoff.user_problem)))
    if not handoff.constraints.get('scope_explicit') and not validated_conversation and not bound_reference and not re.search(r'(?:当前|这个|这道).{0,6}(?:题|知识点|节点)',handoff.user_problem):
        ids=[]  # An unmatched named concept must not inherit the viewed question.
    from backend.services.bank_selection_intent import bank_selection_request
    if (bank_selection_request(handoff.user_problem)
            and handoff.constraints.get('scope_origin') in {'current_study_context','current_task_draft'}
            and (bank_selection_request(handoff.user_problem).get('bank_source') or re.search(r'从那|当前|这个范围|再加',handoff.user_problem))):
        ids=sorted(tools.explicit_scope or handoff.target_knowledge_node_ids,key=str)
    trace=[];lessons=[];draft=None;status='needs_info';error_code=None
    explanation_requested=bool(handoff.constraints.get('explanation_request'))

    def execute(name,args):
        started=perf_counter()
        step={'tool':name,'stage':name,'intent':'plan','args_summary':args,'round':0,'retry':0}
        try:
            result=(tools.validate_paper_candidates(args) if name == 'validate_plan'
                    else tools.execute(name,args))
            step.update(result=result,status='error' if result.get('error') or result.get('valid') is False else 'completed')
            if result.get('error'):raise AppError('learning_task_failed',detail='composite_tool_failed:'+name)
            return result
        except Exception:
            step.update(status='error',error_code='business_tool_failed')
            raise
        finally:
            step['duration_ms']=round((perf_counter()-started)*1000);trace.append(step)

    message='请明确需要讲解和练习的知识点；没有加入今日卷。'
    try:
        if handoff.constraints.get('reference_scope_conflict'):
            message='指定的知识点与参照题不一致，请确认使用哪一个范围；没有生成新题或加入今日卷。'
        elif handoff.constraints.get('similar_requested') and not handoff.constraints.get('similar_reference'):
            message='请先指定一道可核实的参照题，或回到该题后重试；没有生成新题或加入今日卷。'
        elif not ids:
            resolutions=handoff.constraints.get('scope_resolution') or []
            missing=list(dict.fromkeys(handoff.constraints.get('unresolved_topics') or
                [str(item.get('topic')) for item in resolutions if item.get('status')=='unmatched' and item.get('topic')]))
            matched=list(dict.fromkeys(str(item.get('topic')) for item in resolutions
                if item.get('status')=='matched' and item.get('topic')))
            if missing:
                message='知识范围未能全部匹配：未在知识树中找到「'+'、'.join(missing)+'」。'
                if matched:message+='已识别「'+'、'.join(matched)+'」，但不会用它替代未匹配范围。'
                message+='请在现有知识树选择对应节点或取消；没有扩大到整科、当前题或其他主题，也没有加入今日卷。'
            else:
                message='未匹配到明确的知识点，请明确节点名称后再准备题目；没有加入今日卷。'
        elif len(ids)>8:
            message='请把知识范围缩小到具体节点，再准备对应题目；没有加入今日卷。'
        else:
            if explanation_requested:
                for node in ids:
                    lesson=execute('read_lesson',{'kp_id':str(node)})
                    if lesson.get('available'):
                        lessons.append('系统节点讲解 · '+lesson['name']+'\n\n'+lesson['markdown'])
            execute('get_learning_state',{'kp_ids':[str(k) for k in ids]})
            stock=execute('get_question_availability',{'kp_ids':[str(k) for k in ids]})
            # Reference metadata may be insufficient: that is clarification,
            # not an inventory failure or permission to generate a new question.
            found=tools.execute('find_questions',{'kp_ids':[str(k) for k in ids]}) if handoff.constraints.get('similar_requested') else None
            if found is not None and found.get('error') in {'similar_reference_required','similar_reference_invalid','similar_evidence_missing'}:
                trace.append({'tool':'find_questions','stage':'find_questions','intent':'plan','status':'completed','result':found})
                return {'status':'needs_info','draft':None,'trace':trace,'error_code':found['error'],
                    'explanation':'','selection_message':found['hint'],'message':found['hint']}
            if found is not None:
                trace.append({'tool':'find_questions','stage':'find_questions','intent':'plan','status':'error' if found.get('error') else 'completed','result':found})
                if found.get('error'):raise AppError('learning_task_failed',detail='composite_tool_failed:find_questions')
            else:
                found=execute('find_questions',{'kp_ids':[str(k) for k in ids]})
            count=handoff.requested_question_count or 1
            choices=[q for q in found.get('questions',[]) if not q['in_today_plan'] and q.get('question_version')
                and (not handoff.constraints.get('existing_bank_only') or handoff.constraints.get('include_personal_bank') or not q.get('source_category','').startswith('personal'))]
            excluded=set(handoff.constraints.get('excluded_preview_question_ids',[]))
            condition=handoff.constraints.get('preview_query_state') or {}
            choices=[q for q in choices if q['question_id'] not in excluded
                and (not handoff.constraints.get('preview_question_type') or q.get('question_type')==handoff.constraints['preview_question_type'])
                and (not condition.get('source_categories') or q.get('source_category') in condition['source_categories'])
                and q.get('source_category') not in condition.get('excluded_source_categories',[])
                and (not condition.get('question_types') or q.get('question_type') in condition['question_types'])]
            pinned=handoff.constraints.get('selected_question_refs')
            if pinned:
                wanted={(p['question_id'],p['question_version']) for p in pinned}
                choices=[q for q in choices if (q['question_id'],q['question_version']) in wanted]
                if len(choices)!=len(wanted):
                    choices=[]  # Changed version or eligibility: never silently substitute.
            if len(choices)<count:
                if found.get('candidate_list_complete') is False:
                    error_code='candidate_inventory_incomplete'
                    message=(f'本次候选不足：已读取真实题库，本次有界候选中可新增 {len(choices)} 道，尚不足 {count} 道；'
                        '候选读取未覆盖完整库存，不能据此断言没有符合条件的题。'
                        '没有创建方案或加入今日卷；请缩小范围或进一步明确题型、来源。')
                else:
                    message=(f'合格可用题量不足：已读取真实题库，本次候选中可新增 {len(choices)} 道，不能满足 {count} 道要求。'
                        '没有创建方案或加入今日卷；可以减少题数或选择其他知识点。'
                        + (' 相似题要求相同知识点、题型及共同技能标签或变式组；若要放宽，请明确同意。' if handoff.constraints.get('similar_requested') else ''))
                if stock.get('blocked_question_count',0)>0:
                    labels={
                        'content_not_verified':'题目内容未完成核验',
                        'public_formal_review_required':'正式题目审核未完成',
                        'verification_required':'缺少正式准入核验',
                        'answer_verification_missing_or_stale':'答案核验缺失或已随版本失效',
                        'answer_missing':'缺少答案','explanation_missing':'缺少解析',
                        'question_content_incomplete':'题面不完整','choice_options_incomplete':'选项不完整',
                        'choice_answer_invalid':'选项与答案不一致',
                        'inactive':'题目已停用','hidden':'题目已隐藏',
                        'hidden_or_inactive':'题目已隐藏或停用',
                    }
                    reasons=list(dict.fromkeys(labels.get(key,'仍有准入条件未满足')
                        for key,amount in stock.get('blocking_reasons',{}).items() if amount))
                    message+=f" 另有 {stock['blocked_question_count']} 道未通过正式准入，已自动排除。"
                    if reasons:message+='原因包括：'+'、'.join(reasons)+'。'
            else:
                checked=execute('validate_plan',{'question_ids':[q['question_id'] for q in choices[:count]],
                    'rationale':'依据明确知识点、在线可练资格、版本与今日卷去重检查，等待用户确认。'})
                if checked.get('valid') and tools.draft:
                    expected_versions={q['question_id']:q['question_version'] for q in choices[:count]}
                    if any(expected_versions.get(q['question_id']) != q['question_version'] for q in tools.draft['questions']):
                        error_code='candidate_version_changed'
                        message='题库候选在查询和校验之间发生版本变化，请重新检索；没有加入今日卷。'
                    else:
                        draft=tools.draft;status='ready'
                        match_by_id={q['question_id']:q.get('match_basis') for q in choices[:count]}
                        for question in draft['questions']:
                            if match_by_id.get(question['question_id']): question['match_basis']=match_by_id[question['question_id']]
                        message=_validated_plan_summary(draft)
                else:
                    error_code='plan_validation_failed'
                    message='方案未通过正式校验：'+ '、'.join(checked.get('errors',[]))+'。没有加入今日卷。'
    except Exception:
        import logging
        logging.getLogger(__name__).exception('existing bank tool execution failed')
        status='failed';error_code='business_tool_failed'
        message='本次题库查询或方案校验未完成。已取得的节点讲解和工具证据保留，没有加入今日卷；可读取状态后重试。'
    selection_message=message
    explanation='\n\n'.join(lessons)
    if explanation_requested and not explanation:
        explanation='该范围暂未取得可用的系统节点讲解；不编造讲解来源。'
    message=(explanation+'\n\n## 题库选题与待确认方案\n\n'+message
        if explanation_requested else message)
    return {'status':status,'draft':draft,'trace':trace,'error_code':error_code,
        'explanation':explanation,'selection_message':selection_message,
        'message':message}


def prepare_explained_plan(factory, task_id, *, handoff, now: datetime):
    prepared=build_explained_plan(factory,handoff=handoff,now=now)
    with factory.begin() as db:
        row=db.get(LearningTask,task_id,with_for_update=True)
        if row.status=='cancelled':return get_task(factory,task_id)
        row.status=prepared['status'];row.draft=prepared['draft'];row.trace=prepared['trace'];row.error_code=prepared['error_code']
        row.message=prepared['message']
        row.context={**(row.context or {}),'composite_explanation':prepared['explanation']}
        row.metrics={**(row.metrics or {}),'model_calls':0,'tool_calls':len(prepared['trace']),
            'execution':'system_lesson_and_existing_business_tools','memory_lifecycle':'closed'}
    return get_task(factory,task_id)
