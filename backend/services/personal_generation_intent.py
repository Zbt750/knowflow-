"""Deterministic explicit-generation gate; ordinary practice never pays for new questions."""
import re
from backend.schemas.personal_questions import PersonalGenerationRequest, GenerationTarget, DEFAULT_GENERATION_COUNT
from backend.models.learning import KnowledgePoint, Question
from backend.errors import AppError
from sqlalchemy import select
from backend.services.generation_difficulty import normalize_requirement,legacy_difficulty,gradient_requested

NUMERAL = r"([一二两三四五六七八九]?十[一二三四五六七八九]?|[一二两三四五六七八九]|\d+)"


def _legacy_explicitly_generate(message):
    if re.search(r"不要|不用|别|不需要", message): return False
    if re.search(r"(?:出题|生成题|生题).{0,12}(?:功能|流程|怎么用|如何用|是什么意思)|(?:介绍|解释|什么是).{0,12}(?:出题|生题)", message): return False
    if re.search(r"生成.{0,12}(?:练习卷|试卷|卷子|学习计划)", message) and not re.search(r"新题|出题|[一二两三四五\d]+道", message): return False
    if not re.search(r"帮我|给我|请|我要|我想|奶蛙|^(?:生成|出|编)", message.strip()): return False
    return bool(re.search(r"(?:生成|出|编)(?:新)?\s*(?:[一二两三四五六七八九十\d]+\s*道)?[^。？！\n]{0,30}(?:题|练习)", message))


