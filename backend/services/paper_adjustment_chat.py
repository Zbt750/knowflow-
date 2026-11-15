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
    # Resolve withdrawal of the pending operation before topic/subject actions.
    # The remaining clause may explicitly preserve the paper; it is not a
    # second replacement request merely because it contains “408/替换”.
    if re.search(r'取消|撤回',intent_text):
        if re.search(r'不要取消|别取消|不取消|不要撤回|别撤回|能否|能不能|是否|可以吗|如果|假如|[？?]',intent_text):
            return {'action':'query','text':text,'revoke_proposal':False}
        clause=re.split(r'[，,。；;]',intent_text,1)[0].strip()
        if re.fullmatch(r'(?:那|先|请|帮我|麻烦你)*(?:取消|撤回)(?:刚才|这次|本次|当前)?的?.{0,40}(?:方案|替换|调整)',clause):
            return {'action':'cancel'}
    # “恢复刚才删除的题/恢复全部已删除的题目”必须先于 remove 识别：
    # 这类句子里同时含“删除”，否则会被错判成再删一次。
    #
    # 2026-11-13 R74 实测：用户说“恢复刚才删掉的一道隐函数求导”“全部恢复”，
    # 句中并没有“题/题目/知识点”字样（只有“一道”），旧条件不命中，整句落到
    # 通用问答，回复“目前不能直接执行恢复”，恢复能力等于不可用。
    restore_probe=intent_text
    # 2026-11-13 R75 实测：用户说“不换了，撤销刚才的替换。”，句中没有“恢复/还原”，
    # 旧判定不命中，落到普通替换分支，回成“该知识点的题都有学习记录…本次未替换”，
    # 撤销根本没有执行。这里先识别“不换了/撤销替换”这类撤回说法。
    for clause in re.split(r'[，,。；;]',restore_probe):
        if re.search(r'恢复|还原|撤销',clause) and re.search(
                r'(?:不要|别|不想|不需要|先不|暂不).{0,6}(?:恢复|还原|撤销)|能否|能不能|是否|如果|假如|[？?]|吗$',clause):
            denied=bool(re.search(r'(?:不要|别|不想|不需要|先不|暂不).{0,6}(?:恢复|还原|撤销)',clause))
            return {'action':'query','text':text,'revoke_proposal':False,'revoke_undo':denied}
    if re.search(r'不换了|撤销(?:刚才|这次|本次|整次|整套)?的?(?:替换|调整)|恢复原来的?(?:题目|知识点|题)',restore_probe):
        return {'action':'restore_removed','count':99,'text':text}
    if (re.search(r'恢复|还原|(?<!追)加回来|放回来|加回(?:去|到)', restore_probe)
            and (re.search(r'题|题目|知识点|道', restore_probe) or re.search(r'全部|所有|都', restore_probe))
            and not re.search(r'恢复系统推荐|恢复今日最初|恢复原方案|恢复全部原始|恢复上次|恢复默认', restore_probe)):
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
    #
    # 2026-11-13 R73 实测：用户说“再增加两道等价无穷小替换的题目”，
    # 其中“等价无穷小替换”是知识点名，自带“替换”二字，旧逻辑把它判成 replace，
    # 于是回执变成“替换；移除当前第8、13题”，用户的追加请求被改写成了换题。
    # 规则：句子里出现“增加/追加/添加/多安排 + 数量 + 道”，且没有真正的
    # “换成/替换成/改换成/换掉”动词时，一律按 add。
    add_with_count=re.search(
        r'(?:增加|追加|添加|再加|多安排|補充|补充)\s*(?:[零〇一二两三四五六七八九十百千]+|[1-9]\d*|几|一些)\s*道',text)
    remove_with_count=re.search(
        r'(?:减少|减去|减掉|少安排|删(?:除|掉)?|移除|去掉)\s*(?:[零〇一二两三四五六七八九十百千]+|[1-9]\d*|几|一些)\s*道',text)
    real_switch=re.search(r'换成|替换成|替换为|改换成|换掉',text)
    # 2026-11-13 R75 实测：“把刚才生成的等价无穷小替换的题加入今日卷”被识别成
    # “替换；移除第11题”，因为知识点名里有“替换”，而“加入”不含数量词。
    # 明确的“加入今日卷/放进今日卷”优先判为追加。
    join_plan=re.search(r'(?:加入|放进|放到|加进|添加到|加回).{0,10}(?:今日卷|今日学习|今天的学习)',text)
    if join_plan and not real_switch:
        action='add'
    elif add_with_count and not real_switch:
        action='add'
    elif remove_with_count and not real_switch:
        # 2026-11-13 R74 实测：“把等价无穷小替换减少两道”里的“替换”是知识点名，
        # 旧逻辑判成 replace，结果变成“移除2道 + 新增2道”净变化 0，用户要的减法没发生。
        action='remove'
    elif re.search(r'换|替换|改换成|替换为',text):
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


