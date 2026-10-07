"""A bounded capability decision, without tool execution or write permission."""
from dataclasses import asdict, dataclass
import re
from backend.services.learning_task_tools import classify_task_intent


@dataclass(frozen=True)
class CapabilityRoute:
    capability: str
    intent: str
    confidence: float
    reason: str
    fallback: bool=False
    write_risk: bool=False

    def public_dict(self): return asdict(self)


def route_message(message, context, *, action="auto", task=None, classifier=None):
    text=message.strip()
    if action!="auto": return CapabilityRoute("qa","qa",1,"explicit_assistance_action")
    # Meta-explanations containing planning words are still explanations.
    if re.search(r"^(?:为什么|为何|解释|讲解|什么是|这一步|这题考什么|我还是不懂)",text) or re.search(r"(?:提示|不要告诉.*答案|思路.*对吗|为什么.*(?:毕业|安排)|哪里.*(?:错|问题))",text):
        return CapabilityRoute("qa","qa",.98,"learning_explanation")
    if re.search(r"(?:我不会|不明白|先.*(?:解释|讲)|先讲|看.*(?:证明|思路|过程))",text) and not re.search(r"(?:安排|补.{0,4}题|加入|练.{0,4}题)",text):
        return CapabilityRoute("qa","qa",.95,"concept_help_with_task" if task else "concept_help")
    existing=classify_task_intent(text)
    if existing=="modify": return CapabilityRoute("planner","modify",.98,"explicit_plan_mutation",write_risk=True)
    if re.search(r"(?:根据(?:我)?今天|我今天).{0,100}(?:接下来|下一步|应该).{0,25}(?:练|学)",text):
        intent="plan" if re.search(r"安排|加入|给我补",text) else "recommend"
        return CapabilityRoute("planner",intent,.98,"next_step_from_today_evidence",write_risk=intent=="plan")
    if re.search(r"(?:哪些|多少|有没有|是否有|有.*章节|库存|题库里)",text) and re.search(r"(?:题|知识点|章节|练习)",text) and not re.search(r"(?:安排|加入|补\d)",text):
        return CapabilityRoute("planner","query",.98,"inventory_question")
    if re.search(r"(?:安排|加入今日|加到.*卷|补(?:充)?\s*[一二三四五六七八九十\d]*\s*道?题|给我补|帮我.*练|今天.*(?:练|学)|继续练|练.*(?:两|三|\d)道|应该先学|推荐.*(?:练|题)|类似题|相似题)",text):
        intent="recommend" if re.search(r"(?:应该先学|推荐)",text) and not re.search(r"(?:安排|加入|补)",text) else existing
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
    # Match a current request, not the mere mention of a hint in a concept or history.
    hint_request=re.search(r"(?:给我|给|请|帮我|能否|能不能|可以|麻烦)\s*(?:再|只)?\s*(?:给我)?\s*(?:一点|一些|个)?\s*提示(?:一下|一点|下一步|具体|[。？?]|$)|(?:^|[，,；;。])\s*(?:再|一点|只给方向[，,]?)\s*提示|不要(?:告诉|给我)?.{0,4}答案.{0,8}(?:提示|方向)|^\s*(?:一点提示|只给方向)[。？?]?$",text)
    if hint_request:
        return "hint_2" if re.search(r"具体|下一步|再.*提示|第二",text) else "hint_1"
    solution_request=re.search(r"(?:查看|请看|给我|告诉我|讲解|展示)\s*(?:这道题的|当前题的|完整|参考|正确|标准)?\s*(?:答案|解析|解答)|为什么选|标准答案是什么",text)
    if solution_request: return "solution"
    if evidence_explanation(text): return None
    if re.search(r"(?:看过|看了|看完|使用过|提示(?:后|以后|之后)|答案(?:后|以后|之后)|hint.*(?:后|after)|solution.*(?:后|after))",text,re.I): return None
    if re.fullmatch(r"我还是不懂[。？?]?|这题我不懂[。？?]?",text): return "hint_2"
    if re.search(r"为什么.*(?:错|答错)",message): return "process_review"
    if re.search(r"(?:这一步|证明思路|算法.*(?:对|错)|过程.*(?:对|错)|哪里.*(?:错|问题))",message): return "process_review"
    return None