def explicitly_generate(message):
    text = message.strip()
    # A positive existing-bank source is authoritative over vague “来一道类似题”.
    # Explicit new authoring remains on the generation path.
    from backend.services.bank_selection_intent import bank_selection_request
    bank = bank_selection_request(text)
    if bank and bank.get('bank_source'):
        return False
    # Negation applies to the generation action itself, not unrelated parts of
    # the sentence (for example, "不自动出新题").
    # Do not treat positive feedback such as “这道题不错，帮我生成……” as
    # a negation. Bare “不” may only negate the action when it is adjacent;
    # explicit phrases such as “不要自动生成” retain a small modifier gap.
    if re.search(r"(?:不要|不用|不需要|不想|不许|不准|别|无需)(?:[^，,。！？;；\n]{0,6})?(?:自动)?(?:生成|出题|出\s*(?:新)?题|编写题|新编)|"
                 r"不(?:自动)?(?:生成|出题|出\s*(?:新)?题|编写题|新编)", text):
        return False
    if re.search(r'(?:解释|介绍|什么是).{0,12}新编.{0,8}(?:功能|意思|是什么)|新编题.{0,8}(?:功能|是什么意思)',text):
        return False
    if re.search(r'新编|生成.{0,8}(?:新的|新题)|不用查.{0,8}题库.{0,8}直接出题',text):
        return True
    # “生成一道类似的我看看/再生成一道同类型的”也是明确生成请求（排除找题/查题库）。
    if (re.search(r'(?:生成|出|编|来).{0,6}(?:类似|相似|同类|同类型)', text)
            and not re.search(r'找|查|题库|检索', text)):
        return True
    # “给我生成一道让我加入今日学习”也是生成请求（生成后走个人练习追加）。
    if (re.search(r'(?:生成|出|编).{0,10}(?:加入|放进|加到)\s*(?:今日|今天)', text)
            and not re.search(r'题库|检索', text)):
        return True
    # “给我出一道隐函数求导题”也是明确的生成请求（排除找题/查题库）。
    if (re.search(r'(?:给我|帮我|请)?出(?:一|两|几)?道.{2,20}题', text)
            and not re.search(r'找|查|题库|练习|加入', text)):
        return True
    if re.search(r"(?:出题|生成题|生题|(?:生成|出)\s*(?:[一二两三四五六七八九十\d]+\s*道)?\s*(?:新题|练习题|题目|题)).{0,12}(?:功能|流程|怎么用|如何用|是什么意思)|(?:介绍|解释|什么是).{0,12}(?:出题|生题)", text):
        return False
    if re.search(r"生成.{0,12}(?:练习卷|试卷|卷子|学习计划)", text) and not re.search(r"新题|出题|[一二两三四五\d]+道", text):
        return False
    # Asking for an answer/solution is not a generation request, but answer
    # quality constraints often accompany a real generation request (for
    # example, “出一道题，答案与解析一致”). Evaluate the clause that requests
    # the action so a later consistency requirement cannot cancel the earlier
    # explicit request to create a question.
    clauses = re.split(r"[。？！\n，,；;]", text)
    explicit_question_generation = any(re.search(
        r"(?:生成|出|编写)(?:一道|几道|新)?[^。？！\n]{0,35}(?:新题|练习题|变式题|题目|类似题|同类题|题)",
        clause,
    ) for clause in clauses)
    solution_only_request = any(re.search(
        r"(?:生成|写出|给出).{0,20}(?:解答|答案|解析|证明过程|解题步骤)", clause)
        for clause in clauses)
    answer_for_existing_question = any(
        re.search(r"(?:生成|写出|给出).{0,16}(?:这|该|本|原)(?:道)?题.{0,8}(?:解答|答案|解析|证明过程|解题步骤)", clause)
        and not re.search(r"新题|变式题|类似题|同类题|练习题", clause)
        for clause in clauses
    )
    if solution_only_request and (not explicit_question_generation or answer_for_existing_question):
        return False
    # Classify the requested action and its object, not a polite prefix. A
    # follow-up such as “这题我会了，换一道更有挑战性的” is still an explicit action.
    for clause in re.split(r"[。？！\n，,；;]", text):
        # “你刚生成的题怎么做/讲解一下” refers to an existing artifact;
        # the generation verb is descriptive, not a request to generate again.
        # Keep this clause-local so a separate request such as “再出一道” in
        # the same message still takes the generation path.
        if (re.search(r"(?:上面|刚才|刚生成|你(?:刚才)?生成的|生成的).{0,12}(?:题|练习).{0,12}(?:怎么做|如何解|讲解|解释|答案|解析|思路|步骤)", clause)
                and not re.search(r"(?:再|重新|另|换|继续)?(?:生成|出|编写)\s*(?:一道|一题|新题|练习题|变式题)|再来\s*(?:一道|一题)", clause)):
            continue
        if re.search(r"(?:解释|讲解|分析|检查|解答|求解).{0,15}(?:生成|出题).{0,6}(?:过程|原因|方法)", clause):
            continue
        if re.search(r"(?:生成|出|编写)(?:一道|几道|新)?[^。？！\n]{0,35}(?:新题|练习题|变式题|题目|类似题|同类题|题)", clause):
            return True
        if re.search(r'(?:再来|再出|另出|换|再给我|来)\s*'+NUMERAL+r'\s*题',clause):
            return True
        if re.search(r'(?:再来|再出|另出|换|再给我|来)\s*'+NUMERAL+r'\s*道\s*$',clause):
            return True
        if re.search(r'(?:给我|帮我)?(?:出|再来|再出|换)\s*(?:一|1)?个[^。？！\n]{0,12}(?:更难|更简单|更综合|难一点|挑战|类似|同类型)',clause):
            return True
        if re.search(r"(?:再来|再出|另出|换|再给我|来)\s*(?:[一二两三四五六七八九十\d]+\s*道|几道)[^。？！\n]{0,25}(?:同类|同类型|类似|难|挑战|练习|综合)", clause):
            return True
    return False


def number(value):
    if value.isdigit(): return int(value)
    digits={"一":1,"二":2,"两":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9}
    if "十" in value:
        left,right=value.split("十",1)
        return digits.get(left,1)*10+digits.get(right,0)
    return digits[value]


