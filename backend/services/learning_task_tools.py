"""有界只读工具；不导出标准答案，不写学习状态，不把原卷引用当成题。"""
from collections import Counter
import re
from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy import select, func, literal, case, Integer
from backend.models.learning import KnowledgePoint, Question, KpState, KpMasteryPolicy, QuestionAttempt, DailyPlan, PracticeItem, ExamQuestionReference
from backend.services.answer_grading import available_grading_method
from backend.services.lesson_service import read_lesson
from backend.schemas.learning_task import SearchKnowledge, NodeIds, FindQuestions, ReadLesson, ValidatePlan
from zoneinfo import ZoneInfo
from backend.mastery.storage import snapshot_from_storage, policy_from_storage
from backend.mastery.rules import analyze_gaps
from backend.services.capability_service import read_capability_profile
from backend.mastery.capability import capability_keys

TOOL_ARGUMENTS = {
    "search_knowledge": (SearchKnowledge, "按名称或编号查知识范围；返回命中节点和有限直接子节点。父节点没有题时继续查其子节点，不要断言整个范围无题。"),
    "get_learning_state": (NodeIds, "读取客观结果、自评及证据缺口；两种依据必须区分。"),
    "find_questions": (FindQuestions, "查询真实可作答题；原卷引用只有数量，不是在线题。"),
    "read_lesson": (ReadLesson, "按需要读取系统节点讲解，不读取用户上传资料。"),
    "validate_plan": (ValidatePlan, "校验真实题目、已选范围及时间；草案必须校验后才能交付。"),
}


def tool_definitions():
    return [{"type": "function", "function": {"name": name, "description": desc,
            "parameters": schema.model_json_schema()}} for name, (schema, desc) in TOOL_ARGUMENTS.items()]


