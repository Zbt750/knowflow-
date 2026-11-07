"""Deterministic chat adapter for the versioned formal-paper mutation service."""
import re
from uuid import UUID
from types import SimpleNamespace
from sqlalchemy import select
from backend.errors import AppError
from backend.models.chat import ChatMessage
from backend.models.learning import DailyPlan, PracticeItem, KnowledgePoint, Question
from backend.models.learning_task import LearningTask
from backend.schemas.paper_adjustment import PaperAdjustmentRequest, ReplacementReference, PaperAdjustmentConfirmation
from backend.services.paper_adjustment_service import propose_adjustment, confirm_adjustment
from backend.services.practice_display_order import display_key
from backend.services.question_versions import question_for_practice_item, question_version_reference


def parse_command(text):
    text=text.strip()
    intent_text=text.replace('等价无穷小替换','等价无穷小')
    if re.fullmatch(r'取消(?:本次)?调整[。！!]?|撤销(?:本次)?方案[。！!]?',text):
        return {'action':'cancel'}
    if re.fullmatch(r'(?:我)?(?:确认(?:本次)?调整|确认移除已浏览题目|确认超预算调整|确认移除已浏览题目并接受超预算)[。！!]?',text):
        return {'action':'confirm','viewed':'已浏览' in text,'budget_confirmed':'超预算' in text}
    # A comment, question or deferred acknowledgment about an overrun neither
    # authorizes a mutation nor withdraws the saved draft.
    if '超预算' in text and re.search(r'减少|删除|移除|增加|追加|加入|换掉|换成|替换|换一道|重新安排|安排.{0,16}408|408.{0,16}知识点',intent_text) is None:
        return {'action':'query','text':text,'revoke_proposal':False}
    if re.search(r'减少|删除|移除|增加|追加|加入|换掉|换成|替换|换一道|重新安排|安排.{0,16}408|408.{0,16}知识点',intent_text) is None:return None
    if re.search(r'不要|不许|不准|先不|暂不|不必|不用|不需要|不想|不希望|(?:^|[，。！!？?\s])别|不(?:创建|生成|安排|加入|修改|写入|执行)|能不能|能否|可否|是否|要不要|可以吗|如果|假如|等我|以后|明天|吗[。！!]?\s*$|？|\?',text):
        revoke=bool(re.search(r'(?:先\s*(?:不|别)|暂不|暂时不|不要|别|不需要|不必|不用).{0,10}(?:删除|移除|换|替换|加入|增加|追加|调整|执行)',text))
        return {'action':'query','text':text,'revoke_proposal':revoke}
    counts=re.findall(r'(?:减少|删除|移除|增加|追加|加入)\s*([一二两三四五六七八九十\d]+)\s*(?:道|题)',text)
    number=re.search(r'第\s*([一二两三四五六七八九十\d]+)\s*(?:题|道)',text)
    topic_count=re.search(r'(?:安排|选择|选|换成)\s*([一二两三四五六七八九十\d]+)\s*个知识点',text)
    budget=re.search(r'(\d{1,3})\s*分钟',text)
    def integer(value):
        return int(value) if value.isdigit() else {'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}.get(value)
    if (counts and integer(counts[-1]) is None) or (number and integer(number[1]) is None):
        return {'action':'clarify'}
    count=integer(counts[-1]) if counts else 1
    if topic_count and integer(topic_count[1]) is None:
        return {'action':'clarify'}
    return {'action':'replace' if re.search(r'换|替换|408',text) else 'add' if re.search(r'增加|追加|加入',text) else 'remove',
        'count':count,'number':integer(number[1]) if number else None,
        'topic_count':integer(topic_count[1]) if topic_count else None,
        'budget_minutes':int(budget[1]) if budget else None,
        'all_topic':bool(re.search(r'全部|所有|整個|整个|整组|整組|这个知识点的题|该知识点的题',text)),
        'each_topic':bool(re.search(r'各\s*(?:减少|删|移除)|分别',text)),
        'easy':bool(re.search(r'简单|容易|难度',text)),'text':text}


def _requested_408_topic_scope(message, nodes):
    """Resolve an explicit 408 course after the replacement verb to its topic subtree.

    A phrase such as “把洛必达法则全部换成408操作系统” must not silently
    select an unrelated 408 topic merely because it ranks first in the learner's
    general recommendation list. A bare “换成408” intentionally remains broad.
    """
    switches=list(re.finditer(r'换成|替换成|替换为|改成|改为',message))
    if not switches:return None,None
    target_text=message[switches[-1].end():]
    aliases=(
        ('计算机组成原理',('计算机组成原理','组成原理','计组')),
        ('操作系统',('操作系统',)),
        ('计算机网络',('计算机网络','计网')),
        ('数据结构',('数据结构',)),
    )
    found=[]
    for course,values in aliases:
        for alias in values:
            match=re.search(re.escape(alias),target_text)
            if match:found.append((match.start(),-len(alias),course))
    if not found:return None,None
    course=min(found)[2]
    is_408=lambda node:bool(re.search(r'408|计算机学科专业基础|cs408',node.subject,re.I))
    active=[node for node in nodes if getattr(node,'is_active',True) and is_408(node)]
    roots=[node for node in active if node.name==course]
    by_id={node.id:node for node in active}
    if roots:
        root_ids={node.id for node in roots}
        scope=set(root_ids)
        for node in active:
            current=node;seen=set()
            while getattr(current,'parent_id',None) is not None and current.id not in seen:
                seen.add(current.id)
                if current.parent_id in root_ids:
                    scope.add(node.id);break
                current=by_id.get(current.parent_id)
                if current is None:break
        return scope,course
    # Some imports only retain course-qualified leaf names. Fail closed to those
    # exact descendants instead of widening back to the whole 408 bank.
    scope={node.id for node in active if node.is_assessable and course in node.name}
    return scope,course


def _replacement_fill_candidates(pools,selected_pools,*,preserve_replaced_quantity):
    """Return budget-fill questions without silently widening a requested topic set.

    A whole-paper plan with an explicit/default topic count is scoped to the
    selected topics. A scoped course-topic replacement is different: it must
    preserve the number of removed questions, so it may draw spare eligible
    questions from the rest of that explicitly requested course.
    """
    selected_ids={node.id for node,_ in selected_pools}
    source=pools if preserve_replaced_quantity else selected_pools
    candidates=[question for node,pool in source
        for question in (pool[1:] if node.id in selected_ids else pool)]
    return sorted(candidates,key=lambda question:(question.estimated_minutes,str(question.id)))


def _is_whole_math_replacement(message):
    """Only treat an explicit math-paper phrase as a whole-math replacement.

    The bare word “全部” also appears in a single-topic instruction such as
    “把洛必达法则的题目全部换成408操作系统”, so it cannot widen that edit to
    every math item in today's paper.
    """
    return bool(re.search(
        r'(?:数学\s*(?:题目?|内容)\s*(?:全部|所有|都|全)|'
        r'(?:全部|所有)\s*(?:今天|当前)?\s*数学\s*(?:题目?|内容))',
        message))


def _topic_count_batch(message, nodes):
    """Reuse the proposal parser, with every named operation accounted for."""
    operation_text=message
    for node in sorted(nodes,key=lambda node:len(node.name),reverse=True):
        operation_text=operation_text.replace(node.name,'')
    if re.search(r'替换|换成|换掉|换一道',operation_text):return None,None
    if len(re.findall(r'增加|添加|追加|加入|减少|删除|移除|减去|减掉|少安排|多安排',operation_text))<2:
        return None,None
    from backend.services.home_intent import _topic_count_intent,reference_map
    normalized=message.replace('删除','减少').replace('移除','减少').replace('加入','增加')
    paper={'selected_kp_ids':[str(node.id) for node in nodes],
        'scope_nodes':[{'kp_id':str(node.id),'name':node.name} for node in nodes]}
    intent=_topic_count_intent(normalized,paper)
    if intent is None:
        return None,'请分别说明每个知识点增减几道题；整项调整尚未提交。'
    if intent.operation=='clarify':return None,intent.question
    if len(intent.refs)==1:
        # A same-topic count correction stays on the established multi-turn path.
        return None,None
    refs=reference_map(paper);by_id={str(node.id):node for node in nodes}
    return [(by_id[refs[key]['value']],delta) for key,delta in zip(intent.refs,intent.deltas)],None


def handle_paper_chat(factory, *, session_id, ctx, message, now):
    command=parse_command(message)
    if command is None or not ctx.daily_plan_id:return None
    # Explicitly selecting a question from the bank is handled by the shared
    # planner proposal/confirmation path. Keeping it here would turn a valid
    # "add a similar bank question" request into a knowledge-point clarification
    # before the existing-bank router can bind the current question reference.
    from backend.services.bank_selection_intent import bank_selection_request
    bank_request=bank_selection_request(message)
    if (bank_request and bank_request.get('bank_source')
            and bank_request.get('scope_mode')=='append'):
        return None
    # A preview selection belongs to its same-session planner proposal. Do not
    # reinterpret a replayed append confirmation as a new generic paper edit.
    preview_ref=bool(re.search(
        r'(?:预览(?:中|里的|中的)?|候选(?:题|题目)|上一轮(?:检索|找到)|刚才(?:检索|找到)).{0,80}'
        r'(?:这道题|那道题|该题|这题|候选题|题)',message)
        or re.search(r'(?:这道题|那道题|该题|这题).{0,60}(?:预览|候选|上一轮)',message))
    if (preview_ref and re.search(r'加入|添加|追加|放到|放进|放入|放在|加到|加进',message)
            and re.search(r'今日卷|今日学习',message)
            and not re.search(r'不要|别|先不|暂不|能不能|是否|要不要|吗[。！!]?$|？|\?',message)):
        return None
    result={'context':{},'proposal':None,'receipt':None}
    def reply(text):return {**result,'message':text}
    with factory() as db:
        recent=db.scalars(select(ChatMessage).where(ChatMessage.session_id==session_id,
            ChatMessage.role=='assistant',ChatMessage.status=='completed').order_by(ChatMessage.seq.desc()).limit(40))
        memory=next(((row.metadata_ or {})['paper_adjustment'] for row in recent
            if isinstance((row.metadata_ or {}).get('paper_adjustment'),dict)),{})
        saved=memory.get('proposal') or {}
        saved_task=None
        try:saved_task=db.get(LearningTask,UUID(saved.get('task_id','')))
        except (ValueError,TypeError):pass
        pending_draft=(saved_task.draft if saved_task is not None
            and saved_task.session_id==session_id and saved_task.status=='ready'
            and (saved_task.context or {}).get('paper_adjustment')
            and not (saved_task.metrics or {}).get('commit') else None)
    result['context']=memory.get('context',{})
    result['proposal']=memory.get('proposal')
    if pending_draft and command['action'] in {'add','remove','replace'}:
        from datetime import datetime
        try:
            expired=now>=datetime.fromisoformat(pending_draft['expires_at'])
        except (KeyError,TypeError,ValueError):
            expired=True
        if expired:
            return reply('上一次待确认调整方案已过期，不能继续叠加；请取消旧方案并根据当前正式卷重新预览。原卷和历史记录未改变。')
    if command['action']=='clarify':
        return reply('请用阿拉伯数字明确题号和数量，例如“删除第11题”。原卷和已有待确认方案均未改变。')
    if command['action']=='cancel':
        proposal=memory.get('proposal')
        if not proposal:return reply('当前没有待取消的调整方案。')
        from backend.services.learning_task_service import cancel_task
        try:cancel_task(factory,UUID(proposal['task_id']))
        except AppError:return reply('该方案已经执行或失效，不能把历史操作当作未执行方案撤销。')
        result['proposal']=None
        return reply('本次调整方案已取消，正式卷保持原状态。')
    if command['action']=='query':
        # Preserve actual inventory queries and explicitly requested draft
        # previews, but a bare mutation question/denial grants no new Task.
        # An explicit withdrawal of the pending mutation is different from a
        # question: invalidate that draft so a later bare confirmation cannot
        # resurrect the action the user just declined.
        if command.get('revoke_proposal') and memory.get('proposal'):
            from backend.services.learning_task_service import cancel_task
            try:cancel_task(factory,UUID(memory['proposal']['task_id']))
            except (AppError,KeyError,ValueError,TypeError):
                return reply('待确认方案已经执行或失效，不能取消；请刷新核对正式卷状态。')
            result['proposal']=None
            return reply('已取消刚才的待确认调整方案，正式卷保持原状态。')
        from backend.services.assistant_data_queries import classify_read_only_data_query
        from backend.services.bank_selection_intent import explicit_plan_preview
        if classify_read_only_data_query(message) or explicit_plan_preview(message):return None
        return reply('这条是询问或暂不执行的调整，当前正式卷和待确认方案均未修改。请明确需要预览的知识点与题量；预览后再单独确认。')
    if command['action']=='confirm':
        proposal=memory.get('proposal')
        if not proposal:return reply('当前没有可确认的正式卷调整方案，请先指定要调整的题目。')
        result['proposal']=proposal
        try:
            receipt=confirm_adjustment(factory,UUID(proposal['task_id']),PaperAdjustmentConfirmation(
                session_id=session_id,draft_version=proposal['draft_version'],confirm_viewed=command['viewed'],
                accept_budget_overrun=command.get('budget_confirmed',False)),now=now)
        except AppError as exc:
            if exc.code=='paper_budget_confirmation_required':
                workload=proposal.get('workload') or (proposal.get('draft') or {}).get('workload') or {}
                return reply(f"方案预计剩余{workload.get('remaining_minutes')}分钟，超出预算{workload.get('excess_minutes')}分钟，尚未执行。接受超出用时请回复“确认超预算调整”；含已浏览题请回复“确认移除已浏览题目并接受超预算”。")
            return reply({'paper_viewed_confirmation_required':'这些题已经浏览过，需二次确认。确认移除请明确回复“确认移除已浏览题目”。',
                'paper_budget_unknown':'题目缺少可靠的冻结版本用时，无法核验预算；正式卷和历史记录已保留。',
                'paper_item_protected':'题目已经开始、作答、完成或跳过，已保留原题及历史记录。',
                'learning_task_stale_draft':'方案已经过期或卷子状态已变化，请重新预览。'}.get(exc.code,'本次调整未执行，请重新查看当前卷并预览方案。'))
        result.update(receipt=receipt,proposal=proposal,context=memory.get('context',{}))
        from backend.services.today_append_result import source_label
        details='\n'.join(f"第{i['number']}题 · {i['kp_name']}\n{i['stem']}\n来源：{source_label(i['source_category'])}\n题目版本：{i['question_version_id']}" for i in receipt.get('added_items',[]))
        remaining=receipt.get('remaining_minutes')
        timing=f'预计剩余{remaining}分钟。' if remaining is not None else '预计剩余时间暂不可核验。'
        if receipt.get('budget_overrun_accepted'):
            timing+=f"已按本次明确同意接受超出预算{receipt['budget_overrun_minutes']}分钟。"
        before=f"原有{receipt['before_count']}道，" if 'before_count' in receipt else ''
        return reply(f"调整已完成：{before}移除{len(receipt['removed_item_ids'])}道，新增{receipt['added_count']}道，当前共{receipt['total_count']}道。"+timing+ ('\n'+details if details else ''))
    if command['easy']:
        return reply('目前没有可核验的逐题难度评估，不能据此选题；原卷和待确认方案保持不变，尚未执行。请指定题号。')
    implicit_reference=None
    if (command['action']=='add' and re.search(r'刚才|那道|这道|上一道',message)
            and not re.search(r'洛必达|隐函数|数据结构|操作系统|组成原理|计算机网络',message)):
        # Bind pronouns only to a persisted, same-session, unexpired preview.
        # Never use the model's prose as evidence for a question or version.
        from backend.services.practice_preview_reference import latest_preview,preview_question_state
        implicit_reference,notice=latest_preview(factory,session_id,message,now)
        if implicit_reference is None:
            return reply(notice if notice and '没有可确定' in notice
                else '没有可确定的上一轮题目预览；请先在本会话查询或预览一道题。')
        reference_state=preview_question_state(factory,implicit_reference,ctx,now)
        if reference_state:
            if reference_state.get('state')=='already_in_today_plan':
                # Let the existing read-only selection projection attach its
                # established selection_state metadata and exact paper number.
                return None
            return reply(reference_state['message'])
    with factory() as db:
        plan=db.get(DailyPlan,ctx.daily_plan_id)
        if plan is None:return reply('当前正式卷不存在，请刷新页面。')
        plan_rows=list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id==plan.id,PracticeItem.removed_at.is_(None))))
        # A short count correction replaces the previous remove count. An
        # explicit "再/继续/另外减少" remains additive against the current
        # draft; otherwise phrases such as “两道…改成一道” must not silently
        # become a three-question reduction.
        previous_operation=(memory.get('context') or {}).get('operation')
        correcting_removal=(previous_operation=='remove' or
            (previous_operation is None and pending_draft and not pending_draft.get('replacements')))
        quantity_correction=bool(pending_draft and correcting_removal and command['action']=='remove'
            and re.fullmatch(r'(?:那\s*)?(?:(?:改成|改为)\s*)?(?:减少|删除|移除)\s*[一二两三四五六七八九十\d]+\s*(?:道|题)(?:吧|好了)?[。！!？?]*',message.strip())
            and not re.search(r'再|继续|另外|额外',message))
        planned_removals=set(pending_draft.get('remove_item_ids',[])) if pending_draft else set()
        if quantity_correction:
            # Revise only the most recent removal group, preserving unrelated
            # earlier topic edits composed into the same pending proposal.
            planned_removals.difference_update((memory.get('context') or {}).get('item_ids',[]))
        prior_refs=list(pending_draft.get('replacements',[])) if pending_draft else []
        if quantity_correction:
            prior_refs=list((memory.get('context') or {}).get('before_remove_references',prior_refs))
        reserved_pending_ids={str(ref.get('question_id')) for ref in prior_refs}
        effective_rows=[]
        questions={}
        for item in plan_rows:
            if str(item.id) in planned_removals:continue
            question=question_for_practice_item(db,item)
            if question is None:continue
            effective_rows.append(item);questions[item.id]=question
        next_ordinal=max((i.ordinal for i in plan_rows),default=0)+1
        for offset,ref in enumerate(prior_refs):
            try:question=db.get(Question,UUID(ref['question_id']))
            except (ValueError,TypeError):question=None
            if (question is None or question_version_reference(question)!=ref['question_version_id']
                    or question.bank_scope!='public'):
                return reply('上一次待确认方案中的题目版本已变化；该方案不能继续修改，请重新预览当前卷。')
            virtual=SimpleNamespace(id=question.id,kp_id=question.kp_id,ordinal=next_ordinal+offset,
                question_id=question.id,question_version_id=UUID(ref['question_version_id']),
                proposal_item=True)
            effective_rows.append(virtual);questions[virtual.id]=question
        items=effective_rows
        items.sort(key=lambda i:display_key(questions[i.id].question_type,i.ordinal))
        remove_item_ids=set(planned_removals)
        replacement_refs=list(prior_refs)
        # A soft-removed PracticeItem is still historical evidence. Never select
        # its question again as a replacement for the same paper.
        existing_question_ids=set(db.scalars(select(PracticeItem.question_id).where(
            PracticeItem.plan_id==plan.id,PracticeItem.question_id.is_not(None))))
        nodes=list(db.scalars(select(KnowledgePoint).where(KnowledgePoint.is_active.is_(True))))
        matches=[n for n in nodes if n.name in message or (n.name=='隐函数求导' and '隐函数' in message)]
        matches.sort(key=lambda n:(message.find(n.name) if n.name in message else message.find('隐函数'),-len(n.name)))
        batch_edits,batch_error=_topic_count_batch(message,nodes)
        if batch_error:return reply(batch_error)
        if batch_edits:command={**command,'action':'batch'}
        context=memory.get('context',{})
        if pending_draft and pending_draft.get('plan_id')!=str(plan.id):
            return reply('上一次待确认方案关联的正式卷已变化；请刷新并针对当前卷重新预览。')
        if command['action']=='add' and not matches and not context.get('kp_id') and not implicit_reference:
            return reply('请说明要增加题目的知识点，例如“增加一道洛必达法则题”。原卷保持不变。')
        cross='408' in message and command['action']=='replace'
        all_math=cross and _is_whole_math_replacement(message)
        cross_all=cross and bool(re.search(r'当前的题目都换|整卷|整套|全部课程内容',message))
        if batch_edits:
            selected=[]
            for node,delta in batch_edits:
                if delta>=0:continue
                scoped=[item for item in items if item.kp_id==node.id]
                if len(scoped)<-delta:
                    return reply(f'{node.name}当前只有{len(scoped)}道，不能减少{-delta}道；整项调整未提交，原卷保留。')
                selected.extend(scoped[delta:])
        elif all_math:
            math_ids={n.id for n in nodes if re.search('math|数学',n.subject,re.I)}
            selected=[i for i in items if i.kp_id in math_ids]
        elif cross_all:
            selected=list(items)
        elif command['number']:
            selected=items[command['number']-1:command['number']] if command['number']>0 else []
        elif command['action']=='add':
            selected=[]
        else:
            topic=matches[0].id if matches else UUID(context['kp_id']) if context.get('kp_id') else None
            if topic and command['all_topic']:
                topic_ids={n.id for n in matches} if command['each_topic'] and matches else {topic}
                selected=[i for i in items if i.kp_id in topic_ids]
            elif topic and command['each_topic'] and matches:
                selected=[]
                for node in matches:
                    scoped=[i for i in items if i.kp_id==node.id]
                    selected.extend(scoped[-command['count']:] if command['action']=='remove' else scoped[:command['count']])
            else:
                scoped=[i for i in items if i.kp_id==topic] if topic else []
                selected=(scoped[-command['count']:] if command['action'] in {'remove','replace'}
                    else scoped)
            if command['action']=='replace' and not matches and re.search(r'给我换一道',message) and ctx.practice_item_id:
                selected=[i for i in items if i.id==ctx.practice_item_id]
            if not selected and re.search(r'刚才|那道|这道',message) and ctx.practice_item_id:
                selected=[i for i in items if i.id==ctx.practice_item_id]
        target_node=matches[-1] if matches else None
        if batch_edits and target_node is None:target_node=batch_edits[-1][0]
        if not selected and command['action'] not in {'add','batch'} and not (cross and command['topic_count']):return reply('请指定当前卷的实际题号或明确知识点名称。')
        result['context']={'operation':command['action'],
            'kp_id':str((selected[0].kp_id if selected else target_node.id)) if selected or target_node else None,
            'item_ids':[str(i.id) for i in selected], 'subject':'408' if cross else None}
        if command['action']=='remove':
            result['context']['before_remove_references']=[dict(ref) for ref in prior_refs]
        if batch_edits:
            result['context']['kp_id']=None
            result['context']['topic_count_edits']=[{'kp_id':str(node.id),'name':node.name,'delta':delta,
                'before_count':sum(i.kp_id==node.id for i in items),
                'after_count':sum(i.kp_id==node.id for i in items)+delta} for node,delta in batch_edits]
        # Compose each turn against the last uncommitted proposal. Removing a
        # proposed addition edits only the draft; removing a persisted item
        # adds its immutable PracticeItem id to the combined soft-removal set.
        selected_proposal_ids=set()
        for item in selected:
            if getattr(item,'proposal_item',False):selected_proposal_ids.add(str(item.question_id))
            else:remove_item_ids.add(str(item.id))
        if selected_proposal_ids:
            replacement_refs=[ref for ref in replacement_refs if str(ref.get('question_id')) not in selected_proposal_ids]
        if command['action'] in {'remove','replace'} and not cross and not command['all_topic'] and not command['each_topic'] and len(selected)!=command['count']:
            positions=[str(items.index(i)+1) for i in selected]
            return reply(f"该范围有{len(selected)}道题（当前第{'、'.join(positions)}题），请明确要调整的题号。")
        replacements=[]
        if command['action'] in {'replace','add','batch'}:
            if implicit_reference is not None:
                # Reuse the exact version the user saw. The proposal service
                # revalidates public scope, eligibility and duplicates before
                # persisting the adjustment draft.
                replacements=[ReplacementReference(
                    question_id=UUID(implicit_reference['question_id']),
                    question_version_id=UUID(implicit_reference['question_version']))]
                result['context'].update(kp_id=implicit_reference['kp_id'],
                    item_ids=[],selected_question_id=implicit_reference['question_id'])
            elif cross:
                from backend.services.home_recommendation_service import _subject_plan_scope
                from backend.services.question_eligibility import question_eligibility
                course_scope_ids,target_course=_requested_408_topic_scope(message,nodes)
                scoped_topic_replacement=bool(target_course and course_scope_ids and selected
                    and command['all_topic'] and not all_math and not cross_all
                    and command['topic_count'] is None)
                topic_count=command['topic_count'] or (6 if all_math or cross_all or not matches else 1)
                budget_minutes=command['budget_minutes'] or 60
                if not 5<=budget_minutes<=240:return reply('预算请指定为5到240分钟；原卷保持不变。')
                topic_ids,evidence=_subject_plan_scope(db,now,subject='408',count=1000)
                if target_course:
                    evidence=[row for row in evidence if UUID(row['kp_id']) in (course_scope_ids or set())]
                    topic_ids=[UUID(row['kp_id']) for row in evidence]
                    if not topic_ids:
                        return reply(f'408{target_course}当前没有真实、符合正式准入且可安排的知识点；未创建方案，原卷保留。')
                unseen_only=bool(re.search(r'没做过|未做过|未学习|没有做过',message))
                if unseen_only: evidence=[e for e in evidence if e.get('attempt_count',0)==0]
                topic_ids=[UUID(e['kp_id']) for e in evidence]
                existing=existing_question_ids|{UUID(value) for value in reserved_pending_ids}
                pools=[]
                missing=[]
                for topic_id in topic_ids:
                    node=db.get(KnowledgePoint,topic_id)
                    pool=[q for q in db.scalars(select(Question).where(Question.kp_id==topic_id,
                        Question.bank_scope=='public').order_by(Question.estimated_minutes,Question.id))
                        if q.id not in existing and q.current_version_id is not None and question_eligibility(q,node).practice_eligible
                        and type(q.estimated_minutes) is int and q.estimated_minutes>0]
                    if pool:pools.append((node,pool))
                    else:missing.append(node.name)
                if scoped_topic_replacement and command['topic_count'] is None:
                    # Spread a whole-course replacement across as many eligible
                    # target topics as the old quantity allows, then use spare
                    # admitted questions from every topic in that course. A
                    # single high-ranked leaf must not cap the replacement stock.
                    topic_count=min(len(pools),len(selected))
                if len(pools)<topic_count:
                    names='、'.join(missing[:8]) if missing else '当前候选列表中的其他知识点'
                    return reply(f'真实正式准入库存只覆盖{len(pools)}个408知识点，目标{topic_count}个，缺{topic_count-len(pools)}个；无可追加合格题的知识点：{names}。未创建方案，原卷保留。')
                selected_pools=pools[:topic_count]
                chosen=[pool[0] for _,pool in selected_pools];minutes=sum(q.estimated_minutes for q in chosen)
                if minutes>budget_minutes:return reply(f'{topic_count}个知识点各选一道的最短预计用时为{minutes}分钟，超过{budget_minutes}分钟。未创建方案，原卷保留。')
                replacement_limit=len(selected) if scoped_topic_replacement else None
                remaining=_replacement_fill_candidates(pools,selected_pools,
                    preserve_replaced_quantity=replacement_limit is not None)
                if replacement_limit is not None and len(remaining)+len(chosen)<replacement_limit:
                    available=len(remaining)+len(chosen)
                    return reply(f'408{target_course}符合正式准入且卷外可用题量不足：当前需替换{replacement_limit}道，仅有{available}道可用，缺少{replacement_limit-available}道；未创建方案，原卷保留。')
                for q in remaining[:max(0,replacement_limit-len(chosen))] if replacement_limit is not None else remaining:
                    if minutes+q.estimated_minutes<=budget_minutes or replacement_limit is not None:
                        chosen.append(q);minutes+=q.estimated_minutes
                if replacement_limit is not None and len(chosen)!=replacement_limit:
                    return reply(f'408{target_course}替换后的预计用时超过{budget_minutes}分钟；方案未创建，原卷保留。请先提高预算后重新预览。')
                replacements=[ReplacementReference(question_id=q.id,question_version_id=UUID(question_version_reference(q))) for q in chosen]
                result['context']['estimated_minutes']=minutes
                result['context']['recommendation_evidence']=evidence
                chosen_topic_ids={q.kp_id for q in chosen}
                result['context']['selected_408_topics']=[{'kp_id':str(node.id),'name':node.name,'attempt_count':next((e.get('attempt_count',0) for e in evidence if e['kp_id']==str(node.id)),0)} for node,_ in pools if node.id in chosen_topic_ids]
                result['context']['budget_minutes']=budget_minutes
                if scoped_topic_replacement:
                    result['context']['scoped_topic_replacement']={
                        'target_course':target_course,
                        'removed_question_count':len(selected),
                        'replacement_question_count':len(replacements),
                        'preserves_removed_quantity':len(selected)==len(replacements),
                    }
            else:
                from backend.services.question_eligibility import question_eligibility
                existing=existing_question_ids|{UUID(value) for value in reserved_pending_ids}
                if batch_edits:
                    targets=[(node.id,delta) for node,delta in batch_edits if delta>0]
                elif command['each_topic'] and command['action']=='replace' and len(matches)>1:
                    # Each selected topic retains its own candidate scope. Build
                    # every pool before proposing one atomic adjustment.
                    targets=[(node.id,sum(i.kp_id==node.id for i in selected)) for node in matches]
                else:
                    targets=[(matches[-1].id if matches else selected[0].kp_id,
                        command['count'] if command['action']=='add' else len(selected))]
                for target,wanted in targets:
                    if not wanted:continue
                    node=db.get(KnowledgePoint,target)
                    candidates=list(db.scalars(select(Question).where(Question.kp_id==target,Question.bank_scope=='public').order_by(Question.id)))
                    eligible=[q for q in candidates if q.id not in existing and q.current_version_id is not None and question_eligibility(q,node).practice_eligible]
                    if len(eligible)<wanted:
                        return reply(f'{node.name}可追加题量不足：卷外符合正式准入条件的题量为{len(eligible)}道，需要{wanted}道，缺少{wanted-len(eligible)}道；整项调整未提交，原卷保留。')
                    replacements.extend(ReplacementReference(question_id=q.id,question_version_id=UUID(question_version_reference(q))) for q in eligible[:wanted])
    try:
        replacement_refs.extend([r.model_dump(mode='json') for r in replacements])
        if pending_draft and not remove_item_ids and not replacement_refs:
            # Removing a proposed addition can restore the original paper.
            # Cancel the old proposal so a later confirmation cannot append
            # the question the learner has just removed from the draft.
            from backend.services.learning_task_service import cancel_task
            try:
                cancel_task(factory,saved_task.id)
            except AppError:
                return reply('待确认方案状态已变化，未能取消；请刷新核对，正式卷未改变。')
            result['proposal']=None
            return reply('调整后与当前正式卷一致，已取消待确认方案；正式卷和历史记录未改变。')
        ordered_removals=[i.id for i in plan_rows if str(i.id) in remove_item_ids]
        result['proposal']=propose_adjustment(factory,PaperAdjustmentRequest(session_id=session_id,
            plan_id=ctx.daily_plan_id,remove_item_ids=ordered_removals,
            replacements=[ReplacementReference.model_validate(ref) for ref in replacement_refs],
            budget_minutes=result['context'].get('budget_minutes',command['budget_minutes'] or 60)),now=now)
    except AppError as exc:
        stale_reasons={
            'replacement_question_missing':'候选题目已不存在',
            'replacement_already_in_plan':'候选题目已经存在于今日卷，不能重复加入',
            'replacement_not_public':'候选题目不属于正式公共题库',
            'replacement_version_changed':'候选题目的正式版本已变化',
        }
        if exc.code=='learning_task_stale_draft' and exc.detail in stale_reasons:
            return reply(f'{stale_reasons[exc.detail]}；本次没有建立方案，原卷保持不变。')
        if exc.code=='learning_task_stale_draft' and exc.detail=='replacement_not_formally_eligible':
            return reply('候选题目未通过正式准入复核；本次没有建立方案，原卷保持不变。')
        messages={
            'paper_budget_unknown':'部分题目缺少可靠的冻结版本用时，无法核验调整预算；原卷和历史记录保持不变。',
            'paper_item_protected':'该题已有学习记录或已被移除，系统保留了题目与历史记录，本次未执行。',
            'paper_viewed_confirmation_required':'这些题已经浏览过，请先预览并单独确认移除。',
            'learning_task_conflict':'正式卷状态已变化或题目范围无效，本次未执行；请刷新后重新预览。',
            'learning_task_stale_draft':'候选题目准入或版本已变化，本次未执行；原卷保持不变。',
            'chat_session_not_found':'当前会话已失效，本次未执行。',
        }
        return reply(messages.get(exc.code,'所选题目当前受到保护，或卷状态发生变化；本次未执行。'))
    warning='所选题目已浏览，最终移除还需明确二次确认。' if result['proposal']['requires_viewed_confirmation'] else ''
    positions='、'.join(str(items.index(i)+1) for i in selected)
    workload=result['proposal']['workload']
    duration=workload['remaining_minutes']
    timing=f"预计剩余{duration}分钟，预算{workload['budget_minutes']}分钟。"
    instruction=('超出预算'+str(workload['excess_minutes'])+'分钟，尚未执行。接受超出用时请回复“确认超预算调整”；含已浏览题请回复“确认移除已浏览题目并接受超预算”。'
        if workload['requires_confirmation'] else '回复“确认调整”后执行。')
    action_label={'remove':'移除','replace':'替换','add':'追加','batch':'批量增减'}[command['action']]
    removal_summary=f"移除当前第{positions}题，共{len(selected)}道" if selected else '保留现有题目'
    selected_topics=result['context'].get('selected_408_topics',[])
    batch_summary='；'.join(f"{row['name']}：{row['before_count']}→{row['after_count']}道"
        for row in result['context'].get('topic_count_edits',[]))
    topic_summary=('知识点：'+'、'.join(n['name'] for n in selected_topics)+'。') if selected_topics else ''
    return reply(f"待确认方案：{action_label}；{removal_summary}，新增{len(replacements)}道。{topic_summary}{batch_summary}{timing}{warning}{instruction}当前正式卷尚未改变。")