def _preferences(message):
    difficulty = legacy_difficulty(normalize_requirement(message))
    type_names = {"选择题": "single_choice", "单选题": "single_choice", "填空题": "fill_blank",
        "计算题": "calculation", "证明题": "proof", "大题": "calculation",
        "讨论题": "subjective", "程序题": "subjective", "算法题": "subjective"}
    # Resolve fields from the latest explicit amendment, not the first number
    # in a concatenated old request. The pasted original is data, not a count.
    parts=[re.split(r'(?:原题|参考题|题目正文)\s*[:：]',part,1)[0]
           for part in message.split('\n最新出题要求：')]
    quantity_source=None; quantity_part=-1
    for i,part in enumerate(parts):
        actions=list(re.finditer(r'生成|出(?=[一二两三四五六七八九十\d几题])|再来|再给我|换(?=[一二两三四五\d])',part))
        scope=part[actions[-1].start():] if actions else part
        if re.search(r'[百千万]\s*(?:道|题)',scope): raise AppError('validation_failed',status_code=422)
        if re.search(NUMERAL+r'\s*(?:道|题)',scope):quantity_source=scope;quantity_part=i
    type_source=next((p for p in reversed(parts) if any(name in p for name in type_names)),parts[-1])
    requested_type=next((kind for name,kind in type_names.items() if name in type_source),
        'proof' if '证明' in type_source else 'fill_blank' if '填空' in type_source else 'single_choice')
    types=[]
    if quantity_source:
        types=[(type_names[m[2]],number(m[1])) for m in re.finditer(NUMERAL+r'\s*道\s*(选择题|单选题|填空题|计算题|证明题|大题|讨论题|程序题|算法题)',quantity_source)]
        match=re.search(NUMERAL+r'\s*(?:道|题)',quantity_source)
        if not types:types=[(requested_type,number(match[1]))]
        # A later “改成证明题” changes type, not the retained quantity.
        if any(any(name in p for name in type_names) for p in parts[quantity_part+1:]):
            types=[(requested_type,sum(count for _,count in types))]
    else:types=[(requested_type,3 if gradient_requested(message) else DEFAULT_GENERATION_COUNT)]
    if sum(c for _, c in types) > 5 or any(c < 1 for _, c in types): raise AppError("validation_failed", status_code=422)
    return difficulty, types


def requested_generation_topic(message):
    qualified = re.search(r'(?:针对|根据|关于)\s*([^，,。！？\n]{2,35}?)(?:生成|出\s*(?:[一二两三四五六七八九十\d]+\s*道)?)', message)
    if qualified:
        return qualified[1].strip()
    match = re.search(r'(?:出|生成|编写)(?:\s*[一二两三四五六七八九十\d]+\s*道)?\s*([^，,。！？\n]{2,35}?)(?:诊断题|练习题|选择题|单选题|计算题|证明题|填空题|讨论题|程序题|算法题|题目|题)', message)
    if not match:
        return None
    topic = re.sub(r'^(?:关于|有关|一道|两道)', '', match[1]).strip()
    topic = re.sub(r'(?:的|相关|方面|知识点)$', '', topic).strip()
    if re.fullmatch(r'(?:比(?:这|那|原)(?:个|道)?(?:题)?(?:还)?更(?:难|简单|容易)|更难|难一点|容易一点|再难一点|一样难)', topic):
        return None
    return None if re.fullmatch(r'新|类似|同类|变式|计算|证明|单选|选择|诊断|练习|[一二两三四五六七八九十\d]+道?|稍难.{0,5}|基础.{0,5}', topic) else topic or None


_QUESTION_TYPE_NAMES = {
    "选择题": "single_choice", "单选题": "single_choice", "填空题": "fill_blank",
    "计算题": "calculation", "证明题": "proof", "大题": "calculation",
    "讨论题": "subjective", "程序题": "subjective", "算法题": "subjective",
}


def _node_phrases(node):
    """Return deliberately narrow human-readable aliases for one real node."""
    phrases = {node.name.strip()} if getattr(node, "name", None) else set()
    name = getattr(node, "name", "") or ""
    short = re.sub(r"(?:求导|法则|性质|应用|结构|定理|公式|方法)$", "", name).strip()
    if len(short) >= 2 and short != name:
        phrases.add(short)
    integral_topic = re.sub(r'积分$', '', name).strip()
    if len(integral_topic) >= 3 and integral_topic != name:
        phrases.add(integral_topic)
    topic = name.split('的', 1)[0].strip()
    if '的' in name and len(topic) >= 4:
        phrases.add(topic)
    from backend.services.question_generation import FAMILY_NODES
    code = getattr(node, "code", None)
    for aliases in FAMILY_NODES.values():
        if any(alias in name for alias in aliases):
            phrases.update(alias for alias in aliases if len(alias) >= 2)
    return {phrase for phrase in phrases if len(phrase) >= 2}


