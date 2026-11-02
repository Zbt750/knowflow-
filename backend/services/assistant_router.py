"""A bounded capability decision, without tool execution or write permission."""
from dataclasses import asdict, dataclass
import re
from backend.services.learning_task_tools import classify_task_intent


_ADVICE_ONLY_RE = re.compile(
    r"(?:先.{0,8}(?:给|提供|说).{0,8}(?:建议|推荐)|"
    r"(?:只|先)给.{0,8}(?:建议|推荐)|"
    r"未经.{0,8}确认.{0,24}(?:不要|不必|不能|不得).{0,12}(?:创建|加入|追加|写入)|"
    r"(?:先|暂时|暂)?不(?:再|自动|直接)?\s*(?:创建|加入|追加|写入).{0,12}(?:今日|正式|计划|学习卷)?|"
    r"(?:不要|不必|不能|不得).{0,12}(?:创建|加入|追加|写入).{0,12}(?:今日|计划|学习卷)?)"
)


def _advice_only_request(message: str) -> bool:
    """A user can request a recommendation while explicitly withholding write consent."""
    return bool(_ADVICE_ONLY_RE.search(message))


def _explanation_request(text: str) -> str | None:
    """Keep explanation clauses when a message also requests a bank action."""
    clauses = [part.strip() for part in re.split(r"[，,；;。！？?\n]|(?:同时|然后|并且|但是)|(?=但不要|但别)", text) if part.strip()]
    explanations = [part for part in clauses if re.search(
        r"讲解|讲讲|讲清(?:楚)?|讲明(?:白)?|先讲|解释|介绍|什么是|是什么|是怎么(?:样|回事)|怎么用|如何使用|适用条件", part)
        and not re.search(r"(?:不要|不用|无需|不必|别).{0,5}(?:讲解|解释|介绍)", part)
        and not re.search(r"^(?:为什么|为何).{0,12}(?:不能|不该|没有).{0,12}(?:安排|加入|放进)", part)]
    return "；".join(explanations) or None


def _planner_intent(message: str, default: str) -> str:
    return "recommend" if _advice_only_request(message) else default


@dataclass(frozen=True)
class CapabilityRoute:
    capability: str
    intent: str
    confidence: float
    reason: str
    fallback: bool=False
    write_risk: bool=False
    explanation_request: str | None = None

    def public_dict(self): return asdict(self)


def post_graduation_review_query(message):
    """复习一个概念不等于查询毕业后复习状态。必须有明确状态语义。"""
    if re.search(r'安排|加入|生成|出题', message):
        return False
    review = bool(re.search(r'复习|巩固|熟练', message))
    status = bool(re.search(r'毕业|复习(?:状态|风险)|提示复习|熟练(?:度|状态)|'
                            r'(?:哪些|哪个).{0,20}(?:需要|该|要).{0,8}复习', message))
    return review and status


