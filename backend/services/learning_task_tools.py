"""有界只读工具；不导出标准答案，不写学习状态，不把原卷引用当成题。"""
from collections import Counter
from backend.services.grading_basis import submission_grading_basis
import re
from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy import select, func, literal, case, Integer
from backend.models.learning import KnowledgePoint, Question, KpState, KpMasteryPolicy, QuestionAttempt, DailyPlan, PracticeItem, ExamQuestionReference
from backend.services.answer_grading import available_grading_method, available_practice_grading_method
from backend.services.lesson_service import read_lesson
from backend.schemas.learning_task import SearchKnowledge, NodeIds, FindQuestions, ReadLesson, ValidatePlan, QuestionAvailabilityQuery
from backend.schemas.question_source import public_question_source
from zoneinfo import ZoneInfo
from backend.mastery.storage import snapshot_from_storage, policy_from_storage
from backend.mastery.rules import analyze_gaps, effective_confirmation_count
from backend.services.capability_service import read_capability_profile
from backend.mastery.capability import capability_keys
from backend.services.question_eligibility import question_eligibility
from backend.services.question_availability import question_availability
from backend.services.planner_facts import build_planner_factual_summary


def _is_uuid(value) -> bool:
    try:
        UUID(str(value))
        return True
    except (TypeError, ValueError):
        return False

TOOL_ARGUMENTS = {
    "search_knowledge": (SearchKnowledge, "按名称或编号查知识范围；返回命中节点和有限直接子节点。父节点没有题时继续查其子节点，不要断言整个范围无题。"),
    "get_learning_state": (NodeIds, "读取客观结果、自评及证据缺口；两种依据必须区分。"),
    "find_questions": (FindQuestions, "查询真实可作答题；原卷引用只有数量，不是在线题。"),
    "get_question_availability": (QuestionAvailabilityQuery, "查询全局或指定范围的可练题库存；只返回数量和知识点，不返回题干。"),
    "read_lesson": (ReadLesson, "按需要读取系统节点讲解，不读取用户上传资料。"),
    "validate_plan": (ValidatePlan, "校验真实题目、已选范围及时间；草案必须校验后才能交付。"),
}


def tool_definitions(intent: str = "plan"):
    allowed = {
        "query": {"search_knowledge", "get_question_availability"},
        "recommend": {"search_knowledge", "get_learning_state", "find_questions", "read_lesson"},
        "plan": set(TOOL_ARGUMENTS),
        "modify": set(),
    }.get(intent, set(TOOL_ARGUMENTS))
    return [{"type": "function", "function": {"name": name, "description": desc,
            "parameters": schema.model_json_schema()}} for name, (schema, desc) in TOOL_ARGUMENTS.items() if name in allowed]


def classify_task_intent(goal: str) -> str:
    latest = (goal or "").rsplit("\n", 1)[-1]
    if re.search(r"(?:换掉|替换|移除|删除|剔除|换成|改成更|把.{0,12}(?:换|删|移)|换(?:更)?(?:简单|容易|基础)(?:题|的题|一些|一点)?)", latest):
        return "modify"
    asks = re.search(r"(?:哪些|那些|有什么|有几道|几道|多少道|多少题|有没有|是否有|都有哪些|能做哪些|题库里有)", latest)
    writes = re.search(r"(?:安排|加入|加到|补(?:充)?\s*\d|给我\s*\d|练(?:习)?\s*\d|做几道|出几道|挑几道)", latest)
    if asks and not writes:
        return "query"
    if re.search(r"(?:推荐|类似题|相似题|找一道类似|给我看看题)", latest) and not writes:
        return "recommend"
    return "plan"