def _explicit_node_mentions(message, nodes):
    mentions = []
    for node in nodes:
        for phrase in _node_phrases(node):
            for match in re.finditer(re.escape(phrase), message):
                mentions.append((match.start(), match.end(), len(phrase), phrase == node.name, node))
    # Prefer the most specific real node name over a shorter alias at the same
    # text span; keep overlapping distinct spans only when they do not refer to
    # the same words. Ambiguous aliases are surfaced to the caller.
    selected = []
    spans = sorted({(item[0], item[1]) for item in mentions}, key=lambda span: (span[0], -(span[1]-span[0])))
    for start, end in spans:
        candidates = [item for item in mentions if item[0] == start and item[1] == end]
        rank = max((item[2], int(item[3])) for item in candidates)
        best = [item for item in candidates if (item[2], int(item[3])) == rank]
        if len({item[4].id for item in best}) > 1:
            raise AppError("personal_generation_scope_required", status_code=422)
        item = best[0]
        if any(item[0] < old[1] and old[0] < item[1] for old in selected):
            continue
        selected.append(item)
    selected.sort(key=lambda row: (row[0], row[1]))
    return selected


def _count_in_prefix(text):
    found = list(re.finditer(NUMERAL + r"\s*(?:道|题)", text))
    return number(found[-1].group(1)) if found else None


def _question_type_for_text(text, fallback):
    matches = {kind for phrase, kind in _QUESTION_TYPE_NAMES.items() if phrase in text}
    return next(iter(matches)) if len(matches) == 1 else fallback if not matches else None


def _difficulty_for_text(text, fallback):
    requirement = normalize_requirement(text)
    if not requirement.absolute_explicit:
        return fallback
    return {"basic": "basic", "medium": "improved", "hard": "improved", "challenge": "comprehensive"}[requirement.target_level]


def _named_multi_targets(message, nodes, fallback_type, fallback_difficulty):
    mentions = _explicit_node_mentions(message, nodes)
    distinct = {item[4].id for item in mentions}
    if len(distinct) < 2:
        return None
    clauses = re.split(r"[，,、；;。！？\n]+", message)
    target_rows = []
    for clause in clauses:
        local = [item for item in mentions if clause.find(message[item[0]:item[1]]) >= 0
                 and item[0] >= message.find(clause) and item[1] <= message.find(clause) + len(clause)]
        if not local:
            continue
        local_nodes = []
        for item in local:
            if not local_nodes or local_nodes[-1][4].id != item[4].id:
                local_nodes.append(item)
        each = bool(re.search(r"各|每个|每一|分别", clause))
        shared_count = _count_in_prefix(clause)
        if each and shared_count is None:
            shared_count = _count_in_prefix(message)
        if len(local_nodes) > 1 and not each:
            # A compound clause with multiple topics is only safe when each
            # topic has its own immediately preceding count.
            counts = []
            previous_end = 0
            for item in local_nodes:
                counts.append(_count_in_prefix(clause[previous_end:item[0] - message.find(clause)]))
                previous_end = item[1] - message.find(clause)
            if any(value is None for value in counts):
                return None
        else:
            counts = [shared_count] * len(local_nodes) if each else []
            if not each:
                start_at = message.find(clause)
                previous_end = 0
                for item in local_nodes:
                    relative_start = item[0] - start_at
                    counts.append(_count_in_prefix(clause[previous_end:relative_start]))
                    previous_end = item[1] - start_at
                if len(local_nodes) == 1 and counts[0] is None:
                    counts[0] = 1
        if any(value is None or value < 1 for value in counts):
            return None
        start_at = message.find(clause)
        for item, count in zip(local_nodes, counts):
            relative_start = item[0] - start_at
            relative_end = item[1] - start_at
            # The topic-local segment controls type/difficulty where stated;
            # a single global preference remains valid as a fallback.
            right = next((other[0] - start_at for other in local_nodes if other[0] > item[0]), len(clause))
            local_text = clause[max(0, relative_start - 14):right]
            kind = _question_type_for_text(local_text, _question_type_for_text(message, fallback_type))
            if kind is None:
                return None
            level = _difficulty_for_text(local_text, _difficulty_for_text(message, fallback_difficulty))
            target_rows.append(GenerationTarget(kp_id=item[4].id, question_type=kind, count=count, difficulty=level))
    if len({target.kp_id for target in target_rows}) < 2:
        return None
    if sum(target.count for target in target_rows) > 5:
        raise AppError("validation_failed", status_code=422)
    return target_rows


