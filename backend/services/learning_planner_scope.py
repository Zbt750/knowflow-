"""Resolve current explicit > same-session explicit > page > default scope.

The handoff is authoritative for tools, not a model-generated scope claim.
"""
import re
from datetime import timedelta
from sqlalchemy import select
from backend.models.learning import KnowledgePoint, QuestionAttempt
from backend.models.learning_task import LearningTask
from backend.models.chat import ChatMessage
from uuid import UUID


def _recent_conversation_scope(db, ctx, now):
    """Only the immediately preceding completed turn may supply a target.

    A later unrelated answer is a boundary, not an invitation to scan backwards
    for an old convenient topic. Query facts must be server-persisted, successful,
    same-session and recent; no raw model prose is interpreted as an ID.
    """
    row = db.scalar(select(ChatMessage).where(ChatMessage.session_id == ctx.conversation_id,
        ChatMessage.role == 'assistant', ChatMessage.status != 'generating')
        .order_by(ChatMessage.seq.desc()).limit(1))
    if row is None:
        return None, None, None
    if row.status != 'completed':
        return row, None, None
    if not row.created_at or not timedelta(0) <= now-row.created_at <= timedelta(minutes=30):
        return row, None, None
    evidence = (row.metadata_ or {}).get('read_only_data_query') or {}
    if evidence.get('query_status') != 'executed':
        return row, None, None
    state = evidence.get('query_state') or {}
    values = state.get('scope_node_ids', evidence.get('scope_node_ids', []))
    try:
        ids = {UUID(str(value)) for value in values}
    except (ValueError, TypeError, AttributeError):
        return row, None, None
    return row, ids or None, state.get('subject')


def _current_scope_request(message):
    """A page reference is a scope only when its local clause requests it.

    Keep negation attached to its scope phrase, so "不要只围绕当前题" does
    not narrow a subject request and an earlier unrelated "不要" does not
    cancel a later positive instruction in another clause.
    """
    requested, only = False, False
    for match in re.finditer(r"当前(?:这道|这)?题|这道题|这题|当前知识点|当前节点", message):
        prefix = re.split(r"[，,。；;！？!?\n]", message[:match.start()])[-1]
        if re.search(
            r"(?:不要|别|不必|不用|不想|不再|不能|不应|并非|不是|而非|不止|不仅|不只)"
            r"(?:只|仅|仅限)?(?:再|继续)?"
            r"(?:复习|练习|学习|围绕|局限于|限制在|限于|针对|看|讲解|讲)?\s*$",
            prefix,
        ):
            continue
        requested = True
        only = only or bool(re.search(
            r"(?:只|仅|仅限)(?:复习|练习|学习|围绕|看|讲解)?\s*$", prefix
        ))
    return requested, only