def route_message(message, context, *, action="auto", task=None, classifier=None):
    text=message.strip()
    if action!="auto": return CapabilityRoute("qa","qa",1,"explicit_assistance_action")
    # NB-13：质疑判断依据 → 学习证据解释（必须先于题库检索，避免裸词“题”抢走）。
    if re.search(r'(?:为什么|凭什么|依据|怎么).{0,10}(?:判断|认为|说|认定)|判断依据|凭什么说|你的依据|你说我.{0,12}(?:很差|没掌握|薄弱)', text):
        return CapabilityRoute('data_query','evidence_basis',1,'explicit_evidence_basis_query',write_risk=False)
    # NB-01：学习进度/统计查询是只读，先于“学习任务请求”。
    if re.search(r'(?:查看|看看|看下)?.{0,4}(?:今天|今日).{0,6}(?:的)?(?:学习)?(?:进度|学了多少|学得怎么样|完成得如何|完成情况|答对了几道)|(?:今天|今日).{0,6}(?:学习)?(?:进度|学得怎么样|完成得如何)', text):
        return CapabilityRoute('data_query','today_summary',1,'explicit_today_progress_query',write_risk=False)
    if re.search(r'(?:今天|今日).{0,8}(?:独立)?(?:答对|做对).{0,6}几道|还有多少.{0,6}知识点.{0,4}(?:没|未).{0,4}掌握', text):
        return CapabilityRoute('data_query','learning_state',1,'explicit_learning_state_query',write_risk=False)
    # 资料库边界：只有明确“根据资料出题”才进入生成；其余资料阅读/检索/总结保持只读问答。
    if re.search(r'(?:根据|按照|用).{0,8}(?:这份|这篇|该|上传的)?.{0,6}(?:资料|笔记|PDF|文档|材料).{0,10}(?:出|生成|出题|练习题|测试题)', text):
        return CapabilityRoute('generation','generate',1,'material_based_generation',write_risk=True)
    # NB-10：概念/区别类问句不得进入出题（即使含“变式/生成”）。
    if re.search(r'(?:什么是|什么叫|是什么意思|有哪些类型|有何区别|有什么区别|怎么区分|区别是)', text) \
            and re.search(r'变式|生成|出题|AI|个人练习|真题', text):
        return CapabilityRoute('qa','qa',1,'concept_question_not_generation',write_risk=False)
    # “只想看题库/看看题库里有哪些题，不要创建计划”是只读题库检索（否定创建，不是否定检索）。
    if re.search(r'(?:只|就)?(?:想|要)?看(?:看|一下)?题库|看看题库里', text) and re.search(r'不要创建计划|别创建计划|不创建计划|不建计划', text):
        return CapabilityRoute('data_query','find',1,'explicit_read_only_bank_query',write_risk=False)
    # NB-02：明确否定约束（别加入/不要生成/只讲/只查）优先，尊重用户限定。
    if re.search(r'(?:别|不要|不用|无需|不需要).{0,8}(?:加入|生成|出题|修改|写入|调整)|只(?:想)?(?:给|帮我|要)?(?:讲|解释|查询|查看|看看)', text):
        return CapabilityRoute('qa','qa',1,'explicit_negative_constraint',write_risk=False)
    # NB-03：延后学习（产品暂无跨天延期，交给澄清/说明，不伪造写入）。
    if re.search(r'(?:剩下|剩余|没做完|没完成|未完成).{0,12}(?:明天|改天|以后|留到)|今天先(?:做到|到这|到这里)|留到明天|明天再做|剩下的题先不做|先不做', text):
        return CapabilityRoute('qa','qa',1,'deferral_request_not_supported',write_risk=False)
    # NB-04：减少题量/时间不足（交业务层判断是否允许，冻结时由业务层拒绝）。
    if re.search(r'(?:题目|题量|任务).{0,6}(?:有点|太)?多|(?:题目|题量).{0,6}(?:减少|少)|减少.{0,6}[两二三四五\d]+道|少安排|时间(?:不够|来不及|比较紧|有点紧)|总时间不变|减少一(?:点|些)|保留(?:重点|优先级)|低优先级', text) \
            and not re.search(r'^(?:为什么|什么是|解释)', text):
        return CapabilityRoute('planner','modify',1,'explicit_workload_reduction',write_risk=False)
    # NB-11：当前题/上下文题目追问（含“这道题/上一道/接着”）不是题库库存查询。
    if re.search(r'(?:这道题|这题|这个题|上一道|上题|接着上题|刚才那道)', text) \
            and re.search(r'(?:错误|选项|怎么|如何|计算|求解|为什么|含义|问)', text) \
            and not re.search(r'(?:题库|库存|有没有|检索|找几道)', text):
        return CapabilityRoute('qa','qa',1,'current_question_followup',write_risk=False)
    # “类似/相似/同类型/同解法题”必须相对当前原题检索，优先于库存统计。
    if (re.search(r'(?:类似|相似|同类型|同题型|同解法|同考点|同知识点).{0,6}(?:的)?(?:题|练习)', text)
            and not re.search(r'生成|新编|出一道|出题|来一道', text)):
        return CapabilityRoute('data_query','similar',1,'explicit_similar_question_query')
    # 最高优先级：明确的“只做/只练/再来几道”练习指令，不能落入库存查询。
    if re.search(r'(?:今天|今日).{0,8}(?:只做|只练|就做|就练)|只(?:做|练)\s*\d{1,2}\s*道', text):
        return CapabilityRoute('planner','plan',1,'explicit_scope_plan',write_risk=False)
    if re.search(r'再来(?:几|一)道|再来几题|再加几道', text):
        return CapabilityRoute('planner','plan',1,'append_more_request',write_risk=False)
    # A user asking what the assistant can do is not asking it to perform each
    # capability mentioned in the question. Resolve this meta-level intent
    # before the lower-level planner phrases ("安排练习", "看题库", etc.).
    # Keep this structural rather than matching one complete onboarding prompt.
    capability_inquiry = bool(
        re.search(r"(?:你|奶蛙|助手).{0,12}(?:能|可以|能够).{0,8}帮我.{0,8}做什么", text)
        or re.search(r"(?:你|奶蛙|助手).{0,12}(?:支持|提供).{0,10}(?:哪些|什么).{0,8}(?:功能|能力|服务)", text)
        or re.search(r"(?:有哪些|什么).{0,8}(?:功能|能力).{0,10}(?:奶蛙|助手|你)", text)
    )
    if capability_inquiry:
        return CapabilityRoute("qa", "qa", 1, "assistant_capability_inquiry")
    # 明确的“生成一道（类似的）题/变式”必须进入 AI 出题，而不是只读查询或通用问答。
    if (re.search(r'(?:生成|出一道|出题|新编|变式|再来一道|编一道)', text)
            and (re.search(r'题', text) or re.search(r'加入|放进|加到', text) or re.search(r'(?:让我|给我)?看看', text))
            and not re.search(r'计划|方案|专项训练|出题卡|题库|检索|找(?:一|几)?道', text)):
        return CapabilityRoute('generation','generate',1,'explicit_generation_request',write_risk=True)
    # 口语检索：“查一下/查查 … 的题”是只读题库检索。
    if re.search(r'(?:查(?:一下|查|询)|搜一下|搜搜).{0,14}(?:题|习题|练习)', text) and not re.search(r'生成|出题|查题库', text):
        return CapabilityRoute('data_query','find',1,'explicit_read_only_bank_query',write_risk=False)
    # 只读题库查询优先于“选题并加入计划”：用户说“找/看看”时先给真实库存，
    # 只有明确加入/安排/生成时才进入 planner。
    from backend.services.assistant_data_queries import classify_read_only_data_query
    read_only_query=classify_read_only_data_query(text)
    if read_only_query in {'find','inventory'} and not re.search(
            r'加入|追加|加到|安排|放进|放到|生成.{0,6}(?:卷|计划)|创建.{0,6}(?:计划|专项)', text):
        return CapabilityRoute('data_query',read_only_query,1,'explicit_read_only_bank_query',write_risk=False)
    # “生成/变式 + 类似题 + 加入今日卷”是 AI 生成后追加，不是题库选题确认。
    if (re.search(r'(?:生成|出一道|出题|新编|变式|再来一道|编一道)', text)
            and re.search(r'类似|相似|同类|同类型|变式|新题', text)
            and not re.search(r'题库|库存|检索|找.{0,4}题', text)):
        return CapabilityRoute('generation','generate',1,'explicit_variant_then_append',write_risk=True)
    from backend.services.bank_selection_intent import bank_selection_request
    explicit_bank = bank_selection_request(text)
    if explicit_bank and explicit_bank.get('bank_source'):
        selection_only=bool(re.search(r'找|检索|查询|查找|拿|选',text)) and not re.search(r'加入|追加|加到|安排|放.{0,10}(?:卷|计划)|生成.{0,6}(?:卷|计划)',text)
        if _advice_only_request(text) or selection_only:
            return CapabilityRoute('data_query','find',1,'explicit_read_only_bank_selection',write_risk=False,
                explanation_request=_explanation_request(text))
        return CapabilityRoute('planner','plan',1,'explicit_bank_selection',write_risk=False,
            explanation_request=_explanation_request(text))
    from backend.services.assistant_scope_resolution import correction_target, draft_revision
    if correction_target(text):
        return CapabilityRoute('data_query','scope_correction',1,'explicit_scope_correction')
    if draft_revision(text):
        return CapabilityRoute('planner','plan',1,'active_draft_refinement',write_risk=False)
    from backend.services.learner_self_report import evidence_attribution_request, extract_self_reports
    from backend.services.assistant_data_queries import wrong_question_list_request
    if wrong_question_list_request(text):
        return CapabilityRoute('data_query','history',1,'same_scope_wrong_question_list')
    # These read/selection intents must win over generic inventory and planner
    # wording below. The routing contract is about the requested data/action,
    # not whether the sentence happens to contain "题" or "安排".
    if (re.search(r'(?:独立|自己).{0,8}(?:答对|做对|答错|做错)|(?:答对|做对|答错|做错).{0,12}(?:几道|多少|几次)', text)
            and re.search(r'(?:几道|多少|几次|统计|分别|数量)', text)
            and re.search(r'(?:辅助|提示|解析|错误|答对|做对|答错|做错|独立|正确)', text)):
        return CapabilityRoute('data_query', 'learning_state', 1, 'attempt_statistics')
    if re.search(r'(?:我)?今天.{0,10}(?:学得|学习情况|学了多少|完成得怎么样|学习总结)', text):
        return CapabilityRoute('data_query', 'today_summary', 1, 'today_learning_and_next_step')
    add_recent_wrong = bool(re.search(
        r'(?:刚才|刚刚|上一个|最近).{0,12}(?:错题|答错的题|做错的题).{0,12}(?:加入|加到|放进)|'
        r'(?:加入|加到|放进).{0,12}(?:刚才|刚刚|最近).{0,8}(?:错题|答错的题)', text))
    if add_recent_wrong:
        # Creating a formal preview is only safe when the current request carries
        # a specific submitted attempt. A fresh chat cannot resolve “刚才那题”
        # from another session; keep it read-only and ask for a same-session ref.
        if context.attempt_id or context.practice_item_id:
            return CapabilityRoute('planner', 'plan', 1, 'add_recent_wrong_item', write_risk=False)
        return CapabilityRoute('data_query', 'recent_wrong_item', 1, 'add_recent_wrong_item_needs_context')
    self_reports = extract_self_reports(text)
    if self_reports and re.search(r'(?:能|可以|是否|能不能).{0,8}(?:确认|判断).{0,8}(?:掌握|会不会)|(?:确认|判断).{0,8}(?:我|你).{0,8}(?:掌握|会)', text):
        return CapabilityRoute('data_query', 'evidence_basis', 1, 'mastery_claim_requires_objective_evidence')
    # An unnamed or unresolvable knowledge scope must be clarified rather than
    # silently replaced by a current-page lesson or a canned teaching sample.
    if re.search(r'(?:一个|某个|某项).{0,12}知识点', text) and re.search(r'(?:题库里没有|库里没有|找不到|不存在)', text):
        return CapabilityRoute('data_query', 'scope_clarification', 1, 'unresolved_knowledge_scope')
    if re.search(r'(?:再给|再来|换).{0,10}(?:一道|一个).{0,10}(?:同类|相关|相似|题|练习)', text):
        return CapabilityRoute('data_query', 'find', 1, 'same_scope_question_followup')
    if re.search(r'全局|全库',text) and re.search(r'知识点|单独|洛必达|正确率|统计|数字',text):
        return CapabilityRoute('data_query','learning_state',1,'comparison_of_learning_scopes')
    if re.search(r'(?:刚才|之前|上次).{0,8}(?:讨论|聊|说).{0,8}(?:什么|内容)',text):
        return CapabilityRoute('data_query','conversation_topic',1,'same_conversation_history')
    if re.search(r'如果|假如',text) and re.search(r'没有.{0,12}(?:题|库存)',text) and re.search(r'原因|选择|安排|怎么办',text):
        return CapabilityRoute('data_query','inventory_alternatives',1,'inventory_condition_and_alternatives')
    if (task and task.get('status') in {'ready','needs_info','failed'} and not task.get('committed')
            and re.search(r'\d+\s*(?:分钟|分|小时|h)',text)
            and re.search(r'(?:只剩|现在只有|改成|压缩|保留|推迟|调整|优先|最重要)',text)):
        return CapabilityRoute('planner','plan',1,'active_draft_refinement',write_risk=False)
    # Questions about the basis of a prior weakness judgment are read-only
    # evidence queries, even when the learner ends with "调整" or "新信息".
    if evidence_attribution_request(text):
        return CapabilityRoute('data_query', 'evidence_basis', 1, 'learning_evidence_attribution')
    # A request for an artifact is separate from consent to commit it. Ignore
    # only negative write clauses when deciding what the learner wants to see.
    # “今天只做X / 只做N道X”是组卷范围，不是库存查询。
    if re.search(r'(?:今天|今日).{0,8}(?:只做|只练|就做|就练)|只(?:做|练)\s*\d{1,2}\s*道', text):
        return CapabilityRoute('planner','plan',1,'explicit_scope_plan',write_risk=False)
    # “再来几道X”是追加/新预览，不是库存统计。
    if re.search(r'再来(?:几|一)道|再来几题|再加几道', text):
        return CapabilityRoute('planner','plan',1,'append_more_request',write_risk=False)
    # 计划约束修改（题量锁定/复盘缩短）属于规划调整。
    if re.search(r'题量.{0,8}(?:不要增加|不增加|别增加|不变|保持不变)', text) \
            or re.search(r'复盘.{0,8}(?:缩短|减少)', text):
        return CapabilityRoute('planner','plan',1,'plan_constraint_refine',write_risk=False)
    # “只练洛必达法则，60分钟/5道”是明确的组卷范围+预算，进入规划而非通用问答。
    if (re.search(r'(?:只练|只做|就练|就做|给我安排|帮我安排).{0,24}(?:\d{1,3}\s*分钟|\d{1,2}\s*道|几道)', text)
            and not re.search(r'多少|库存|有没有|还剩|还差', text)):
        return CapabilityRoute('planner','plan',1,'explicit_scope_and_budget',write_risk=False)
    positive_schedule_text='；'.join(part for part in re.split(r'[，,。；;！？?\n]',text)
        if not re.search(r'(?:不要|不需要|先不|暂不|先别|别|不).{0,12}(?:创建|加入|追加|写入)',part))
    schedule = (re.search(r'安排|压缩|调整|复习建议|规划|(?:复习|学习)计划',positive_schedule_text) and
        re.search(r'复习|学习|分钟|小时|薄弱|新信息',positive_schedule_text))
    advice_request = bool(re.search(r'(?:复习|学习|练习).{0,8}(?:建议|推荐)|(?:建议|推荐).{0,8}(?:复习|学习|练习)',text))
    explicit_schedule_action = bool(re.search(r'安排|(?:复习|学习)计划|创建计划|正式计划|加入今日|执行(?:这个|该)?(?:安排|计划)?',positive_schedule_text))
    if schedule and advice_request and not re.search(r'计划|方案|草案|预览',positive_schedule_text):
        return CapabilityRoute('planner','recommend',1,'explicit_learning_advice',write_risk=False)
    question_selection_request = bool(re.search(
        r'(?:安排|加入|补).{0,12}(?:一道|几道|几(?:道)?|一些|若干|[一二两三四五六七八九十\d]+道).{0,8}(?:练习|题)|安排.{0,16}练习', text))
    if schedule and (not _advice_only_request(text) or explicit_schedule_action) and not question_selection_request and not re.search(r'找.{0,8}题|出.{0,8}题|题库|加入|换一',positive_schedule_text):
        return CapabilityRoute('planner','plan',1,'study_activity_schedule',write_risk=False)
    if extract_self_reports(text) and not re.search(r'安排|计划|出.{0,8}题|生成|讲解|解释|找.{0,8}题', text):
        return CapabilityRoute('data_query', 'self_report', 1, 'student_self_report')
    if re.search(r'(?:只想|只要|只|这次).{0,10}(?:看|查).{0,8}题库',text) and re.search(r'不要.{0,6}(?:创建|安排|计划)',text):
        return CapabilityRoute('data_query','find',1,'explicit_read_only_business_data_query')
    if re.search(r'换一(?:道|个)|换道',text) and not re.search(r'换个知识点',text):
        return CapabilityRoute('planner','plan',1,'replace_preview',write_risk=False)
    if re.search(r'(?:刚才|上面|上一|第\s*[一二两三四五六七八九十\d]+\s*道).{0,12}(?:加入|加到|放进)|(?:加入|加到|放进).{0,12}(?:刚才|上面)',text):
        return CapabilityRoute('planner','plan',1,'select_preview',write_risk=False)
    if re.search(r'如果没有.{0,16}(?:资格|合格).{0,12}题',text) and re.search(r'只讲解',text):
        return CapabilityRoute('planner','plan',1,'explicit_bank_selection',write_risk=False,explanation_request=text)
    if re.search(r'(?:取消|撤回).{0,12}(?:安排|方案|需求)|(?:安排|方案|需求).{0,8}(?:取消|撤回)',text) and not re.search(r'换|再选|再安排',text):
        return CapabilityRoute('qa','practice_request_cancel',1,'cancel_latest_unconfirmed_request')
    # Resolve explicit bank selection + destination BEFORE standalone concept QA.
    # Clauses retain separate goals; "解释为什么不能加入" is not an operation.
    clauses=[part.strip() for part in re.split(r"[，,；;。！？?\n]|(?:同时|然后|并且|但是)|(?=但不要|但别)",text) if part.strip()]
    # Negated/past operations are not present-tense write requests. Keep the
    # original text for goals and diagnostics, but route from positive clauses.
    operation_clauses=[part for part in clauses if not re.search(
        r'(?:不要|不需要|不想|先别|先不|暂不|不再|别|不管|不(?=安排|加入|选题|生成|创建计划)).{0,16}(?:安排|加入|选题|生成|计划)',part)]
    operation_text='；'.join(operation_clauses)
    bank_plan=any(re.search(r"题库|库存",part)
        and re.search(r"拿(?:出)?|取(?:出)?|挑(?:选|出)?|选(?:出)?|找(?:出)?|检索|抽(?:取)?",part)
        and re.search(r"(?:放(?:进|入|到)|加(?:入|进|到)|安排(?:到|进)?|添(?:加|入)).{0,8}今日(?:卷|学习|试卷)",part)
        and not re.search(r"不要|不需要|不能|无法|别",part) for part in clauses)
    explanations=[part for part in clauses if re.search(r"讲解|讲讲|讲清(?:楚)?|讲明(?:白)?|先讲|解释|介绍|什么是|是什么|是怎么(?:样|回事)|怎么用|如何使用|适用条件",part)
        and not re.search(r"(?:不要|不用|无需|不必|别).{0,5}(?:讲解|解释|介绍)",part)
        and not re.search(r"^(?:为什么|为何).{0,12}(?:不能|不该|没有).{0,12}(?:安排|加入|放进)",part)]
    preview=any(not re.search(r'多少|几道|数量',part) and (
        re.search(r"(?:找|挑|选(?:择)?|拿|安排).{0,12}(?:题|练习)",part)
        or re.search(r"(?:给我看|让我看|请展示|展示给我).{0,24}(?:题|练习)",part)
        or re.search(r"题目.{0,8}(?:选好|挑好|先选)",part)
        or re.search(r'(?:找|挑|选|安排|加入)[一二两三四五六七八九十\d]+道',part)
        or re.search(r'(?:找|挑|选|安排)[一二两三四五六七八九十\d]+(?:道|个).{0,12}(?:看看|看一看)',part)) for part in operation_clauses)
    source_correction=bool(re.search(r'题库.{0,8}(?:已有|现有|原题)',text)
        and re.search(r'(?:不要|别).{0,5}生成',text))
    withheld=bool(re.search(r"先别.{0,6}(?:加|安排|选|找)|只(?:需|要)?.{0,4}(?:解释|讲)|再问我是否|问我.{0,5}(?:要不要|是否)|等我确认后再安排",text))
    # A bank preview with an explicit prohibition on plan creation has no
    # planning lifecycle. Keep both explanation and selection on read tools;
    # a later, affirmative add/confirm request can create the normal proposal.
    no_plan = bool(re.search(r'(?:不要|不需要|不必|不得|不想|不).{0,4}创建.{0,3}计划', text))
    if (no_plan and not bank_plan and (preview or source_correction)
            and re.search(r'题库|库存|预览|先看|看看', text)):
        return CapabilityRoute('data_query','find',1,'explicit_read_only_business_data_query',
            explanation_request='；'.join(explanations) or None)
    # “生成/变式 + 类似题 + 加入今日卷”是 AI 生成后追加，不是题库选题确认。
    if (re.search(r'(?:生成|出一道|出题|新编|变式|再来一道|编一道)', text)
            and re.search(r'类似|相似|同类|同类型|变式|新题', text)
            and not re.search(r'题库|库存|检索|找.{0,4}题', text)):
        return CapabilityRoute('generation','generate',1,'explicit_variant_then_append',write_risk=True)
    from backend.services.bank_selection_intent import bank_selection_request
    bank_operation = bank_selection_request(text)
    if bank_operation and (bank_operation['append'] or bank_operation['difficulty']) and not withheld:
        return CapabilityRoute('planner','plan',1,'explicit_bank_selection',write_risk=False,explanation_request=_explanation_request(text))
    if bank_plan or source_correction or (preview and not withheld):
        if preview and not bank_plan and not source_correction and not explanations and not re.search(r'安排|加入|放进|加到',operation_text):
            return CapabilityRoute('data_query','find',1,'read_only_question_preview')
        return CapabilityRoute("planner","plan",1,"explicit_bank_selection",
            write_risk=not _advice_only_request(text),explanation_request="；".join(explanations) or None)
    # “类似/相似/同类型/同解法题”是相对当前原题的检索，不是普通库存统计。
    if (re.search(r'(?:类似|相似|同类型|同题型|同解法|同考点|同知识点).{0,6}(?:的)?(?:题|练习)', text)
            and not re.search(r'生成|新编|出一道|出题|来一道', text)):
        return CapabilityRoute('data_query','similar',1,'explicit_similar_question_query')
    # Read-only source and inventory facts must be routed before the broad
    # explanation detector (which sees "是什么" in questions such as
    # "这些题的来源是什么"). The classifier excludes actual teaching and
    # plan-writing requests, so this does not turn a lesson into a bank query.
    from backend.services.assistant_data_queries import classify_read_only_data_query
    data_query = classify_read_only_data_query(text)
    if data_query:
        return CapabilityRoute("data_query", data_query, 1, "explicit_read_only_business_data_query")
    if explanations and getattr(context, "question_id", None):
        return CapabilityRoute('qa','qa',1,'current_question_explain',explanation_request='；'.join(explanations))
    if explanations and (withheld or not re.search(r'安排|计划|规划|复习建议',operation_text)):
        return CapabilityRoute('qa','qa',1,'explanation_without_selection',explanation_request='；'.join(explanations))
    # Evidence terms inside a request FOR advice are tool inputs, not a
    # standalone status query. Resolve this before the read-only query router.
    advice = (re.search(r"(?:复习|学习|练习).{0,8}(?:建议|规划)",text)
        or (_advice_only_request(text) and re.search(r"复习|学习|练习",text))
        or re.search(r"(?:继续|重新).{0,6}(?:给我|提供).{0,4}建议",text))
    if advice and not re.search(r"^(?:为什么|为何|解释|讲解|什么是|这一步|我还是不懂)",text):
        return CapabilityRoute("planner","recommend",.98,"explicit_learning_advice")
    # A retrospective learning-evidence question that asks for a next step is
    # an Agent request even when the evidence mentions a hint or solution.
    # Keep a standalone explanation/hint request on the QA path below.
    has_learning_evidence = bool(re.search(
        r"(?:学习(?:历史|记录)|作答记录|实际记录|提示后|看(?:过|了|完)?解析|独立(?:做对|答对)|先错.{0,16}后.{0,12}做对)", text))
    asks_for_next_step = bool(re.search(r"(?:推荐|安排|下一步|复习|练习|复测|学习方案)", text))
    if has_learning_evidence and asks_for_next_step:
        intent = _planner_intent(text,
            "recommend" if re.search(r"推荐|下一步", text) and not re.search(r"安排|加入", text) else "plan")
        return CapabilityRoute("planner",intent,.98,"learning_evidence_task_request",write_risk=intent=="plan")
    # Meta-explanations containing planning words are still explanations.
    if re.search(r"^(?:为什么|为何|解释|讲解|什么是|这一步|这题考什么|我还是不懂)",text) or re.search(r"(?:给我.{0,5}提示|不要告诉.*答案|思路.*对吗|为什么.*(?:毕业|安排)|哪里.*(?:错|问题))",text):
        return CapabilityRoute("qa","qa",.98,"learning_explanation")
    if re.search(r"(?:我不会|不明白|先.*(?:解释|讲)|先讲|看.*(?:证明|思路|过程))",text) and not re.search(r"(?:安排|补.{0,4}题|加入|练.{0,4}题)",text):
        return CapabilityRoute("qa","qa",.95,"concept_help_with_task" if task else "concept_help")
    existing=classify_task_intent(operation_text)
    if existing=="modify": return CapabilityRoute("planner","modify",.98,"explicit_plan_mutation",write_risk=True)
    if re.search(r"(?:根据(?:我)?今天|我今天).{0,100}(?:接下来|下一步|应该).{0,25}(?:练|学)",text):
        intent = _planner_intent(text, "plan" if re.search(r"安排|加入|给我补", text) else "recommend")
        return CapabilityRoute("planner",intent,.98,"next_step_from_today_evidence",write_risk=intent=="plan")
    explicit_inventory = bool(re.search(
        r"(?:题库|库存).{0,12}(?:多少|几道|数量|有没有|有哪些|是否有)|"
        r"(?:多少|几道|数量|有没有|是否有|有哪些).{0,12}(?:可练(?:习)?题|练习题|题目)|"
        r"哪些知识点.{0,12}(?:有题|有练习)|"
        r"(?:可以|能够|可|能)练习的题目.{0,8}(?:有哪些|多少|几道)|"
        r"(?:查询|查看|看看|列出).{0,20}(?:题库|库存)|"
        r"(?:哪些|多少|几道|数量|有没有|是否有).{0,20}(?:历年真题|原创题|真题变式|真题改编)|"
        r"(?:历年真题|原创题|真题变式|真题改编).{0,12}(?:多少|几道|数量|有哪些)|"
        r"(?:正式题|公共题).{0,15}(?:个人(?:AI|生成)?题|个人生成题).{0,8}(?:区别|区分)|"
        r"(?:题目|这些题).{0,8}(?:来源|来自哪里)", text))
    if explicit_inventory and not re.search(r"(?:安排|加入|补\s*[一二三四五六七八九十\d])",text):
        return CapabilityRoute("planner","query",.98,"inventory_question")
    if re.search(r"(?:安排|加入今日|加到.*卷|补(?:充)?\s*[一二三四五六七八九十\d]*\s*道?题|给我补|帮我.*练|今天.*(?:练|学)|继续练|练.*(?:两|三|\d)道|应该先学|推荐.*(?:练|题)|类似题|相似题)",operation_text):
        intent = _planner_intent(text,
            "recommend" if re.search(r"(?:应该先学|推荐)", text) and not re.search(r"(?:安排|加入|补)", text) else existing)
        return CapabilityRoute("planner",intent,.95,"learning_task_request",write_risk=intent in {"plan","modify"})
    if task and task.get("status") in {"ready","needs_info","failed"} and not task.get("committed") and re.search(r"^(?:少一点|多一点|只做|只要|基础一点|简单一点|不用复习|再减少)",text):
        return CapabilityRoute("planner","plan",.90,"active_draft_refinement",write_risk=True)
    # Optional bounded classifier cannot authorize apply; invalid output is ignored.
    if classifier:
        try: classified=classifier(text,context)
        except Exception: classified=None
        if classified in {"QA","PLANNER_QUERY","PLANNER_RECOMMEND","PLANNER_PLAN","PLANNER_MODIFY"}:
            if classified=="QA": return CapabilityRoute("qa","qa",.65,"bounded_classifier",fallback=True)
            intent=classified.removeprefix("PLANNER_").lower()
            return CapabilityRoute("planner",intent,.65,"bounded_classifier",fallback=True,write_risk=intent in {"plan","modify"})
    return CapabilityRoute("qa","qa",.55,"study_context_fallback" if context.question_id or context.knowledge_node_ids else "ambiguous_safe_qa",fallback=True)