def _difficulty_bucket_targets(message, nodes, context_ids, fallback_type):
    pattern = NUMERAL + r"\s*(?:道|题)?\s*(基础|入门|简单|容易|中等|适中|中级|困难|较难|高难|挑战|综合)(?:的)?(?:练习|题目|题)?"
    groups = list(re.finditer(pattern, message))
    if len(groups) < 2:
        return None
    mentions = _explicit_node_mentions(message, nodes)
    explicit = list({item[4].id: item[4] for item in mentions}.values())
    scope = explicit if explicit else [node for node in nodes if node.id in context_ids]
    if len(scope) != 1:
        return None
    level_map = {"基础": "basic", "入门": "basic", "简单": "basic", "容易": "basic",
        "中等": "improved", "适中": "improved", "中级": "improved", "困难": "comprehensive",
        "较难": "comprehensive", "高难": "comprehensive", "挑战": "comprehensive", "综合": "comprehensive"}
    targets = [GenerationTarget(kp_id=scope[0].id, question_type=fallback_type,
        count=number(group.group(1)), difficulty=level_map[group.group(2)]) for group in groups]
    if sum(target.count for target in targets) > 5:
        raise AppError("validation_failed", status_code=422)
    return targets


def _context_each_targets(message, nodes, context_ids, fallback_type, fallback_difficulty):
    """Expand an explicit each-node request only over validated current scope."""
    if not re.search(r"(?:每个|各个|各)(?:知识点|节点)", message):
        return None
    count = _count_in_prefix(message)
    if count is None:
        raise AppError("personal_generation_scope_required", status_code=422)
    in_scope = [node for node in nodes if node.id in context_ids]
    unique = list({node.id: node for node in in_scope}.values())
    if len(unique) < 2:
        raise AppError("personal_generation_scope_required", status_code=422)
    kind = _question_type_for_text(message, fallback_type)
    if kind is None:
        raise AppError("personal_generation_scope_required", status_code=422)
    level = _difficulty_for_text(message, fallback_difficulty)
    targets = [GenerationTarget(kp_id=node.id, question_type=kind, count=count, difficulty=level)
        for node in unique]
    if sum(target.count for target in targets) > 5:
        raise AppError("validation_failed", status_code=422)
    return targets


