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
    # “恢复刚才删除的题/恢复全部已删除的题目”必须先于 remove 识别：
    # 这类句子里同时含“删除”，否则会被错判成再删一次。
    if (re.search(r'恢复|还原|(?<!追)加回来|放回来|加回(?:去|到)', text)
            and re.search(r'题|题目|知识点', text)
            and not re.search(r'恢复系统推荐|恢复今日最初|恢复原方案|恢复全部原始|恢复上次|恢复默认', text)):
        quantity=re.search(r'([一二两三四五六七八九十\d]+)\s*道', text)
        count=1
        if quantity:
            from backend.services.home_intent import question_count as _qc
            count=_qc(quantity.group(1)) or 1
        if re.search(r'全部|所有|原来的|原本的|刚才的|刚刚的|之前的', text):
            count=99
        return {'action':'restore_removed','count':count,'text':text}
    if re.fullmatch(r'取消(?:本次)?调整[。！!]?|撤销(?:本次)?方案[。！!]?',text):
        return {'action':'cancel'}
    # 「不换了 / 算了 / 取消替换」是用户撤回待确认方案的高频说法；
    # 不识别会落到普通问答，模型嘴上说“已取消”，待确认方案其实还在。
    if re.fullmatch(r'(?:那)?(?:不换了|算了|不要了|取消替换|取消这次替换|撤销替换)[。！!，,]?',text.strip()):
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
    # 动作判定：显式的“换/替换”才是 replace；“增加/追加/加入”是 add。
    # “408” 只作为科目修饰词出现（“增加一道408操作系统的题目”），
    # 不能凭它就判成 replace，否则会增加请求被当成更换。
    if re.search(r'换|替换|改换成|替换为',text):
        action='replace'
    elif re.search(r'增加|追加|加入|再加|添加',text):
        action='add'
    elif re.search(r'减少|删除|移除|去掉',text):
        action='remove'
    else:
        action='add' if re.search(r'408',text) else 'remove'
    return {'action':action,
        'count':count,'number':integer(number[1]) if number else None,
        'explicit_count':bool(counts),
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


def _latest_ready_adjustment(factory, session_id):
    """返回该会话最新仍未提交的正式卷调整方案（可能为空）。"""
    from backend.services.paper_adjustment_service import _version
    with factory() as db:
        rows=db.scalars(select(LearningTask)
            .where(LearningTask.session_id==session_id)
            .order_by(LearningTask.updated_at.desc().nullslast(), LearningTask.id.desc()))
        for row in rows:
            if (row.status=='ready' and (row.context or {}).get('paper_adjustment')
                    and not (row.metrics or {}).get('commit') and row.draft):
                draft=row.draft
                return {'task_id':str(row.id),'draft_version':_version(draft),
                    'draft':draft,'workload':draft.get('workload')}
    return None


def handle_paper_chat(factory, *, session_id, ctx, message, now, target_item_id=None):
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
    if command['action']=='restore_removed':
        result['proposal']=None
        from backend.models.learning import LearningEvent as _LE
        undo_replace=bool(re.search(r'不换了|撤销(?:这次|本次)?替换|恢复原来的题目|恢复原本的题目|撤销刚才的替换',message))
        if undo_replace:
            # 「不换了」= 撤销最近一次完整替换：把被换掉的旧题恢复，同时把本次新增的题软移除。
            # 依据替换任务自身的 draft（remove_item_ids / replacements），不靠知识点名推断。
            with factory() as db:
                task=None
                for cand in db.scalars(select(LearningTask).where(
                        LearningTask.session_id==session_id).order_by(
                        LearningTask.created_at.desc().nullslast()).limit(20)):
                    draft=cand.draft or {}
                    if (draft.get('remove_item_ids') and draft.get('replacements')
                            and (cand.metrics or {}).get('commit')):
                        task=cand
                        break
                if task is None:
                    return reply('没有找到最近一次可撤销的替换记录；原卷保持不变。')
                draft=task.draft or {}
                old_ids={str(x) for x in (draft.get('remove_item_ids') or [])}
                new_qids={str(r.get('question_id')) for r in (draft.get('replacements') or [])}
                items=list(db.scalars(select(PracticeItem).where(
                    PracticeItem.plan_id==ctx.daily_plan_id)))
                restored=removed_new=0
                for item in items:
                    if str(item.id) in old_ids and item.removed_at is not None:
                        item.removed_at=None
                        db.add(_LE(kp_id=item.kp_id,source_id=item.id,
                            question_version_id=item.question_version_id,
                            event_type='paper_item_restored',occurred_at=now,
                            idempotency_key=f'paper-undo-restore:{item.id}:{int(now.timestamp())}',
                            payload={'changes_mastery':False,'undo_of_task':str(task.id)}))
                        restored+=1
                    elif str(item.question_id) in new_qids and item.removed_at is None:
                        item.removed_at=now
                        db.add(_LE(kp_id=item.kp_id,source_id=item.id,
                            question_version_id=item.question_version_id,
                            event_type='paper_item_removed',occurred_at=now,
                            idempotency_key=f'paper-undo-remove:{item.id}:{int(now.timestamp())}',
                            payload={'changes_mastery':False,'undo_of_task':str(task.id)}))
                        removed_new+=1
                db.flush()
                db.commit()
            return reply(f'已撤销这次替换：恢复{restored}道原题、移除{removed_new}道本次新增的题；'
                '其他题目的ID与版本保持不变，历史作答未受影响。')
        with factory() as db:
            removed=list(db.scalars(select(PracticeItem).where(
                PracticeItem.plan_id==ctx.daily_plan_id,
                PracticeItem.removed_at.is_not(None)).order_by(PracticeItem.removed_at.desc())))
            if not removed:
                return reply('当前卷没有已删除的题目可以恢复。')
            # 优先恢复“最近一次替换/删除真正移除的题”：用户说“不换了/恢复原来的题目”时，
            # 指的是刚被换掉的那批，而不是任意一道更早软移除的题。
            recent_ids=[]
            try:
                tasks=list(db.scalars(select(LearningTask).where(
                    LearningTask.session_id==session_id).order_by(
                    LearningTask.created_at.desc().nullslast()).limit(5)))
                for task in tasks:
                    draft=task.draft or {}
                    ids=[str(x) for x in (draft.get('remove_item_ids') or [])]
                    if ids:
                        recent_ids=ids
                        break
            except Exception:
                recent_ids=[]
            by_id={str(item.id):item for item in removed}
            ordered=[by_id[i] for i in recent_ids if i in by_id]
            rest=[item for item in removed if str(item.id) not in {i for i in recent_ids}]
            pool=ordered+rest
            take=pool[:min(int(command.get('count') or 1),len(pool))]
            for item in take:
                item.removed_at=None
                db.add(_LE(kp_id=item.kp_id,source_id=item.id,
                    question_version_id=item.question_version_id,
                    event_type='paper_item_restored',occurred_at=now,
                    idempotency_key=f'paper-restore:{item.id}:{int(now.timestamp())}',
                    payload={'changes_mastery':False}))
            db.flush()
            db.commit()
            restored=len(take)
        return reply(f'已恢复{restored}道题到今日卷；原题ID与版本保持不变，历史作答未受影响。')
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
        # 连续多轮调整时，上一条消息里记住的 proposal 可能已被同一会话的
        # 新方案取代（旧 task 被标记 cancelled）。确认动作绝不能静默作用到
        # 一份用户没看过的方案上：先展示最新方案并要求用户再确认一次。
        fresh=_latest_ready_adjustment(factory,session_id)
        if (fresh and fresh['task_id']!=proposal.get('task_id')):
            result['proposal']=fresh
            count=len((fresh.get('draft') or {}).get('remove_item_ids') or [])
            return reply(f'方案已更新：最新一次调整是移除{count}道题。为避免误删，本次没有直接执行；请核对上方最新方案后再次回复“确认调整”。')
        proposal=fresh or proposal
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
        result['proposal']=None
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
        # “把某个知识点换成另一种题”是一次针对当前正式卷的整段替换：它不该继承
        # 同一会话里更早的待确认方案（那些方案可能已经把源知识点整段排掉），
        # 否则 items 里找不到该知识点，请求会退化成“请指定题号”，或移除数量越滚越多。
        nodes=list(db.scalars(select(KnowledgePoint).where(KnowledgePoint.is_active.is_(True))))
        # 替换类请求里“A 换成 B”：A 是源、B 是目标。“目标知识点”也常出现在消息中
        # （“把等比级数换成408计算机组成原理”），若整句参与匹配就会把目标当成源。
        # 因此只在前半段（“换成/替换为”之前）里找源知识点。
        source_text=message
        for marker in ('换成','替换为','替换成','换到','改换成'):
            if marker in message:
                source_text=message.split(marker)[0]
                break
        matches=[n for n in nodes if n.name in source_text or (n.name=='隐函数求导' and '隐函数' in source_text)]
        matches.sort(key=lambda n:(source_text.find(n.name) if n.name in source_text else source_text.find('隐函数'),-len(n.name)))
        if not matches:
            # 用户常说的是简称（“等比级数”），而知识点全名是“等比级数的敛散性与求和”。
            # 这里做有界前缀回退：取全名前 2..6 字，若该前缀出现在前段文本里，且只有
            # 唯一一个知识点满足，就采用它；出现歧义时不猜，保持原来的澄清行为。
            hits={}
            for node in nodes:
                for length in range(min(6,len(node.name)),1,-1):
                    if node.name[:length] in source_text:
                        hits.setdefault(node.name,length)
                        break
            if hits:
                # 取“最长前缀”的命中：用户说“等比级数”时，“408 计算机学科专业基础”
                # 也会因为消息里的“408”以 3 字前缀命中；按最长前缀唯一才采纳，
                # 可以避免科目级节点抢走具体知识点。
                best=max(hits.values())
                winners=[name for name,length in hits.items() if length==best]
                if len(winners)==1:
                    picked=winners[0]
                    matches=[node for node in nodes if node.name==picked]
                    named_replace_by_prefix=True
                else:
                    named_replace_by_prefix=False
            else:
                named_replace_by_prefix=False
        else:
            named_replace_by_prefix=False
        # 只有“换成 408/计算机”这类跨科目替换才从当前正式卷重新起算；同科目内的
        # 多轮编辑仍要继承上一份待确认方案（R40 契约：多轮组合成一份方案）。
        named_replace=(command['action']=='replace' and bool(matches)
            and bool(re.search(r'408|计算机', message)))
        # A short count correction replaces the previous remove count. An
        # explicit "再/继续/另外减少" remains additive against the current
        # draft; otherwise phrases such as “两道…改成一道” must not silently
        # become a three-question reduction.
        previous_operation=(memory.get('context') or {}).get('operation')
        correcting_removal=(previous_operation=='remove' or
            (previous_operation is None and pending_draft and not pending_draft.get('replacements')))
        quantity_correction=bool(pending_draft and correcting_removal and command['action']=='remove'
            # 只有“减少一道/减少两道”这种不带知识点的短句才是对上一组数量的修正；
            # 带知识点的“减少一道X的题”按 R40 契约继续累加，不能被误当成修正。
            and re.fullmatch(r'(?:那\s*)?(?:(?:改成|改为)\s*)?(?:减少|删除|移除)\s*[一二两三四五六七八九十\d]+\s*(?:道|题)(?:吧|好了)?[。！!？?]*',message.strip())
            and not re.search(r'再|继续|另外|额外',message))
        planned_removals=(set() if named_replace else
            set(pending_draft.get('remove_item_ids',[])) if pending_draft else set())
        if quantity_correction:
            # Revise only the most recent removal group, preserving unrelated
            # earlier topic edits composed into the same pending proposal.
            planned_removals.difference_update((memory.get('context') or {}).get('item_ids',[]))
        # 点名知识点的整段替换是一次新的替换：不要继承上一份待确认方案的 replacements，
        # 否则连续两次替换会把新增量叠加（实测 3换3 再确认变成 25 道）。
        _fresh_topic_replace=(command['action']=='replace' and bool(matches)
            and command['topic_count'] is None)
        prior_refs=([] if _fresh_topic_replace
            else list(pending_draft.get('replacements',[])) if pending_draft else [])
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
        # “一样的题量/题量不变”：替换必须保持被替换知识点的题量，不能只换当前
        # 打开的一道、再用剩余预算补满。
        # “把隐函数求导的题目换成408操作系统”在用户语义里指该知识点的整段题目，
        # 不是只换一道。点名知识点、未给数量、动作为替换时默认按整段替换；
        # 用户显式说了“一样的题量/题量不变”时同样成立。
        # 只有“点名知识点 + 没给数量 + 指明了换成什么”的替换才按整段处理
        # （“把隐函数换成408”）；“替换一道X的题目”这类同节点换题必须按数量走。
        named_topic_replace=(command['action']=='replace' and bool(matches)
            and command['topic_count'] is None and not command.get('explicit_count')
            and bool(re.search(r'换成|替换成|替换为|改换成|408',message)))
        same_quantity=(bool(re.search(r'一样的?题量|同样的?题量|题量不变|数量不变|相同的?题量',message))
            or named_topic_replace)
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
        elif target_item_id is not None and not matches:
            # 只有“换掉当前这一道”才用 target_item_id。消息点名了知识点时
            # （如“把行列式的性质换成408”），必须走下面的知识点分支。
            selected=[item for item in items if str(item.id)==str(target_item_id)]
            if len(selected)!=1:
                return reply('刚才引用的题目已不在当前可调整方案中；今日卷未改变，请刷新后重新预览。')
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
                whole_topic_replace=(command['action']=='replace' and matches and same_quantity)
                selected=(scoped if whole_topic_replace else
                    scoped[-command['count']:] if command['action'] in {'remove','replace'}
                    else scoped)
            if command['action']=='replace' and not matches and re.search(r'给我换一道',message) and ctx.practice_item_id:
                selected=[i for i in items if i.id==ctx.practice_item_id]
            if not selected and re.search(r'刚才|那道|这道',message) and ctx.practice_item_id:
                selected=[i for i in items if i.id==ctx.practice_item_id]
            # 用户已明确授权“随便/任意/按稳定规则”任选时，不能因为没有难度数据就拒绝。
            # 稳定规则：按卷内顺序从后往前，取仍可移除（planned/viewed）的题；
            # 可移除数量不足目标时，按实际数量生成方案并如实告知，而不是要求用户再指定题号。
            if (not selected and command['action']=='remove'
                    and re.search(r'随便|任意|你选|你挑|你来选|按稳定规则|随你',message)):
                from backend.services.paper_adjustment_service import _state as _protection
                removable=[i for i in items if _protection(db,i) in {'planned','viewed'}]
                if removable:
                    take=removable[-min(command['count'],len(removable)):]
                    selected=take
                    command={**command,'count':len(take)}
                else:
                    return reply('当前卷里剩下的题都已开始、作答、完成或跳过，不能直接移除；'
                        '如需调整，请先取消对应的学习记录保护，或换一道未开始的题。')
        target_node=matches[-1] if matches else None
        if batch_edits and target_node is None:target_node=batch_edits[-1][0]
        # 整段替换时，知识点里常有一两道已经浏览过/作答过/跳过的题。整体拒绝会
        # 让“换掉这个知识点”在正常使用中几乎不可用；这里只替换仍可替换的题，
        # 其余保留，并在回复里如实说明保留了几道。
        protected_kept=0
        if command['action'] in {'replace','remove'} and selected:
            from backend.services.paper_adjustment_service import _state as _item_protection
            keep=[]
            for item in selected:
                state=_item_protection(db,item)
                if state in {'planned','viewed'}:keep.append(item)
                else:protected_kept+=1
            if protected_kept and keep:
                selected=keep
            elif protected_kept and not keep:
                return reply(f'该知识点的{protected_kept}道题都已经有学习记录（已作答/已跳过/已完成），系统保留了它们与历史记录，本次未替换。')
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
            # 用户已明确授权“随便/任意/按稳定规则”时，按实际可移除数量执行，
            # 不再要求他逐题点名；只有未授权时才让用户明确题号。
            if selected and re.search(r'随便|任意|你选|你挑|你来选|按稳定规则|随你',message):
                command={**command,'count':len(selected)}
            else:
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
                scoped_topic_replacement=bool(selected and (command['all_topic'] or same_quantity)
                    and not all_math and not cross_all
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
        # 用户没有在这句话里指定预算时，默认预算应取当前正式卷的剩余用时，
        # 而不是写死的 60 分钟。否则“减少一道题”会因为 90 分钟的卷子被拿去
        # 和 60 分钟比较，被误判成“超出预算 30 分钟”而无法确认。
        from backend.services.today_append_result import paper_time_estimates
        remaining_now=paper_time_estimates(db,plan_rows)['remaining_minutes']
        # 追加是用户明确要求的“再加一道”，加上去必然让用时变长；如果拿“当前剩余”
        # 或已扣减过的小预算去比，每次追加都会被要求“确认超预算调整”，把一次正常
        # 确认拆成两轮（实测 f02 用例即因此拿不到 receipt）。追加时给足预算，
        # 超预算提示仍用于移除/替换场景。
        # 多轮组合时（已有待确认方案），后续无论是 add 还是 remove，最终方案都可能
        # 同时包含“新增”，用当前剩余做预算必然超预算（实测：先加两道、再减一道，
        # 第三步按 remove 取 45 分钟，组合后 53 分钟直接超）。因此只要在组合模式，
        # 就给足预算；纯单轮移除仍用当前剩余，避免 R52-04 的“减题误判超预算”复发。
        if (command['action'] in {'add','replace','batch'} or pending_draft) and not command['budget_minutes']:
            # 上限 600 与 PaperAdjustmentRequest 的字段约束保持一致；超出会触发
            # pydantic 校验失败、整条调整报 internal_error。
            default_budget=min(600,max(int(getattr(plan,'budget_minutes',None) or 0),int(remaining_now or 0))+60)
        else:
            default_budget=int(remaining_now or 0) or 90
        result['proposal']=propose_adjustment(factory,PaperAdjustmentRequest(session_id=session_id,
            plan_id=ctx.daily_plan_id,remove_item_ids=ordered_removals,
            replacements=[ReplacementReference.model_validate(ref) for ref in replacement_refs],
            budget_minutes=command['budget_minutes'] or default_budget),now=now)
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
    kept_summary=(f'另有{protected_kept}道已有学习记录，保留不动。' if protected_kept else '')
    return reply(f"待确认方案：{action_label}；{removal_summary}，新增{len(replacements)}道。{topic_summary}{batch_summary}{kept_summary}{timing}{warning}{instruction}当前正式卷尚未改变。")