def _requested_408_leaf_scope(message, nodes):
    """Resolve an explicitly named 408 leaf topic after the replacement verb.

    2026-11-12（R63-02）：用户说“把行列式的性质换成408文件基本概念”时，
    “文件基本概念”是一个具体知识点，但旧实现只识别四门课程名，于是把这个
    目标当成“整门 408”，自行挑 4 个热门知识点凑题量，且回执只列出被选中的
    4 个知识点，没有说明“目标知识点只有 1 道、其余是从别的知识点补的”。
    这里把具体知识点解析出来，供调用方如实披露库存与补足来源。
    """
    switches=list(re.finditer(r'换成|替换成|替换为|改成|改为',message))
    if not switches:return set(),None
    tail=message[switches[-1].end():]
    if not re.search(r'408|计算机学科专业基础|cs408',tail,re.I):return set(),None
    text=re.sub(r'408|计算机学科专业基础|cs408','',tail,flags=re.I)
    text=re.sub(r'[。！!？?，,；;：:、\s]','',text)
    text=re.sub(r'(?:的)?(?:题目|题|知识点|内容)$','',text).strip('的')
    if len(text)<2:return set(),None
    is_408=lambda node:bool(re.search(r'408|计算机学科专业基础|cs408',node.subject or '',re.I))
    active=[node for node in nodes if getattr(node,'is_active',True) and is_408(node)
        and getattr(node,'is_assessable',False)]
    hits=[node for node in active if text in node.name or node.name in text or text==node.code]
    if not hits:return set(),None
    # Prefer the most specific name so “操作系统概念”不会匹配到整门“操作系统”。
    best=max(len(node.name) for node in hits)
    hits=[node for node in hits if len(node.name)==best]
    return {node.id for node in hits},hits[0].name


def _replacement_fill_candidates(pools,selected_pools,*,preserve_replaced_quantity,priority_ids=None):
    """Return budget-fill questions without silently widening a requested topic set.

    A whole-paper plan with an explicit/default topic count is scoped to the
    selected topics. A scoped course-topic replacement is different: it must
    preserve the number of removed questions, so it may draw spare eligible
    questions from the rest of that explicitly requested course.

    ``priority_ids`` keeps an explicitly named target topic first: when the
    learner asks for “408 文件基本概念”, that topic's remaining admitted
    questions must be used before borrowing from unrelated 408 topics.
    """
    selected_ids={node.id for node,_ in selected_pools}
    source=pools if preserve_replaced_quantity else selected_pools
    candidates=[question for node,pool in source
        for question in (pool[1:] if node.id in selected_ids else pool)]
    priority=set(priority_ids or ())
    if priority:
        return sorted(candidates,key=lambda question:(0 if question.kp_id in priority else 1,
            question.estimated_minutes,str(question.id)))
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
    # 2026-11-13 R74 实测：用户说“隐函数求导加一道，等比级数减一道”，
    # 口语里只写“加/减 + 数量 + 道”。动词表里没有单字“加/减”，
    # 于是被判成“不足两个操作”，整句退化成普通追加，只执行了第一个动作。
    operation_text=re.sub(r'(?<![增追添])(?:再)?加\s*([一二两三四五六七八九十\d]+)\s*道',r'增加\1道',operation_text)
    operation_text=re.sub(r'(?:再)?减\s*([一二两三四五六七八九十\d]+)\s*道',r'减少\1道',operation_text)
    if re.search(r'替换|换成|换掉|换一道',operation_text):return None,None
    if len(re.findall(r'增加|添加|追加|加入|减少|删除|移除|减去|减掉|少安排|多安排',operation_text))<2:
        return None,None
    from backend.services.home_intent import _topic_count_intent,reference_map
    normalized=message.replace('删除','减少').replace('移除','减少').replace('加入','增加')
    normalized=re.sub(r'(?<![增追添])(?:再)?加\s*([一二两三四五六七八九十\d]+)\s*道',r'增加\1道',normalized)
    normalized=re.sub(r'(?:再)?减\s*([一二两三四五六七八九十\d]+)\s*道',r'减少\1道',normalized)
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