def generation_intent(db, message, ctx, request_key, *, generation_mode="ai_generated", confirmed_kp_id=None,
                      confirmed_targets=None):
    difficulty, types = _preferences(message)
    nodes = list(db.scalars(select(KnowledgePoint).where(KnowledgePoint.is_active.is_(True), KnowledgePoint.is_assessable.is_(True))))
    mentions = _explicit_node_mentions(message, nodes)
    matches = list({item[4].id: item[4] for item in mentions}.values())
    matched_ids = {node.id for node in matches}
    matches.extend(node for node in nodes if node.code in message and node.id not in matched_ids)
    if not matches:
        from backend.services.question_generation import FAMILY_NODES
        terms = {t for values in FAMILY_NODES.values() for t in values if t in message}
        matches = [n for n in nodes if any(t in n.name for t in terms)]
        contextual = [n for n in matches if n.id in ctx.knowledge_node_ids]
        if contextual: matches = contextual
    # Avoid substring-derived unrelated scope; ambiguous requests require clarification.
    context_each_request = bool(re.search(r"(?:每个|各个|各)(?:知识点|节点)", message))
    if (not matches and requested_generation_topic(message) and confirmed_kp_id is None
            and confirmed_targets is None and not context_each_request):
        raise AppError("personal_generation_scope_required", status_code=422)
    if not matches: matches = [n for n in nodes if n.id in ctx.knowledge_node_ids]
    if not matches and ctx.question_id:
        q = db.get(Question, ctx.question_id)
        matches = [n for n in nodes if q and n.id == q.kp_id]
    if confirmed_targets is not None:
        targets = [GenerationTarget.model_validate(item) for item in confirmed_targets]
        allowed = {n.id for n in nodes if n.is_active and n.is_assessable}
        if (not targets or any(target.kp_id not in allowed for target in targets)
                or sum(target.count for target in targets) > 5):
            raise AppError("personal_generation_confirmation_invalid", status_code=409)
        matches = []
    else:
        targets = None
        if confirmed_kp_id is None and not _explicit_node_mentions(message, nodes):
            targets = _context_each_targets(message, nodes, ctx.knowledge_node_ids, types[0][0], difficulty)
        if targets is None and confirmed_kp_id is None:
            targets = _named_multi_targets(message, nodes, types[0][0], difficulty)
        if targets is None:
            targets = _difficulty_bucket_targets(message, nodes, ctx.knowledge_node_ids, types[0][0]) if confirmed_kp_id is None else None
    if confirmed_kp_id is not None:
        # 用户在确认卡中选择的规范节点具有优先级；不再暗中沿用当前练习节点。
        matches = [n for n in nodes if n.id == confirmed_kp_id]
    if targets is None:
        if len(matches) != 1: raise AppError("personal_generation_scope_required", status_code=422)
        targets=[GenerationTarget(kp_id=matches[0].id, question_type=t, count=c, difficulty=difficulty) for t,c in types]
    if confirmed_targets is None and gradient_requested(message):
        total=sum(t.count for t in targets)
        if total<2:raise AppError('validation_failed',status_code=422)
        slots=[target for target in targets for _ in range(target.count)]
        levels=['basic','improved','comprehensive']
        targets=[target.model_copy(update={'count':1,'difficulty':levels[round(i*2/(total-1))]}) for i,target in enumerate(slots)]
    return PersonalGenerationRequest(request_key=request_key, generation_mode=generation_mode,
        user_requirement=message,
        difficulty_requirement=normalize_requirement(message),
        targets=targets,
        surface=ctx.surface if ctx.surface in {"study","chat","knowledge"} else "chat", plan_id=ctx.daily_plan_id,
        # Initial generation always saves a Question only. Adding it to a
        # DailyPlan is a separate, explicit user action after preview.
        append_to_today=False,
        reference_question_id=ctx.question_id if re.search(r"类似|相似|同类|这(?:道)?题|这道|变式|原题",message) else None)