def resolve_planner_scope(factory, ctx, message, observed, now, is_current, fallback=None):
    subject = "408" if re.search(r"408", message) else "考研数学" if re.search(r"数学二|数二|考研数学", message) else None
    current_requested, current_only = _current_scope_request(message)
    # Using wrong answers as evidence is not itself a hard 'only wrong nodes'
    # scope. Explicit wrong-node requests are; a whole-subject request wins.
    wrong_requested = bool(re.search(r"(?:只|仅).{0,6}错题|错题(?:所)?涉及|最近错题.{0,5}(?:知识点|范围)", message))
    broad = bool(subject and re.search(r"整体|全部|全科|整门|所有章节", message))
    scoped_only = bool(observed.explicit_scope and not current_only
        and re.search(r"(?<!不要)(?<!不)(?:只|仅)(?:复习|练习|学习)", message))
    if scoped_only:
        broad = False
        current_requested = False
    with factory() as db:
        nodes = list(db.scalars(select(KnowledgePoint).where(KnowledgePoint.is_active.is_(True)).order_by(KnowledgePoint.code)))
        by_id = {n.id: n for n in nodes}
        def expand(ids):
            result = set(ids) & by_id.keys()
            while True:
                grown = result | {n.id for n in nodes if n.parent_id in result}
                if grown == result:
                    return result
                result = grown
        def anchors(ids):
            return [n.id for n in nodes if n.id in ids and n.parent_id not in ids]
        ids, origin, explicit = None, None, True
        antecedent_id = None
        from backend.services.assistant_scope_resolution import resolve_topics
        resolutions=resolve_topics(nodes,message)
        unresolved=[r['topic'] for r in resolutions if r['status']=='unmatched']
        if resolutions and not broad and not current_only:
            ids=expand({UUID(k) for r in resolutions for k in r['node_ids']}) if not unresolved else set()
            origin='unresolved_explicit_topic' if unresolved else 'explicit_user_scope'
        elif current_only:
            ids = expand(ctx.knowledge_node_ids)
            origin = "explicit_current_question"
        elif broad:
            ids = {n.id for n in nodes if n.subject == subject}
            origin = "explicit_subject_scope"
        elif subject and "积分" in message and not re.search(r"二重积分|多元.{0,8}积分|积分.{0,8}(?:区域|次序|极坐标)", message):
            # “数学二积分” is a named chapter scope even when the user does
            # not repeat the knowledge-tree label “一元函数积分学”. Resolve
            # it by the canonical tree code and union any other explicit nodes
            # already recognized in the same request (for example “极限和积分”).
            # If this chapter node is absent, keep the scope unresolved rather
            # than silently broadening back to the whole subject or current page.
            integral_root = next((n for n in nodes if n.code == "math.calculus.exam.integral"), None)
            requested_ids = set(observed.explicit_scope or [])
            if integral_root is not None:
                requested_ids.add(integral_root.id)
            ids = expand(requested_ids)
            origin = "explicit_user_scope" if ids else "unresolved_explicit_topic"
        elif observed.explicit_scope and not wrong_requested:
            ids = set(observed.explicit_scope)
            if subject:
                ids = {i for i in ids if by_id[i].subject == subject}
            origin = "explicit_user_scope"
        elif current_requested:
            ids = expand(ctx.knowledge_node_ids)
            origin = "explicit_current_question"
        elif wrong_requested and not broad:
            wrong = set(db.scalars(select(QuestionAttempt.kp_id).where(
                QuestionAttempt.objective_result == "wrong", QuestionAttempt.submitted_at >= now-timedelta(days=30),
                QuestionAttempt.submitted_at <= now).distinct()))
            ids = expand(wrong)
            if subject:
                ids = {i for i in ids if by_id[i].subject == subject}
            if observed.explicit_scope:
                ids &= observed.explicit_scope
            origin = "explicit_recent_wrong_scope"
        elif observed.explicit_scope and not broad:
            ids = set(observed.explicit_scope)
            if subject:
                ids = {i for i in ids if by_id[i].subject == subject}
            origin = "explicit_user_scope"
        elif re.search(r"这一章|这个章节|这一章节", message) and not broad:
            ids, origin = set(), "unresolved_explicit_chapter"
        elif subject:
            ids = {n.id for n in nodes if n.subject == subject}
            origin = "explicit_subject_scope"
        else:
            row, query_ids, query_subject = _recent_conversation_scope(db, ctx, now)
            prior_evidence=(row.metadata_ or {}).get('read_only_data_query',{}) if row else {}
            if prior_evidence.get('query_type')=='scope_correction':
                prior_resolutions=prior_evidence.get('scope_resolution',[])
                prior_missing=[r['topic'] for r in prior_resolutions if r['status']=='unmatched']
                if prior_missing:
                    ids,origin,unresolved=set(),'unresolved_explicit_topic',prior_missing
            followup = bool(re.search(r"安排|加(?:入|到)|再来|再补|继续|这种|这个|这样|类似", message))
            reset = bool(re.search(r"结束|取消|换个话题|不要继承|不再", message))
            if query_ids and followup and not reset:
                ids, subject = expand(query_ids), query_subject
                origin = 'same_session_query_scope'
                antecedent_id = str(row.id)
            # An unrelated/newer completed answer invalidates old task scope.
            # If it is itself a planner answer, only that task can be inherited.
            previous_query = select(LearningTask).where(LearningTask.session_id == ctx.conversation_id)
            if row is not None:
                task_id = (row.metadata_ or {}).get('planner_task_id')
                try:
                    previous_query = previous_query.where(LearningTask.id == UUID(str(task_id)))
                except (TypeError, ValueError):
                    previous_query = previous_query.where(False)
            previous = db.scalars(previous_query.order_by(LearningTask.created_at.desc()).limit(20)) if ids is None and not reset else []
            for task in previous:
                handoff = (task.context or {}).get("planner_handoff") or {}
                constraints = handoff.get("constraints") or {}
                if (task.status!='cancelled' and is_current(task, now) and constraints.get("scope_version") == 1
                        and constraints.get("scope_explicit") is True):
                    ids = {UUID(i) for i in constraints.get("resolved_scope_node_ids", [])} & by_id.keys()
                    subject = constraints.get("inventory_subject")
                    origin = "same_session_explicit_scope"
                    break
        if ids is None:
            explicit = False
            if fallback and fallback[1] == "current_task_draft":
                ids, origin = expand(fallback[0]), "current_task_draft"
            elif fallback and fallback[1] in {"today_evidence_scope", "latest_validated_qa_context"}:
                ids, origin = expand(fallback[0]), fallback[1]
            elif ctx.knowledge_node_ids:
                ids, origin = expand(ctx.knowledge_node_ids), "current_study_context"
            elif subject or ctx.subject:
                subject = subject or ctx.subject
                ids, origin = {n.id for n in nodes if n.subject == subject}, "default_subject_scope"
            else:
                ids, origin = set(by_id), "default_learning_scope"
        ids -= observed.excluded_scope
        subjects = {by_id[i].subject for i in ids}
        subject = subject or (next(iter(subjects)) if len(subjects) == 1 else None)
        return anchors(ids)[:8], subject, {
            "scope_version": 1, "scope_explicit": explicit, "scope_origin": origin,
            "scope_resolution":resolutions,"unresolved_topics":unresolved,
            "scope_antecedent_message_id": antecedent_id,
            "resolved_scope_node_ids": [str(n.id) for n in nodes if n.id in ids],
            "scope_anchor_truncated": len(anchors(ids)) > 8,
            "inventory_subject": subject,
            "scope_evidence_note": "recent wrong records select scope, not independently proven mastery failures" if wrong_requested else None,
        }
