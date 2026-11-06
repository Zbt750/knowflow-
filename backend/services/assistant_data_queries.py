"""Bounded, read-only queries shared by the assistant entry points.

These queries deliberately reuse the question-eligibility and learning-state
services. They do not invoke an LLM, mutate a plan, create a practice item, or
turn a query into a generation request.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime,timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from backend.models.chat import ChatMessage
from backend.models.learning import (
    DailyPlan,
    KnowledgePoint,
    LearningEvent,
    PracticeItem,
    Question,
    QuestionAttempt,
    QuestionVersion,
)
from backend.models.chat import ChatSession
from backend.schemas.learning_assistant import StudyContext
from backend.schemas.learning_task import FindQuestions, NodeIds
from backend.services.learning_task_tools import TaskTools
from backend.services.question_availability import (
    _descendant_ids,
    question_availability,
    question_source_category,
)
from backend.services.question_versions import (
    question_for_attempt,
    question_for_practice_item,
    question_version_reference,
    question_for_version,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")

_FOLLOWUP = re.compile(r"其中|这些题|那些题|那里面|这里面|这其中|上述题|它们|^(?:只看|只要|不要个人|我(?:做过|做错)|有多少|几道|几题|找|再找|有没有难|难一点|简单一点|再给我)")
SOURCE_LABELS = {"exam_curated": "真题改编题（整理）", "exam_variant": "真题改编题（变式）",
    "development_original": "原创题", "personal_ai_practice": "个人AI练习",
    "personal_practice": "个人练习", "unclassified_public": "其他公共题"}


def bank_preview_count(message):
    from backend.services.bank_selection_intent import QUESTION_COUNT_PATTERN, question_count
    match=re.search(QUESTION_COUNT_PATTERN,message)
    if match:
        count=question_count(match[1])
        if count:return count
    return 16 if re.search(r'有哪些|列出|只想|只看|看看题库',message) else 1


def apply_practice_filters(state,message):
    """Persist query refinements so a follow-up cannot lose history/difficulty."""
    from backend.services.bank_selection_intent import bank_selection_request
    from backend.services.generation_difficulty import LEGACY_LEVEL
    request=bank_selection_request('找一道题；'+message)
    if request and request.get('difficulty'):
        level=request['difficulty']
        state['difficulties']=[level]+[k for k,v in LEGACY_LEVEL.items() if v==level]
        state['excluded_difficulties']=[d for d in state.get('excluded_difficulties',[]) if d not in state['difficulties']]
    if re.search(r'不限难度|所有难度',message):state['difficulties']=[];state['excluded_difficulties']=[]
    if request and request.get('excluded_difficulties'):
        excluded=request['excluded_difficulties']
        state['excluded_difficulties']=list(set(excluded)|{k for k,v in LEGACY_LEVEL.items() if v in excluded})
    if request and request.get('question_type'):
        state['excluded_question_types']=[t for t in state.get('excluded_question_types',[]) if t!=request['question_type']]
    if request and request.get('excluded_question_types'):
        state['excluded_question_types']=request['excluded_question_types']
    if re.search(r'不限题型|所有题型',message):state['excluded_question_types']=[]
    if re.search(r'做过的也可以|包括做过|不排除.{0,3}做过|不要排除.{0,3}做过',message):state['unattempted_only']=False
    elif re.search(r'没做过|未做过|未做的|没练过|排除.{0,5}做过|做过的.{0,4}(?:不要|排除)',message):
        state['unattempted_only']=True


def _subject_from_message(message: str) -> str | None:
    if re.search(r"数学二|数二|考研数学|math2|高数|高等数学|微积分|线代|线性代数", message, re.I):
        return "考研数学"
    if re.search(r"408|计算机统考|数据结构|操作系统|计算机网络", message):
        return "408"
    return None


def _previous_query(db, session_id: UUID, now=None):
    # Only the latest completed assistant turn in this exact conversation can
    # supply a query antecedent. An unrelated answer ends that query context.
    row = db.scalar(select(ChatMessage).where(ChatMessage.session_id == session_id,
        ChatMessage.role == "assistant", ChatMessage.status == "completed")
        .order_by(ChatMessage.seq.desc()).limit(1))
    if row and (row.metadata_ or {}).get('source_policy') in {'no_original_exam_inventory','existing_bank_only'}:
        prior_rows=db.scalars(select(ChatMessage).where(ChatMessage.session_id==session_id,
            ChatMessage.role=='assistant',ChatMessage.status=='completed',ChatMessage.seq<row.seq)
            .order_by(ChatMessage.seq.desc()).limit(8))
        for prior in prior_rows:
            if (prior.metadata_ or {}).get('source_policy') in {'no_original_exam_inventory','existing_bank_only'}:
                continue
            row=prior
            break
    evidence = (row.metadata_ or {}).get("read_only_data_query") if row else None
    if isinstance(evidence, dict) and evidence.get("query_status") != "needs_clarification":
        pass
    else:
        # A same-session, still-live practice preview is also structured query
        # context. This lets a learner switch from "arrange one" back to
        # "show me the bank" without widening to every subject in the bank.
        from backend.models.practice_request import PracticeRequest
        request_id=(row.metadata_ or {}).get('practice_request_id') if row else None
        if request_id:
            try:request=db.get(PracticeRequest,UUID(str(request_id)))
            except (ValueError,TypeError):request=None
            clock=now or datetime.now(timezone.utc)
            if (request and request.source_conversation_id==session_id and request.status in {'draft','proposed'}
                    and request.expires_at>clock):
                details=request.request or {}
                constraints=details.get('constraints') or {}
                state=(constraints.get('preview_query_state') or {
                    'subject':details.get('subject'),
                    'scope_node_ids':constraints.get('resolved_scope_node_ids') or details.get('target_knowledge_node_ids',[]),
                    'eligibility':'practice_eligible','source_categories':[],
                    'question_types':[],'excluded_source_categories':[]})
                if state.get('scope_node_ids'):
                    return row,state
        return None,None
    state = evidence.get("query_state")
    if not isinstance(state, dict):
        # Read-only compatibility for conversations saved before query_state.
        user = db.scalar(select(ChatMessage).where(ChatMessage.session_id == session_id,
            ChatMessage.role == "user", ChatMessage.seq < row.seq)
            .order_by(ChatMessage.seq.desc()).limit(1))
        state = {"subject": _subject_from_message(user.content) if user else None,
            "scope_node_ids": evidence.get("scope_node_ids", []),
            "eligibility": "practice_eligible" if evidence.get("query_type") in {"inventory", "find"} else "all_recorded",
            "source_categories": []}
    return row, state


def continues_read_only_selection(factory, *, session_id: UUID, message: str, now=None) -> bool:
    """An immediate 'another one' inherits inspection, never insertion consent."""
    from backend.services.bank_selection_intent import QUESTION_COUNT_PATTERN
    if (not re.search(r'^\s*再来\s*' + QUESTION_COUNT_PATTERN, message)
            or not re.search(r'题|练习', message)
            or re.search(r'加入|追加|加到|放进|安排|生成|新编|今日|今天|计划|方案', message)):
        return False
    with factory() as db:
        previous, _ = _previous_query(db, session_id, now=now)
        evidence=(previous.metadata_ or {}).get('read_only_data_query',{}) if previous else {}
    return bool(evidence.get('query_type') == 'find'
        and evidence.get('preview_questions') and evidence.get('writes') is False)


def classify_session_data_query(factory, *, session_id: UUID, message: str, now=None) -> str | None:
    """Resolve bounded ellipsis before routing; never ask a model for counts."""
    classified = classify_read_only_data_query(message)
    if classified:
        return classified
    if _FOLLOWUP.search(message) and re.search(r"多少道|有多少|几道|几题|数量|做过|做错|答错|选择题|公共题库|找|看看|难一点|简单一点|再找|\d+\s*道|没做过|未做", message):
        with factory() as db:
            previous, _ = _previous_query(db, session_id,now=now)
        if previous:
            return "history" if re.search(r"做过|做错|答错|答过|练过", message) else "inventory"
    return None


def classify_read_only_data_query(message: str) -> str | None:
    """Classify explicit data requests, not explanations that merely mention questions."""
    text = (message or "").strip()
    from backend.services.bank_selection_intent import explicit_plan_preview
    if explicit_plan_preview(text):
        return None
    if (re.search(r'(?:给我|帮我|请)?补(?:充)?\s*[一二两三四五六七八九十\d]+\s*道', text)
            and not re.search(r'为什么|为何|是否|能不能|要不要|不要|别|先不|暂不|吗|[？?]', text)):
        return None
    if (re.search(r'减少|删(?:除|掉)|移除|替换|换掉|换成|换简单|换少|换.{0,4}一点', text)
            and re.search(r'题|知识点|卷', text)
            and not re.search(r'多少|几道可用|题库|库存|记录', text)):
        return None
    # Mathematical quantities in a follow-up are not bank inventory counts.
    if (re.search(r'行列式|特征值|特征空间|特征多项式|对角化', text)
            and not re.search(r'题库|库存|几道|多少道|作答记录|安排|加入', text)):
        return None
    # “根据最近表现安排明天”是规划请求，不是只读统计。
    if re.search(r'(?:明天|下一轮).{0,10}(?:怎么|如何|安排|建议)|根据.{0,10}(?:最近|近期|表现).{0,10}(?:安排|建议)', text):
        return None
    # 未做题是库存筛选，不是历史作答统计。
    if re.search(r"没做过|没有做过|未做|尚未做", text) and re.search(r"题|练习", text):
        return "find"
    # 题目来源查询：关联本会话最近一次真实预览/生成，不猜。
    if re.search(r"(?:这道|刚才|上一道|预览的|生成的).{0,12}(?:题|题目).{0,12}(?:来源|真题|AI|原创|哪年|哪里|来自)|(?:来源|哪年真题).{0,8}(?:这道|刚才)", text):
        return "source"
    # A destination mentioned only to deny insertion is not the query target.
    # Keep the original text for subsequent filters and consent validation.
    fact_text = '；'.join(part for part in re.split(r'[，,。；;！？?\n]', text)
        if not re.search(r'(?:不要|别|先不|暂不|无需|不需要|不(?=加入|追加|放进|加到|创建|修改)).{0,10}(?:加入|追加|放进|加到|创建|修改)', part))
    if (re.search(r'(?:看|找|展示|检索)\s*[一二两三四五六七八九十\d]+\s*道[^，。；！？\n]{0,30}(?:题|练习)', fact_text)
            and not re.search(r'生成|新编|加入|追加|安排|放进|加到|为什么|如何|怎么|讲解|解释|解法|推导', fact_text)):
        return 'find'
    if (re.search(r"今天|今日", fact_text)
            and re.search(r"学习卷|今日卷|推荐|这套卷|主要练|知识点|完成|线代|高数|隐函数|来源|多久|多长时间|生成|预计|花多少时间", fact_text)
            and not re.search(r"题库|库存|可练题|做错|答错|错题|做过|练过|正确率", fact_text)):
        return "today_detail"
    from backend.services.learner_self_report import evidence_attribution_request
    if evidence_attribution_request(text):
        return 'evidence_basis'
    if wrong_question_list_request(text):return 'history'
    if (re.search(r'(?:独立|自己).{0,8}(?:答对|做对|答错|做错)|(?:答对|做对|答错|做错).{0,12}(?:几道|多少|几次)', text)
            and re.search(r'(?:几道|多少|几次|统计|分别)', text)
            and re.search(r'(?:辅助|提示|解析|错误|答错|独立|正确)', text)):
        return 'learning_state'
    if re.search(r'(?:我)?今天.{0,10}(?:学得|学习情况|学了多少|完成得怎么样)', text) and re.search(r'明天|下一步|接下来', text):
        return 'today_summary'
    if re.search(r'(?:再给|再来|换).{0,10}(?:一道|一个).{0,10}(?:同类|相关|相似|题|练习)', text):
        return 'find'
    if re.search(r'我(?:最近|近期|这段时间).{0,8}(?:做得|学得|表现|学习情况)|我的(?:近期|最近)(?:作答|学习)(?:情况|表现)', text):
        return 'learning_state'
    if re.search(r'(?:只想|只要|只|这次).{0,10}(?:看|查).{0,8}题库',text) and re.search(r'不要.{0,6}(?:创建|安排|计划)',text):
        return 'find'
    if not text or re.search(r"^(?:帮我|给我|请)?\s*(?:生成|出|编写)\s*(?:一道|几道|\d+道)?\s*(?:类似|变式|练习)?题", text):
        return None
    # A plan may cite weak nodes and history as inputs. Those nouns must not
    # let a read-only fact classifier swallow the user's requested next action.
    # "先建议，不创建" is still planning (draft only), not a state lookup.
    positive_clauses = [part for part in re.split(r'[，,；;。！？?\n]', text)
                        if not re.search(r'(?:不要|不需要|不想|先别|别).{0,12}(?:安排|规划|创建|制定|生成|加入)', part)]
    positive_text = '；'.join(positive_clauses)
    if (re.search(r"安排|规划|制定|设计.{0,6}方案", positive_text)
            and re.search(r"复习|学习|练习|计划|[一二两三四五六七八九十\d]+\s*道|这种题|这样的题", text)
            and not re.match(r"^(?:为什么|为何|解释|讲解)", text)):
        return None

    if re.search(r"讲解|解释|解题思路|检查.*思路|怎么(?:解|做)|为什么|讲题|讲一下|讲讲", text) and not re.search(r"题库|数量|多少道|几道|作答记录", text):
        return None
    if re.search(r"解法|方法|条件|含义|推导|步骤|公式|思路", text) and not re.search(r"题库|可练|数量|多少道|几道|做过|真题|原创", text):
        return None
    if (_FOLLOWUP.search(text) and re.search(r"(?:我.{0,8})?(?:做过|做错(?:过|了)?|答错(?:过|了)?|练过|答过)", text)
            and re.search(r"多少|几道|哪些|哪几|记录|吗", text)):
        return "history"

    if re.search(r'(?:查|查看|查询).{0,12}(?:我)?(?:做过的)?错题',text):
        return 'history'

    # Explicit inventory/source questions take precedence over the broad
    # "current/today + question" pattern below. In particular, "当前可练题
    # 目库存" asks about the bank, while "今日卷还有几题" asks about the
    # already-created paper.
    source_comparison = bool(re.search(
        r"(?:正式题|公共题库题?|公共题).{0,16}(?:个人(?:AI)?(?:生成|练习)题).{0,12}(?:区别|区分|来源|不同)|"
        r"个人(?:AI)?(?:生成|练习)题.{0,12}(?:与|和).{0,10}(?:正式题|公共题库题?|公共题).{0,12}(?:区别|区分|来源|不同)|"
        r"(?:正式|公共).{0,8}个人.{0,12}(?:区别|差别|不同|来源)|个人.{0,12}(?:正式|公共).{0,12}(?:区别|差别|不同|来源)",
        text))
    scoped_source_question = bool(re.search(
        r"(?:这道题|这些题|这些题目|当前题目|当前这题|刚才那道题).{0,12}(?:来源|来自哪里|是哪来的)|"
        r"(?:来源|来自哪里).{0,12}(?:这道题|这些题|这些题目|当前题目|当前这题|刚才那道题)",
        text))
    explicit_inventory = bool(re.search(
        r"(?:可练(?:习)?题目?|练习题|题库|节点|知识点).{0,16}(?:库存|有几|多少|数量|有哪些|可用)|"
        r"(?:库存|可练题目?).{0,16}(?:题|节点|知识点|可用)|"
        r"(?:查询|查看|看看|列出).{0,12}(?:定积分|洛必达|隐函数|知识点|节点).{0,12}(?:库存|可练题)",
        text)) and not (re.search(r"今天|今日", text)
                        and re.search(r"学习卷|今日卷|推荐|主要练|知识点|哪些", text))
    if source_comparison or scoped_source_question or explicit_inventory:
        return "inventory"

    if re.search(r"没做过|未做过|没练过|未练过", text) and re.search(r"题|练习", text):
        return "find"
    if (re.search(r"(?:今天|今日|当前).{0,20}(?:学习卷|今日卷|练习卷|这套卷|推荐|题目|卷|题).{0,20}(?:几道|多少|哪些|什么|哪里|来源|多久|多长时间|完成|生成|有没有|是否|线代|高数|隐函数|知识点)|(?:今天|今日).{0,10}(?:线代|高数|隐函数|概率)|(?:今天|今日).{0,8}完成.{0,8}(?:多少|几道)|(?:今天|今日).{0,12}(?:预计|需要|要花|用).{0,8}(?:多少|多久|多长时间).{0,6}(?:时间|分钟)", text)
            and not re.search(r"做错|答错|错题|做过|练过|正确率", text)):
        return "today_detail"
    if re.search(r"(?:我|自己).{0,16}(?:做过|练过|答过|提交过|做错过|答错过|做对过|练习过).{0,24}(?:题|记录|洛必达|知识点)|"
                 r"(?:作答|做题|错题|学习)历史|(?:我今天|今天).{0,18}(?:做对|做错|答对|答错|完成).{0,8}(?:题|道)", text):
        return "history"
    if re.search(r"(?:今天|今日|当前).{0,18}(?:有几道|多少道|还剩|完成|未做|题目|练习卷)|"
                 r"(?:现在|当前).{0,12}(?:做的是哪道|正在做哪道|这道题是哪道)|今日卷.{0,16}(?:几道|多少|哪些|剩)", text):
        return "today"
    if re.search(r"(?:哪个|哪些|什么).{0,12}(?:知识点|节点).{0,12}(?:薄弱|不熟|需要复习)|"
                 r"(?:薄弱|不熟|掌握状态|掌握程度).{0,18}(?:知识点|节点|我)", text):
        return "learning_state"
    from backend.services.bank_selection_intent import read_only_selection_request
    if read_only_selection_request(text):
        return 'find'
    inventory_ask = bool(re.search(r"多少|几道|几题|数量|哪些|有没有|是否有|找|列出|看看|还有|剩下|剩余|可练|能做|还能练|能练|\d+\s*道", text))
    inventory_subject = bool(re.search(r"题库|库里|库里面|我的库|可练(?:习)?题|练习题|题目|真题|原创题|AI生成题|的题|这些题|那些题|题|知识点", text))
    inventory_subject = inventory_subject or bool(re.search(r"(?:多少|几|\d+)\s*(?:道|题)", text) and "题" in text)
    context_reference = bool(re.search(r"这样|这种|这种类型|同类|类似|相关|对应|刚才|上面|这个知识点", text) and
                              re.search(r"题|练习|题目|库存", text))
    if inventory_ask and (inventory_subject or context_reference) and not (
            re.search(r"今天|今日", text) and re.search(r"学习卷|今日卷|推荐|主要练|哪些", text)):
        if re.search(r"找|列出|给我看看|看一下", text) and not re.search(r"多少|几道|数量", text):
            return "find"
        return "inventory"
    if re.search(r"(?:帮我|给我|请)?\s*(?:找|看看|列出).{0,18}(?:现成|已有|库里|可练|一道题|题目)", text):
        return "find"
    return None


def wrong_question_list_request(text):
    return bool(_FOLLOWUP.search(text) and re.search(r'哪些|哪几',text)
                and re.search(r'做错|答错|错题',text)
                and not re.search(r'生成|追加|加入|安排|出题',text))


def _context_node_ids(db, factory, session_id: UUID, ctx: StudyContext, message: str) -> list[UUID]:
    """Resolve a current scope first, then only same-session conversation facts."""
    resolver = TaskTools(factory, budget_minutes=90,
                         now=datetime.now().astimezone(), goal=message)
    explicit = set(resolver.explicit_scope or ())
    if explicit:
        return _scope_roots(db, explicit)
    if ctx.knowledge_node_ids:
        return list(dict.fromkeys(ctx.knowledge_node_ids))[:8]
    if ctx.question_id:
        question = db.get(Question, ctx.question_id)
        if question:
            return [question.kp_id]
    if ctx.task_id:
        from backend.models.learning_task import LearningTask
        task = db.get(LearningTask, ctx.task_id)
        handoff = (task.context or {}).get("planner_handoff") if task else None
        ids = _uuid_list((handoff or {}).get("target_knowledge_node_ids", []))
        if ids:
            return ids[:8]

    # Reference words need a same-session antecedent. Do not silently expand
    # "这样的题" to the whole bank when the previous topic is ambiguous.
    if not re.search(r"这样|这种|同类|相关|对应|刚才|上面|这个知识点", message):
        return []
    rows = list(db.scalars(select(ChatMessage).where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.seq.desc()).limit(24)))
    for row in rows:
        meta = row.metadata_ or {}
        trace = meta.get("learning_trace") or {}
        ids = _uuid_list(trace.get("resolved_knowledge_node_ids", []))
        ids += _uuid_list(trace.get("knowledge_node_ids_used", []))
        if row.matched_kp_id:
            ids.append(row.matched_kp_id)
        context = meta.get("study_context") or {}
        ids += _uuid_list(context.get("knowledge_node_ids", []))
        for ref in meta.get("generated_question_refs", []):
            if isinstance(ref, dict):
                try:
                    ids.append(UUID(str(ref.get("kp_id"))))
                except (TypeError, ValueError, AttributeError):
                    pass
        ids = _active_node_ids(db, ids)
        if ids:
            return _scope_roots(db, set(ids))[:8]
        if row.role == "user":
            previous = TaskTools(factory, budget_minutes=90,
                                 now=datetime.now().astimezone(), goal=row.content)
            if previous.explicit_scope:
                return _scope_roots(db, set(previous.explicit_scope))[:8]
    return []


def _uuid_list(values) -> list[UUID]:
    result = []
    for value in values or []:
        try:
            result.append(UUID(str(value)))
        except (TypeError, ValueError, AttributeError):
            continue
    return result


def _active_node_ids(db, values) -> list[UUID]:
    ids = list(dict.fromkeys(_uuid_list(values)))
    return list(db.scalars(select(KnowledgePoint.id).where(
        KnowledgePoint.id.in_(ids or [UUID(int=0)]), KnowledgePoint.is_active.is_(True))))


def _scope_roots(db, scope: set[UUID]) -> list[UUID]:
    if not scope:
        return []
    return list(db.scalars(select(KnowledgePoint.id).where(
        KnowledgePoint.id.in_(scope),
        (KnowledgePoint.parent_id.is_(None) | KnowledgePoint.parent_id.not_in(scope))
    ).order_by(KnowledgePoint.ordinal, KnowledgePoint.code)))


def _resolve_previous_generated_question(db, session_id: UUID, message: str):
    referential = bool(re.search(r"上面|刚才|刚生成|你生成|生成的题|那道题|这道题|这个题", message))
    if not referential:
        return None, "not_requested"
    rows = list(db.scalars(select(ChatMessage).where(ChatMessage.session_id == session_id,
        ChatMessage.role == "assistant", ChatMessage.status == "completed")
        .order_by(ChatMessage.seq.desc()).limit(30)))
    for row in rows:
        refs = (row.metadata_ or {}).get("generated_question_refs") or []
        if not refs:
            continue
        available = []
        for ref in refs:
            try:
                qid, vid = UUID(str(ref["question_id"])), UUID(str(ref["question_version_id"]))
            except (KeyError, TypeError, ValueError):
                continue
            version = db.get(QuestionVersion, vid)
            question = db.get(Question, qid)
            if version and version.question_id == qid and question:
                available.append((question, version, ref))
        if len(available) == 1:
            return available[0], "resolved_same_session_generation"
        if len(available) > 1:
            return None, "ambiguous_same_session_generation"

        # Compatibility for already persisted generation cards that predate
        # version references: use only the current snapshot when its immutable
        # batch lineage proves it belongs to that exact saved generation.
        result = (row.metadata_ or {}).get("personal_generation") or {}
        batch_id = str(result.get("batch_id") or "")
        question_ids = _uuid_list(result.get("question_ids", []))
        if len(question_ids) == 1 and batch_id:
            question = db.get(Question, question_ids[0])
            version = db.get(QuestionVersion, question.current_version_id) if question and question.current_version_id else None
            lineage = (version.snapshot_json or {}).get("generation_batch_id") if version else None
            if version and version.question_id == question.id and str(lineage) == batch_id:
                return (question, version, {"question_id": str(question.id),
                    "question_version_id": str(version.id), "kp_id": str(question.kp_id)}), "resolved_legacy_generation_snapshot"
            return None, "legacy_version_unavailable"
        if len(question_ids) > 1:
            return None, "ambiguous_same_session_generation"
    return None, "not_found"


def resolve_question_reference(factory, *, session_id: UUID, ctx: StudyContext, message: str):
    """Return a trusted exact question snapshot for an explicit question reference."""
    with factory() as db:
        add_recent_wrong = bool(re.search(
            r'(?:刚才|刚刚|上一个|最近).{0,12}(?:错题|答错的题|做错的题).{0,12}(?:加入|加到|放进)|'
            r'(?:加入|加到|放进).{0,12}(?:刚才|刚刚|最近).{0,8}(?:错题|答错的题)', message))
        if add_recent_wrong:
            attempt = db.get(QuestionAttempt, ctx.attempt_id) if ctx.attempt_id else None
            if attempt is None and ctx.practice_item_id:
                attempt = db.scalar(select(QuestionAttempt).where(
                    QuestionAttempt.practice_item_id == ctx.practice_item_id,
                    QuestionAttempt.objective_result == 'wrong')
                    .order_by(QuestionAttempt.submitted_at.desc(), QuestionAttempt.id.desc()).limit(1))
            if (attempt is None or attempt.objective_result != 'wrong'
                    or (ctx.practice_item_id and attempt.practice_item_id != ctx.practice_item_id)):
                return None, None, 'recent_wrong_attempt_unavailable'
            question = question_for_attempt(db, attempt)
            if question is None or question.id != attempt.question_id:
                return None, None, 'recent_wrong_question_version_unavailable'
            return question, {'kind': 'recent_wrong_attempt', 'attempt_id': str(attempt.id),
                'practice_item_id': str(attempt.practice_item_id), 'question_id': str(question.id),
                'question_version_id': str(attempt.question_version_id), 'kp_id': str(question.kp_id)}, \
                'resolved_recent_wrong_attempt'
        current_question = None
        current_version = None
        if ctx.question_id:
            if ctx.practice_item_id:
                item = db.get(PracticeItem, ctx.practice_item_id)
                current_question = question_for_practice_item(db, item) if item else None
                current_version = current_question.version_id if current_question else None
            elif ctx.question_version_id:
                current_version = ctx.question_version_id
                version = db.get(QuestionVersion, current_version)
                if version and version.question_id == ctx.question_id:
                    from backend.services.question_versions import question_for_version
                    current_question = question_for_version(db, current_version)
            else:
                question = db.get(Question, ctx.question_id)
                current_version = question.current_version_id if question else None
                if current_version:
                    from backend.services.question_versions import question_for_version
                    current_question = question_for_version(db, current_version)
        if current_question and not re.search(r"(?:上面|刚才|你生成|生成的题)", message):
            return current_question, {"kind": "current_question", "question_id": str(current_question.id),
                "question_version_id": str(current_version), "kp_id": str(current_question.kp_id)}, "resolved_current_question"
        generated, status = _resolve_previous_generated_question(db, session_id, message)
        if generated:
            question, version, _ = generated
            return question, {"kind": "same_session_generation", "question_id": str(question.id),
                "question_version_id": str(version.id), "kp_id": str(question.kp_id)}, status
        if current_question:
            return current_question, {"kind": "current_question", "question_id": str(current_question.id),
                "question_version_id": str(current_version), "kp_id": str(current_question.kp_id)}, "resolved_current_question"
        return None, None, status


def persist_generated_question_refs(factory, *, message_id: UUID, generation: dict) -> list[dict]:
    """Bind a successful saved generation to its immutable QuestionVersion IDs."""
    refs = []
    batch_id = str(generation.get("batch_id") or "")
    for ident in generation.get("question_ids", []):
        try:
            question_id = UUID(str(ident))
        except (TypeError, ValueError):
            continue
        with factory() as db:
            question = db.get(Question, question_id)
            version = db.get(QuestionVersion, question.current_version_id) if question and question.current_version_id else None
            if (not question or not version or version.question_id != question.id
                    or str(question.generation_batch_id) != batch_id):
                continue
            refs.append({"question_id": str(question.id), "question_version_id": str(version.id),
                "kp_id": str(question.kp_id), "generation_batch_id": batch_id})
    if refs:
        with factory.begin() as db:
            row = db.get(ChatMessage, message_id)
            if row is not None:
                row.metadata_ = {**(row.metadata_ or {}), "generated_question_refs": refs}
    return refs


def _generic_inventory_scope_name(name):
    value=re.sub(r'^(?:查询|查看|看看)', '', name)
    value=re.sub(r'^系统(?=题库)', '', value)
    from backend.services.bank_selection_intent import QUESTION_COUNT_PATTERN
    if re.fullmatch(r'(?:帮我|给我|请)?(?:找|查|选|挑|看|展示)\s*' + QUESTION_COUNT_PATTERN, value):
        return True
    if re.fullmatch(r'(?:那(?:么)?|你|我|的|题库(?:里(?:面)?)?|库里(?:面)?|有|多少|几|道|一共|总共|可练习|可练|可用|这(?:样|种)(?:类型)?)+', value):
        return True
    return bool(re.fullmatch(
        r'(?:我(?:的)?)?(?:题库|库里(?:面)?)(?:一共|总共|有|多少|几|道|可练习|可练|的)*|'
        r'(?:我)?(?:当前|现在|目前)(?:可练习|可练|可以练习|的)*', value))


def _resolve_query_scope(db, *, factory, session_id, ctx, message):
    tool = TaskTools(factory, budget_minutes=90, now=datetime.now().astimezone(), goal=message)
    roots = list(tool.explicit_scope or [])
    if roots:
        return _scope_roots(db, set(roots)), "explicit_message_scope"
    if _subject_from_message(message):
        return [], "global_or_subject_inventory"
    prior,state=_previous_query(db,session_id)
    if prior and (prior.metadata_ or {}).get('read_only_data_query',{}).get('query_type')=='scope_correction':
        return _active_node_ids(db,state.get('scope_node_ids',[])), 'same_session_scope_correction'
    if ctx.knowledge_node_ids:
        return list(dict.fromkeys(ctx.knowledge_node_ids))[:8], "current_knowledge_context"
    if ctx.question_id:
        question = db.get(Question, ctx.question_id)
        if question:
            return [question.kp_id], "current_question_context"
    if ctx.task_id:
        from backend.models.learning_task import LearningTask
        task = db.get(LearningTask, ctx.task_id)
        handoff = (task.context or {}).get("planner_handoff") if task else None
        ids = _uuid_list((handoff or {}).get("target_knowledge_node_ids", []))
        if ids:
            return ids[:8], "current_task_context"
    if re.search(r"这样|这种|同类|相关|对应|刚才|上面|这个知识点", message):
        ids = _context_node_ids(db, factory, session_id, ctx, message)
        if ids:
            return ids, "same_session_conversation_context"
        return [], "ambiguous_or_missing_antecedent"
    return [], "global_or_subject_inventory"


def _query_conditions(db, *, factory, session_id, ctx, message, query_type, now=None):
    # A source-only refinement is still about the immediately preceding query,
    # even without "其中". With no antecedent it remains a global source query.
    source_refinement=bool(re.fullmatch(r'(?:有没有|有多少|只看|只要).{0,6}(?:历年真题|真题改编题|改编题|真题|原创题)[。？?]?',message.strip()))
    # Switching from history to browsing is a query-mode change, not permission
    # to silently widen the previous same-session subject/node/source scope.
    browse_refinement = bool(query_type == 'find' and
        re.search(r'(?:只想|只要|只|这次).{0,10}(?:看|查).{0,8}题库', message) and
        not re.search(r'全库|全部科目|所有科目|换个话题|不继承|重新开始', message))
    same_scope_alternative = bool(query_type == 'find' and
        re.search(r'(?:再|另|换).{0,8}(?:一道|一题|一个题)', message))
    previous, prior = _previous_query(db, session_id,now=now) if (
        _FOLLOWUP.search(message) or source_refinement or browse_refinement or same_scope_alternative
    ) else (None, None)
    roots, origin = _resolve_query_scope(db, factory=factory, session_id=session_id, ctx=ctx, message=message)
    # “高数/线代”是科目内的根节点范围，不能退化成整科或全库。
    if not roots:
        subject_root = ("高等数学" if re.search(r"高数|高等数学", message)
                        else "线性代数" if re.search(r"线代|线性代数", message) else None)
        if subject_root:
            node = db.scalar(select(KnowledgePoint).where(
                KnowledgePoint.parent_id.is_(None), KnowledgePoint.name == subject_root,
                KnowledgePoint.is_active.is_(True)))
            if node:
                roots, origin = [node.id], "explicit_subject_scope"
    explicit_subject = _subject_from_message(message)
    fresh_scope = origin in {"explicit_message_scope", "explicit_subject_scope"}
    # A named node after “其中” refines the previous subject/source scope.
    # Only a standalone new query may discard those filters.
    base_prior = {} if fresh_scope and not prior else (prior or {})
    subject = explicit_subject or base_prior.get("subject") or _subject_from_message(ctx.subject or "") or ctx.subject
    state = {"version": "business-query-v1", "subject": subject,
        "scope_node_ids": [str(k) for k in roots],
        "eligibility": "practice_eligible" if query_type in {"inventory", "find"} else base_prior.get("eligibility", "all_recorded"),
        "source_categories": list(base_prior.get("source_categories", [])),
        "question_types":list(base_prior.get('question_types',[])),
        'difficulties':list(base_prior.get('difficulties',[])),
        'unattempted_only':bool(base_prior.get('unattempted_only',False)),
        'excluded_difficulties':list(base_prior.get('excluded_difficulties',[])),
        'excluded_question_types':list(base_prior.get('excluded_question_types',[])),
        "excluded_source_categories":list(base_prior.get('excluded_source_categories',[]))}
    if re.search(r'个人(?:AI)?(?:题|练习|题库)|我的个人题库', message):
        state['bank_scope'] = 'personal'
    elif re.search(r'公共(?:正式)?题库|正式题库|公共题', message):
        state['bank_scope'] = 'public'
    else:
        state['bank_scope'] = 'all'
    # Query metadata can outlive code versions. Parse persisted IDs defensively
    # so a malformed historical value cannot turn a read-only lookup into 500.
    previous_excluded = [str(value) for value in _uuid_list(
        base_prior.get("excluded_question_ids", []))]
    selecting_another = same_scope_alternative
    if selecting_another and ctx.question_id:
        previous_excluded.append(str(ctx.question_id))
    if previous and selecting_another:
        previous_meta = previous.metadata_ or {}
        displayed = previous_meta.get("read_only_data_query", {}).get("preview_questions", [])
        previous_excluded.extend(str(value) for value in _uuid_list(
            ref.get("question_id") for ref in displayed
            if isinstance(ref, dict) and ref.get("question_id")))
    if previous_excluded:
        state["excluded_question_ids"] = sorted({str(value) for value in previous_excluded})
    clarification = None
    from backend.services.assistant_scope_resolution import resolve_topics
    active_nodes=list(db.scalars(select(KnowledgePoint).where(KnowledgePoint.is_active.is_(True))))
    resolutions=resolve_topics(active_nodes,message)
    unresolved=[r['topic'] for r in resolutions if r['status']=='unmatched']
    if resolutions:
        state['scope_resolution']=resolutions
        if unresolved:
            roots=[]
            clarification='没有匹配到你指定的知识点：'+ '、'.join(unresolved)+'。请从现有知识树选择准确节点；没有扩大到整科或当前题目。'
            origin='unresolved_explicit_topic'
        else:
            roots=_scope_roots(db,{UUID(k) for r in resolutions for k in r['node_ids']})
            origin='explicit_message_scope'
    if prior and not unresolved and not fresh_scope:
        prior_roots = _active_node_ids(db, prior.get("scope_node_ids", []))
        if prior_roots:
            roots = prior_roots
        origin = "same_session_query_refinement"
    elif _FOLLOWUP.search(message) and not roots and not explicit_subject:
        clarification = "当前会话没有可继承的题库筛选范围。请先说明科目或知识点，我再查询这些题的数量和作答记录。"

    # A new named knowledge-point constraint must not quietly disappear and
    # broaden the query back to the previous/global bank.
    named = re.search(r"(?:其中|那里面|这里面|关于)?([\u4e00-\u9fffA-Za-z0-9._+-]{2,40})的(?:练习)?题", message)
    named_is_reference = bool(named and re.search(r"(?:对应|相关|这样|这种|同类)$", named.group(1)))
    if named and not named_is_reference and origin != "explicit_message_scope" and not roots and not clarification:
        name = re.sub(r"^(?:那|那么)?(?:其中|那里面|这里面|关于)", "", named.group(1))
        if not _generic_inventory_scope_name(name) and not _subject_from_message(name) and name not in {"我", "我题库里", "当前", "可练", "可练习", "全部", "这样", "这种", "同类", "相关"}:
            clarification = f"没有可靠匹配到「{name}」这个知识点。请提供知识树中的准确名称；我没有扩大范围或猜测数量。"
    # 未知知识点（无“的题”结构）不能静默退化为全库。
    if re.search(r"没做过|没有做过|未做|尚未做", message):
        state["unattempted_only"] = True
    generic_topics = {"选择题", "填空题", "计算题", "证明题", "高数", "线代", "数学", "真题",
                      "原创题", "基础题", "中等题", "难题", "简单题", "类似题", "同类题",
                      "这些题", "那些题", "没做过", "没有做过", "未做", "做过", "题库",
                      "个人题库", "公共题库", "非选择题", "非选择", "真题改编", "改编"}
    candidate = re.search(r"(?:有没有|还有|找|查|看看)?([\u4e00-\u9fff]{2,12})(?:的)?题", message)
    if candidate and not roots and not clarification:
        name = candidate.group(1)
        if name not in generic_topics and not _generic_inventory_scope_name(name) and not _subject_from_message(name):
            clarification = (f"没有可靠匹配到「{name}」这个知识点。请提供知识树中的准确名称；"
                             "没有扩大到全库或猜测数量。")
    # Even when the inherited scope has roots, a newly named unknown node must
    # not be ignored. The explicit resolver did not match it at all.
    if prior and named and not named_is_reference and not clarification:
        named_tool = TaskTools(factory, budget_minutes=90, now=datetime.now().astimezone(), goal=message)
        name = re.sub(r"^(?:那|那么)?(?:其中|那里面|这里面|关于)", "", named.group(1))
        if not named_tool.explicit_scope and not _subject_from_message(name) and name not in {"这样", "这种", "同类", "相关", "可练", "可练习"}:
            clarification = f"没有可靠匹配到「{name}」这个知识点。请提供知识树中的准确名称；我没有沿用旧范围冒充这次筛选。"
    if roots and subject:
        allowed = set(db.scalars(select(KnowledgePoint.id).where(KnowledgePoint.subject == subject,
            KnowledgePoint.is_active.is_(True))))
        intersection = _descendant_ids(db, set(roots)) & allowed
        roots = _scope_roots(db, intersection)
        if not roots:
            clarification = "这个知识点与当前继承的科目范围不一致，请确认要查询的科目和知识点。"
    if re.search(r'(?:不要|排除).{0,12}(?:个人|AI)|公共题库|正式题库',message,re.I):
        state['excluded_source_categories']=['personal_ai_practice','personal_practice']
        state['source_categories']=[]
    elif re.search(r"真题改编|改编题", message):
        state["source_categories"] = ["exam_curated", "exam_variant"]
    elif re.search(r"真题变式|真题的变式", message):
        state["source_categories"] = ["exam_variant"]
    elif re.search(r"真题|历年题", message):
        state["source_categories"] = ["exam_curated"]
    elif re.search(r"原创", message):
        state["source_categories"] = ["development_original"]
    elif re.search(r"个人AI|AI练习|AI生成", message, re.I):
        state["source_categories"] = ["personal_ai_practice"]
    if re.search(r'(?:不要|排除|不含|非)\s*(?:选择题|单选|多选)', message):
        state['question_types'] = []
        state['excluded_question_types'] = sorted(set(state.get('excluded_question_types', [])
                                                     + ['single_choice', 'multiple_choice']))
    elif re.search(r'单选',message):state['question_types']=['single_choice']
    elif re.search(r'多选',message):state['question_types']=['multiple_choice']
    elif re.search(r'选择题',message):state['question_types']=['single_choice','multiple_choice']
    elif re.search(r'填空',message):state['question_types']=['fill_blank']
    elif re.search(r'计算题',message):state['question_types']=['calculation']
    elif re.search(r'证明题',message):state['question_types']=['proof']
    elif re.search(r'所有题型|不限题型',message):state['question_types']=[]
    apply_practice_filters(state,message)
    # “非选择题/不要选择题”必须在 apply_practice_filters 覆盖之后再次强制，
    # 否则 bank_selection_request 可能只排除单选而留下多选。
    if re.search(r'非选择题|不要选择题|不含选择题|排除选择题', message):
        state['question_types'] = []
        state['excluded_question_types'] = sorted(set(state.get('excluded_question_types', [])
                                                     + ['single_choice', 'multiple_choice']))
    state['question_types']=[t for t in state['question_types'] if t not in state.get('excluded_question_types',[])]
    if roots and not state['subject']:
        subjects=set(db.scalars(select(KnowledgePoint.subject).where(KnowledgePoint.id.in_(roots))))
        if len(subjects)==1:state['subject']=next(iter(subjects))
    state["scope_node_ids"] = [str(k) for k in roots]
    return roots, origin, state, str(previous.id) if previous else None, clarification


def _questions_for_conditions(db, state, scope_ids):
    """Read the same live Question set for inventory and historical subsets."""
    from backend.services.study_read_context import question_read_options
    from backend.services.question_eligibility import question_eligibility
    nodes = select(KnowledgePoint).where(KnowledgePoint.is_active.is_(True))
    if scope_ids:
        nodes = nodes.where(KnowledgePoint.id.in_(scope_ids))
    if state.get("subject"):
        nodes = nodes.where(KnowledgePoint.subject == state["subject"])
    node_map = {n.id: n for n in db.scalars(nodes)}
    questions = list(db.scalars(select(Question).options(*question_read_options()).where(
        Question.kp_id.in_(node_map or {UUID(int=0)}), Question.is_active.is_(True), Question.is_hidden.is_(False))))
    categories = state.get("source_categories", [])
    if categories:
        questions = [q for q in questions if question_source_category(q) in categories]
    if state.get('excluded_source_categories'):
        questions=[q for q in questions if question_source_category(q) not in state['excluded_source_categories']]
    if state.get('question_types'):
        questions=[q for q in questions if q.question_type in state['question_types']]
    if state.get('difficulties'):
        questions=[q for q in questions if q.difficulty in state['difficulties']]
    if state.get('excluded_difficulties'):
        questions=[q for q in questions if q.difficulty not in state['excluded_difficulties']]
    if state.get('excluded_question_types'):
        questions=[q for q in questions if q.question_type not in state['excluded_question_types']]
    if state.get('unattempted_only'):
        attempted=set(db.scalars(select(QuestionAttempt.question_id).where(
            QuestionAttempt.question_id.in_([q.id for q in questions] or [UUID(int=0)])).distinct()))
        questions=[q for q in questions if q.id not in attempted]
    if state.get("eligibility") == "practice_eligible":
        questions = [q for q in questions if question_eligibility(q, node_map[q.kp_id]).practice_eligible]
    return questions


def execute_read_only_data_query(factory, *, session_id: UUID, ctx: StudyContext,
                                 message: str, query_type: str, now: datetime) -> dict:
    """Execute the selected read-only business query and return auditable facts."""
    with factory() as db:
        session=db.get(ChatSession,session_id)
        today=now.astimezone(SHANGHAI).date().isoformat()
        today_plan=db.scalar(select(DailyPlan).where(DailyPlan.study_date==today))
        pre_generation_home=bool(session and session.purpose=='study' and today_plan is None)
        if pre_generation_home and query_type in {'source','history','conversation_topic'}:
            return {'answer':'今日正式学习卷尚未生成。生成前只展示知识点名称和符合正式准入条件的题量，不回显具体题目、作答题干或来源详情；本次只读，没有创建今日卷。',
                'evidence':{'query_type':query_type,'query_status':'pre_generation_blindbox',
                    'model_called':False,'writes':False,'preview_questions':[],
                    'returned_preview_count':0,'tools_used':['pre_generation_blindbox_policy']}}
        if query_type == 'scope_correction':
            from backend.services.assistant_scope_resolution import resolve_topics
            nodes=list(db.scalars(select(KnowledgePoint).where(KnowledgePoint.is_active.is_(True))))
            resolutions=resolve_topics(nodes,message)
            missing=[r['topic'] for r in resolutions if r['status']=='unmatched']
            ids=[k for r in resolutions for k in r['node_ids']] if not missing else []
            names=[n.name for n in nodes if str(n.id) in ids]
            answer=('未匹配到「'+'、'.join(missing)+'」。请在知识树选择现有节点或取消；没有用洛必达、整科或其他主题替代。' if missing else
                '已将本会话后续查询范围纠正为：'+'、'.join(names)+'。纠正范围不等于创建计划；没有生成题目或加入今日卷。')
            return {'answer':answer,'evidence':{'query_type':query_type,'query_status':'needs_clarification' if missing else 'executed',
                'scope_resolution':resolutions,'scope_node_ids':ids,'query_state':{'scope_node_ids':ids,'scope_resolution':resolutions},
                'tools_used':['resolve_knowledge_scope'],'writes':False,'model_called':False}}
        if query_type == 'conversation_topic':
            history=list(db.scalars(select(ChatMessage).where(ChatMessage.session_id==session_id,
                ChatMessage.status=='completed').order_by(ChatMessage.seq.desc()).limit(8)))
            # The current user turn is not its own antecedent.
            history=[r for r in reversed(history) if not (r.role=='user' and r.content==message)]
            return {'answer':'本会话最近实际讨论记录：\n\n'+'\n\n'.join(f"{'你' if r.role=='user' else '奶蛙'}：{r.content[:1200]}" for r in history) if history else '本会话还没有可回顾的已完成讨论，请说明你要继续哪个话题。',
                'evidence':{'query_type':query_type,'query_status':'executed','writes':False,'model_called':False,'message_ids':[str(r.id) for r in history]}}
        if query_type == 'scope_clarification':
            subject = _subject_from_message(message)
            query = select(KnowledgePoint).where(KnowledgePoint.is_active.is_(True), KnowledgePoint.parent_id.is_(None))
            if subject:
                query = query.where(KnowledgePoint.subject == subject)
            names = [node.name for node in db.scalars(query.order_by(KnowledgePoint.code).limit(12))]
            answer = '你还没有说出具体知识点名称；我不会把它替换成幂级数或当前页面的其他主题。'
            if names:
                answer += ' 可以从知识树现有范围中选择：' + '、'.join(names) + '。'
            answer += ' 指定节点后，我再检查该节点的在线题目与可练资格；本次没有创建计划或题目。'
            return {'answer': answer, 'evidence': {'query_type': query_type,
                'query_status': 'needs_clarification', 'available_scope_names': names,
                'tools_used': ['resolve_knowledge_scope'], 'writes': False, 'model_called': False}}
        if query_type == 'recent_wrong_item':
            # A fresh topic has no trustworthy antecedent for “刚才那道错题”.
            # Do not search another session or create a plan from a guessed row.
            return {'answer': '我无法从当前话题定位你说的那次错答，也不会跨话题猜题或创建学习任务。请回到对应题目的作答卡，或在“回看错题”中打开那道题后再告诉我；如果它已在今日卷，我会提示你使用重练入口，不会重复加入。',
                'evidence': {'query_type': query_type, 'query_status': 'needs_same_session_attempt_reference',
                    'tools_used': ['same_session_attempt_reference'], 'writes': False, 'model_called': False}}
        if query_type == 'today_summary':
            today = now.astimezone(SHANGHAI).date().isoformat()
            plan = db.scalar(select(DailyPlan).where(DailyPlan.study_date == today))
            empty_counts = {'independent_right': 0, 'independent_wrong': 0, 'assisted_right': 0,
                'assisted_wrong': 0, 'unknown': 0}
            if not plan:
                return {'answer': '今天还没有今日学习卷，因此没有今日卷完成情况可统计。明天的建议需要先有实际学习记录；如需安排具体分钟，请告诉我可用时长。我没有创建计划。',
                    'evidence': {'query_type': query_type, 'query_status': 'no_today_plan', 'study_date': today,
                        'item_count': 0, 'attempt_summary': empty_counts, 'model_called': False,
                        'writes': False, 'tools_used': ['daily_plan_and_question_attempts']}}
            paper_items = list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id == plan.id)
                .order_by(PracticeItem.ordinal, PracticeItem.id)))
            root_ids = [row.id for row in paper_items]
            retry_ids = list(db.scalars(select(PracticeItem.id).where(
                PracticeItem.retry_source_id.in_(root_ids or [UUID(int=0)]))))
            item_ids = root_ids + retry_ids
            local_start = datetime.combine(now.astimezone(SHANGHAI).date(), datetime.min.time(), tzinfo=SHANGHAI)
            attempts = list(db.scalars(select(QuestionAttempt).where(
                QuestionAttempt.practice_item_id.in_(item_ids or [UUID(int=0)]),
                QuestionAttempt.submitted_at >= local_start.astimezone(timezone.utc),
                QuestionAttempt.submitted_at <= now).order_by(QuestionAttempt.submitted_at, QuestionAttempt.id)))
            counts = Counter(**empty_counts)
            wrong_by_node = Counter()
            for attempt in attempts:
                receipt = attempt.grading_evidence or {}
                assisted = receipt.get('assisted') is True or receipt.get('assistance_level') in {'hint_1', 'hint_2', 'solution', 'process_review'}
                category = ('assisted_right' if attempt.objective_result == 'right' and assisted else
                    'independent_right' if attempt.objective_result == 'right' and assisted is False else
                    'assisted_wrong' if attempt.objective_result == 'wrong' and assisted else
                    'independent_wrong' if attempt.objective_result == 'wrong' and assisted is False else 'unknown')
                counts[category] += 1
                if attempt.objective_result == 'wrong':
                    wrong_by_node[attempt.kp_id] += 1
            completed = [row for row in paper_items if row.completed_at is not None]
            kp_names = dict(db.execute(select(KnowledgePoint.id, KnowledgePoint.name).where(
                KnowledgePoint.id.in_(list(wrong_by_node) or [UUID(int=0)]))).all())
            next_focus = [kp_names[kp_id] for kp_id, _ in wrong_by_node.most_common(4) if kp_id in kp_names]
            evidence = {'query_type': query_type, 'query_status': 'executed', 'study_date': today,
                'plan_id': str(plan.id), 'item_count': len(paper_items), 'completed_count': len(completed),
                'remaining_count': len(paper_items) - len(completed), 'attempt_summary': dict(counts),
                'attempt_ids': [str(row.id) for row in attempts], 'attempt_item_ids': [str(k) for k in item_ids],
                'tomorrow_focus_node_names': next_focus, 'time_budget_supplied': False,
                'model_called': False, 'writes': False, 'tools_used': ['daily_plan_and_question_attempts'],
                'preview_questions': [], 'returned_preview_count': 0}
            answer = (f'今天（{today}）今日卷共 {len(paper_items)} 道，已完成 {len(completed)} 道，'
                f'未完成 {len(paper_items)-len(completed)} 道。今日实际作答：独立答对 {counts["independent_right"]} 次、'
                f'独立答错 {counts["independent_wrong"]} 次、辅助后答对 {counts["assisted_right"]} 次、'
                f'辅助后答错 {counts["assisted_wrong"]} 次、无法判定 {counts["unknown"]} 次。')
            if next_focus:
                answer += ' 明天可优先复盘今天实际答错涉及的知识点：' + '、'.join(next_focus) + '；这是依据今日错答记录的建议。'
            elif paper_items:
                answer += ' 今天没有错答记录支持薄弱点排序；明天可先完成未做题或复盘已完成题的步骤，不把次数当作掌握结论。'
            else:
                answer += ' 当前没有题目作答证据支持薄弱点排序。'
            answer += ' 你没有指定明天的时长，所以我不替你设定90分钟；需要精确分钟安排时请告诉我预算。本次只查询，没有创建LearningTask或改动今日卷。'
            return {'answer': answer, 'evidence': evidence}
        if query_type == 'source':
            latest = db.scalar(select(ChatMessage).where(
                ChatMessage.session_id == session_id, ChatMessage.role == 'assistant',
                ChatMessage.status == 'completed').order_by(ChatMessage.seq.desc()).limit(1))
            meta = (latest.metadata_ or {}) if latest else {}
            evidence_data = meta.get('read_only_data_query') or {}
            previews = evidence_data.get('preview_questions') or []
            refs = meta.get('generated_question_refs') or []
            qid = previews[0].get('question_id') if previews else (refs[0].get('question_id') if refs else None)
            if not qid:
                return {'answer': '当前会话还没有可关联的题目预览或生成记录；我不会猜测题目来源。',
                        'evidence': {'query_type': query_type, 'query_status': 'no_recent_question',
                                     'writes': False, 'model_called': False, 'tools_used': ['chat_messages']}}
            question = db.get(Question, UUID(str(qid)))
            if question is None:
                return {'answer': '最近记录的题目已不可读取；不会用其他题目的来源代替。',
                        'evidence': {'query_type': query_type, 'query_status': 'question_missing',
                                     'writes': False, 'model_called': False}}
            source_label = SOURCE_LABELS.get(question_source_category(question), question_source_category(question))
            answer = (f"最近一次预览/生成的题目：{question.stem[:120]}\n\n"
                      f"来源分类：{source_label}；题库范围：{question.bank_scope}；"
                      f"题目 ID：{question.id}。来源分类不等于真实历年出处已核实。")
            return {'answer': answer, 'evidence': {'query_type': query_type, 'query_status': 'executed',
                'question_id': str(question.id), 'source_category': question_source_category(question),
                'bank_scope': question.bank_scope, 'writes': False, 'model_called': False,
                'tools_used': ['chat_messages', 'questions']}}
        if query_type == 'today_detail':
            today = now.astimezone(SHANGHAI).date().isoformat()
            plan = db.scalar(select(DailyPlan).where(DailyPlan.study_date == today))
            if plan is None:
                return {'answer': '今天还没有正式今日卷（未生成）。可以先生成推荐方案；本次只查询，没有创建计划或题目。',
                    'evidence': {'query_type': query_type, 'query_status': 'no_today_plan', 'study_date': today,
                        'model_called': False, 'writes': False, 'tools_used': ['daily_plan']}}
            items = list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id == plan.id)
                .order_by(PracticeItem.ordinal, PracticeItem.id)))
            questions = [q for q in (question_for_practice_item(db, item) for item in items) if q is not None]
            node_ids = {q.kp_id for q in questions}
            nodes = {n.id: n for n in db.scalars(select(KnowledgePoint).where(
                KnowledgePoint.id.in_(node_ids or {UUID(int=0)})))}
            kp_counter = Counter(nodes[q.kp_id].name for q in questions if q.kp_id in nodes)
            source_counter = Counter(question_source_category(q) for q in questions)
            total_minutes = sum(int(q.estimated_minutes or 0) for q in questions)
            completed = sum(1 for item in items if item.completed_at is not None)
            aliases = {'线代': '线性代数', '高数': '高等数学'}
            def _matched(name: str) -> bool:
                if name and name in message:
                    return True
                for short, full in aliases.items():
                    if short in message and (short in name or full in name):
                        return True
                return False
            matched_names = [name for name in kp_counter if _matched(name)]
            matched_subjects = [s for s in {nodes[q.kp_id].subject for q in questions if q.kp_id in nodes}
                                if s and s in message]
            answer = (f'今天的正式今日卷（{today}）已生成：共 {len(items)} 道，已完成 {completed} 道，'
                      f'剩余 {len(items) - completed} 道，预计 {total_minutes} 分钟。')
            if kp_counter:
                answer += '知识点：' + '、'.join(f'{name}（{count}道）' for name, count in kp_counter.most_common()) + '。'
            if source_counter:
                answer += '题目来源：' + '、'.join(
                    f'{SOURCE_LABELS.get(label, label)}（{count}道）' for label, count in source_counter.most_common()) + '。'
            if matched_names:
                answer += '你提到的范围在今日卷中匹配到：' + '、'.join(
                    f'{name}（{kp_counter[name]}道）' for name in matched_names) + '。'
            elif matched_subjects:
                answer += '你提到的科目在今日卷中匹配到：' + '、'.join(matched_subjects) + '。'
            elif re.search(r'线代|高数|隐函数|概率|有没有|是否', message):
                answer += '你提到的范围没有出现在今日卷的知识点列表中。'
            answer += ' 这是今日卷真实记录；本次没有修改正式卷。'
            evidence = {'query_type': query_type, 'query_status': 'executed', 'study_date': today,
                'plan_id': str(plan.id), 'item_count': len(items), 'completed_count': completed,
                'remaining_count': len(items) - completed, 'total_minutes': total_minutes,
                'kp_counts': dict(kp_counter), 'source_counts': dict(source_counter),
                'matched_kp_names': matched_names, 'matched_subjects': matched_subjects,
                'model_called': False, 'writes': False,
                'tools_used': ['daily_plan', 'practice_items', 'question_versions']}
            return {'answer': answer, 'evidence': evidence}
        alternatives = query_type == 'inventory_alternatives'
        if alternatives: query_type='find'
        if query_type in {'learning_state', 'evidence_basis', 'self_report'}:
            from backend.services.learning_evidence_query import learning_evidence_query
            return learning_evidence_query(db, factory, session_id=session_id, ctx=ctx,
                message=message, query_type=query_type, now=now)
        roots, scope_source, query_state, antecedent_id, clarification = _query_conditions(
            db, factory=factory, session_id=session_id, ctx=ctx, message=message, query_type=query_type,now=now)
        node_rows = list(db.scalars(select(KnowledgePoint).where(
            KnowledgePoint.id.in_(roots or [UUID(int=0)]), KnowledgePoint.is_active.is_(True)))) if roots else []
        node_names = [node.name for node in node_rows]
        scope_ids = _descendant_ids(db, set(roots)) if roots else set()
        evidence = {"query_type": query_type, "scope_source": scope_source,
            "scope_node_ids": [str(value) for value in roots], "scope_node_names": node_names,
            "model_called": False, "writes": False, "tools_used": [], "version_binding": [],
            # 预览键必须始终存在：没有可用候选时返回空列表，前端与调用方
            # 依据 returned_preview_count 判断，而不是 KeyError。
            "preview_questions": [], "returned_preview_count": 0,
            "query_state": query_state, "antecedent_message_id": antecedent_id, "query_status": "executed"}
        if clarification and query_type in {"inventory", "find", "history"}:
            evidence.update(query_status="needs_clarification", tools_used=["resolve_query_scope"])
            return {"answer": clarification, "evidence": evidence}

        if query_type in {"inventory", "find"}:
            if scope_source == "ambiguous_or_missing_antecedent":
                evidence.update(query_status="needs_clarification", tools_used=["resolve_query_scope"])
                return {"answer": "我没法可靠判断“这样的题”指哪个知识点。请说出知识点名称，或先在知识树/当前题目中选定范围。",
                    "evidence": evidence}
            subject = query_state["subject"]
            # The page's explicitly bound plan is authoritative for this
            # conversation. A restored/frozen-date session can differ from the
            # host clock, so do not silently count against another day's plan.
            query_plan_id=ctx.daily_plan_id if ctx.daily_plan_id and db.get(DailyPlan,ctx.daily_plan_id) else None
            stock = question_availability(db, now=now, subject=subject,
                kp_ids=roots or None, plan_id=query_plan_id, limit=16,
                include_node_summaries=pre_generation_home,
                bank_scope=query_state.get('bank_scope', 'all'))
            if roots:
                visible_nodes = _descendant_ids(db, set(roots))
            else:
                visible_node_query = select(KnowledgePoint.id).where(KnowledgePoint.is_active.is_(True))
                if subject:
                    visible_node_query = visible_node_query.where(KnowledgePoint.subject == subject)
                visible_nodes = set(db.scalars(visible_node_query))
            visible_questions = list(db.scalars(select(Question).where(
                Question.kp_id.in_(visible_nodes or {UUID(int=0)}),
                Question.is_active.is_(True), Question.is_hidden.is_(False),
                *([Question.bank_scope == query_state['bank_scope']]
                  if query_state.get('bank_scope') in {'personal', 'public'} else []))))
            visible_source_counts = Counter(question_source_category(question) for question in visible_questions)
            personal_ai_count = sum(question.bank_scope == "personal" and
                question.question_provenance == "ai_generated_practice" for question in visible_questions)
            evidence["tools_used"].append("question_availability")
            evidence["question_count"] = stock["practice_eligible_count"]
            evidence["active_question_count"] = stock["active_question_count"]
            evidence["blocked_question_count"] = stock["blocked_question_count"]
            evidence["available_to_append_count"] = stock["available_to_append_count"]
            evidence["already_in_plan_count"] = stock["already_in_plan_count"]
            evidence["previously_attempted_count"] = stock["previously_attempted_count"]
            evidence["current_plan_id"] = stock.get("current_plan_id")
            evidence["visible_source_category_counts"] = dict(visible_source_counts)
            evidence["visible_personal_ai_practice_count"] = personal_ai_count
            evidence["source_category_counts"] = stock["source_category_counts"]
            evidence["bank_scope_counts"] = stock["bank_scope_counts"]
            evidence["reference_count"] = stock["reference_count"]
            filtered=bool(query_state["source_categories"] or query_state.get('question_types') or query_state.get('difficulties') or query_state.get('unattempted_only') or query_state.get('excluded_difficulties') or query_state.get('excluded_question_types')
                or query_state.get('excluded_source_categories'))
            if filtered:
                from backend.services.question_eligibility import question_eligibility
                selected_active=_questions_for_conditions(db,{**query_state,'eligibility':'all_recorded'},scope_ids)
                from backend.services.question_admission import formal_use_allowed
                selected=[q for q in selected_active if question_eligibility(q,db.get(KnowledgePoint,q.kp_id)).practice_eligible
                          and formal_use_allowed(q)]
                selected_ids={q.id for q in selected}
                current_plan_id=UUID(stock['current_plan_id']) if stock.get('current_plan_id') else None
                in_plan=set(db.scalars(select(PracticeItem.question_id).where(
                    PracticeItem.plan_id==current_plan_id,
                    PracticeItem.question_id.in_(selected_ids or {UUID(int=0)})))) if current_plan_id else set()
                attempted=set(db.scalars(select(QuestionAttempt.question_id).where(
                    QuestionAttempt.question_id.in_(selected_ids or {UUID(int=0)})).distinct()))
                evidence.update(question_count=len(selected),active_question_count=len(selected_active),
                    blocked_question_count=len(selected_active)-len(selected),
                    available_to_append_count=len(selected_ids-in_plan),already_in_plan_count=len(selected_ids&in_plan),
                    previously_attempted_count=len(selected_ids&attempted),
                    source_category_counts=dict(Counter(question_source_category(q) for q in selected)))
            evidence['inventory_state']=('no_matching_query_conditions' if filtered and not evidence['active_question_count'] and stock['active_question_count'] else
                'no_online_questions' if not evidence['active_question_count'] else
                'no_eligible_questions' if not evidence['question_count'] else
                'all_eligible_questions_in_today_plan' if not evidence['available_to_append_count'] else
                'eligible_questions_available')
            if pre_generation_home:
                summaries=stock.get('node_summaries') or []
                counts_by_id={UUID(str(row['kp_id'])):row for row in summaries}
                scope_counts=[]
                for root_id in roots:
                    root=db.get(KnowledgePoint,root_id)
                    descendants=_descendant_ids(db,{root_id})
                    scoped=[row for node_id,row in counts_by_id.items() if node_id in descendants]
                    scope_counts.append({'kp_id':str(root_id),'name':root.name if root else '',
                        'practice_eligible_count':sum(int(row.get('practice_eligible_count') or 0) for row in scoped)})
                if not scope_counts:
                    scope_counts=[{'kp_id':str(row['kp_id']),'name':row['name'],
                        'practice_eligible_count':int(row['practice_eligible_count'])}
                        for row in (stock.get('eligible_nodes') or [])[:8]]
                safe_evidence={'query_type':query_type,'query_status':'pre_generation_blindbox',
                    'scope_node_counts':scope_counts,
                    'question_count':int(stock['practice_eligible_count']),
                    'available_to_append_count':int(stock['available_to_append_count']),
                    'preview_questions':[],'returned_preview_count':0,
                    'model_called':False,'writes':False,
                    'tools_used':['question_availability']}
                from backend.services.pre_generation_query_view import inventory_answer
                return {'answer':inventory_answer(safe_evidence),'evidence':safe_evidence}
            requested_question_list = bool(re.search(
                r"(?:题目|练习题|真题|原创题|真题变式).{0,12}(?:有哪些|哪几道|列出)|"
                r"有哪些.{0,10}(?:题目|练习题|真题|原创题|真题变式)|"
                r"(?:这道题|这些题|当前题目).{0,8}(?:来源|来自哪里)", message))
            if (query_type == "find" or requested_question_list or
                    (query_type == 'inventory' and re.search(r'有没有|是否有', message) and not re.search(r'多少|数量|几道',message))):
                rows = []
                available_nodes = roots
                # 父节点（如“矩阵/线性代数”）本身没有题；预览必须落到叶子节点。
                if filtered and selected:
                    available_nodes = list(dict.fromkeys(q.kp_id for q in selected))[:8]
                elif roots:
                    pool = _questions_for_conditions(db, {**query_state, 'eligibility': 'practice_eligible'}, scope_ids)
                    available_nodes = list(dict.fromkeys(q.kp_id for q in pool))[:8]
                if not available_nodes:
                    if filtered:
                        from backend.services.question_eligibility import question_eligibility
                        matching=_questions_for_conditions(db,{**query_state,'eligibility':'all_recorded'},scope_ids)
                        available_nodes=list(dict.fromkeys(q.kp_id for q in matching
                            if question_eligibility(q,db.get(KnowledgePoint,q.kp_id)).practice_eligible))[:8]
                    else:
                        # A global "what can I practice?" list should not
                        # silently sample only the first knowledge point.
                        # Keep the tool bounded, and expose truncation below.
                        available_nodes = [UUID(str(n["kp_id"])) for n in stock["eligible_nodes"][:8]]
                        evidence["inventory_node_list_truncated"] = bool(stock.get("node_list_truncated"))
                if available_nodes:
                    tool = TaskTools(factory, budget_minutes=90, now=now, goal=message)
                    tool.intent = "recommend"
                    tool.nodes.update(scope_ids or set(available_nodes))
                    excluded_question_ids = set(_uuid_list(query_state.get("excluded_question_ids", [])))
                    # Both an explicit search and an availability-style
                    # "有没有可练题" request may render candidates. Counts
                    # above still describe the full eligible inventory, but a
                    # preview must never render a question already on today's
                    # paper as though it were a new candidate.
                    if stock.get('current_plan_id'):
                        excluded_question_ids.update(db.scalars(select(PracticeItem.question_id).where(
                            PracticeItem.plan_id == UUID(stock['current_plan_id']), PracticeItem.question_id.is_not(None))))
                    evidence["excluded_question_ids"] = sorted(str(value) for value in excluded_question_ids)
                    requested_count=bank_preview_count(message)
                    tool.handoff={'constraints':{'existing_bank_only':True,'preview_query_state':query_state,
                        'include_personal_bank':True,'home_unattempted_only':query_state.get('unattempted_only',False),
                        'home_requested_count':min(1000,requested_count)}}
                    tool.required_difficulty=query_state['difficulties'][0] if query_state.get('difficulties') else None
                    from backend.schemas.home_recommendation import HomeBankQuery
                    candidate = tool.find_questions(db, HomeBankQuery(kp_ids=available_nodes,
                        exclude_question_ids=sorted(excluded_question_ids)))
                    evidence["tools_used"].append("find_questions")
                    rows = candidate.get("questions", [])
                    allowed={str(q.id) for q in _questions_for_conditions(db,query_state,scope_ids)}
                    rows=[q for q in rows if q['question_id'] in allowed]
                    rows=rows[:requested_count]
                    evidence['requested_preview_count']=requested_count
                    evidence['returned_preview_count']=len(rows)
                    evidence['candidate_list_complete']=candidate.get('candidate_list_complete')
                    evidence['preview_questions']=[{'question_id':r['question_id'],'question_version':r['question_version'],
                        'kp_id':r['kp_id'],'question_type':r.get('question_type'),
                        'source_category':r.get('source_category'), 'difficulty':r.get('difficulty'),
                        'minutes':r.get('minutes')} for r in rows if r.get('question_version')]
                    evidence['preview_generated_at']=now.isoformat()
                    if rows:
                        qid = UUID(rows[0]["question_id"])
                        q = db.get(Question, qid)
                        item = question_for_version(db, UUID(rows[0]["question_version"])) if rows[0].get("question_version") else None
                        if q and item:
                            evidence["question_id"] = str(q.id)
                            evidence["question_version_id"] = str(item.version_id)
                            evidence["knowledge_node_id"] = str(q.kp_id)
                            evidence["version_binding"].append({"question_id": str(q.id),
                                "question_version_id": str(item.version_id), "kp_id": str(q.kp_id)})
                            parts=[]
                            for index, ref in enumerate(evidence['preview_questions'],1):
                                bound=question_for_version(db,UUID(ref['question_version']))
                                if bound:
                                    options=bound.options or {}
                                    option_text='\n'.join(f'{key}. {value}' for key,value in options.items()) if isinstance(options,dict) else '\n'.join(map(str,options))
                                    parts.append(f"### 第 {index} 道\n\n{bound.stem}\n\n{option_text}")
                            preview_sources = Counter(r.get('source_category', 'unclassified_public') for r in rows)
                            preview_source_summary = "、".join(
                                f"{SOURCE_LABELS.get(key, key)} {value} 道" for key, value in sorted(preview_sources.items()))
                            answer = (f"真实题库当前符合查询条件的合格在线题 {evidence['question_count']} 道；"
                                f"其中 {evidence['already_in_plan_count']} 道已在当前今日卷（{evidence['previously_attempted_count']} 道有历史作答），"
                                f"可新增 {evidence['available_to_append_count']} 道。以下预览 {len(parts)} 道，尚未加入今日卷。"
                                f"预览题来源分类：{preview_source_summary or '当前无可展示题目'}。来源分类不等于原版历年真题出处已核实。\n\n"
                                +'\n\n'.join(parts)+'\n\n数据来源：系统题库只读查询；可以指定预览题号后准备待确认方案。')
                            if evidence.get('inventory_node_list_truncated'):
                                answer += "\n本次知识点列表有范围上限，以上不是全库完整清单；可指定知识点继续查询。"
                            if len(rows)<requested_count:
                                answer+=f'\n本次要求 {requested_count} 道，实际返回 {len(rows)} 道；未补入其他范围题。候选读取'+('完整。' if candidate.get('candidate_list_complete') else '有界，不能据此断言全库库存不足。')
                            return {"answer": answer, "evidence": evidence}
                if evidence['question_count'] and evidence['inventory_state'] != 'all_eligible_questions_in_today_plan':
                    evidence['inventory_state']=('no_alternative_after_previous_preview'
                        if query_state.get('excluded_question_ids') else 'no_appendable_candidates')
                state_text={'no_online_questions':'知识点范围存在，但没有在线题。',
                    'no_eligible_questions':'知识点范围存在，有在线题但没有符合当前可练资格的题。',
                    'no_matching_query_conditions':'知识范围有在线题，但没有题目符合当前来源或题型筛选条件。',
                    'all_eligible_questions_in_today_plan':('、'.join(node_names) if node_names else (subject or '当前题库查询范围'))+'有合格题，但当前范围的合格题都已在今日卷中；不会重复展示为新候选。',
                    'no_alternative_after_previous_preview':'上一轮已经展示的候选已排除；当前范围没有其他符合条件的题目。',
                    'no_appendable_candidates':'当前查询没有返回满足本次范围、资格、版本或筛选条件的候选；不能据此断言题目已经入卷。',
                    'eligible_questions_available':'存在合格题，但没有匹配本次筛选条件的候选。'}[evidence['inventory_state']]
                if evidence['inventory_state']=='all_eligible_questions_in_today_plan':
                    state_text+=f"合格题共 {evidence['question_count']} 道，已在当前卷 {evidence['already_in_plan_count']} 道，其中 {evidence['previously_attempted_count']} 道已有作答；可新增 0 道。"
                return {"answer": state_text+' 可以查看当前卷、复盘已学题或选择其他知识点；没有生成新题或创建计划。',
                    "evidence": evidence}
            label = "、".join(node_names) if node_names else (subject or "全部科目")
            if query_state.get('bank_scope') == 'personal':
                pending = max(0, len(visible_questions) - evidence['question_count'])
                answer = (f"{label}的个人题库共有 {len(visible_questions)} 道；"
                          f"其中可练（已通过独立验证）{evidence['question_count']} 道，"
                          f"待审核/未验证 {pending} 道。统计按 Question 实体计数；"
                          "待审核题只在个人题库查看，不进入推荐、今日卷或专项训练。")
                return {"answer": answer, "evidence": evidence}
            categories = evidence["source_category_counts"] or {}
            source_summary = "；".join(f"{SOURCE_LABELS.get(key, key)} {value} 道" for key, value in sorted(categories.items())) or "当前没有可练题"
            visible_summary = "；".join(f"{SOURCE_LABELS.get(key, key)} {value} 道" for key, value in sorted(visible_source_counts.items())) or "当前没有可见有效题"
            selected_label = "、".join(SOURCE_LABELS.get(k, k) for k in query_state["source_categories"])
            type_labels={'single_choice':'单选题','multiple_choice':'多选题','fill_blank':'填空题'}
            if query_state.get('question_types'):
                selected_label+=' / '+'、'.join(type_labels.get(t,t) for t in query_state['question_types'])
            if query_state.get('excluded_source_categories'):selected_label+=' / 排除个人练习'
            answer = (f"{label}{' / ' + selected_label if selected_label else ''}范围内有 {evidence['question_count']} 道符合当前可练资格的在线题。"
                f"该知识范围全部来源的可见有效题共 {stock['active_question_count']} 道，其中个人 AI 练习 {personal_ai_count} 道；"
                f"按全部可见题的来源分类：{visible_summary}。符合可练资格的题中：{source_summary}。"
                f"另有 {stock['blocked_question_count']} 道目前不符合可练资格；关联原卷引用 {stock['reference_count']} 条（引用不含可作答题干）。\n\n"
                "统计按 Question 题目实体计数，不按 QuestionVersion 版本数；未审核或不符合资格的题不计入可练数。"
                "个人 AI 练习仍不因此成为正式毕业证据。来源分类不等于已核实的真实历年出处。数据来源：系统题库实时只读查询。")
            return {"answer": answer, "evidence": evidence}

        if query_type == "today":
            today = now.astimezone(SHANGHAI).date().isoformat()
            plan = db.scalar(select(DailyPlan).where(DailyPlan.study_date == today))
            if not plan:
                evidence.update({"plan_id": None, "item_count": 0, "remaining_count": 0})
                return {"answer": "今天还没有今日学习卷。你可以先从今日学习选择知识点或追加题目；我没有自动创建计划。",
                    "evidence": evidence}
            items = list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id == plan.id)
                .order_by(PracticeItem.ordinal, PracticeItem.id)))
            completed = [item for item in items if item.completed_at is not None]
            evidence.update({"plan_id": str(plan.id), "item_count": len(items),
                "completed_count": len(completed), "remaining_count": len(items) - len(completed)})
            if ctx.practice_item_id:
                current = next((item for item in items if item.id == ctx.practice_item_id), None)
                if current and current.question_id:
                    q = question_for_practice_item(db, current)
                    evidence["version_binding"].append({"question_id": str(current.question_id),
                        "question_version_id": str(current.question_version_id), "kp_id": str(current.kp_id)})
                    node = db.get(KnowledgePoint, current.kp_id)
                    answer = (f"你今天正在做「{node.name}」的题：{q.stem[:260]}。"
                        f"今日卷共 {len(items)} 道，已完成 {len(completed)} 道，还剩 {len(items)-len(completed)} 道。")
                    evidence["tools_used"].append("daily_plan_and_practice_items")
                    return {"answer": answer, "evidence": evidence}
            answer = f"今天的学习卷共 {len(items)} 道，已完成 {len(completed)} 道，还剩 {len(items)-len(completed)} 道。"
            evidence["tools_used"].append("daily_plan_and_practice_items")
            return {"answer": answer, "evidence": evidence}

        if query_type == "history":
            if scope_source == "ambiguous_or_missing_antecedent":
                return {"answer": "我没法从当前会话确定要查询哪个知识点的作答记录。请说出知识点名称，或选中对应知识点/题目后再问。",
                    "evidence": evidence}
            attempt_filters = [QuestionAttempt.question_id.is_not(None)]
            if scope_ids:
                attempt_filters.append(QuestionAttempt.kp_id.in_(scope_ids))
            if query_state["subject"]:
                attempt_filters.append(QuestionAttempt.kp_id.in_(select(KnowledgePoint.id).where(
                    KnowledgePoint.subject == query_state["subject"])))
            if query_state["eligibility"] == "practice_eligible" or query_state["source_categories"] or query_state.get('question_types') or query_state.get('excluded_source_categories'):
                candidates = _questions_for_conditions(db, query_state, scope_ids)
                attempt_filters.append(QuestionAttempt.question_id.in_([q.id for q in candidates] or [UUID(int=0)]))
            wrong_only = bool(re.search(r"做错(?:过|了)?|答错(?:过|了)?|错过哪些|哪些错题", message))
            if wrong_only:
                attempt_filters.append(QuestionAttempt.objective_result == "wrong")
            evidence["result_filter"] = "wrong" if wrong_only else "all"
            attempt_count = db.scalar(select(func.count()).select_from(QuestionAttempt).where(*attempt_filters)) or 0
            distinct_question_count = db.scalar(select(func.count(func.distinct(QuestionAttempt.question_id)))
                .where(*attempt_filters)) or 0
            grouped_results = db.execute(select(QuestionAttempt.objective_result, func.count())
                .where(*attempt_filters).group_by(QuestionAttempt.objective_result)).all()
            result_counts = Counter()
            for result, count in grouped_results:
                label = "correct" if result in {"right", "correct"} else "wrong" if result == "wrong" else "unknown"
                result_counts[label] += count
            assisted_rows = list(db.scalars(select(QuestionAttempt.grading_evidence).where(*attempt_filters)))
            assisted = sum(bool((receipt or {}).get("assisted")) or
                           (receipt or {}).get("assistance_level") in {'hint_1', 'hint_2', 'solution', 'process_review'} for receipt in assisted_rows)
            learning_event_count = db.scalar(select(func.count()).select_from(LearningEvent).join(
                QuestionAttempt, LearningEvent.source_id == QuestionAttempt.id).where(
                    LearningEvent.event_type == "answer_submitted", *attempt_filters)) or 0
            attempts = list(db.scalars(select(QuestionAttempt).where(*attempt_filters)
                .order_by(QuestionAttempt.submitted_at.desc(), QuestionAttempt.id.desc()).limit(8)))
            attempts.reverse()
            binding_rows = []
            question_previews = []
            for attempt in attempts:
                bound = question_for_attempt(db, attempt)
                binding_rows.append({"attempt_id": str(attempt.id), "question_id": str(bound.id),
                    "question_version_id": str(bound.version_id), "kp_id": str(bound.kp_id),
                    "binding_valid": str(bound.version_id) == str(attempt.question_version_id)})
                question_previews.append({"question_id": str(bound.id), "stem": bound.stem[:180]})
            evidence.update({"tools_used": ["question_attempts", "learning_events"],
                "attempt_count": attempt_count, "distinct_question_count": distinct_question_count,
                "objective_results": dict(result_counts), "assisted_attempt_count": assisted,
                "learning_event_count": learning_event_count,
                "recent_question_previews": question_previews,
                "attempts": [{"attempt_id": str(a.id), "question_id": str(a.question_id) if a.question_id else None,
                    "question_version_id": str(a.question_version_id) if a.question_version_id else None,
                    "kp_id": str(a.kp_id), "objective_result": a.objective_result,
                    "assisted": bool((a.grading_evidence or {}).get("assisted")),
                    "assistance_level": (a.grading_evidence or {}).get("assistance_level"),
                    "submitted_at": a.submitted_at.isoformat()} for a in attempts],
                "version_binding": binding_rows})
            if roots:
                tool = TaskTools(factory, budget_minutes=90, now=now, goal=message)
                tool.nodes.update(scope_ids)
                state = tool.get_learning_state(db, NodeIds(kp_ids=roots[:8]))
                evidence["tools_used"].append("get_learning_state")
                evidence["learning_state"] = state["states"]
            if not attempt_count:
                name = "、".join(node_names) if node_names else (query_state["subject"] or "全库")
                return {"answer": f"在{name}范围内没有查到 QuestionAttempt 作答记录；这表示当前数据库没有匹配到作答记录，不代表你没有在系统外做过题。",
                    "evidence": evidence}
            name = "、".join(node_names) if node_names else (query_state["subject"] or "全库")
            if query_state["source_categories"]:
                name += " / " + "、".join(SOURCE_LABELS.get(k, k) for k in query_state["source_categories"])
            if query_state["eligibility"] == "practice_eligible":
                name += " / 当前可练题"
            correct = result_counts.get("correct", 0)
            wrong = result_counts.get("wrong", 0)
            unknown = result_counts.get("unknown", 0)
            answer = (f"查到你在{name}范围内提交过 {attempt_count} 次作答，涉及 {distinct_question_count} 道题："
                f"客观记录为正确 {correct} 次、错误 {wrong} 次、无法判定 {unknown} 次。"
                f"其中 {assisted} 次记录带有提示/解析等辅助信息；这与是否正式毕业是两回事。")
            if wrong_only and question_previews:
                unique = {row["question_id"]: row for row in question_previews}
                answer += "\n最近做错的题（按保存的作答版本读取）：\n" + "\n".join(
                    f"- {row['stem']}" for row in unique.values())
            answer += "\n数据来源：系统 QuestionAttempt / LearningEvent；按题目去重与提交次数分别统计，沿用的题库资格与来源筛选条件保持不变。"
            return {"answer": answer, "evidence": evidence}

        if query_type == "learning_state":
            if not roots:
                return {"answer": "请先选择一个具体知识点，或说出知识点名称；我再读取该节点的学习状态和证据来源。",
                    "evidence": evidence}
            tool = TaskTools(factory, budget_minutes=90, now=now, goal=message)
            tool.nodes.update(scope_ids)
            state = tool.get_learning_state(db, NodeIds(kp_ids=roots[:8]))
            evidence["tools_used"] = ["get_learning_state"]
            evidence["learning_state"] = state["states"]
            summaries = []
            for item in state["states"]:
                summaries.append(f"{next((n.name for n in node_rows if str(n.id)==item['kp_id']), '该节点')}："
                    f"状态 {item['state']}，近期记录 {len(item['recent_attempts'])} 条；"
                    f"自评证据{'可用' if item['self_report_available'] else '暂无可用记录（不等于用户自评不会）'}，"
                    f"客观确认 {item['verified_objective_confirmation_count']} 次。")
            return {"answer": "\n".join(summaries) + "\n状态按当前有效证据读取；未验证或没有记录不能等同于不会，也不会据此修改毕业资格。",
                "evidence": evidence}

    return {"answer": "当前问题没有匹配到可执行的只读查询。请换一种问法，或明确知识点范围。",
        "evidence": {"query_type": query_type, "model_called": False, "writes": False}}