def _committed_receipt(factory, task_id):
    """已执行方案自己的提交回执（用于同一方案重复确认的幂等重放）。"""
    if not task_id:
        return None
    with factory() as db:
        try:
            row=db.get(LearningTask,UUID(str(task_id)))
        except (TypeError,ValueError):
            return None
        if row is None:
            return None
        # 已执行的唯一可信标记就是 metrics.commit；确认流程不会改 status，
        # 用 status=='answered' 判断会永远拿不到回执。
        commit=(row.metrics or {}).get('commit')
        return commit or None


def _latest_generated_question(factory, session_id):
    """最近一次个人题生成结果（来自 assistant 消息的 generated_question_refs）。

    2026-11-13 R77：用户生成个人题后说“把刚才生成的题加入今日卷”，
    旧实现只查 practice_preview_reference.latest_preview（题库查询预览），
    生成结果并不在那里，于是回“没有可确定的上一轮题目预览”。
    这里直接读生成消息里记录的 question_id / question_version_id，
    并带回独立核验状态，避免按题干文字模糊匹配。
    """
    from backend.models.chat import ChatMessage
    with factory() as db:
        rows=db.scalars(select(ChatMessage).where(
            ChatMessage.session_id==session_id,
            ChatMessage.role=='assistant',
            ChatMessage.status=='completed').order_by(ChatMessage.seq.desc()).limit(20))
        for row in rows:
            refs=(row.metadata_ or {}).get('generated_question_refs') or []
            fallback=None
            # 一次生成可能同时产出“已核验的题”和“个人参考题（未核验）”。
            # 用户说“刚才生成的题”时要优先挑已核验的那道，否则会把可加入的题
            # 误判成不可加入。全部未核验时再回退到最后一条并如实说明原因。
            for ref in reversed(refs):
                qid=ref.get('question_id');qver=ref.get('question_version_id')
                if not qid or not qver:continue
                try:question=db.get(Question,UUID(str(qid)))
                except (TypeError,ValueError):question=None
                if question is None:continue
                config=question.grading_config or {}
                state=str((config.get('math_verification') or {}).get('status') or 'unverified')
                candidate={'question_id':str(qid),'question_version':str(qver),
                    'kp_id':str(ref.get('kp_id') or question.kp_id),
                    'scope':question.bank_scope,'verification':state}
                if state=='verified':
                    return candidate
                if fallback is None:
                    fallback=candidate
            if fallback is not None:
                return fallback
    return None