def evidence_explanation(message):
    """A question about learning facts, including retrospective assistance use."""
    return bool(re.search(r"毕业|学完|独立(?:掌握|确认)|掌握(?:状态|程度)|是否.*掌握|作答记录|学习记录|证据|提示.*(?:不算|为什么)|答案.*不算", message))


def answer_reliability_question(message):
    return bool(re.search(r"(?:答案|题解).{0,24}(?:是否|是不是|可靠吗|靠谱吗|正确吗|一定(?:正确|对)吗|核验(?:过|了)?吗|(?:是)?官方.{0,8}吗)|(?:是否|是不是|有没有).{0,20}(?:答案|题解).{0,16}(?:核验|官方|可靠)",message))


def assistance_action(message, *, explicit="auto", question_present=False):
    if not question_present: return None
    if explicit!="auto": return explicit
    text=message.strip()
    # P1 证据安全：知识点毕业/掌握度/判断依据咨询属于“学习证据咨询”，
    # 不得因存在当前题就自动揭示答案或写入 qa_assistance_used。
    if re.search(r'毕业|掌握度|掌握(?:状态|程度)|(?:为什么|凭什么).{0,12}(?:没|没有|认为|判断|算|是)'
                 r'|差什么|判断依据|证据|学习记录|为什么.*(?:这么|这样)|凭什么', text) \
            and not re.search(r'(?:给|帮我|请)我?(?:讲解|讲讲)这(?:道|个)题|查看(?:这道题)?(?:的)?(?:答案|解析)|给我(?:答案|解析)', text):
        return None
    # Match a current request, not the mere mention of a hint in a concept or history.
    hint_request=re.search(r"(?:给我|给|请|帮我|能否|能不能|可以|麻烦)\s*(?:再|只)?\s*(?:给我)?\s*(?:一点|一些|个)?\s*提示(?:一下|一点|下一步|具体|[。？?]|$)|(?:^|[，,；;。])\s*(?:再|一点|只给方向[，,]?)\s*提示|不要(?:告诉|给我)?.{0,4}答案.{0,8}(?:提示|方向)|^\s*(?:一点提示|只给方向)[。？?]?$",text)
    if hint_request:
        return "hint_2" if re.search(r"具体|下一步|再.*提示|第二",text) else "hint_1"
    solution_request=re.search(r"(?:查看|请看|给我|告诉我|讲解|展示)\s*(?:这道题的|当前题的|完整|参考|正确|标准)?\s*(?:答案|解析|解答)|为什么选|标准答案是什么",text)
    if solution_request: return "solution"
    if question_present and re.search(r"为什么.{0,10}(?:这样|这么|此处|这里|这一步).{0,8}(?:算|计算|做|写)", text):
        return "solution"
    if question_present and re.search(r"(?:这|那|该)题.{0,8}(?:怎么做|如何做|怎么解|讲解|答案|解析)|这道题.{0,8}(?:怎么做|如何)", text):
        return "solution"
    if question_present and re.search(r"解释|讲讲|讲一下|详细讲|分析|不太理解|不懂|考什么|知识点|其他解法", text):
        return "solution"
    if question_present and not answer_reliability_question(text) and re.search(
            r"(?:上面|刚才|刚生成|你生成|生成的|那道|这道|这题).{0,24}(?:题|练习).{0,16}(?:怎么做|如何解|讲解|解答|答案|解析|思路|步骤)|"
            r"(?:怎么做|如何解|讲解|解答).{0,12}(?:这题|这道题|刚才那道)", text):
        return "solution"
    if evidence_explanation(text): return None
    if re.search(r"(?:看过|看了|看完|使用过|提示(?:后|以后|之后)|答案(?:后|以后|之后)|hint.*(?:后|after)|solution.*(?:后|after))",text,re.I): return None
    if re.fullmatch(r"我还是不懂[。？?]?|这题我不懂[。？?]?",text): return "hint_2"
    if re.search(r"为什么.*(?:错|答错)",message): return "process_review"
    if re.search(r"(?:这一步|证明思路|算法.*(?:对|错)|过程.*(?:对|错)|哪里.*(?:错|问题))",message): return "process_review"
    return None
