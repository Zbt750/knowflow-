"""Revalidate the exact previous question preview; no substitution or writes."""
from uuid import UUID
from sqlalchemy import select
from backend.models.learning import DailyPlan, KnowledgePoint, PracticeItem, Question, QuestionAttempt, QuestionVersion
from backend.services.question_eligibility import question_eligibility
from backend.services.learning_task_tools import TaskTools
from backend.services.question_versions import question_version_reference, _json_value
from backend.services.question_availability import _descendant_ids, question_source_category


def revise_question_preview(factory,context,budget,goal,now):
    previous=context.get('previous_draft') or {}
    handoff=context.get('planner_handoff') or {}
    old_handoff=context.get('previous_planner_handoff') or {}
    old_constraints=old_handoff.get('constraints') or {}
    constraints={**old_constraints,**(handoff.get('constraints') or {})}
    constraints['preview_query_state']={**(old_constraints.get('preview_query_state') or {}),
        **(constraints.get('preview_query_state') or {})}
    effective_handoff={**old_handoff,**handoff,'constraints':constraints,
        'exclusions':list(dict.fromkeys((old_handoff.get('exclusions') or [])+(handoff.get('exclusions') or [])))}
    relax_count=constraints.get('relax_count') or __import__('re').search(
        r'减少练习量|减少题量|少做几道|压缩练习|保留最重要|其他内容以后再学',goal)
    if type(handoff.get('requested_question_count')) is not int:
        effective_handoff['requested_question_count']=None if relax_count else old_handoff.get('requested_question_count')
    prior_goal=context.get('previous_goal') or ''
    tools=TaskTools(factory,budget_minutes=budget,now=now,goal=prior_goal+'\n'+goal,handoff=effective_handoff)
    requested_count=handoff.get('requested_question_count')
    if type(requested_count) is int:
        tools.required_count=requested_count
    elif relax_count:
        tools.required_count=None
    trace=[]
    def call(name,args):
        result=(tools.validate_paper_candidates(args) if name == 'validate_plan'
                else tools.execute(name,args))
        trace.append(_json_value({'tool':name,'arguments_summary':args,'result':result,'status':'completed' if not result.get('error') else 'error'}))
        return result
    draft=None
    rejected=[]
    message='没有可供修改的有效题目草案。请重新选择范围；没有创建正式计划或修改今日卷。'
    try:
        scope=list(old_handoff.get('target_knowledge_node_ids') or handoff.get('target_knowledge_node_ids') or [])
        if scope and previous.get('questions'):
            original=previous['questions']
            try:
                expected={str(q['question_id']):str(q['question_version']) for q in original}
                qids=[UUID(value) for value in expected]
                scope_roots={UUID(str(value)) for value in scope}
            except (KeyError,TypeError,ValueError):
                expected={};qids=[];scope_roots=set()
            with factory() as db:
                # The saved resolved scope is authoritative. Legacy root-only
                # handoffs use the same subtree resolver as the normal bank query.
                if old_constraints.get('scope_version')==1:
                    scope_ids={UUID(str(k)) for k in old_constraints.get('resolved_scope_node_ids',[])}
                else:
                    scope_ids=_descendant_ids(db,scope_roots)
                if tools.explicit_scope is not None:scope_ids &= tools.explicit_scope
                scope_ids -= tools.excluded_scope
                rows={q.id:q for q in db.scalars(select(Question).where(Question.id.in_(qids or [UUID(int=0)])))}
                today_ids=set(db.scalars(select(PracticeItem.question_id).join(DailyPlan).where(
                    DailyPlan.study_date==now.astimezone(__import__('zoneinfo').ZoneInfo('Asia/Shanghai')).date().isoformat(),
                    PracticeItem.question_id.in_(qids or [UUID(int=0)]))))
                eligible={}
                for saved in original:
                    raw_id=str(saved.get('question_id'))
                    try:qid=UUID(raw_id);version_id=UUID(str(saved.get('question_version')))
                    except (TypeError,ValueError):
                        rejected.append({'question_id':raw_id,'reasons':['invalid_saved_reference']});continue
                    question=rows.get(qid)
                    version=db.get(QuestionVersion,version_id)
                    node=db.get(KnowledgePoint,question.kp_id) if question else None
                    reasons=[]
                    if question is None:reasons.append('question_missing')
                    elif not version or version.question_id!=qid or question_version_reference(question)!=str(version_id):
                        reasons.append('question_version_changed')
                    if question and question.kp_id not in scope_ids:reasons.append('outside_original_scope')
                    assessment=question_eligibility(question,node) if question and node else None
                    if question and (not assessment or not assessment.practice_eligible):reasons.append('question_not_practice_eligible')
                    if qid in today_ids:reasons.append('already_in_today_plan')
                    if question:
                        state=constraints.get('preview_query_state') or {}
                        source=question_source_category(question)
                        if ((constraints.get('existing_bank_only') and source.startswith('personal'))
                                or (state.get('source_categories') and source not in state['source_categories'])
                                or source in state.get('excluded_source_categories',[])):
                            reasons.append('source_constraint')
                        if ((tools.required_type and question.question_type!=tools.required_type)
                                or (constraints.get('preview_question_type') and question.question_type!=constraints['preview_question_type'])
                                or (state.get('question_types') and question.question_type not in state['question_types'])):
                            reasons.append('question_type_constraint')
                        if tools.basic_only and question.difficulty!='basic':reasons.append('difficulty_constraint')
                    if reasons:
                        rejected.append({'question_id':raw_id,'reasons':reasons});continue
                    eligible[raw_id]=question
                if scope_ids:
                    tools.nodes.update(scope_ids)
                    tools.questions.update(q.id for q in eligible.values())
            trace.append({'tool':'revalidate_saved_candidates','arguments_summary':{'question_count':len(original),
                'scope_root_ids':[str(value) for value in scope_roots],
                'scope_node_ids':[str(value) for value in scope_ids]},'result':{'valid_original_count':len(eligible),
                'stale_or_ineligible_count':len(rejected),'stale_question_ids':[r['question_id'] for r in rejected],
                'rejected_candidates':rejected},'status':'completed'})
            ids=[];total=0;review=previous.get('review_minutes') or 0
            for saved in original:
                qid=str(saved.get('question_id'))
                current=eligible.get(qid)
                if not current:continue
                minutes=int(current.estimated_minutes or 0)
                # Trim the saved question sequence first. A review block is a
                # separate activity and must not make an otherwise feasible
                # prefix look impossible; retain it only if it still fits.
                if minutes>0 and total+minutes<=budget:
                    ids.append(current.id);total+=minutes
            review_nodes=[]
            for node in previous.get('review_nodes') or []:
                try:kp_id=UUID(str(node.get('kp_id')))
                except (TypeError,ValueError,AttributeError):continue
                if kp_id in scope_ids:review_nodes.append(kp_id)
            keep_review=bool(review_nodes and review>0 and total+review<=budget)
            if ids or keep_review:
                evidence_nodes={eligible[str(qid)].kp_id for qid in ids}|set(review_nodes if keep_review else [])
                for offset in range(0,len(evidence_nodes),8):
                    call('get_learning_state',{'kp_ids':list(sorted(evidence_nodes,key=str))[offset:offset+8]})
                valid=call('validate_plan',{'question_ids':ids,'review_kp_ids':review_nodes if keep_review else [],
                    'review_minutes':review if keep_review else 0,
                    'rationale':'按原草案顺序缩减，复核原题版本、资格、范围和时间；保留当前仍有效的原活动，等待用户确认。'})
                if valid.get('valid'):
                    draft=tools.draft
                    total=int(draft.get('total_minutes') or 0)
                    message=f'已按原草案顺序重新校验修改版：{len(ids)} 道原草案题目，共 {total} 分钟，不超过 {budget} 分钟预算。' \
                        '只保留原 Question 与 QuestionVersion 中仍符合范围、资格且尚未入卷的题目；旧草案版本已失效，确认前不会创建或修改今日卷。'
            if draft is None:
                if rejected:
                    labels={'invalid_saved_reference':'保存的题目引用无效','question_missing':'题目不存在',
                        'question_version_changed':'题目版本变化','outside_original_scope':'不属于原草案知识范围',
                        'question_not_practice_eligible':'不再符合可练资格','already_in_today_plan':'已进入今日卷',
                        'source_constraint':'不符合原来源限制','question_type_constraint':'不符合原题型限制',
                        'difficulty_constraint':'不符合原难度限制'}
                    reason='候选复核结果：'+'；'.join(f"{labels[code]} {sum(code in r['reasons'] for r in rejected)} 道"
                        for code in labels if any(code in r['reasons'] for r in rejected))
                else:
                    reason='原草案中没有预计时间大于零且符合本次预算及数量限制的合法组合'
                if trace and trace[-1]['tool']=='validate_plan' and trace[-1]['result'].get('errors'):
                    reason+='；正式校验未通过：'+'、'.join(trace[-1]['result']['errors'])
                message=f'无法形成 {budget} 分钟内的修改版：{reason}。' \
                    '本次没有可确认的新草案，旧版本仅保留为历史；没有新增计划或题目，可重新查看候选或调整预算/范围。'
    except Exception as exc:
        trace.append({'tool':'revise_previous_preview','status':'error','exception_type':type(exc).__name__})
        message='重新核验旧草案时发生查询或校验异常，修改版未生成。旧版本已失效；请读取状态后重试，没有写入今日卷。'
    return {'status':'ready' if draft else 'needs_info','draft':draft,'message':message,'trace':trace,
        'metrics':{'model_calls':0,'intent':'plan','completion_reason':'revalidated_previous_preview' if draft else 'preview_revision_failed'},
        'error_code':None if draft else 'plan_draft_missing'}