def handle_paper_chat(factory, *, session_id, ctx, message, now, target_item_id=None):
    command=parse_command(message)
    if command and command['action']=='query':
        from backend.services.personal_generation_intent import explicitly_generate
        if explicitly_generate(message):
            # Do not let a declined paper insertion swallow separately
            # authorized personal authoring; generation owns its confirmation.
            return None
    if command is None and ctx.daily_plan_id and re.search(r'恢复|还原', message) \
            and not re.search(r'恢复系统推荐|恢复今日最初|恢复原方案|恢复上次|恢复默认', message):
        # 2026-11-13 R74 实测：用户说“恢复刚才删掉的等价无穷小替换”，
        # 句中只有知识点名、没有“题/道/知识点”字样，parse_command 认不出，
        # 整句落到通用问答（“计划已冻结”），恢复能力等于不可用。
        # 这里用当前启用知识点名做一次兜底识别。
        with factory() as _db:
            _names=[row for row in _db.scalars(select(KnowledgePoint.name)
                .where(KnowledgePoint.is_active.is_(True))) if row]
        if any(name in message for name in _names):
            count=99 if re.search(r'全部|所有|都', message) else 1
            command={'action':'restore_removed','count':count,'text':message}
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
            # 2026-11-13 R76：过期草案会把后续所有新请求都挡在这里。
            # 2026-11-14 R87：但 R40 的契约要求“过期后继续做数量调整”必须
            # 明确告知已过期、且不得基于旧草案生成新方案。两条需求并不矛盾：
            # 只有“引用刚生成个人题加入今日卷”这种**与旧草案无关**的独立意图
            # 才自动作废旧方案并继续；其余数量调整一律提示已过期。
            independent_intent=bool(re.search(r'刚才生成的|刚生成的那道|把这道加入|这道加入',
                message))
            if independent_intent:
                with factory.begin() as _db:
                    _old=_db.get(LearningTask,saved_task.id)
                    if _old is not None and _old.status=='ready':
                        _old.status='cancelled'
                        _old.context={**(_old.context or {}),'auto_cancelled_reason':'expired',
                            'auto_cancelled_at':now.isoformat()}
                result['proposal']=None
                result['context']={}
                pending_draft=None
            else:
                return reply('上一次待确认调整方案已过期，不能再基于它继续修改；正式卷保持不变。'
                    '如需继续调整，请重新说明要调整的题目或知识点。')
    pending_undo=(memory.get('context') or {}).get('pending_undo')
    if pending_undo and (command['action']=='cancel' or command.get('revoke_undo')):
        result['context']={};result['proposal']=None
        return reply('已取消待确认撤销，正式卷保持原状态。')
    undo_requested=command['action']=='restore_removed' and bool(re.search(
        r'不换了|撤销(?:刚才|这次|本次|整次|整套)?的?(?:替换|调整)|恢复原来的?题目|恢复原本的题目',message))
    if undo_requested or (command['action']=='confirm' and pending_undo):
        result['proposal']=None
        if undo_requested and pending_draft:
            from backend.services.learning_task_service import cancel_task
            try:cancel_task(factory,UUID(memory['proposal']['task_id']))
            except AppError:return reply('待确认方案状态已变化，请刷新核对；正式卷没有改变。')
            result['context']={}
            return reply('待确认替换方案已取消，正式卷保持原状态。')
        from backend.services.paper_adjustment_reversal import undo_latest_replacement,ReversalConfirmationRequired
        try:
            receipt=undo_latest_replacement(factory,session_id=session_id,plan_id=ctx.daily_plan_id,now=now,
                operation_id=pending_undo['task_id'] if pending_undo and command['action']=='confirm' else None,
                expected_signature=pending_undo['signature'] if pending_undo and command['action']=='confirm' else None,
                confirm_viewed=bool(command.get('viewed')),accept_budget_overrun=bool(command.get('budget_confirmed')))
        except ReversalConfirmationRequired as exc:
            result['context']={'pending_undo':exc.pending}
            w=exc.pending['workload']
            instruction=('确认移除已浏览题目并接受超预算' if exc.pending['viewed'] and w['excess_minutes']
                else '确认移除已浏览题目' if exc.pending['viewed'] else '确认超预算调整')
            return reply(f"待确认撤销：恢复{exc.pending['restored_count']}道原题，移除{exc.pending['removed_count']}道本次新增题；"
                f"预计剩余{w['remaining_minutes']}分钟，预算{w['budget_minutes']}分钟。"
                f'尚未执行；请回复“{instruction}”明确确认，或取消本次调整。')
        except AppError as exc:
            result['context']={}
            messages={'paper_item_protected':'本次新增题中有题已经开始、作答、完成或跳过，受到学习记录保护，整次撤销未执行；原卷和历史记录保持不变。',
                'paper_restore_not_admitted':'原题的准入资格或冻结版本已变化，整次撤销未执行；原卷和历史记录保持不变。',
                'paper_undo_no_operation':'没有找到当前卷最近一次可撤销的替换记录；原卷保持不变。',
                'paper_budget_unknown':'无法核验原题的冻结版本用时，整次撤销未执行。'}
            return reply(messages.get(exc.code,'当前卷、会话或待确认撤销版本已变化，整次撤销未执行；请刷新后重新请求。'))
        result['context']={};result['receipt']=receipt
        count_label='该次撤销完成时共' if receipt.get('replayed') else '当前共'
        return reply(f"已撤销这次替换：恢复{receipt['restored_count']}道原题、移除{len(receipt['removed_item_ids'])}道本次新增题；"
            f"{count_label}{receipt['total_count']}道。其他题目的ID与版本保持不变，历史作答未受影响。")
    if command['action']=='restore_removed':
        result['proposal']=None
        from backend.services.paper_adjustment_reversal import restore_removed_items
        try:
            receipt=restore_removed_items(factory,session_id=session_id,plan_id=ctx.daily_plan_id,now=now,
                count=command.get('count') or 1,recent_only=bool(re.search(r'刚才|这次|本次|那道|原来',message)))
        except AppError as exc:
            notices={'paper_restore_not_admitted':'所选原题的准入资格或冻结版本已变化，未恢复任何题；原卷保持不变。',
                'paper_budget_confirmation_required':'恢复后将超出当前预算，尚未恢复任何题；请先调整预算后重新预览。',
                'paper_budget_unknown':'无法核验原题的冻结版本用时，未恢复任何题。'}
            return reply(notices.get(exc.code,'原题或当前卷状态已变化，未恢复任何题；请刷新核对。'))
        if not receipt:return reply('当前范围没有可恢复的已移除题目，未修改其他题目。')
        result['context']={};result['receipt']=receipt
        return reply(f"已恢复{receipt['restored_count']}道题到今日卷，当前共{receipt['total_count']}道；原题ID与版本保持不变，历史作答未受影响。")
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
        if fresh is None:
            # 2026-11-13 R82：R40/R41 的契约要求“同一方案重复确认返回同一回执”。
            # R73 为了防止“没有形成方案却重放旧回执”，把这句改成一律“没有方案”，
            # 结果把真正的幂等重放也打死了（test_r40/test_r41 回归失败）。
            # 正解：只对**确实已执行**的同一份方案重放它自己的 receipt，
            # 并在文案里明确“已经执行过”，不冒充“刚刚执行”。
            replayed=_committed_receipt(factory,proposal.get('task_id'))
            if replayed is not None:
                result.update(receipt=replayed,proposal=proposal,context=memory.get('context',{}))
                return reply(f"这次调整已经执行过：原有{replayed.get('before_count')}道，"
                    f"移除{len(replayed.get('removed_item_ids') or [])}道，"
                    f"新增{replayed.get('added_count')}道，当前共{replayed.get('total_count')}道。"
                    f"重复确认不会重复执行，正式卷保持不变。")
            return reply('当前没有新的待确认调整方案；上一条调整没有形成可执行方案（或已经执行过），正式卷保持不变。请先说明要调整的题目，再确认。')
        proposal=fresh
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
    generated_reference=False
    if (command['action']=='add' and re.search(r'刚才|那道|这道|上一道',message)
            and not re.search(r'洛必达|隐函数|数据结构|操作系统|组成原理|计算机网络',message)):
        # Bind pronouns only to a persisted, same-session, unexpired preview.
        # Never use the model's prose as evidence for a question or version.
        from backend.services.practice_preview_reference import latest_preview,preview_question_state
        implicit_reference,notice=latest_preview(factory,session_id,message,now)
        if implicit_reference is None:
            generated=_latest_generated_question(factory,session_id)
            if generated is not None:
                if generated.get('verification')!='verified':
                    return reply('这道是刚生成的个人练习题，但答案还没有通过独立核验，不能加入今日卷；'
                        '请重新生成一道（或换成正式题库的题），生成结果里会写明是否已通过核验。')
                implicit_reference={'question_id':generated['question_id'],
                    'question_version':generated['question_version'],'kp_id':generated['kp_id']}
                # 这一次是“把刚生成的那道题加入”，只应带这一道；
                # 不能把上一份待确认方案里的旧个人题一起继承进来。
                generated_reference=True
            else:
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
        prior_refs=([] if (_fresh_topic_replace or generated_reference)
            else list(pending_draft.get('replacements',[])) if pending_draft else [])
        if quantity_correction:
            prior_refs=list((memory.get('context') or {}).get('before_remove_references',prior_refs))
        reserved_pending_ids={str(ref.get('question_id')) for ref in prior_refs}
        # 2026-11-13 R77（R76-BUG-03）：“删除第7题”发两次再确认，会累加成移除 2 道。
        # 原因是第二次解析时上一道已被当成“已移除”从有效列表里跳过，题号顺势落到下一道。
        # 同一题号的重复请求必须幂等：方案里已经包含这一题，就提示直接确认，不再新建。
        if pending_draft and command.get('number') and planned_removals:
            # 用户说的“第12题”是**显示题号**（按题型分组后的顺序），
            # 不是数据库里的 ordinal（ordinal=23 也可能是第12题）。
            # 这里必须换算成显示题号再比较，否则幂等永远不命中。
            from backend.services.today_append_result import display_key as _dk
            _deco=[]
            for _it in plan_rows:
                _q=question_for_practice_item(db,_it)
                _deco.append((_dk((_q.question_type if _q else 'external_exam'),_it.ordinal),str(_it.id)))
            _deco.sort()
            _display={iid:idx for idx,(_,iid) in enumerate(_deco,1)}
            if any(_display.get(str(_x))==command['number'] for _x in planned_removals):
                return reply(f'当前待确认方案已经包含第{command["number"]}题的移除，'
                    f'回复“确认调整”即可执行；不会因为重复说一次而多删一道。')
        effective_rows=[]
        questions={}
        for item in plan_rows:
            if str(item.id) in planned_removals:continue
            question=question_for_practice_item(db,item)
            if question is None:continue
            effective_rows.append(item);questions[item.id]=question
        next_ordinal=max((i.ordinal for i in plan_rows),default=0)+1
        # 2026-11-13 R77：上一份待确认方案里可能含“已核验的个人题”。
        # 旧条件只要 bank_scope != 'public' 就整句阻塞，于是“生成→加入”第一次失败后，
        # 第二次请求会被上一份个人题方案卡住，永远进不去。
        # 这里先统一校验：无效就自动作废旧方案、从当前卷重新开始，而不是拒绝用户。
        valid_prior=True
        for ref in prior_refs:
            try:_q=db.get(Question,UUID(str(ref.get('question_id'))))
            except (ValueError,TypeError):_q=None
            if _q is None or question_version_reference(_q)!=ref.get('question_version_id'):
                valid_prior=False;break
            if _q.bank_scope!='public':
                _cfg=_q.grading_config or {}
                _state=str((_cfg.get('math_verification') or {}).get('status') or '')
                if not (_q.bank_scope=='personal' and _state=='verified'):
                    valid_prior=False;break
        if not valid_prior:
            if pending_draft:
                with factory.begin() as _db:
                    _old=_db.get(LearningTask,saved_task.id)
                    if _old is not None and _old.status=='ready':
                        _old.status='cancelled'
                        _old.context={**(_old.context or {}),'auto_cancelled_reason':'stale_prior_refs',
                            'auto_cancelled_at':now.isoformat()}
            prior_refs=[]
            reserved_pending_ids=set()
        for offset,ref in enumerate(prior_refs):
            try:question=db.get(Question,UUID(ref['question_id']))
            except (ValueError,TypeError):question=None
            if question is None:
                continue
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
            if topic and (command['all_topic'] or named_topic_replace):
                # All explicitly named source topics belong to this scope.
                # The destination was already excluded from source_text above.
                topic_ids={n.id for n in matches} if matches else {topic}
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
                leaf_ids,leaf_name=_requested_408_leaf_scope(message,nodes)
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
                # 用户点名的 408 具体知识点：单独核一次真实库存（不受推荐证据
                # 排序裁剪影响），把它排在候选首位，并在回执里披露缺口。
                leaf_stock=0
                if leaf_ids:
                    leaf_node=db.get(KnowledgePoint,next(iter(leaf_ids)))
                    leaf_pool=[] if leaf_node is None else [q for q in db.scalars(
                        select(Question).where(Question.kp_id==leaf_node.id,Question.bank_scope=='public')
                        .order_by(Question.estimated_minutes,Question.id))
                        if q.id not in existing and q.current_version_id is not None
                        and question_eligibility(q,leaf_node).practice_eligible
                        and type(q.estimated_minutes) is int and q.estimated_minutes>0]
                    leaf_stock=len(leaf_pool)
                    if leaf_node is not None and leaf_pool:
                        pools=[(leaf_node,leaf_pool)]+[pair for pair in pools if pair[0].id!=leaf_node.id]
                    elif leaf_node is not None:
                        missing.append(leaf_node.name)
                if scoped_topic_replacement and command['topic_count'] is None:
                    # Spread a whole-course replacement across as many eligible
                    # target topics as the old quantity allows, then use spare
                    # admitted questions from every topic in that course. A
                    # single high-ranked leaf must not cap the replacement stock.
                    topic_count=min(len(pools),len(selected))
                if leaf_ids:
                    # 目标是一个知识点：先保它，题量缺口必须从同学科补足，
                    # 但补了多少、来自哪里要在方案回执里说清（R63-02）。
                    topic_count=1
                if len(pools)<topic_count:
                    names='、'.join(missing[:8]) if missing else '当前候选列表中的其他知识点'
                    return reply(f'真实正式准入库存只覆盖{len(pools)}个408知识点，目标{topic_count}个，缺{topic_count-len(pools)}个；无可追加合格题的知识点：{names}。未创建方案，原卷保留。')
                total_budget_minutes=budget_minutes
                kept_minutes=0
                if all_math or cross_all:
                    from backend.services.paper_adjustment_service import _adjustment_workload
                    try:
                        kept_minutes=_adjustment_workload(db,plan_rows,remove_item_ids,
                            replacement_refs,total_budget_minutes)['remaining_minutes']
                    except AppError as exc:
                        if exc.code=='paper_budget_unknown':
                            return reply('保留题目缺少可靠的冻结版本用时，无法核验整卷预算；未创建方案，原卷和历史记录保留。')
                        raise
                    # The user's budget covers the resulting paper, including
                    # protected/other-subject items and prior pending additions.
                    budget_minutes=total_budget_minutes-kept_minutes
                    result['context']['kept_remaining_minutes']=kept_minutes
                    result['context']['replacement_budget_minutes']=max(0,budget_minutes)
                selected_pools=pools[:topic_count]
                chosen=[pool[0] for _,pool in selected_pools];minutes=sum(q.estimated_minutes for q in chosen)
                if minutes>budget_minutes:
                    if all_math or cross_all:
                        return reply(f'保留题目预计仍需{kept_minutes}分钟，总预算{total_budget_minutes}分钟；'
                            f'{topic_count}个408知识点各选一道最短还需{minutes}分钟，剩余预算{max(0,budget_minutes)}分钟不足。'
                            '未创建方案，原卷和历史记录保留。请减少知识点或明确增加预算。')
                    return reply(f'{topic_count}个知识点各选一道的最短预计用时为{minutes}分钟，超过{budget_minutes}分钟。未创建方案，原卷保留。')
                replacement_limit=len(selected) if scoped_topic_replacement else None
                remaining=_replacement_fill_candidates(pools,selected_pools,
                    preserve_replaced_quantity=replacement_limit is not None,
                    priority_ids=leaf_ids)
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
                result['context']['budget_minutes']=total_budget_minutes
                if scoped_topic_replacement:
                    result['context']['scoped_topic_replacement']={
                        'target_course':target_course,
                        'removed_question_count':len(selected),
                        'replacement_question_count':len(replacements),
                        'preserves_removed_quantity':len(selected)==len(replacements),
                    }
                    if leaf_ids and replacement_limit is not None:
                        chosen_by_kp={}
                        for question in chosen:
                            chosen_by_kp[str(question.kp_id)]=chosen_by_kp.get(str(question.kp_id),0)+1
                        leaf_key=str(next(iter(leaf_ids)))
                        leaf_assigned=chosen_by_kp.get(leaf_key,0)
                        supplemented=[]
                        for kp_id,count in chosen_by_kp.items():
                            if UUID(kp_id) in leaf_ids:continue
                            node=db.get(KnowledgePoint,UUID(kp_id))
                            supplemented.append({'kp_id':kp_id,'name':node.name if node else '','count':count})
                        result['context']['replacement_disclosure']={
                            'requested_leaf':{'kp_id':leaf_key,'name':leaf_name or '',
                                'available':leaf_stock,'assigned':leaf_assigned},
                            'required':replacement_limit,
                            'shortfall':max(0,replacement_limit-leaf_assigned),
                            'supplemented_count':sum(row['count'] for row in supplemented),
                            'supplemented':supplemented,
                            'cross_topic_supplement':bool(supplemented),
                            'replacement_count':len(replacements),
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
        # Materialize version-backed estimates before closing this read session.
        # Reusing a closed Session below would autobegin another transaction
        # without a context manager to release its connection and relation locks.
        from backend.services.today_append_result import paper_time_estimates
        remaining_now=paper_time_estimates(db,plan_rows)['remaining_minutes']
        plan_budget=int(getattr(plan,'budget_minutes',None) or 0)
        inherited_scope_budget=None
        if result['context'].get('scoped_topic_replacement'):
            # A local, same-quantity replacement inherits the accepted plan
            # budget. The append allowance below is not a budget change the
            # learner authorized for a replacement.
            if pending_draft:
                inherited_scope_budget=saved_task.budget_minutes
            else:
                for prior in db.scalars(select(LearningTask).where(
                        LearningTask.session_id==session_id,
                        LearningTask.status=='answered').order_by(LearningTask.created_at.desc())):
                    if ((prior.context or {}).get('home_recommendation')
                            and ((prior.metrics or {}).get('commit') or {}).get('plan_id')==str(plan.id)):
                        inherited_scope_budget=prior.budget_minutes
                        break
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
        # 追加是用户明确要求的“再加一道”，加上去必然让用时变长；如果拿“当前剩余”
        # 或已扣减过的小预算去比，每次追加都会被要求“确认超预算调整”，把一次正常
        # 确认拆成两轮（实测 f02 用例即因此拿不到 receipt）。追加时给足预算，
        # 超预算提示仍用于移除/替换场景。
        # 多轮组合时（已有待确认方案），后续无论是 add 还是 remove，最终方案都可能
        # 同时包含“新增”，用当前剩余做预算必然超预算（实测：先加两道、再减一道，
        # 第三步按 remove 取 45 分钟，组合后 53 分钟直接超）。因此只要在组合模式，
        # 就给足预算；纯单轮移除仍用当前剩余，避免 R52-04 的“减题误判超预算”复发。
        if result['context'].get('scoped_topic_replacement') and not command['budget_minutes']:
            default_budget=max(5,int(inherited_scope_budget or plan_budget or remaining_now or 90))
        elif replacement_refs and (command['action'] in {'add','replace','batch'} or pending_draft) and not command['budget_minutes']:
            # 上限 600 与 PaperAdjustmentRequest 的字段约束保持一致；超出会触发
            # pydantic 校验失败、整条调整报 internal_error。
            default_budget=min(600,max(plan_budget,int(remaining_now or 0))+60)
        else:
            default_budget=max(5,int(remaining_now or 0) or 90)
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
    disclosure=result['context'].get('replacement_disclosure') or {}
    disclosure_summary=''
    if disclosure:
        leaf=disclosure['requested_leaf']
        if disclosure['shortfall']>0:
            detail='、'.join(f"{row['name']}{row['count']}道" for row in disclosure['supplemented'])
            disclosure_summary=(f"目标知识点「{leaf['name']}」本次替换{leaf['assigned']}道（卷外可用{leaf['available']}道），"
                f"需替换{disclosure['required']}道，缺{disclosure['shortfall']}道；"
                f"已从408同学科其他知识点补足{disclosure['supplemented_count']}道（{detail}）。"
                f"如果不接受跨知识点补足，请回复“取消”，原卷保持不变。")
        else:
            disclosure_summary=(f"目标知识点「{leaf['name']}」本次替换{leaf['assigned']}道，"
                f"卷外可用{leaf['available']}道，未跨知识点补足。")
    kept_summary=(f'另有{protected_kept}道已有学习记录，保留不动。' if protected_kept else '')
    return reply(f"待确认方案：{action_label}；{removal_summary}，新增{len(replacements)}道。{topic_summary}{disclosure_summary}{batch_summary}{kept_summary}{timing}{warning}{instruction}当前正式卷尚未改变。")