class TaskTools:
    def __init__(self, factory, *, budget_minutes: int, now: datetime, goal: str = ""):
        self.factory, self.budget_minutes, self.now = factory, budget_minutes, now
        self.nodes: set[UUID] = set()
        self.questions: set[UUID] = set()
        self.state_read: set[UUID] = set()
        self.draft = None
        types = {"选择题": "single_choice", "单选题": "single_choice", "填空题": "fill_blank", "计算题": "calculation", "证明题": "proof", "讨论题": "discussion", "程序题": "program"}
        matches = list(re.finditer(r"只(?:做|要|练)\s*(?:\d+\s*道\s*)?(选择题|单选题|填空题|计算题|证明题|讨论题|程序题)", goal))
        resets = list(re.finditer(r"不限题型|题型不限|不限制题型", goal))
        self.required_type = types[matches[-1].group(1)] if matches and (not resets or matches[-1].start() > resets[-1].start()) else None
        # 只解析明确的精确数量，不将“推荐三题”“三到五题”等偏好误当硬要求。
        exact = list(re.finditer(r"(?:必须(?:有|做)?|恰好|正好|只(?:要|做|练))\s*([1-9]\d?|[一二三四五六七八九十])\s*道", goal))
        number = exact[-1].group(1) if exact else None
        self.required_count = int(number) if number and number.isdigit() else "一二三四五六七八九十".index(number) + 1 if number else None
        self.basic_only = "基础题" in goal and not re.search(r"(?:不要|不做|不选)\s*基础题", goal)
        self.explicit_scope = self._explicit_scope(goal)
        self.excluded_scope = self._excluded_scope(goal)

    def _excluded_scope(self, goal):
        # 仅支持明确名称/编号前的排除词；复杂自然语言排除仍需澄清。
        with self.factory() as db:
            excluded = []
            for node in db.scalars(select(KnowledgePoint).where(KnowledgePoint.is_active.is_(True))):
                patterns = [re.escape(node.name)] if len(node.name) >= 3 else []
                if len(node.code) >= 3:
                    patterns.append(r"(?<![a-z0-9._-])" + re.escape(node.code) + r"(?![a-z0-9._-])")
                if any(re.search(r"(?:不要|不练|不做|不选|排除|避开|不复习)(?:复习|练习|学习|安排)?\s*$", goal[max(0, m.start() - 12):m.start()])
                       for pattern in patterns for m in re.finditer(pattern, goal)):
                    excluded.append(node.id)
            if not excluded:
                return set()
            tree = select(KnowledgePoint.id).where(KnowledgePoint.id.in_(excluded)).cte("task_excluded", recursive=True)
            tree = tree.union(select(KnowledgePoint.id).join(tree, KnowledgePoint.parent_id == tree.c.id).where(KnowledgePoint.is_active.is_(True)))
            return set(db.scalars(select(tree.c.id)))

    def _explicit_scope(self, goal):
        # 明确名称/编号才设硬范围；简称或含糊表达仍交给查询与澄清，不猜映射。
        with self.factory() as db:
            anchors = []
            for text_goal in dict.fromkeys([goal.rsplit("\n", 1)[-1], goal]):
                candidates = db.scalars(select(KnowledgePoint).where(KnowledgePoint.is_active.is_(True),
                    ((func.length(KnowledgePoint.name) >= 3) & (func.strpos(literal(text_goal), KnowledgePoint.name) > 0)) |
                    ((func.length(KnowledgePoint.code) >= 3) & (func.strpos(literal(text_goal), KnowledgePoint.code) > 0)))).all()
                anchors = []
                for node in candidates:
                    name_matches = list(re.finditer(re.escape(node.name), text_goal)) if len(node.name) >= 3 else []
                    code_matches = list(re.finditer(r"(?<![a-z0-9._-])" + re.escape(node.code) + r"(?![a-z0-9._-])", text_goal)) if len(node.code) >= 3 else []
                    if any(not re.search(r"(?:不要|不练|不做|不选|排除|避开|不复习)(?:复习|练习|学习|安排)?\s*$", text_goal[max(0, m.start() - 12):m.start()]) for m in name_matches + code_matches):
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

    def execute(self, name, arguments):
        if name not in TOOL_ARGUMENTS:
            return {"error": "tool_not_allowed"}
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
                "history_available": bool(attempts), "recent_attempts": [{"question_id": str(a.question_id) if a.question_id else None,
                    "result": a.objective_result, "self_grade": a.self_grade,
                    "submitted_at": a.submitted_at.isoformat(),
                    "assisted": (a.grading_evidence or {}).get("assisted"),
                    "attempt_number": (a.grading_evidence or {}).get("attempt_number"),
                    "sequence_category": (a.grading_evidence or {}).get("sequence_category"),
                    "assistance_level": (a.grading_evidence or {}).get("assistance_level"),
                    "confidence": (a.grading_evidence or {}).get("confidence"),
                    "basis": (a.grading_evidence or {}).get("assessment_basis", "legacy_self_reported")} for a in attempts],
                "next_step": "优先复测之前答错的题；看过解析不等于复测通过" if objective_pending else gap.next_step if gap else "尚无学习证据",
                "gaps": [{"key": g.key, "current": g.current, "required": g.required, "satisfied": g.satisfied} for g in gap.items] if gap else []})
        self.state_read.update(args.kp_ids)
        return {"states": result, "note": "用户自述弱项不是客观错题；无历史时如实说明。能力维度仅是证据分布，不是全面掌握；最终答案证据不证明过程正确，未验证不等于不会。"}

    def _today_question_ids(self, db):
        return set(db.scalars(select(PracticeItem.question_id).join(DailyPlan).where(
            DailyPlan.study_date == self.now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat(), PracticeItem.question_id.is_not(None))).all())

    def find_questions(self, db, args):
        self._check_nodes(args.kp_ids)
        pending = set()
        for state in db.scalars(select(KpState).where(KpState.kp_id.in_(args.kp_ids), KpState.assessment_basis == "objective_v1")):
            for identifier in state.pending_review_question_ids or []:
                try:
                    pending.add(UUID(str(identifier)))
                except (ValueError, TypeError, AttributeError):
                    continue  # 不能让历史损坏的标识导致整次安排失败。
        query = select(Question).join(KnowledgePoint).where(Question.kp_id.in_(args.kp_ids), Question.is_active.is_(True), Question.estimated_minutes > 0, KnowledgePoint.is_active.is_(True), KnowledgePoint.is_assessable.is_(True))
        if args.question_type:
            query = query.where(Question.question_type == args.question_type)
        fetched = db.scalars(query.order_by(case((Question.id.in_(pending), 0), else_=1), Question.estimated_minutes, Question.id).limit(17)).all()
        rows = fetched[:16]
        self.questions.update(q.id for q in rows)
        today = self._today_question_ids(db)
        references = Counter(db.scalars(select(ExamQuestionReference.knowledge_point_id).where(ExamQuestionReference.knowledge_point_id.in_(args.kp_ids))).all())
        return {"questions": [{"question_id": str(q.id), "kp_id": str(q.kp_id), "stem": q.stem[:300],
            "question_type": q.question_type, "difficulty": q.difficulty, "minutes": q.estimated_minutes,
            "question_role": q.question_role, "is_variant": q.is_variant,
            "capability_keys": list(capability_keys(q.question_type, q.question_role, q.is_variant)),
            "pending_review": q.id in pending,
            "can_repractice_in_new_item": q.id not in today,
            "in_today_plan": q.id in today, "grading_method": available_grading_method(question_type=q.question_type,
                config=q.grading_config, expected=q.correct_answer, options=q.options)} for q in rows],
            "exam_reference_counts": {str(k): v for k, v in references.items()}, "limit": 16,
            "candidate_list_complete": len(fetched) <= 16,
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
        if any(not available_grading_method(question_type=q.question_type, config=q.grading_config,
                                           expected=q.correct_answer, options=q.options) for q in rows):
            warnings.append("部分题目需要纸笔作答并人工对照解析，不支持自动核对。")
        if errors: return {"valid": False, "errors": errors, "required_count": self.required_count,
                           "hint": "同一张卷不重复安排同一道题；数量或预算不足需说明，不能重复题目凑数。"}
        by_id = {q.id: q for q in rows}
        self.draft = {"questions": [{"question_id": str(qid), "kp_id": str(by_id[qid].kp_id),
            "stem": by_id[qid].stem[:300], "question_type": by_id[qid].question_type,
            "minutes": by_id[qid].estimated_minutes,
            "question_version": by_id[qid].updated_at.astimezone(timezone.utc).isoformat()} for qid in args.question_ids],
            "review_nodes": [{"kp_id": str(k), "name": db.get(KnowledgePoint, k).name} for k in args.review_kp_ids],
            "review_minutes": args.review_minutes, "total_minutes": total,
            "budget_minutes": self.budget_minutes, "rationale": args.rationale, "warnings": warnings,
            "can_commit": bool(rows)}
        return {"valid": True, "draft": self.draft}