class TaskTools:
    def __init__(self, factory, *, budget_minutes: int, now: datetime, goal: str = "", current_plan: dict | None = None, handoff: dict | None = None):
        self.factory, self.budget_minutes, self.now = factory, budget_minutes, now
        self.handoff=handoff or {}
        self.nodes: set[UUID] = set()
        self.questions: set[UUID] = set()
        self.state_read: set[UUID] = set()
        self.draft = None
        self.availability_read = False
        self.state_facts: dict[str, dict] = {}
        self.state_read_ids: set[str] = set()
        self.inventory_facts: dict[str, dict] = {}
        self.inventory_complete_ids: set[str] = set()
        types = {"选择题": "single_choice", "单选题": "single_choice", "填空题": "fill_blank", "计算题": "calculation", "证明题": "proof", "讨论题": "discussion", "程序题": "program"}
        matches = list(re.finditer(r"只(?:做|要|练)\s*(?:\d+\s*道\s*)?(选择题|单选题|填空题|计算题|证明题|讨论题|程序题)", goal))
        resets = list(re.finditer(r"不限题型|题型不限|不限制题型", goal))
        self.required_type = types[matches[-1].group(1)] if matches and (not resets or matches[-1].start() > resets[-1].start()) else None
        # 只解析明确的精确数量，不将“推荐三题”“三到五题”等偏好误当硬要求。
        exact = list(re.finditer(r"(?:必须(?:有|做)?|恰好|正好|只(?:要|做|练))\s*([1-9]\d?|[一二三四五六七八九十])\s*道", goal))
        number = exact[-1].group(1) if exact else None
        self.required_count = int(number) if number and number.isdigit() else "一二三四五六七八九十".index(number) + 1 if number else None
        self.basic_only = "基础题" in goal and not re.search(r"(?:不要|不做|不选)\s*基础题", goal)
        self.intent = classify_task_intent(goal)
        self.current_plan = current_plan or {}
        try:
            self.current_plan_node_ids = {UUID(str(k)) for k in self.current_plan.get("knowledge_point_ids", [])}
        except (TypeError, ValueError):
            self.current_plan_node_ids = set()
        self.explicit_scope = self._explicit_scope(goal.rsplit("\n", 1)[-1] if self.intent == "query" else goal)
        self.excluded_scope = self._excluded_scope(goal)
        if self.explicit_scope:
            self.nodes.update(self.explicit_scope)
        self.nodes.update(self.current_plan_node_ids)
        self.questions.update(UUID(str(q)) for q in self.current_plan.get("unstarted_question_ids", []) if _is_uuid(q))
        if handoff and handoff.get("version")=="planner-handoff-v1":
            if handoff.get("request_type") in {"query","recommend","plan","modify"}: self.intent=handoff["request_type"]
            count=handoff.get("requested_question_count")
            if type(count) is int and 1<=count<=99: self.required_count=count
            elif (handoff.get("constraints") or {}).get("relax_count"): self.required_count=None
            self.nodes.update(UUID(str(k)) for k in handoff.get("target_knowledge_node_ids",[]) if _is_uuid(k))
            if (handoff.get("constraints") or {}).get("scope_origin")=="today_evidence_scope":
                self.explicit_scope={UUID(str(k)) for k in handoff.get("target_knowledge_node_ids",[]) if _is_uuid(k)}
            excluded={UUID(str(k)) for k in handoff.get("exclusions",[]) if _is_uuid(k)}
            if excluded:
                from backend.services.question_availability import _descendant_ids
                with factory() as db: self.excluded_scope.update(_descendant_ids(db,excluded))

    @staticmethod
    def _is_excluded(text: str, match: re.Match) -> bool:
        left = text[max(0, match.start() - 16):match.start()]
        right = text[match.end():match.end() + 12]
        return bool(re.search(r"(?:除了|除|不要|不练|不做|不选|排除|避开|不复习)(?:复习|练习|学习|安排)?\s*$", left)
                    or re.match(r"\s*(?:以外|之外)(?:的)?", right))

    def _excluded_scope(self, goal):
        # 仅支持明确名称/编号前的排除词；复杂自然语言排除仍需澄清。
        with self.factory() as db:
            excluded = []
            for node in db.scalars(select(KnowledgePoint).where(KnowledgePoint.is_active.is_(True))):
                patterns = [re.escape(alias) for alias in self._scope_aliases(node.name)]
                if len(node.code) >= 3:
                    patterns.append(r"(?<![a-z0-9._-])" + re.escape(node.code) + r"(?![a-z0-9._-])")
                if any(self._is_excluded(goal, m) for pattern in patterns for m in re.finditer(pattern, goal)):
                    excluded.append(node.id)
            if not excluded:
                return set()
            tree = select(KnowledgePoint.id).where(KnowledgePoint.id.in_(excluded)).cte("task_excluded", recursive=True)
            tree = tree.union(select(KnowledgePoint.id).join(tree, KnowledgePoint.parent_id == tree.c.id).where(KnowledgePoint.is_active.is_(True)))
            return set(db.scalars(select(tree.c.id)))

    def _explicit_scope(self, goal):
        # 明确名称/编号才设硬范围；简称或含糊表达仍交给查询与澄清，不猜映射。
        with self.factory() as db:
            active_nodes = list(db.scalars(select(KnowledgePoint).where(KnowledgePoint.is_active.is_(True))))
            anchors = []
            for text_goal in dict.fromkeys([goal.rsplit("\n", 1)[-1], goal]):
                candidates = [node for node in active_nodes if
                    any(alias in text_goal for alias in self._scope_aliases(node.name))
                    or (len(node.code) >= 3 and node.code in text_goal)]
                anchors = []
                for node in candidates:
                    name_matches = [match for alias in self._scope_aliases(node.name)
                        for match in re.finditer(re.escape(alias), text_goal)]
                    code_matches = list(re.finditer(r"(?<![a-z0-9._-])" + re.escape(node.code) + r"(?![a-z0-9._-])", text_goal)) if len(node.code) >= 3 else []
                    if any(not self._is_excluded(text_goal, m) for m in name_matches + code_matches):
                        anchors.append(node.id)
                # 课程背景与具体章节同时命中时，以更具体节点为界，避免父编号前缀放宽范围。
                ancestor_ids = set()
                for node in candidates:
                    if node.id not in anchors:
                        continue
                    parent, seen = node.parent_id, set()
                    while parent and parent not in seen:
                        seen.add(parent); ancestor_ids.add(parent)
                        row = db.get(KnowledgePoint, parent)
                        parent = row.parent_id if row else None
                anchors = [a for a in anchors if a not in ancestor_ids]
                if anchors:
                    break
            if not anchors:
                return None
            # UNION 去重防止脏树环导致递归无限；父节点范围允许其后代。
            tree = select(KnowledgePoint.id).where(KnowledgePoint.id.in_(anchors)).cte("task_scope", recursive=True)
            tree = tree.union(select(KnowledgePoint.id).join(tree, KnowledgePoint.parent_id == tree.c.id).where(KnowledgePoint.is_active.is_(True)))
            return set(db.scalars(select(tree.c.id)).all())

    @staticmethod
    def _scope_aliases(name: str) -> list[str]:
        aliases = [name]
        short = re.sub(r"(?:法则|定理|原理|方法|概念|性质|公式|判据|定律)$", "", name)
        if len(short) >= 3 and short != name:
            aliases.append(short)
        return aliases

    def execute(self, name, arguments):
        if name not in TOOL_ARGUMENTS:
            return {"error": "tool_not_allowed"}
        allowed = {entry["function"]["name"] for entry in tool_definitions(self.intent)}
        if name not in allowed:
            return {"error": "unsupported_operation" if self.intent == "modify" else "tool_not_allowed"}
        args = TOOL_ARGUMENTS[name][0].model_validate(arguments)
        with self.factory() as db:
            return getattr(self, name)(db, args)

    def search_knowledge(self, db, args):
        # contains(autoescape) makes '%' and '_' literal rather than an unbounded wildcard.
        query = select(KnowledgePoint).where(KnowledgePoint.is_active.is_(True),
            KnowledgePoint.name.contains(args.query, autoescape=True) | KnowledgePoint.code.contains(args.query, autoescape=True))
        if self.explicit_scope is not None:
            query = query.where(KnowledgePoint.id.in_(self.explicit_scope))
        if self.excluded_scope:
            query = query.where(KnowledgePoint.id.not_in(self.excluded_scope))
        nodes = db.scalars(query.order_by(KnowledgePoint.ordinal, KnowledgePoint.code).limit(8)).all()
        # 有界展开一层，让模型能发现父节点下的知识；不把整棵树塞入上下文。
        children_query = select(KnowledgePoint).where(KnowledgePoint.parent_id.in_([n.id for n in nodes]), KnowledgePoint.is_active.is_(True))
        if self.explicit_scope is not None:
            children_query = children_query.where(KnowledgePoint.id.in_(self.explicit_scope))
        if self.excluded_scope:
            children_query = children_query.where(KnowledgePoint.id.not_in(self.excluded_scope))
        children = db.scalars(children_query.order_by(KnowledgePoint.ordinal, KnowledgePoint.code).limit(9)).all() if nodes else []
        child_truncated = len(children) > 8
        nodes = list({n.id: n for n in [*nodes, *children[:8]]}.values())
        excluded = db.scalars(select(KnowledgePoint).where(KnowledgePoint.id.in_(self.excluded_scope)).order_by(KnowledgePoint.code).limit(8)).all() if self.excluded_scope else []
        self.nodes.update(node.id for node in nodes)
        return {"nodes": [{"kp_id": str(n.id), "name": n.name, "code": n.code,
                           "reference_only": n.is_reference_only, "assessable": n.is_assessable,
                           "path": self._path(db, n)} for n in nodes], "limit": 16,
                "children_truncated": child_truncated,
                "excluded_nodes": [{"name": n.name, "code": n.code} for n in excluded],
                "exclusion_note": "excluded_nodes是用户排除的已存在节点，不代表不存在或没有题。不要据此断言该节点无题。",
                "navigation_note": "包含有限直接子节点；父节点无题不等于后代无题。继续按子节点名称或编号查询，子节点截断时收窄关键词。",
                "explicit_scope_enforced": self.explicit_scope is not None,
                "note": "查询受用户明确指定的范围约束；没有题时先询问，不得自行切换范围。" if self.explicit_scope is not None else "没有命中时请改用关键词或询问范围，不要假设用户没有薄弱点。"}

    def _path(self, db, node):
        path, seen = [], set()
        while node and node.id not in seen and len(path) < 20:
            seen.add(node.id)
            path.insert(0, node.name)
            node = db.get(KnowledgePoint, node.parent_id) if node.parent_id else None
        return path

    def _check_nodes(self, ids):
        if not set(ids).issubset(self.nodes):
            raise ValueError("scope_not_observed")

    def get_question_availability(self, db, args):
        constraints=self.handoff.get("constraints",{})
        if self.intent=="query" and constraints.get("global_inventory"):
            self.availability_read=True
            aliases={"数学二":"考研数学","math2":"考研数学","数学":"考研数学"}
            subject=constraints.get("inventory_subject") or aliases.get(args.subject,args.subject)
            if subject not in {"考研数学","408"}: subject=None
            global_result=question_availability(db,now=self.now,exclude_kp_ids=list(self.excluded_scope) or None,limit=0)
            result=question_availability(db,now=self.now,subject=subject,exclude_kp_ids=list(self.excluded_scope) or None,limit=24)
            result["eligible_nodes"]=[{k:n[k] for k in ("kp_id","code","name","subject","practice_eligible_count","available_to_append_count","previously_attempted_count","unused_count","evidence_pool_status")} for n in result["eligible_nodes"]]
            context_ids=[UUID(k) for k in constraints.get("context_node_ids",[])]
            current_nodes=[{"node_id":str(n.id),"name":n.name,"subject":n.subject,"excluded":n.id in self.excluded_scope}
                for n in db.scalars(select(KnowledgePoint).where(KnowledgePoint.id.in_(context_ids)))]
            return {**result,"scope_enforced":"global_inventory","requested_group":subject,
                "global_count_scope":"all_subjects_after_exclusions",
                "count_scope_note":"完整统计与预览分离；subject_scope为null表示全部科目。所有计数均已应用排除条件；不是未排除的全库库存。",
                "inventory_counts":{"count_scope":"after_exclusions","question_count_total":global_result["practice_eligible_count"],
                    "node_count_total":global_result["eligible_node_count"],"subject_totals":global_result["subject_counts"],
                    "subject_scope":subject,"question_count_in_list_scope":result["practice_eligible_count"],
                    "node_count_in_list_scope":result["eligible_node_count"],"returned_node_count":len(result["eligible_nodes"]),
                    "node_list_is_truncated":result["node_list_truncated"],"preview_is_not_complete_inventory":result["node_list_truncated"]},
                "current_context_nodes":current_nodes,
                "global_practice_eligible_count":global_result["practice_eligible_count"],"global_nodes_with_questions":global_result["eligible_node_count"]}
        if args.kp_ids:
            self._check_nodes(args.kp_ids)
        scope_ids = args.kp_ids or (list(self.explicit_scope) if self.explicit_scope else None)
        self.availability_read = True
        excluded_nodes = set(self.excluded_scope) | set(args.exclude_kp_ids)
        result = question_availability(db, now=self.now, subject=args.subject,
            kp_ids=scope_ids, exclude_kp_ids=list(excluded_nodes) or None,
            exclude_question_ids=args.exclude_question_ids or None,
            question_type=args.question_type,
            plan_id=UUID(str(self.current_plan["plan_id"])) if self.current_plan.get("plan_id") else None,
            limit=60)
        return result

    def get_learning_state(self, db, args):
        self._check_nodes(args.kp_ids)
        result = []
        for kp_id in dict.fromkeys(args.kp_ids):
            state = db.get(KpState, kp_id)
            objective_pending = (state.pending_review_question_ids or []) if state and state.assessment_basis == "objective_v1" else []
            capability = read_capability_profile(db, db.get(KnowledgePoint, kp_id))
            # Same-item submissions may share a timestamp (clock precision/imports).
            # Do not let random UUID order invert correction history. Legacy malformed
            # JSON is not an integer receipt and must not abort the entire task.
            attempt_number = QuestionAttempt.grading_evidence["attempt_number"].as_string()
            sequence_order = case((attempt_number.op("~")(r"^[0-9]{1,2}$"),
                                   attempt_number.cast(Integer)), else_=0)
            attempts = db.scalars(select(QuestionAttempt).where(QuestionAttempt.kp_id == kp_id)
                .order_by(QuestionAttempt.submitted_at.desc(),
                    sequence_order.desc(),
                    QuestionAttempt.id).limit(8)).all()
            snapshot = snapshot_from_storage(state) if state else None
            gap = analyze_gaps(snapshot.evidence_window, manual_credit_count=snapshot.manual_credit_count,
                manual_confirmed_at=snapshot.manual_confirmed_at,
                policy=policy_from_storage(db.get(KpMasteryPolicy, kp_id))) if snapshot else None
            result.append({"kp_id": str(kp_id), "basis": state.assessment_basis if state else "no_state",
                "capability_profile": capability.model_dump(mode="json", include={
                    "version": True, "mapping_version": True, "history_truncated": True,
                    "confirmation_lookup_truncated": True, "excluded_confirmation_count": True,
                    "dimensions": {"__all__": {"key", "label", "status", "evidence_scope",
                        "online_question_count", "reliable_grading_question_count",
                        "independent_question_count", "pending_review_question_count"}},
                }) if capability else None,
                "state": state.state if state else "unknown", "self_report": state.node_self_grade if state else None,
                "self_report_available": bool(state and state.node_self_grade is not None),
                "basis_note": "basis是存储/评估口径，不是反馈存在证明；self_report_available=false表示没有节点自评，不能说已有用户自述。",
                "pending_review_question_ids": objective_pending,
                "effective_confirmation_count": effective_confirmation_count(
                    snapshot.evidence_window, manual_credit_count=snapshot.manual_credit_count) if snapshot else 0,
                "verified_objective_confirmation_count": sum(
                    item.reliability == "verified_objective" for item in snapshot.evidence_window) if snapshot else 0,
                "history_available": bool(attempts), "recent_attempts": [{"question_id": str(a.question_id) if a.question_id else None,
                    "attempt_id": str(a.id),
                    "result": a.objective_result, "self_grade": a.self_grade,
                    "submitted_at": a.submitted_at.isoformat(),
                    "assisted": (a.grading_evidence or {}).get("assisted"),
                    "attempt_number": (a.grading_evidence or {}).get("attempt_number"),
                    "sequence_category": (a.grading_evidence or {}).get("sequence_category"),
                    "assistance_level": (a.grading_evidence or {}).get("assistance_level"),
                    "confidence": (a.grading_evidence or {}).get("confidence"),
                    "basis": submission_grading_basis(a.grading_evidence or {}),
                    "mastery_basis": (a.grading_evidence or {}).get("assessment_basis"),
                    "feedback_observed": a.self_grade is not None,
                    "evidence_reliability": (a.grading_evidence or {}).get("evidence_reliability"),
                    "assessment_origin": submission_grading_basis(a.grading_evidence or {})} for a in attempts],
                "next_step": "优先复测之前答错的题；看过解析不等于复测通过" if objective_pending else gap.next_step if gap else "尚无学习证据",
                "gaps": [{"key": g.key, "current": g.current, "required": g.required, "satisfied": g.satisfied} for g in gap.items] if gap else []})
            self.state_facts[str(kp_id)] = result[-1]
        self.state_read.update(args.kp_ids)
        self.state_read_ids.update(str(value) for value in args.kp_ids)
        return {"states": result, "note": "用户自述弱项不是客观错题；无历史时如实说明。能力维度仅是证据分布，不是全面掌握；最终答案证据不证明过程正确，未验证不等于不会。"}

    def planner_factual_summary(self):
        return build_planner_factual_summary(
            current_plan=self.current_plan,
            state_by_node=self.state_facts,
            inventory_by_node=self.inventory_facts,
            state_read_ids=self.state_read_ids,
            inventory_complete_ids=self.inventory_complete_ids,
        )

    def _today_question_ids(self, db):
        return set(db.scalars(select(PracticeItem.question_id).join(DailyPlan).where(
            DailyPlan.study_date == self.now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat(), PracticeItem.question_id.is_not(None))).all())

    def find_questions(self, db, args):
        requested_ids = list(args.kp_ids)
        if not requested_ids:
            requested_ids = list(self.explicit_scope or self.current_plan_node_ids or [])
            requested_ids = list(db.scalars(select(KnowledgePoint.id).where(
                KnowledgePoint.id.in_(requested_ids or [UUID(int=0)]),
                KnowledgePoint.is_active.is_(True), KnowledgePoint.is_assessable.is_(True)).order_by(KnowledgePoint.code).limit(8)))
        if not requested_ids:
            return {"error": "scope_needed", "hint": "当前学习卷没有可用知识范围；先定位明确的知识点，不能扩大成整门课程。"}
        self._check_nodes(requested_ids)
        requested_ids = [kp_id for kp_id in requested_ids if kp_id not in self.excluded_scope]
        if not requested_ids:
            return {"error": "excluded_scope", "hint": "本次范围内节点都已被用户排除，未查询其他题目。"}
        pending = set()
        for state in db.scalars(select(KpState).where(KpState.kp_id.in_(requested_ids), KpState.assessment_basis == "objective_v1")):
            for identifier in state.pending_review_question_ids or []:
                try:
                    pending.add(UUID(str(identifier)))
                except (ValueError, TypeError, AttributeError):
                    continue  # 不能让历史损坏的标识导致整次安排失败。
        query = select(Question).join(KnowledgePoint).where(Question.kp_id.in_(requested_ids), Question.is_active.is_(True), Question.estimated_minutes > 0, KnowledgePoint.is_active.is_(True), KnowledgePoint.is_assessable.is_(True))
        if args.question_type:
            query = query.where(Question.question_type == args.question_type)
        fetched = db.scalars(query.order_by(case((Question.id.in_(pending), 0), else_=1), Question.estimated_minutes, Question.id).limit(1001)).all()
        assessments = {q.id: question_eligibility(q, db.get(KnowledgePoint, q.kp_id)) for q in fetched}
        available = [q for q in fetched if assessments[q.id].practice_eligible]
        rows = available[:16]
        self.questions.update(q.id for q in rows)
        today = self._today_question_ids(db)
        additional = [q for q in available if q.id not in today]
        count_is_exact = args.question_type is None and len(fetched) <= 1000
        by_node: dict[UUID, list[Question]] = {}
        for question in additional:
            by_node.setdefault(question.kp_id, []).append(question)
        for kp_id in requested_ids:
            if count_is_exact:
                node_additional = by_node.get(kp_id, [])
                self.inventory_facts[str(kp_id)] = {
                    "additional_eligible_count": len(node_additional),
                    "additional_eligible_question_ids": [str(q.id) for q in node_additional],
                    "today_question_trust": [],
                }
                self.inventory_complete_ids.add(str(kp_id))
        for q in fetched:
            if q.id in today:
                facts = self.inventory_facts.setdefault(str(q.kp_id), {
                    "additional_eligible_count": None,
                    "additional_eligible_question_ids": [],
                    "today_question_trust": [],
                })
                trust = assessments[q.id].public_dict()
                if not any(existing.get("question_id") == str(q.id) for existing in facts["today_question_trust"]):
                    facts["today_question_trust"].append({
                        "question_id": str(q.id),
                        "answer_reliability": trust.get("answer_reliability", "unknown"),
                    })
        references = Counter(db.scalars(select(ExamQuestionReference.knowledge_point_id).where(ExamQuestionReference.knowledge_point_id.in_(requested_ids))).all())
        attempted = set(db.scalars(select(QuestionAttempt.question_id).where(
            QuestionAttempt.question_id.in_([q.id for q in fetched] or [UUID(int=0)])).distinct()))
        blocked = Counter(reason for q in fetched for reason in assessments[q.id].blocking_reasons)
        return {"questions": [{"question_id": str(q.id), "kp_id": str(q.kp_id), "kp_name": db.get(KnowledgePoint, q.kp_id).name,
            "question_type": q.question_type, "difficulty": q.difficulty, "minutes": q.estimated_minutes,
            "question_role": q.question_role, "is_variant": q.is_variant,
            "question_source": public_question_source(q.grading_config).model_dump(),
            "question_trust": assessments[q.id].public_dict(),
            "skill_tags": list(q.skill_tags or [])[:12], "question_version": q.updated_at.astimezone(timezone.utc).isoformat(),
            "capability_keys": list(capability_keys(q.question_type, q.question_role, q.is_variant)),
            "pending_review": q.id in pending,
            "can_repractice_in_new_item": q.id not in today,
            "previously_attempted": q.id in attempted,
            "in_today_plan": q.id in today,
            "answer_key_comparison_method": assessments[q.id].answer_comparison_method,
            "grading_method": assessments[q.id].verified_grading_method} for q in rows],
            "requested_kp_ids": [str(k) for k in requested_ids],
            "practice_eligible_count": len(available), "active_question_count": len(fetched),
            "blocked_question_count": len(fetched) - len(available), "blocking_reasons": dict(blocked),
            "exam_reference_counts": {str(k): v for k, v in references.items()},
            "candidate_count": None, "candidate_inventory_status": "not_indexed", "limit": 16,
            "candidate_list_complete": len(fetched) <= 1000 and len(available) <= 16,
            "additional_eligible_count": len(additional) if count_is_exact else None,
            "additional_eligible_question_ids": [str(q.id) for q in additional[:16]] if count_is_exact else [],
            "evidence_boundary": "answer_key_comparison_method表示按题库参考答案作练习对照；grading_method表示符合当前已核验客观证据门槛。AI答案对照可以帮助练习，但不会因此变成人工/权威答案或强客观Evidence。",
            "note": "原卷引用没有题干，不能当在线题添加；今日是否已有题只看in_today_plan，已做过不等于今天已加入。pending_review=false只表示没有客观错题待复测，不表示禁止重做；can_repractice_in_new_item=true时，看解析后完成、猜对或unknown的历史题也能按用户要求在新的练习项复验，仍须符合预算及范围。candidate_list_complete=false时不能把候选数当全库题量。题目是否变式只看question_role/is_variant/capability_keys，不从题干猜；毕业缺口不代表题库已存在该类题。pending_review是真实待复测记录，不是用户自述；优先考虑但仍须满足范围、题型和时间预算。"}

    def read_lesson(self, db, args):
        self._check_nodes([args.kp_id])
        node = db.get(KnowledgePoint, args.kp_id)
        text = read_lesson(node.code)
        return {"kp_id": str(node.id), "name": node.name, "available": text is not None,
                "markdown": (text or "")[:4000], "truncated": bool(text and len(text) > 4000)}

    def validate_plan(self, db, args):
        self.draft = None
        errors, warnings = [], []
        if len(set(args.question_ids)) != len(args.question_ids): errors.append("duplicate_questions")
        if self.required_count is not None and len(args.question_ids) != self.required_count: errors.append("question_count_constraint")
        if len(set(args.review_kp_ids)) != len(args.review_kp_ids): errors.append("duplicate_review_nodes")
        if not set(args.question_ids).issubset(self.questions): errors.append("questions_not_observed")
        if not set(args.review_kp_ids).issubset(self.nodes): errors.append("nodes_not_observed")
        if bool(args.review_kp_ids) != bool(args.review_minutes): errors.append("review_time_mismatch")
        rows = db.scalars(select(Question).join(KnowledgePoint).where(Question.id.in_(args.question_ids), Question.is_active.is_(True), Question.estimated_minutes > 0, KnowledgePoint.is_active.is_(True), KnowledgePoint.is_assessable.is_(True))).all()
        by_id = {q.id: q for q in rows}
        assessments = {q.id: question_eligibility(q, db.get(KnowledgePoint, q.kp_id)) for q in rows}
        if len(rows) != len(args.question_ids) or any(not assessments[q.id].practice_eligible for q in rows):
            errors.append("question_not_practice_eligible")
        for kp_id in args.review_kp_ids:
            node = db.get(KnowledgePoint, kp_id)
            if node is None or not node.is_active or read_lesson(node.code) is None:
                errors.append("review_lesson_unavailable")
        if len(rows) != len(args.question_ids): errors.append("question_missing")
        if self.required_type and any(q.question_type != self.required_type for q in rows): errors.append("question_type_constraint")
        if self.basic_only and any(q.difficulty != "basic" for q in rows): errors.append("difficulty_constraint")
        if not ({q.kp_id for q in rows} | set(args.review_kp_ids)).issubset(self.state_read): errors.append("learning_state_not_read")
        if self.explicit_scope is not None and not ({q.kp_id for q in rows} | set(args.review_kp_ids)).issubset(self.explicit_scope): errors.append("outside_explicit_scope")
        if ({q.kp_id for q in rows} | set(args.review_kp_ids)) & self.excluded_scope: errors.append("excluded_scope")
        if any(q.id in self._today_question_ids(db) for q in rows): errors.append("already_in_today_plan")
        total = args.review_minutes + sum(q.estimated_minutes for q in rows)
        if total > self.budget_minutes: errors.append("time_budget_exceeded")
        if total <= 0: errors.append("empty_plan")
        if not rows: warnings.append("没有选到在线题，仅安排知识复习；原卷引用不算在线题。")
        if any(assessments[q.id].grading_capability in {"process_review_only", "unsupported"} for q in rows):
            warnings.append("部分题目需要纸笔作答并人工对照解析，不支持自动核对。")
        if any(assessments[q.id].answer_provenance == "ai_generated" for q in rows):
            warnings.append("部分题目使用 AI 生成参考答案；练习比较不代表权威核验，不自动产生最高强度客观证据。")
        if errors: return {"valid": False, "errors": errors, "required_count": self.required_count,
                           "hint": "同一张卷不重复安排同一道题；数量或预算不足需说明，不能重复题目凑数。"}
        self.draft = {"selected_question_ids": [str(qid) for qid in args.question_ids],
            "questions": [{"question_id": str(qid), "kp_id": str(by_id[qid].kp_id),
            "kp_name": db.get(KnowledgePoint, by_id[qid].kp_id).name,
            "question_type": by_id[qid].question_type, "difficulty": by_id[qid].difficulty,
            "question_role": by_id[qid].question_role, "is_variant": by_id[qid].is_variant,
            "question_source": public_question_source(by_id[qid].grading_config).model_dump(),
            "question_trust": assessments[qid].public_dict(),
            "eligibility_snapshot": assessments[qid].public_dict(),
            "minutes": by_id[qid].estimated_minutes,
            "question_version": by_id[qid].updated_at.astimezone(timezone.utc).isoformat()} for qid in args.question_ids],
            "review_nodes": [{"kp_id": str(k), "name": db.get(KnowledgePoint, k).name} for k in args.review_kp_ids],
            "review_minutes": args.review_minutes, "total_minutes": total,
            "budget_minutes": self.budget_minutes, "rationale": args.rationale, "warnings": warnings,
            "can_commit": bool(rows)}
        return {"valid": True, "draft": self.draft}