def generation_confirmation(db, message, ctx, request_key, *, generation_mode="ai_generated", preferred_kp_id=None):
    """所有有效可考核节点均可AI出题；确认本身不调用模型、不预留费用。"""
    from backend.services.personal_question_families import resolve_family, supports_difficulty
    difficulty, types = _preferences(message)
    nodes = list(db.scalars(select(KnowledgePoint).where(KnowledgePoint.is_active.is_(True),
        KnowledgePoint.is_assessable.is_(True)).order_by(KnowledgePoint.subject, KnowledgePoint.name)))
    options = []
    parents = set(db.scalars(select(KnowledgePoint.parent_id).where(
        KnowledgePoint.is_active.is_(True), KnowledgePoint.parent_id.is_not(None))))
    for node in nodes:
        if node.id in parents: continue
        spec = resolve_family(node.code)
        if generation_mode == "ai_generated" or (
                spec and all(t in spec.question_types for t, _ in types) and supports_difficulty(spec, difficulty)):
            options.append({"kp_id": str(node.id), "name": node.name, "code": node.code,
                "question_types": ["single_choice", "fill_blank", "calculation", "proof", "subjective"]
                    if generation_mode == "ai_generated" else list(spec.question_types)})
    selected = None
    current = None
    proposed_targets = None
    proposed = None
    # 明确基于原题生成时，原题知识点优先且默认选中，不把无关节点排首位。
    if preferred_kp_id is not None:
        preferred = str(preferred_kp_id)
        options.sort(key=lambda option: option["kp_id"] != preferred)
        if any(option["kp_id"] == preferred for option in options):
            selected = preferred
            current = next((node for node in nodes if str(node.id) == preferred), None)
    try:
        proposed = generation_intent(db, message, ctx, request_key, generation_mode=generation_mode)
        current = next((n for n in nodes if n.id == proposed.targets[0].kp_id), None)
        option_ids = {o["kp_id"] for o in options}
        if len(proposed.targets) > 1 and all(str(target.kp_id) in option_ids for target in proposed.targets):
            names = {str(node.id): node.name for node in nodes}
            proposed_targets = [{"kp_id": str(target.kp_id), "name": names[str(target.kp_id)],
                "question_type": target.question_type, "count": target.count,
                "difficulty": target.difficulty} for target in proposed.targets]
        elif current and len({target.kp_id for target in proposed.targets}) == 1 \
                and any(o["kp_id"] == str(current.id) for o in options) and selected is None:
            selected = str(current.id)
    except AppError as exc:
        if exc.code != "personal_generation_scope_required": raise
    note = (f"当前预设出题模式不覆盖「{current.name}」的所选题型，请使用「奶蛙生成新题」。本次没有调用模型。"
        if current and not selected and not proposed_targets else
        "已按知识点、题量和题型整理本次个人练习分配。确认后才会生成，保存后再由你决定是否加入今日学习。"
        if proposed_targets else
        "先确认这次要练的具体知识点。确认后才会生成，题目保存后再由你决定是否加入今日学习。")
    requested = requested_generation_topic(message)
    if requested and not current:
        note = f'没有找到与「{requested}」可靠匹配的现有知识点，不能沿用当前题代替。请明确选择下面的现有节点（表示更换出题范围），或取消；本次没有调用模型。'
        matches = [o for o in options if requested in o["name"] or o["name"] in requested]
        if not matches:
            parent_node = next((node for node in nodes if node.name == requested), None)
            if parent_node is None:
                from sqlalchemy import select as _select
                from backend.models.learning import KnowledgePoint as _Kp
                parent_node = db.scalar(_select(_Kp).where(_Kp.name == requested, _Kp.is_active.is_(True)))
            if parent_node is not None:
                matches = [o for o in options if o.get("code", "").startswith(parent_node.code + ".")]
        if len(matches) == 1:
            selected = matches[0]["kp_id"]
            current = next((node for node in nodes if str(node.id) == selected), None)
            note = f'已匹配知识点「{matches[0]["name"]}」。确认后生成，保存后再由你决定是否加入今日学习。'
        elif len(matches) > 1:
            math_matches = [m for m in matches if not m.get("code", "").startswith("cs408")]
            if math_matches:
                matches = math_matches
            subject = getattr(ctx, "subject", None)
            if subject:
                same_subject = []
                for match_item in matches:
                    node = next((node for node in nodes if str(node.id) == match_item["kp_id"]), None)
                    if node is not None and node.subject == subject:
                        same_subject.append(match_item)
                if same_subject:
                    matches = same_subject
            note = (f'「{requested}」匹配到多个知识点：' + '、'.join(o["name"] for o in matches[:6])
                    + '；请明确一个节点。本次没有调用模型。')
    if selected:
        options.sort(key=lambda option: option["kp_id"] != selected)
    if not options: note = "当前没有可选择的有效叶子知识点。没有调用模型，也没有改动今日学习。"
    total = sum(target.count for target in proposed.targets) if proposed else sum(c for _, c in types)
    difficulty_labels={"basic":"基础","improved":"中等","comprehensive":"综合挑战"}
    steps=([difficulty_labels[target.difficulty] for target in proposed.targets for _ in range(target.count)]
        if proposed and gradient_requested(message) else [])
    return {"question": message, "message": note, "nodes": options, "selected_kp_id": selected,
        "question_count": total, "difficulty": difficulty,'difficulty_steps':steps,
        "proposed_targets": proposed_targets}
