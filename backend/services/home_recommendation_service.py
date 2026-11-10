"""Homepage adapter for the existing recommendation -> formal paper pipeline.

Bounded semantic proposals only; no alternative ranking or mastery writes during preview.
Only LearningTask/ChatMessage workspace state is persisted before confirmation.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
import logging
import hashlib
import re
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified
from backend.errors import AppError
from backend.models.chat import ChatMessage, ChatSession
from backend.models.learning import DailyPlan, KnowledgePoint, PracticeItem, Question, QuestionAttempt, QuestionVersion
from backend.models.learning_task import LearningTask
from backend.schemas.learning_task import NodeIds
from backend.services.learning_task_tools import TaskTools
from backend.services.learner_self_report import read_self_reports
from backend.services.learner_self_report import extract_self_reports
from backend.services.practice_service import (
    DAILY_PLAN_MATERIALIZATION_LOCK_KEY,
    create_initial_plan,
    preview_initial_questions,
    DEFAULT_PER_KP_LIMIT,
)
from backend.services.question_versions import _json_value, question_version_reference
from backend.services.question_eligibility import question_eligibility
from backend.services.learning_task_service import _draft_version
from backend.mastery.rules import SHANGHAI
from backend.services.recommendation_copy import recommendation_sentence
from backend.services.chat_session_scope import require_session_purpose


def _session(db, session_id):
    row = require_session_purpose(db, session_id, "study")
    if row.mode != "builtin":
        raise AppError("forbidden", status_code=403)
    return db.scalar(select(ChatSession).where(ChatSession.id == row.id).with_for_update())


def _serialize_daily_plan_mutation(db):
    """Share the formal materialization lock with every DailyPlan writer."""
    db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"),
               {"lock_key": DAILY_PLAN_MATERIALIZATION_LOCK_KEY})


def _reject_materialized_daily_plan_mutation(db, now):
    study_date = now.astimezone(SHANGHAI).date().isoformat()
    plan = db.scalar(select(DailyPlan).where(
        DailyPlan.study_date == study_date
    ).with_for_update())
    if plan is not None and db.scalar(select(PracticeItem.id).where(
            PracticeItem.plan_id == plan.id).limit(1)) is not None:
        raise AppError("plan_already_generated", status_code=409)


def _request_origin(body):
    # Action is the business boundary: scope saves/default/restore are system
    # edits even if a client supplies a nonempty label in goal.
    return 'chat' if body.action in {'adjust','explain'} and body.goal.strip() else 'system'


def _record_request_dialogue(db, session, body, message):
    if _request_origin(body)!='chat':
        return False
    db.add(ChatMessage(session_id=session.id,role='user',content=body.goal,status='completed',
        metadata_={'learner_self_reports':extract_self_reports(body.goal)}))
    db.add(ChatMessage(session_id=session.id,role='assistant',content=message,status='completed',
        metadata_={'home_recommendation':True}))
    if session.title=='首页推荐调整':
        session.title=body.goal[:60]
    return True


def _latest(db, session_id):
    rows=[r for r in db.scalars(select(LearningTask).where(
        LearningTask.session_id == session_id).order_by(LearningTask.created_at.desc(), LearningTask.id))
        if (r.context or {}).get("home_recommendation")]
    # A first-turn fallback is inserted after its failed/pending attempt. It is
    # a recovery target, not a newer user decision. Do not let its insert time
    # hide that attempt or the workload choice on refresh.
    fallback_ids={(r.context or {}).get('fallback_task_id') for r in rows}
    return next((r for r in rows if str(r.id) not in fallback_ids),None)


def _history_entry(row, paper):
    """Keep history compact: link prior tasks, snapshot only an unpersisted baseline."""
    if row is not None and row.draft and not (row.metrics or {}).get('commit'):
        return {'task_id': str(row.id)}
    if isinstance(paper, dict) and paper.get('questions'):
        return {'snapshot': _json_value(deepcopy(paper))}
    return None


def _history_paper(db, session_id, entry):
    if not isinstance(entry, dict):
        return None
    task_id = entry.get('task_id')
    if task_id:
        try:
            row = db.get(LearningTask, UUID(str(task_id)))
        except (TypeError, ValueError):
            return None
        if (row is None or row.session_id != session_id
                or not (row.context or {}).get('home_recommendation')
                or not row.draft or (row.metrics or {}).get('commit')):
            return None
        return deepcopy(row.draft)
    snapshot = entry.get('snapshot')
    if isinstance(snapshot, dict) and snapshot.get('questions') and snapshot.get('selected_kp_ids'):
        return deepcopy(snapshot)
    return None


def _workload_pending(row):
    return bool(row and row.status=='ready' and row.draft
                and (row.context or {}).get('workload_pending')
                and not (row.metrics or {}).get('commit'))


def _effective_row(db, row):
    if row is not None and (row.status in {'failed','needs_info'} or _legacy_incomplete_addition(row) or _workload_pending(row)
            or (row.status=='cancelled' and (row.context or {}).get('workload_decision')=='declined')):
        identifier=((row.context or {}).get('fallback_task_id')
                    or (row.context or {}).get('previous_task_id'))
        try:
            fallback=db.get(LearningTask,UUID(identifier)) if identifier else None
        except (ValueError,TypeError):
            return row
        consumed_original=(fallback is not None and fallback.status=='answered'
                           and (fallback.metrics or {}).get('commit')
                           and (_workload_pending(row) or (row.context or {}).get('workload_decision')=='declined'))
        if (fallback is not None and fallback.session_id==row.session_id
                and ((fallback.status=='ready' and not (fallback.metrics or {}).get('commit')) or consumed_original)
                and (fallback.context or {}).get('home_recommendation')
                and not _legacy_incomplete_addition(fallback)):
            return fallback
    return row


def _retained_baseline(row):
    """Legacy failure snapshot, not a ready task or proof of current eligibility.

    GET remains read-only. A user must explicitly restore and pass the existing
    selector/version checks before this collection can be confirmed.
    """
    context=row.context or {}
    paper=context.get('baseline')
    if ((row.status not in {'failed','needs_info'} and not _legacy_incomplete_addition(row)) or not context.get('home_recommendation')
            or (row.metrics or {}).get('commit') or not isinstance(paper,dict)
            or paper.get('error')):
        return None
    questions=paper.get('questions') or []
    if not questions or not paper.get('selected_kp_ids'):
        return None
    if any(not isinstance(q,dict) or not q.get('question_id') or not q.get('question_version_id')
           or type(q.get('minutes')) is not int or q['minutes']<=0 for q in questions):
        return None
    if (len({q['question_id'] for q in questions})!=len(questions)
            or paper.get('total_minutes')!=sum(q['minutes'] for q in questions)
            or type(paper.get('budget_minutes')) is not int
            or paper['total_minutes']>paper['budget_minutes']):
        return None
    return paper


def _preview_view(db, row):
    result = view(row)
    if result is not None:
        required = []
        if result.get('draft') and not result.get('receipt'):
            from backend.services.study_read_context import policies_for_nodes
            policies, _ = policies_for_nodes(db, _allocation_ids(result['draft']), include_missing=True)
            required = sorted(str(key) for key, policy in policies.items()
                              if policy.graduation_binding_pending)
        # Read current policy state for the actual allocated leaves, including
        # topics introduced after the system recommendation. Recovery must not
        # rely on stale flags saved with the original recommendation.
        result['context']['required_graduation_set_transition_ids'] = required
    return result


def _result_view(db, row):
    active=_effective_row(db,row)
    result=_preview_view(db,active)
    if result is not None:
        notice=(row.message if active is not row and row.status in {'failed','needs_info'}
                else (row.context or {}).get('adjustment_notice'))
        if notice:
            result['adjustment_error']=notice
            if (row.context or {}).get('request_origin') in {'system','chat'}:
                result['adjustment_origin']=row.context['request_origin']
        if _workload_pending(row) and not result.get('receipt'):
            result['workload_candidate']=_preview_view(db,row)
        if active is row:
            retained=_retained_baseline(row)
            if retained:
                result['retained_baseline']=retained
                result['adjustment_error']=result['message']
                if (row.context or {}).get('request_origin') in {'system','chat'}:
                    result['adjustment_origin']=row.context['request_origin']
    return result


def _adjustment_view(db, row):
    result=_preview_view(db,row)
    active=_effective_row(db,row)
    if active is not row:
        result['fallback_preview']=_result_view(db,row)
    else:
        retained=_retained_baseline(row)
        if retained:
            result['retained_baseline']=retained
            result['adjustment_error']=row.message
            if (row.context or {}).get('request_origin') in {'system','chat'}:
                result['adjustment_origin']=row.context['request_origin']
    return result


def _workload_target(db, session_id, body):
    if body.target_task_id is None:
        raise AppError('validation_failed',status_code=422)
    row=db.get(LearningTask,body.target_task_id,with_for_update=True)
    if row is None or row.session_id!=session_id or not (row.context or {}).get('home_recommendation'):
        raise AppError('learning_task_not_found',status_code=404)
    latest=_latest(db,session_id)
    if latest is None or latest.id!=row.id:
        raise AppError('learning_task_conflict',status_code=409)
    return row


def _decide_workload(db, row, body, now):
    """Change only workspace selection; formal generation remains confirm()."""
    if row is None or not body.expected_version or _draft_version(row)!=body.expected_version:
        raise AppError('learning_task_conflict',status_code=409)
    accepting=body.action=='accept_workload'
    context=row.context or {}
    if not _workload_pending(row):
        if (accepting and context.get('workload_accepted') and row.status in {'ready','answered'}
                or not accepting and context.get('workload_decision')=='declined'):
            return _result_view(db,row)
        raise AppError('learning_task_stale_draft',status_code=409)
    from datetime import datetime
    if (context['study_date']!=now.astimezone(SHANGHAI).date().isoformat()
            or datetime.fromisoformat(context['expires_at'])<=now):
        raise AppError('learning_task_stale_draft',status_code=409)
    if accepting:
        paper=row.draft
        ids=_allocation_ids(paper)
        candidates=[UUID(q['question_id']) for q in paper['questions']]
        current=_paper(db,ids,row.budget_minutes,now,paper.get('question_limit'),candidates,workload_preview=True)
        if current['questions']!=paper['questions'] or current['total_minutes']!=paper['total_minutes']:
            raise AppError('learning_task_stale_draft',status_code=409)
        for previous in db.scalars(select(LearningTask).where(LearningTask.session_id==row.session_id)):
            if (previous.id!=row.id and previous.status=='ready'
                    and (previous.context or {}).get('home_recommendation')
                    and not (previous.metrics or {}).get('commit')):
                previous.status='cancelled'
    else:
        row.status='cancelled'
    row.context={**context,'workload_pending':False,'workload_accepted':accepting,
                 'workload_decision':'accepted' if accepting else 'declined'}
    if accepting:
        undo_stack=list(context.get('home_undo_stack') or [])
        previous_id=context.get('previous_task_id')
        try:
            previous=db.get(LearningTask, UUID(previous_id)) if previous_id else None
        except (TypeError, ValueError):
            previous=None
        entry=_history_entry(previous, previous.draft if previous else context.get('baseline'))
        if entry and (not undo_stack or undo_stack[-1] != entry):
            undo_stack.append(entry)
        row.context={**row.context,'home_undo_stack':undo_stack[-30:],'home_redo_stack':[]}
    db.flush()
    return _result_view(db,row)


def _legacy_incomplete_addition(row):
    """Fail closed on old append previews that discarded their saved baseline.

    New previews carry bank_scope, including intentional prior scope edits.
    Do not infer a replacement or silently repair historical rows on GET.
    """
    context = row.context or {}
    if row.status != 'ready' or not row.draft or (row.metrics or {}).get('commit'):
        return False
    # A compound per-topic count edit is already routed through exact formal
    # candidate validation and carries its own before/after scope receipt.
    # Do not reclassify its ordinary word “增加” as a legacy bank append.
    if context.get('topic_count_changes') or context.get('subject_plan'):
        return False
    if context.get('bank_scope'):
        scope=context['bank_scope']
        if scope.get('scope_mode')!='append':return False
        expected=(context.get('bank_selection') or {}).get('base_question_ids',[])
        current={q['question_id'] for q in row.draft.get('questions',[])}
        return (not set(expected).issubset(current)
                or not set(scope.get('base_scope_ids',[])).issubset(row.draft.get('selected_kp_ids',[])))
    from backend.services.bank_selection_intent import bank_selection_request
    request = bank_selection_request(row.goal)
    base = {q['question_id'] for q in (context.get('baseline') or {}).get('questions', [])}
    current = {q['question_id'] for q in row.draft.get('questions', [])}
    return bool(request and request.get('append') and base and not base.issubset(current))


def view(row):
    if row is None:
        return None
    context = dict(row.context or {})
    # Undo/redo snapshots are server-side control state. The API exposes only
    # availability flags so clients cannot replay or tamper with stored history.
    context.pop('home_undo_stack', None)
    context.pop('home_redo_stack', None)
    result = {"task_id": str(row.id), "session_id": str(row.session_id), "goal": row.goal,
        "status": row.status, "message": row.message, "error_code": row.error_code, "draft": row.draft,
        "draft_version": _draft_version(row), "budget_minutes": row.budget_minutes,
        "context": context, "receipt": (row.metrics or {}).get("commit")}
    result['undo_available'] = bool((row.context or {}).get('home_undo_stack'))
    result['redo_available'] = bool((row.context or {}).get('home_redo_stack'))
    if _legacy_incomplete_addition(row):
        result.update(status='needs_info', draft=None, error_code='legacy_incomplete_addition',
            message='旧追加方案未保留原推荐，不能确认。请采用系统推荐重新调整；历史记录未删除。')
    return result


def recover(db, session_id):
    _session(db, session_id)
    return _result_view(db,_latest(db, session_id))


def _tools(db, now, goal="", budget=90):
    @contextmanager
    def existing_session():
        yield db
    return TaskTools(existing_session, budget_minutes=budget, now=now, goal=goal)


def _referenced_scope(goal, previous, additions):
    """Resolve explicit ordinal edits against the list actually displayed, not ranking anew."""
    if not previous:
        return None
    values = [q['kp_id'] for q in previous.get('questions', [])] + previous.get('selected_kp_ids', [])
    ids = list(dict.fromkeys(UUID(str(value)) for value in values))
    def number(value):
        return int(value) if value.isdigit() else {'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}.get(value, 0)
    drop = re.fullmatch(r'(?:把)?(?:刚才推荐的|推荐的)?第([一二两三四五六七八九十\d]+)个知识点(?:去掉|移除|删除|删掉|取消)[。！!]?', goal.strip())
    if drop:
        index = number(drop.group(1)) - 1
        return [value for i, value in enumerate(ids) if i != index] if 0 <= index < len(ids) else []
    keep = re.fullmatch(r'(?:只)?保留前([一二两三四五六七八九十\d]+)个知识点(?:[，,\s]*再?增加(.+?))?[。！!]?', goal.strip())
    if keep:
        count = number(keep.group(1))
        if not 0 < count <= len(ids) or (keep.group(2) and not additions):
            return []
        return list(dict.fromkeys(ids[:count] + (list(additions or []) if keep.group(2) else [])))
    return None


def resolve_scope(db, now, goal, previous, selected):
    tools = _tools(db, now, goal)
    if tools.explicit_scope is not None:
        ids = [n.id for n in db.scalars(select(KnowledgePoint).where(
            KnowledgePoint.id.in_(tools.explicit_scope), KnowledgePoint.is_active.is_(True),
            KnowledgePoint.is_assessable.is_(True)).order_by(KnowledgePoint.code))]
    elif selected is not None:
        ids = selected
    elif previous and tools.excluded_scope:
        ids = [UUID(str(k)) for k in previous.get('selected_kp_ids', [])]
    elif previous and (
        re.search(r"改成|改为|缩短|太长|只有\s*\d+\s*分钟", goal)
        or re.fullmatch(r"(?:保留推荐范围[，,\s]*)?(?:减少到|减到|最多|不超过|只做|只练)\s*\d+\s*道(?:题)?[。！!]?", goal.strip())
    ):
        ids = [UUID(k) for k in previous.get("selected_kp_ids", [])]
    else:
        # Unknown natural-language targets must not become unrestricted selection.
        ids = []
    referenced = _referenced_scope(goal, previous, ids if tools.explicit_scope is not None else None)
    if referenced is not None:
        ids = referenced
    elif tools.explicit_scope is not None and ids and previous:
        from backend.services.bank_selection_intent import bank_selection_request
        # Node edits extend the displayed scope; counted bank additions keep
        # their separate candidate-preserving merge below in adjust().
        if (bank_selection_request(goal) is None
                and re.search(r'加进去|加进来|加入|增加|添加|补充', goal)
                and not re.search(r'只练|只做|只保留|替换|改成|改为|不要其他', goal)):
            base = [UUID(str(k)) for k in previous.get('selected_kp_ids', [])]
            ids = list(dict.fromkeys(base + ids))
    return [k for k in dict.fromkeys(ids) if k not in tools.excluded_scope]


def _bank_scope_plan(base_scope_ids, requested_scope_ids, request, *, explicit_scope):
    """Keep the homepage baseline when the user asks to add bank questions.

    An explicitly named additional topic constrains the bank lookup; it does not
    replace the base scope. Replacement remains available only when intent
    parsing marks it explicitly.
    """
    base = list(dict.fromkeys(base_scope_ids or []))
    requested = list(dict.fromkeys(requested_scope_ids or []))
    if request.get('scope_mode') == 'append':
        additional = requested if explicit_scope else base
        selected = list(dict.fromkeys(base + additional))
    else:
        additional = []
        selected = requested
    return {
        'base_scope_ids': base,
        'additional_scope_ids': additional,
        'selected_scope_ids': selected,
        'additional_count': request.get('additional_count') if request.get('scope_mode') == 'append' else None,
        'scope_mode': request.get('scope_mode', 'replace'),
    }


def _paper(db, ids, minutes, now, question_limit=None, candidate_question_ids=None, *, workload_preview=False, coverage_preview=False, selection_diagnostics=None, adaptive_schedule=False):
    # Ranking and eligibility remain shared. Exact bank additions retain their
    # complete candidate collection; workload is confirmed rather than truncated.
    preset = "deep" if minutes > 90 else "standard"
    picked = preview_initial_questions(db, selected_kp_ids=ids, now=now,
        budget=preset, minute_limit=None if workload_preview or coverage_preview else minutes, question_limit=None if workload_preview else question_limit,
        candidate_question_ids=candidate_question_ids,
        per_kp_limit=max(DEFAULT_PER_KP_LIMIT, len(candidate_question_ids)) if candidate_question_ids is not None else DEFAULT_PER_KP_LIMIT,
        require_active_version=True,
        adaptive_schedule=adaptive_schedule,
        **({'selection_diagnostics':selection_diagnostics} if selection_diagnostics is not None else {}))
    from backend.services.study_read_context import question_read_options
    question_ids = list(dict.fromkeys(item[3] for item in picked))
    question_rows = {q.id: q for q in db.scalars(select(Question).options(
        *question_read_options(defer_auto_review_snapshot=True)).where(Question.id.in_(question_ids)))} if question_ids else {}
    node_ids = list(dict.fromkeys(item[0] for item in picked))
    node_rows = {n.id: n for n in db.scalars(select(KnowledgePoint).where(
        KnowledgePoint.id.in_(node_ids)))} if node_ids else {}
    review_events = {str(q.auto_review_event_id): q.current_auto_review
        for q in question_rows.values() if q.auto_review_event_id and q.current_auto_review is not None}
    from backend.services.auto_question_review import preload_uncached_auto_review_snapshots
    preload_uncached_auto_review_snapshots(db,
        [(q, node_rows.get(q.kp_id)) for q in question_rows.values()], review_events)
    version_ids = [q.current_version_id for q in question_rows.values() if q.current_version_id]
    version_rows = {v.id: v for v in db.scalars(select(QuestionVersion).where(
        QuestionVersion.id.in_(version_ids)))} if version_ids else {}
    questions = []
    for kp_id, selection, _, question_id, _ in picked:
        q = question_rows.get(question_id)
        node = node_rows.get(kp_id)
        version = version_rows.get(q.current_version_id) if q and q.current_version_id else None
        assessment = question_eligibility(q, node,
            auto_review_events=review_events) if version and version.is_active else None
        if assessment is None or not assessment.practice_eligible:
            raise ValueError("question_version_or_eligibility_invalid")
        questions.append({"question_id": str(q.id), "question_version_id": str(q.current_version_id),
            "version": question_version_reference(q), "kp_id": str(kp_id), "kp_name": node.name,
            "stem": q.stem, "options": q.options, "difficulty": q.difficulty, "minutes": selection.estimated_minutes,
            "reason": selection.reason, "eligibility": assessment.public_dict()})
    return {"questions": _json_value(questions), "selected_kp_ids": [str(k) for k in ids],
        "budget_minutes": minutes, "total_minutes": sum(q["minutes"] for q in questions),
        "preset": preset, "question_limit": question_limit,
        "_adaptive_schedule": bool(adaptive_schedule and candidate_question_ids is None)}


def _allocation_ids(paper):
    # Selected scope includes explicitly selected empty leaves; formal selection
    # receives only leaves with actual allocated candidates.
    return [UUID(k) for k in paper.get('allocation_kp_ids', paper['selected_kp_ids'])]


def _manual_scope_paper(db, ids, minutes, now, previous, *, diagnostics=None):
    """Deterministic range edit: retain selected old refs, allocate one per new leaf.

    Reuse the formal selector and whole-paper validation. Never cap the merged
    collection to the advisory time budget or mutate the previous snapshot.
    """
    from backend.schemas.home_recommendation import HomePaperValidation
    ids=list(dict.fromkeys(ids))
    diagnostics=diagnostics if diagnostics is not None else {}
    diagnostics.setdefault('diagnostic_id',uuid4().hex)
    diagnostics.update(stage='received',requested_scope_ids=[str(k) for k in ids],nodes=[])
    diagnostics['base_questions']=[{k:q[k] for k in ('question_id','question_version_id')} for q in (previous or {}).get('questions',[])]
    nodes=[]
    for key in ids:
        node=db.get(KnowledgePoint,key)
        if node is None or not node.is_active or not node.is_assessable:
            diagnostics.update(stage='scope_validation',rejected_reason='manual_scope_node_invalid',rejected_kp_id=str(key))
            raise ValueError('manual_scope_node_invalid')
        nodes.append(node)
    chosen=[q for q in (previous or {}).get('questions',[]) if UUID(q['kp_id']) in ids]
    for ref in chosen:
        q=db.get(Question,UUID(ref['question_id']))
        if (q is None or str(q.current_version_id)!=ref['question_version_id']
                or question_version_reference(q)!=ref['version']):
            raise ValueError('manual_retained_question_stale')
    seen={q['question_id'] for q in chosen}
    reasons={}
    for node in nodes:
        retained_count=sum(q['kp_id']==str(node.id) for q in chosen)
        entry={'kp_id':str(node.id),'received':True,'query_attempted':False,'candidates_found':None,
            'eligible_count':None,'candidates_accepted':0,'assigned':retained_count,'rejected_reason':None}
        diagnostics['nodes'].append(entry)
        if retained_count:
            continue
        diagnostics['stage']='node_selection';entry['query_attempted']=True
        try:
            candidate=_paper(db,[node.id],minutes,now,question_limit=1,coverage_preview=True,selection_diagnostics=entry)
        except ValueError as exc:
            entry['rejected_reason']=str(exc)
            if str(exc) not in {'question_pool_incomplete','question_version_or_eligibility_invalid',
                                'graduation_set_transition_confirmation_required'}:
                raise
            reasons[str(node.id)]=('no_eligible_questions' if entry['eligible_count']==0 else 'selection_rejected')
            logging.getLogger(__name__).info('home manual node id=%s result=%s',diagnostics['diagnostic_id'],entry)
            continue
        except Exception as exc:
            entry['rejected_reason']='query_exception';entry['exception_type']=type(exc).__name__
            logging.getLogger(__name__).exception('home manual query failed id=%s node=%s type=%s',diagnostics['diagnostic_id'],node.id,type(exc).__name__)
            raise
        for ref in candidate['questions'][:1]:
            if ref['kp_id']!=str(node.id):
                entry['rejected_reason']='candidate_scope_mismatch'
            elif ref['question_id'] in seen:
                entry['rejected_reason']='duplicate_candidate'
            else:
                chosen.append(ref);seen.add(ref['question_id']);entry.update(candidates_accepted=1,assigned=1)
        if not any(q['kp_id']==str(node.id) for q in chosen):
            reasons[str(node.id)]='no_eligible_questions'
            entry['rejected_reason']=entry['rejected_reason'] or 'no_formal_candidate'
        logging.getLogger(__name__).info('home manual node id=%s result=%s',diagnostics['diagnostic_id'],entry)
    assigned=[k for k in ids if any(q['kp_id']==str(k) for q in chosen)]
    if not chosen:
        raise ValueError('manual_scope_no_allocatable_questions')
    wanted=[UUID(q['question_id']) for q in chosen]
    tools=_tools(db,now)
    tools.nodes.update(assigned);tools.questions.update(wanted)
    for start in range(0,len(assigned),8):
        tools.get_learning_state(db,NodeIds(kp_ids=assigned[start:start+8]))
    tools.required_count=len(wanted)
    tools.budget_minutes=max(minutes,sum(q['minutes'] for q in chosen))
    checked=tools.validate_plan(db,HomePaperValidation(question_ids=wanted,rationale='手动编辑范围，保留原题并逐节点分配；等待用户确认。'))
    diagnostics.update(stage='whole_paper_validation',validation_errors=checked.get('errors',[]))
    if not checked.get('valid'):
        raise ValueError('manual_paper_invalid:'+','.join(checked.get('errors',[])))
    paper=_paper(db,assigned,minutes,now,candidate_question_ids=wanted,workload_preview=True)
    actual={q['question_id']:(q['question_version_id'],q) for q in paper['questions']}
    expected={q['question_id']:q['question_version_id'] for q in chosen}
    if actual.keys()!=expected.keys() or any(actual[qid][0]!=version_id for qid,version_id in expected.items()):
        diagnostics.update(stage='formal_revalidation',rejected_reason='manual_retained_question_identity_or_order_changed')
        raise ValueError('manual_retained_question_identity_or_order_changed')
    # The shared selector may rank the same eligible candidates differently.
    # Keep the user's displayed order after verifying the complete ID/version
    # set, so a scope edit cannot silently reorder or replace retained items.
    paper['questions']=[actual[q['question_id']][1] for q in chosen]
    paper['total_minutes']=sum(q['minutes'] for q in paper['questions'])
    paper.update(selected_kp_ids=[str(k) for k in ids],allocation_kp_ids=[str(k) for k in assigned],
        candidate_question_ids=[str(k) for k in wanted],scope_nodes=[{
            'kp_id':str(node.id),'name':node.name,'parent_id':str(node.parent_id) if node.parent_id else None,
            'assigned_count':sum(q['kp_id']==str(node.id) for q in paper['questions']),
            'allocation_status':reasons.get(str(node.id),'allocated'),
            'allocation_reason':('暂无合格题目' if reasons.get(str(node.id))=='no_eligible_questions' else
                '尚未分配：未满足正式选题资格或策略要求' if str(node.id) in reasons else None),
        } for node in nodes])
    diagnostics.update(stage='assembled',assigned_question_ids=paper['candidate_question_ids'],
        total_count=len(paper['questions']),total_minutes=paper['total_minutes'],
        new_assignment_count=sum(n['candidates_accepted'] for n in diagnostics['nodes']))
    return paper


def _subject_plan_paper(db, ids, minutes, now, *, diagnostics=None):
    """Allocate an adaptive, budget-aware set over every selected subject topic."""
    from backend.schemas.home_recommendation import HomePaperValidation

    ids=list(dict.fromkeys(ids))
    diagnostics=diagnostics if diagnostics is not None else {}
    diagnostics.update(stage='topic_candidate_pools',requested_scope_ids=[str(k) for k in ids],nodes=[])
    pools=[]
    for key in ids:
        node=db.get(KnowledgePoint,key)
        if node is None or not node.is_active or not node.is_assessable:
            raise ValueError('subject_plan_node_invalid')
        node_paper=_paper(db,[key],minutes,now,question_limit=DEFAULT_PER_KP_LIMIT,
            adaptive_schedule=True)
        pool=list(node_paper['questions'])
        diagnostics['nodes'].append({'kp_id':str(key),'name':node.name,
            'candidate_count':len(pool),'candidate_minutes':[q['minutes'] for q in pool],
            'candidate_ids':[q['question_id'] for q in pool]})
        if not pool:
            raise ValueError('subject_plan_topic_no_eligible_question:'+str(key))
        pools.append(pool)

    # First cover all six selected topics, then add FSRS/new candidates in
    # per-topic priority order until the actual estimated-time budget is full.
    chosen=[];seen=set();total=0;offsets=[0]*len(pools);blocked=[False]*len(pools)
    for pool in pools:
        question=pool[0]
        minutes_for_question=question.get('minutes')
        if type(minutes_for_question) is not int or minutes_for_question<=0:
            raise ValueError('subject_plan_question_time_unavailable')
        if total+minutes_for_question>minutes:
            raise ValueError('subject_plan_minimum_coverage_exceeds_budget')
        if question['question_id'] in seen:
            raise ValueError('subject_plan_duplicate_candidate')
        chosen.append(question);seen.add(question['question_id']);total+=minutes_for_question
    offsets=[1]*len(pools)
    progress=True
    while progress and total<minutes:
        progress=False
        for index,pool in enumerate(pools):
            if blocked[index]:continue
            while offsets[index]<len(pool) and pool[offsets[index]]['question_id'] in seen:
                offsets[index]+=1
            if offsets[index]>=len(pool):
                blocked[index]=True;continue
            question=pool[offsets[index]];offsets[index]+=1
            estimate=question.get('minutes')
            if type(estimate) is not int or estimate<=0:
                raise ValueError('subject_plan_question_time_unavailable')
            if total+estimate>minutes:
                blocked[index]=True
                continue
            if question['question_id'] in seen:
                raise ValueError('subject_plan_duplicate_candidate')
            chosen.append(question);seen.add(question['question_id']);total+=estimate;progress=True
            if total>=minutes:break

    wanted=[UUID(q['question_id']) for q in chosen]
    tools=_tools(db,now);tools.nodes.update(ids);tools.questions.update(wanted)
    for start in range(0,len(ids),8):
        tools.get_learning_state(db,NodeIds(kp_ids=ids[start:start+8]))
    tools.required_count=len(wanted);tools.budget_minutes=minutes
    checked=tools.validate_plan(db,HomePaperValidation(question_ids=wanted,
        rationale='按六个低历史知识点与每日时间预算分配FSRS复习题和新题；等待用户确认。'))
    diagnostics.update(stage='whole_paper_validation',validation_errors=checked.get('errors',[]))
    if not checked.get('valid'):
        raise ValueError('subject_plan_invalid:'+','.join(checked.get('errors',[])))

    paper=_paper(db,ids,minutes,now,candidate_question_ids=wanted,workload_preview=True)
    actual={q['question_id']:(q['question_version_id'],q) for q in paper['questions']}
    expected={q['question_id']:q['question_version_id'] for q in chosen}
    if actual.keys()!=expected.keys() or any(actual[qid][0]!=version for qid,version in expected.items()):
        raise ValueError('subject_plan_revalidation_mismatch')
    paper['questions']=[actual[q['question_id']][1] for q in chosen]
    paper['total_minutes']=sum(q['minutes'] for q in paper['questions'])
    counts={str(key):sum(q['kp_id']==str(key) for q in paper['questions']) for key in ids}
    paper.update(selected_kp_ids=[str(key) for key in ids],
        allocation_kp_ids=[str(key) for key in ids],candidate_question_ids=[str(key) for key in wanted],
        question_limit=len(wanted),scope_nodes=[{
            'kp_id':str(key),'name':db.get(KnowledgePoint,key).name,
            'parent_id':str(db.get(KnowledgePoint,key).parent_id) if db.get(KnowledgePoint,key).parent_id else None,
            'assigned_count':counts[str(key)],'allocation_status':'allocated','allocation_reason':None,
        } for key in ids])
    diagnostics.update(stage='assembled',assigned_question_ids=paper['candidate_question_ids'],
        total_count=len(paper['questions']),total_minutes=paper['total_minutes'],
        budget_minutes=minutes,topic_count=len(ids))
    return paper


def _home_inventory(db, ids, now):
    """Return exact, per-selected-scope counts from formally eligible questions.

    Question availability already derives these summaries from live question
    records and formal admission checks. Aggregate descendants per selected
    topic so parent scopes remain accurate, and retain zero-count selections.
    The internal per-node diagnostic rows are discarded before persistence.
    """
    from backend.services.question_availability import question_availability, _descendant_ids
    ids=list(dict.fromkeys(ids or []))
    if not ids:
        return None
    inventory=question_availability(db,now=now,kp_ids=ids,limit=24,include_node_summaries=True)
    summaries=inventory.pop('node_summaries',[])
    by_id={UUID(str(row['kp_id'])):row for row in summaries}
    recommendation_nodes=[]
    for kp_id in ids:
        node=db.get(KnowledgePoint,kp_id)
        descendants=_descendant_ids(db,{kp_id})
        scoped=[row for node_id,row in by_id.items() if node_id in descendants]
        recommendation_nodes.append({
            'kp_id':str(kp_id),
            'name':node.name if node else '',
            'practice_eligible_count':sum(int(row.get('practice_eligible_count') or 0) for row in scoped),
            'available_to_append_count':sum(int(row.get('available_to_append_count') or 0) for row in scoped),
        })
    inventory['recommendation_nodes']=recommendation_nodes
    return inventory


def read_system(db, recommendations, now, *, include_evidence=True):
    """Read the canonical recommendation without creating a conversation or task."""
    # Keep request-local strong references: SQLAlchemy's weak identity map
    # otherwise reloads the same nodes during inventory and paper assembly.
    scope_nodes = list(db.scalars(select(KnowledgePoint).options(
        selectinload(KnowledgePoint.children))))
    ids = [r.kp_id for r in recommendations]
    inventory = _home_inventory(db,ids,now)
    paper, blockers = None, []
    if ids:
        try:
            paper = _paper(db, ids, 90, now, adaptive_schedule=True)
        except ValueError as exc:
            blockers.append(f"正式选题暂不能形成初案：{exc}；请核对题库资格或选择其他范围。")
    else:
        blockers.append("当前没有可推荐的考核节点，请在知识树选择现有范围。")
    states = []
    if include_evidence:
        tools = _tools(db, now)
        tools.nodes.update(ids)
        for kp_id in ids:
            states.extend(tools.get_learning_state(db, NodeIds(kp_ids=[kp_id]))["states"])
    return _json_value({"recommendations": [r.model_dump(mode="json") for r in recommendations],
        "inventory": inventory, "initial_paper": paper, "blockers": blockers,
        "evidence": {"states": states, "captured_at": now.isoformat()},
        "note": "90分钟仅为可调整的建议预算。推荐依据为系统策略和已有记录；没有客观作答时是初始诊断，不代表已识别薄弱点。库存数量不代表掌握度。"})


def _bank_failure(exc, stage):
    from pydantic import ValidationError
    from sqlalchemy.exc import SQLAlchemyError
    if isinstance(exc, ValidationError):
        return 'bank_parameter_contract_error', '选题参数与内部接口不一致'
    if isinstance(exc, SQLAlchemyError):
        return 'bank_database_error', '题库数据库查询暂时异常'
    if stage == 'query':
        return 'bank_query_error', '真实题库查询服务异常'
    return 'bank_internal_error', '题目合并或校验程序异常'


def _target_time_choices(choices, remaining, states):
    """Bounded subset selection over already eligible, versioned bank results.

    Never changes the baseline. Unknown evidence is not labelled weakness.
    Prefer observed errors for equal time; preserve tool order otherwise.
    """
    remaining=max(0,min(240,int(remaining)))
    def priority(q):
        state=states.get(q.get('kp_id'),{})
        wrong=sum(a.get('result')=='wrong' for a in state.get('recent_attempts',[]))
        return -wrong
    ordered=sorted(choices,key=priority)
    paths={0:[]}
    for q in ordered:
        duration=q.get('minutes')
        if type(duration) is not int or duration<=0:continue
        for total,path in sorted(list(paths.items()),reverse=True):
            new=total+duration
            if new<=remaining and new not in paths:paths[new]=path+[q]
    return paths[max(paths)]


def _bank_candidates(db, now, goal, ids, previous, request, minutes, *, base_scope_ids=None, diagnostics=None):
    """Use the existing bounded bank tools; preserve a valid displayed paper on add."""
    diagnostics = diagnostics if diagnostics is not None else {}
    diagnostics.update(stage='retained_versions',scope_ids=[str(k) for k in ids],budget_minutes=minutes)
    retained = list(previous.get('questions', [])) if previous and request['append'] else []
    diagnostics['retained_count']=len(retained)
    if not ids:
        return None, {'tool':'find_questions', 'error':'bank_scope_needed'}, '请明确要从哪个知识点范围选题；没有使用其他会话的范围，也没有加入今日卷。'
    base_scope_ids=list(dict.fromkeys(base_scope_ids or []))
    all_ids=list(dict.fromkeys(base_scope_ids+ids+[UUID(q['kp_id']) for q in retained]))
    for ref in retained:
        q=db.get(Question,UUID(ref['question_id']))
        if q is None or str(q.current_version_id)!=ref['question_version_id'] or question_version_reference(q)!=ref['version']:
            return None, {'tool':'find_questions','error':'bank_preview_stale'}, '原预览题目已不存在或版本已变化，请重新生成预览；没有替换旧题或加入今日卷。'
    tools = _tools(db, now, goal, minutes)
    tools.required_difficulty=request['difficulty']
    tools.nodes.update(all_ids)
    tools.explicit_scope = set(all_ids)
    reference=None
    if request.get('similar'):
        reference=request.get('similar_reference')
        if reference is None:
            questions=(previous or {}).get('questions',[])
            if len(questions)!=1:
                return None, {'tool':'find_questions','error':'similar_reference_required'}, '请先明确一题作为相似题的参照；没有生成新题或加入今日卷。'
            reference={'question_id':questions[0]['question_id'],'version_id':questions[0]['question_version_id']}
    tools.handoff = {'constraints':{'existing_bank_only':True,'include_personal_bank':request.get('include_personal',False),
        'preview_query_state':{'excluded_question_types':request.get('excluded_question_types',[]),
                               'excluded_difficulties':request.get('excluded_difficulties',[])},
        'similar_requested':request.get('similar',False),'similar_reference':reference,
        'home_requested_count':1000 if request.get('target_minutes') else request['count'],
        'home_unattempted_only':not bool(re.search(r'重练|重做|已做过的也可以',goal))}}
    for start in range(0,len(all_ids),8):
        tools.get_learning_state(db,NodeIds(kp_ids=all_ids[start:start+8]))
    from backend.schemas.learning_task import FindQuestions
    from backend.schemas.home_recommendation import HomePaperValidation, HomeBankQuery
    diagnostics['stage']='query_parameters'
    query_args=HomeBankQuery(kp_ids=ids,question_type=request.get('question_type') or getattr(tools,'required_type',None),
        exclude_question_ids=[UUID(q['question_id']) for q in retained])
    diagnostics['stage']='query'
    found = tools.find_questions(db,query_args)
    diagnostics.update(stage='candidate_merge',returned_count=len(found.get('questions',[])),candidate_list_complete=found.get('candidate_list_complete'))
    if found.get('error'):
        return None, {'tool':'find_questions','error':found['error']}, found.get('hint','题库检索失败，请重试；没有加入今日卷。')
    choices=[];seen={q['question_id'] for q in retained}
    for candidate in found.get('questions',[]):
        if (candidate['question_id'] in seen or candidate['in_today_plan'] or not candidate.get('question_version')
                or tools.handoff['constraints']['home_unattempted_only'] and candidate.get('previously_attempted')):
            continue
        seen.add(candidate['question_id']);choices.append(candidate)
    evidence = {'tool':'find_questions', 'scope_ids':[str(k) for k in ids], 'difficulty':request['difficulty'],
        'requested_count':request['count'], 'candidate_ids':[q['question_id'] for q in choices],
        'candidate_list_complete':found.get('candidate_list_complete'), 'retained_ids':[q['question_id'] for q in retained],
        'base_scope_ids':[str(k) for k in base_scope_ids],
        'additional_scope_ids':[str(k) for k in ids] if request.get('scope_mode') == 'append' else [],
        'additional_count':request.get('additional_count') if request.get('scope_mode') == 'append' else None,
        'scope_mode':request.get('scope_mode','replace'),
        'base_question_ids':[q['question_id'] for q in retained]}
    target=request.get('target_minutes')
    chosen = (_target_time_choices(choices,target-sum(q['minutes'] for q in retained),getattr(tools,'state_facts',{}))
              if target else choices[:request['count']])
    if target:
        evidence['target_time']={'target_minutes':target,'original_minutes':sum(q['minutes'] for q in retained),
            'actual_minutes':sum(q['minutes'] for q in retained+chosen),
            'candidate_list_complete':found.get('candidate_list_complete')}
    evidence['additional_candidate_ids'] = [q['question_id'] for q in chosen]
    evidence['selected_addition_ids'] = [q['question_id'] for q in chosen]
    if not target and len(chosen) < request['count']:
        evidence['error']='bank_candidates_insufficient'
        if not choices and found.get('home_attempted_excluded_count',0) and found.get('candidate_list_complete'):
            evidence['error']='bank_unattempted_exhausted'
            return None,evidence,'该范围剩余合格题都已做过，没有新的未做题可追加；若想重练，请明确要求重练。原方案未删题，未创建正式卷。'
        if not choices and any(UUID(q['kp_id']) in ids for q in retained) and found.get('candidate_list_complete'):
            return None,evidence,'当前范围没有新的合格题可追加，已有题目已安排在当前方案中；没有重复加入，也未删除原题。'
        return None, evidence, f"已查询真实题库，当前范围及难度要求下可新增 {len(choices)} 道，少于所需 {request['count']} 道；没有加入今日卷。若候选读取不完整，请缩小范围重试。"
    if target and not chosen:
        evidence['error']='bank_target_no_fitting_candidates'
        return None,evidence,'未找到能在剩余目标时间内追加的合格题目；原有效方案已保留，没有虚构题目凑时长。'
    wanted=[UUID(q['question_id']) for q in retained+chosen]
    replacement=request.get('replacement_index')
    if replacement is not None:
        if len(chosen)!=1 or not 0<=replacement<len(retained):
            raise ValueError('replacement_target_invalid')
        wanted=[UUID(q['question_id']) for q in retained]
        wanted[replacement]=UUID(chosen[0]['question_id'])
    for candidate in chosen:
        current=db.get(Question,UUID(candidate['question_id']))
        if current is None or question_version_reference(current)!=candidate['question_version']:
            evidence['error']='bank_candidate_stale'
            return None,evidence,'新增候选的题目版本已变化，请重新检索；原方案未替换，也未写入今日卷。'
    # Feed retained rows through the same read boundary before validation too.
    if retained:
        tools.questions.update(UUID(q['question_id']) for q in retained)
    tools.required_count=len(wanted)
    # Difficulty applies to the requested additions, not to previously accepted questions.
    tools.required_difficulty=None
    tools.required_type=None
    tools.basic_only=False
    diagnostics.update(stage='validation_parameters',merged_count=len(wanted))
    validation_args=HomePaperValidation(question_ids=wanted,rationale='保留当前预览并追加真实题库候选；等待用户确认。')
    diagnostics['stage']='whole_paper_validation'
    checked=tools.validate_plan(db,validation_args)
    if not checked.get('valid'):
        evidence['error']='bank_plan_invalid'; evidence['validation']=checked
        selected_rows=[db.get(Question,question_id) for question_id in wanted]
        total_minutes=sum(q.estimated_minutes for q in selected_rows if q is not None)
        evidence['combined_minutes']=total_minutes
        evidence['budget_minutes']=minutes
        if set(checked.get('errors',[])) == {'time_budget_exceeded'}:
            # Keep the whole collection and re-run every shared validation rule.
            tools.budget_minutes=total_minutes
            checked=tools.validate_plan(db,HomePaperValidation(question_ids=wanted,rationale='完整保留原题和追加题；超出原预算需用户确认。'))
            if checked.get('valid'):
                evidence.pop('error',None)
                evidence['budget_validation']=evidence['validation']
                evidence['validation']=checked
                evidence['workload']={'requested_budget_minutes':minutes,'effective_budget_minutes':total_minutes,
                    'extra_minutes':total_minutes-minutes,'requires_confirmation':True}
                evidence['selected_ids']=[str(k) for k in wanted]
                evidence['matches']={q['question_id']:{'match_basis':q.get('match_basis'),'source_category':q.get('source_category')} for q in chosen}
                return wanted,evidence,None
        return None,evidence,'选题未通过正式范围、资格、去重或预算校验：'+ '、'.join(checked.get('errors',[]))+'；没有加入今日卷。'
    evidence['selected_ids']=[str(k) for k in wanted]
    evidence['matches']={q['question_id']:{'match_basis':q.get('match_basis'),'source_category':q.get('source_category')} for q in chosen}
    return wanted,evidence,None


def _subject_plan_scope(db, now, *, subject, count, unattempted_only=False):
    """Select fresh/low-history topics while retaining any genuinely due FSRS nodes."""
    from backend.api.routes.study import _recommendations
    candidates=_recommendations(db,now,subject=subject,limit=1000)
    if not candidates:return [],[]
    ids=[row.kp_id for row in candidates]
    attempts={str(kp_id):int(total) for kp_id,total in db.execute(
        select(QuestionAttempt.kp_id,func.count(QuestionAttempt.id))
        .where(QuestionAttempt.kp_id.in_(ids)).group_by(QuestionAttempt.kp_id)).all()}
    if unattempted_only:
        # An explicit "没做过" constraint is a hard filter. Due review stays
        # available to ordinary adaptive plans, but cannot override this
        # user's request to choose only never-attempted, still-unseen topics.
        candidates=[row for row in candidates
            if attempts.get(str(row.kp_id),0)==0 and row.state=='unseen']
        ids=[row.kp_id for row in candidates]
    original_order={str(row.kp_id):index for index,row in enumerate(candidates)}
    def rank(row):
        due=row.reason=='due_review' or '到期' in (row.next_step or '')
        history=attempts.get(str(row.kp_id),0)
        unseen=history==0 and row.state=='unseen'
        # Due memory is never cooled down or discarded; among other candidates,
        # unlearned/low-history nodes lead, then the scheduler's BKT/cooldown rank.
        return (0 if due else 1,0 if unseen else 1,history,original_order[str(row.kp_id)])
    ordered=sorted(candidates,key=rank)
    chosen=ordered[:count]
    return [row.kp_id for row in chosen],[{
        'kp_id':str(row.kp_id),'name':row.name,'attempt_count':attempts.get(str(row.kp_id),0),
        'reason':row.reason,'due_review':row.reason=='due_review' or '到期' in (row.next_step or ''),
    } for row in chosen]


def _ensure_scope_node_names(db, paper):
    """补齐草案中每个已选知识点的 scope_nodes 名称与题量。

    历史草案存在只保存 selected_kp_ids、scope_nodes 为空的情况：前端只能
    用品题的 kp_name 反推名称，一旦某知识点被减到 0 题，名称就变成空白
    （用户看到“· 11道可用题 今日安排 0 道”）。这里在保存草案前用
    knowledge_points 的真实名称统一补齐，避免名称随题量归零而丢失。
    """
    if not isinstance(paper, dict):
        return paper
    selected=[str(k) for k in paper.get('selected_kp_ids') or []]
    if not selected:
        return paper
    existing={str(node.get('kp_id')):node for node in paper.get('scope_nodes') or []
        if isinstance(node,dict) and node.get('kp_id')}
    questions=paper.get('questions') or []
    nodes=[]
    for key in selected:
        base=dict(existing.get(key) or {'kp_id':key})
        node=db.get(KnowledgePoint,UUID(key))
        if not base.get('name'):
            base['name']=node.name if node else ''
        if not base.get('parent_id'):
            base['parent_id']=str(node.parent_id) if node is not None and node.parent_id else None
        count=sum(str(q.get('kp_id'))==key for q in questions)
        base['assigned_count']=count
        base['allocation_status']='allocated' if count else 'no_eligible_questions'
        base.setdefault('allocation_reason',None)
        nodes.append(base)
    paper['scope_nodes']=nodes
    return paper


def _mentioned_outside_topic(db, goal, paper):
    """文本点名的知识点已不在当前方案时返回其名称，否则 None。

    “我今天不学洛必达法则”会把该知识点整体移出今日范围；用户随后再说
    “删除洛必达法则的题目”时，方案里已没有它的引用，纯规则层只能要求重新
    指定知识点。这里用真实知识点表补一句准确状态，避免用户被反复要求重述。
    """
    current={str(k) for k in (paper or {}).get('selected_kp_ids') or []}
    matched=[node for node in db.scalars(select(KnowledgePoint).where(KnowledgePoint.is_active.is_(True)))
        if node.name and node.name in goal]
    matched.sort(key=lambda node: len(node.name), reverse=True)
    seen=set()
    for node in matched:
        if node.name in seen:
            continue
        seen.add(node.name)
        if all(str(peer.id) not in current for peer in matched if peer.name==node.name):
            return node.name
    return None


def _topic_count_revision(db, now, previous, intent, goal, minutes):
    """Apply named topic count deltas to a draft using formally admitted bank candidates."""
    from copy import deepcopy
    from backend.services.home_intent import reference_map
    from backend.services.question_availability import question_availability

    if not previous or not previous.get('questions'):
        return None, [], '当前没有可调整的学习方案；原方案未改变。'
    refs=reference_map(previous)
    selected=list(dict.fromkeys(UUID(str(k)) for k in previous.get('selected_kp_ids',[])))
    result=deepcopy(previous)
    summaries=[]
    for ref,delta in zip(intent.refs,intent.deltas):
        target=refs.get(ref)
        if not target or target.get('kind')!='scope':
            return None, [], '目标知识点已不在当前方案中；原方案未改变。'
        kp_id=UUID(str(target['value']))
        node=db.get(KnowledgePoint,kp_id)
        if kp_id not in selected or node is None or not node.is_active or not node.is_assessable:
            return None, [], f'{target.get("name") or "目标知识点"}不在当前可调整范围内；原方案已保留。'
        current=[q for q in result['questions'] if q.get('kp_id')==str(kp_id)]
        if delta<0:
            requested=-delta
            if requested>len(current):
                return None, [], f'{node.name}当前方案只有{len(current)}道题，无法减少{requested}道；原方案已保留。'
            # Without a verified per-question difficulty label there is no
            # claim about which item is easier; remove the last displayed item
            # in this topic's stable plan order and report only the count.
            remove_ids={q['question_id'] for q in current[-requested:]}
            result['questions']=[q for q in result['questions'] if q['question_id'] not in remove_ids]
            summaries.append({'kp_id':str(kp_id),'name':node.name,'delta':-requested,
                'before_count':len(current),'count':len(current)-requested,
                'removed_question_ids':[q['question_id'] for q in current if q['question_id'] in remove_ids],
                'added_question_ids':[],'protected_count':0})
            continue

        request={'count':delta,'append':True,'scope_mode':'append','additional_count':delta,
            'difficulty':None,'question_type':None,'excluded_question_types':[],
            'excluded_difficulties':[],'bank_source':True,'include_personal':False,
            'similar':False}
        diagnostics={'stage':'topic_count_query','kp_id':str(kp_id),'requested_count':delta}
        wanted,evidence,error=_bank_candidates(db,now,goal,[kp_id],result,request,minutes,
            base_scope_ids=selected,diagnostics=diagnostics)
        if error or not wanted:
            availability=question_availability(db,now=now,kp_ids=[kp_id],limit=1)
            eligible=int(availability.get('practice_eligible_count') or 0)
            # The inventory endpoint does not know about this pending draft.
            # Its available_to_append_count can therefore include questions
            # already pinned in the preview. Use the actual candidate query,
            # which excludes both retained draft IDs and prior attempts.
            candidate_count=len((evidence or {}).get('candidate_ids') or [])
            complete=(evidence or {}).get('candidate_list_complete') is True
            failure_id=uuid4().hex
            logging.getLogger(__name__).warning(
                'home topic count addition rejected id=%s stage=topic_count_candidate_query kp_id=%s requested=%s candidates=%s complete=%s error=%s',
                failure_id,kp_id,delta,candidate_count,complete,(evidence or {}).get('error'))
            if eligible==0:
                reason='没有符合正式准入条件的题目；不合格题已自动排除'
            elif candidate_count==0:
                reason='本次查询没有找到可追加的新题；题库合格总量可能已被当前草案占用，或题目已有作答记录'
            else:
                reason=f'本次候选查询找到{candidate_count}道未在当前草案中的合格题，少于需要的{delta}道'
            if not complete:
                reason+='；候选列表不完整，无法据此确认全库是否还有更多可用题'
            elif error:
                reason+=f'；候选校验原因：{error.rstrip("。")}'
            return None, [], (f'{node.name}未能增加{delta}道：{reason}。原方案已保留。'
                f'服务分支 home_recommendation_service.topic_count_candidate_query，错误编号 {failure_id}。')

        allocation=list(dict.fromkeys(db.get(Question,UUID(str(qid))).kp_id for qid in wanted))
        next_paper=_paper(db,allocation,minutes,now,candidate_question_ids=[UUID(str(qid)) for qid in wanted],
            workload_preview=True)
        next_paper['selected_kp_ids']=[str(k) for k in selected]
        next_paper['allocation_kp_ids']=[str(k) for k in allocation]
        next_paper['candidate_question_ids']=[str(k) for k in wanted]
        prior_nodes={str(n.get('kp_id')):n for n in result.get('scope_nodes') or []}
        question_names={q['kp_id']:q.get('kp_name','') for q in next_paper['questions']}
        next_paper['scope_nodes']=[{
            'kp_id':str(key),'name':(prior_nodes.get(str(key)) or {}).get('name') or
                (db.get(KnowledgePoint,key).name if db.get(KnowledgePoint,key) else question_names.get(str(key),'')),
            'parent_id':str(db.get(KnowledgePoint,key).parent_id) if db.get(KnowledgePoint,key) and db.get(KnowledgePoint,key).parent_id else None,
            'assigned_count':sum(q['kp_id']==str(key) for q in next_paper['questions']),
            'allocation_status':'allocated' if any(q['kp_id']==str(key) for q in next_paper['questions']) else 'no_eligible_questions',
            'allocation_reason':None,
        } for key in selected]
        result=next_paper
        summaries.append({'kp_id':str(kp_id),'name':node.name,'delta':delta,
            'before_count':len(current),
            'count':sum(q.get('kp_id')==str(kp_id) for q in result['questions']),
            'removed_question_ids':[],
            'added_question_ids':[q['question_id'] for q in result['questions']
                if q.get('kp_id')==str(kp_id) and q['question_id'] not in {old['question_id'] for old in current}],
            'protected_count':0})

    result['total_minutes']=sum(int(q['minutes']) for q in result['questions'])
    result['question_limit']=len(result['questions'])
    result['allocation_kp_ids']=list(dict.fromkeys(q['kp_id'] for q in result['questions']))
    counts={str(k):sum(q['kp_id']==str(k) for q in result['questions']) for k in selected}
    result['scope_nodes']=[{
        'kp_id':str(k),'name':((next((n.get('name') for n in (result.get('scope_nodes') or []) if n.get('kp_id')==str(k)),None))
            or (db.get(KnowledgePoint,k).name if db.get(KnowledgePoint,k) else '')),
        'parent_id':str(db.get(KnowledgePoint,k).parent_id) if db.get(KnowledgePoint,k) and db.get(KnowledgePoint,k).parent_id else None,
        'assigned_count':counts[str(k)],'allocation_status':'allocated' if counts[str(k)] else 'no_eligible_questions',
        'allocation_reason':None,
    } for k in selected]
    return result,summaries,None


def _subject_topic_revision(db, now, previous, intent, minutes):
    """Replace only named current topics with eligible 408 questions in a draft."""
    from copy import deepcopy
    from backend.services.home_intent import reference_map

    if not previous or not previous.get('questions'):
        return None, None, '当前没有可调整的学习方案；原方案未改变。'
    refs=reference_map(previous)
    source_ids=[]
    for ref in intent.refs:
        target=refs.get(ref)
        if not target or target.get('kind')!='scope':
            return None, None, '要替换的原知识点已不在当前方案中；原方案已保留。'
        source_ids.append(str(target['value']))
    source_questions=[q for q in previous['questions'] if q['kp_id'] in set(source_ids)]
    if not source_questions:
        return None, None, '所选原知识点当前没有题目；当前方案未改变。'
    if intent.quantity is not None and len(source_questions)!=intent.quantity:
        return None, None, f'当前有效方案中目标范围有{len(source_questions)}道题，与读取时的{intent.quantity}道不一致；原方案已保留，请重新读取。'

    topic_count=int(intent.topic_count or 1)
    target_count=max(len(source_questions),topic_count)
    if target_count<topic_count:
        return None, None, '题目数量不足以覆盖请求的408知识点数量；原方案已保留。'
    selected,selection_facts=_subject_plan_scope(db,now,subject='408',count=1000,
        unattempted_only=bool(intent.unattempted_only))
    if intent.destination_topic:
        wanted=intent.destination_topic.strip()
        explicit=[key for key in selected if (db.get(KnowledgePoint,key) and
            (wanted in db.get(KnowledgePoint,key).name or
             wanted in db.get(KnowledgePoint,key).code or
             any(alias==wanted for alias in __import__('backend.services.home_intent',fromlist=['_topic_aliases'])._topic_aliases(db.get(KnowledgePoint,key).name))))]
        if explicit:
            selected=explicit[:topic_count]
        else:
            return None, None, f'408中没有找到符合正式准入及学习记录条件的“{wanted}”知识点；原方案已保留。'
    if target_count<topic_count:
        return None, None, f'当前需至少{topic_count}道题才能覆盖所选408知识点，原知识点仅有{target_count}道；原方案已保留。'

    retained=[q for q in previous['questions'] if q['kp_id'] not in set(source_ids)]
    seen={q['question_id'] for q in retained+source_questions}
    pools=[]
    diagnostics=[]
    ranked_candidates=list(selected)
    if not intent.destination_topic and topic_count>1:
        ranked_candidates=ranked_candidates[:max(topic_count,topic_count*3)]
    elif not intent.destination_topic:
        ranked_candidates=ranked_candidates[:24]
    elif intent.destination_topic:
        ranked_candidates=ranked_candidates[:topic_count]
    for kp_id in ranked_candidates:
        node=db.get(KnowledgePoint,kp_id)
        if node is None or not node.is_active or not node.is_assessable:
            diagnostics.append({'kp_id':str(kp_id),'stage':'candidate_query','reason':'inactive_or_unassessable'})
            continue
        per_topic_need=(target_count//topic_count)+(1 if len(pools)<target_count%topic_count else 0)
        try:
            pool_paper=_paper(db,[kp_id],max(int(minutes),5),now,
                question_limit=max(DEFAULT_PER_KP_LIMIT,per_topic_need),coverage_preview=True,
                adaptive_schedule=True)
        except Exception as exc:
            diagnostics.append({'kp_id':str(kp_id),'stage':'candidate_query',
                'error_type':type(exc).__name__,'reason':str(exc)[:100]})
            return None, {'topics':selection_facts,'diagnostics':diagnostics}, f'读取408知识点“{node.name}”正式候选失败（{type(exc).__name__}）；原方案已保留。'
        pool=[q for q in pool_paper['questions'] if q['question_id'] not in seen]
        if not pool:
            diagnostics.append({'kp_id':str(kp_id),'stage':'candidate_query','eligible_unseen_count':0})
            continue
        pools.append((kp_id,pool))
        # With no named destination and a single replacement topic, preserve
        # the scheduler's history ranking but skip low-stock topics until one
        # can actually honor the source topic's full quantity. Never silently
        # shrink the requested plan to whatever happened to be first.
        if topic_count==1 and len(pool)>=target_count:
            break
        if topic_count>1 and len(pools)>=topic_count:
            break

    if len(pools)<topic_count:
        return None, {'topics':selection_facts,'diagnostics':diagnostics}, f'当前仅有{len(pools)}个符合正式准入且有可用题的408知识点，少于请求的{topic_count}个；原方案已保留。'
    if topic_count==1:
        adequate=next(((key,pool) for key,pool in pools if len(pool)>=target_count),None)
        if adequate is None:
            available=max((len(pool) for _,pool in pools),default=0)
            return None, {'topics':selection_facts,'diagnostics':diagnostics}, f'按学习记录顺序检查后，408单个知识点最多有{available}道未重复的正式合格题，少于原题量{target_count}道；原方案已保留。'
        pools=[adequate]
    selected=[key for key,_ in pools]
    pools=[pool for _,pool in pools]
    if sum(len(pool) for pool in pools)<target_count:
        return None, {'topics':selection_facts,'diagnostics':diagnostics}, f'所选{topic_count}个408知识点共有{sum(len(pool) for pool in pools)}道未重复的正式合格题，少于所需{target_count}道；原方案已保留。'

    chosen=[]
    # Every requested topic gets a question before any topic gets a second one.
    if target_count<topic_count:
        return None, {'topics':selection_facts}, f'保持原题量时无法覆盖{topic_count}个408知识点；原方案已保留。'
    offsets=[0]*len(pools)
    for index,pool in enumerate(pools):
        candidate=pool[0]
        if candidate['question_id'] in seen:return None, {'topics':selection_facts}, '408候选出现重复题目；原方案已保留。'
        chosen.append(candidate);seen.add(candidate['question_id']);offsets[index]=1
    while len(chosen)<target_count:
        progressed=False
        for index,pool in enumerate(pools):
            while offsets[index]<len(pool) and pool[offsets[index]]['question_id'] in seen:
                offsets[index]+=1
            if offsets[index]>=len(pool):continue
            candidate=pool[offsets[index]];offsets[index]+=1
            chosen.append(candidate);seen.add(candidate['question_id']);progressed=True
            if len(chosen)==target_count:break
        if not progressed:
            return None, {'topics':selection_facts}, f'408合格且未重复的候选只有{len(chosen)}道，少于所需{target_count}道；原方案已保留。'

    result=deepcopy(previous)
    questions=retained+chosen
    result['questions']=questions
    replacement_ids={str(key) for key in selected}
    result['selected_kp_ids']=[key for key in previous['selected_kp_ids'] if key not in set(source_ids)]
    result['selected_kp_ids']=list(dict.fromkeys(result['selected_kp_ids']+[str(key) for key in selected]))
    result['allocation_kp_ids']=list(dict.fromkeys(q['kp_id'] for q in questions))
    result['candidate_question_ids']=[q['question_id'] for q in questions]
    result['question_limit']=len(questions)
    result['budget_minutes']=int(minutes)
    result['preset']='deep' if minutes>90 else 'standard'
    result['total_minutes']=sum(int(q['minutes']) for q in questions)
    result['_adaptive_schedule']=False
    names={str(key):db.get(KnowledgePoint,key).name for key in selected if db.get(KnowledgePoint,key)}
    for key in result['selected_kp_ids']:
        node=db.get(KnowledgePoint,UUID(key))
        names.setdefault(key,node.name if node else '')
    result['scope_nodes']=[{'kp_id':key,'name':names.get(key,''),
        'parent_id':str(db.get(KnowledgePoint,UUID(key)).parent_id) if db.get(KnowledgePoint,UUID(key)) and db.get(KnowledgePoint,UUID(key)).parent_id else None,
        'assigned_count':sum(q['kp_id']==key for q in questions),
        'allocation_status':'allocated' if any(q['kp_id']==key for q in questions) else 'no_eligible_questions',
        'allocation_reason':None} for key in result['selected_kp_ids']]
    result['diff']={'added':sorted({q['question_id'] for q in chosen}),
        'removed':sorted({q['question_id'] for q in source_questions}),
        'retained':sorted({q['question_id'] for q in retained})}
    topic_summary={'source_kp_ids':source_ids,
        'source_topics':[{'kp_id':key,'name':refs[ref]['name'],
            'before_count':sum(q['kp_id']==key for q in source_questions)} for ref,key in zip(intent.refs,source_ids)],
        # The canonical system baseline may not contain a user-selected topic.
        # Keep the exact pre-replacement source snapshot in server-side task
        # context so “restore original topic” works for every editable draft.
        'source_questions_snapshot':deepcopy(source_questions),
        'destination_topics':[{'kp_id':str(key),'name':names.get(str(key),''),
            'assigned_count':sum(q['kp_id']==str(key) for q in chosen)} for key in selected],
        'removed_count':len(source_questions),'added_count':len(chosen),
        'budget_minutes':int(minutes),'estimated_minutes':result['total_minutes'],
        'unattempted_only':bool(intent.unattempted_only)}
    return result,topic_summary,None


def _bank_exact_revision(db,now,goal,previous,operation,minutes,refs):
    """Build an exact candidate with existing bank tools and formal selection.

    Returns a detached snapshot only. adjust() publishes it using its existing
    savepoint, version, workload acceptance and last-valid-plan protection.
    """
    import copy
    from backend.services.bank_selection_intent import bank_selection_request
    request=bank_selection_request('加入一道题')
    request.update((bank_selection_request('加入一道题；'+goal) or {}))
    request.update(append=True,scope_mode='append',count=1,additional_count=1)
    scopes=[UUID(k) for k in previous['selected_kp_ids']]
    if operation=='fill_time':
        if previous['total_minutes']>=minutes:
            return None,{},'当前方案已达到目标时长，原题没有删减；如需缩减请明确说明。'
        request['target_minutes']=minutes
        query_tools=_tools(db,now,goal,minutes)
        if query_tools.explicit_scope is not None:
            scopes=[k for k in scopes if k in query_tools.explicit_scope]
    else:
        index=int(refs[0][1:])-1
        target=previous['questions'][index]
        request['replacement_index']=index
        scopes=[UUID(target['kp_id'])]
        explicit=_tools(db,now,goal,minutes).explicit_scope
        if explicit is not None and set(explicit)!=set(scopes):
            return None,{},'这次单题替换需要确认新的知识点范围；当前只按原题知识点安全替换，原方案已保留。'
        named=re.search(r'(?:换成|替换为)(?:一|1)?道?\s*(.*?)(?:题目|题)',goal)
        if named and explicit is None:
            rest=re.sub(r'同知识点|同类型|选择|单选|填空|计算|证明|基础|简单|困难|中等|较难|难一点|更难|更简单|的|一道|1道|\s','',named[1])
            if rest:return None,{},'无法核对替换要求中的知识点，请明确现有知识点或同知识点替换；原方案已保留。'
        if request.get('similar'):
            request['similar_reference']={'question_id':target['question_id'],'version_id':target['question_version_id']}
        if re.search(r'难一点|更难|难一些',goal):
            order={'basic':0,'medium':1,'improved':1,'hard':2,'advanced':3,'comprehensive':3,'challenge':3}
            if target.get('difficulty') not in order or order[target['difficulty']]>=2:
                return None,{},'无法保证候选比这道题更难，请指定绝对难度或其他条件；原方案已保留。'
    type_names={'单选题':'single_choice','选择题':'single_choice','填空题':'fill_blank','计算题':'calculation','证明题':'proof'}
    requested_types={kind for name,kind in type_names.items() if name in goal and kind not in request.get('excluded_question_types',[])}
    if len(requested_types)>1:return None,{},'一次替换或补题包含多个题型，请分别说明；原方案已保留。'
    request['question_type']=next(iter(requested_types),None)
    if operation=='replace_question' and not request['question_type'] and '同类型' in goal:
        original=db.get(Question,UUID(target['question_id']))
        request['question_type']=original.question_type if original else None
    ids,evidence,error=_bank_candidates(db,now,goal,scopes,previous,request,minutes,
        base_scope_ids=[UUID(k) for k in previous['selected_kp_ids']])
    if error:return None,evidence,error
    # 逐题替换/追加的候选集已经过 validate_plan 正式校验；这里不能再用
    # _paper 的毕业策略重选（会漏掉合法候选）。按候选集原顺序构造纸面，
    # 并逐题重新校验 Question.current_version_id、版本配对与可练资格。
    previous_by_id={q['question_id']:q for q in previous['questions']}
    questions=[]
    for question_id in ids:
        question=db.get(Question,question_id)
        version=db.get(QuestionVersion,question.current_version_id) if question else None
        node=db.get(KnowledgePoint,question.kp_id) if question else None
        if (question is None or version is None or version.question_id!=question.id
                or version.id!=question.current_version_id or not version.is_active
                or not question.is_active or question.is_hidden
                or node is None or not question_eligibility(question,node).practice_eligible):
            raise ValueError('exact_revision_selection_changed')
        prior=previous_by_id.get(str(question.id))
        questions.append({"question_id":str(question.id),"question_version_id":str(version.id),
            "version":question_version_reference(question),"kp_id":str(question.kp_id),"kp_name":node.name,
            "stem":question.stem,"options":question.options,"difficulty":question.difficulty,
            "minutes":version.estimated_minutes,
            "reason":prior['reason'] if prior else '同知识点候选题替换',
            "eligibility":question_eligibility(question,node).public_dict()})
    result={"questions":_json_value(questions),"selected_kp_ids":list(previous['selected_kp_ids']),
        "budget_minutes":minutes,"total_minutes":sum(q['minutes'] for q in questions),
        "preset":'deep' if minutes>90 else 'standard',"question_limit":len(ids)}
    before=previous['questions'];after=result['questions']
    retained=list(range(len(before)))
    if operation=='replace_question':retained.remove(request['replacement_index'])
    if any((before[i]['question_id'],before[i]['question_version_id'])!=
           (after[i]['question_id'],after[i]['question_version_id']) for i in retained):
        raise ValueError('exact_revision_retained_identity_changed')
    if operation=='replace_question' and len(after)!=len(before):raise ValueError('replacement_count_changed')
    result['selected_kp_ids']=list(previous['selected_kp_ids'])
    result['scope_nodes']=copy.deepcopy(previous.get('scope_nodes',[]))
    result['question_limit']=len(ids)
    for node in result['scope_nodes']:
        node['assigned_count']=sum(q['kp_id']==node['kp_id'] for q in after)
    return result,evidence,None


def adjust(db, body, recommendations, now, *, intent_provider_factory=None):
    original_body=body
    request_fingerprint=hashlib.sha256(body.model_dump_json().encode('utf-8')).hexdigest()
    session = _session(db, body.session_id)
    if session.study_date is not None and session.study_date!=now.astimezone(SHANGHAI).date().isoformat():
        raise AppError('study_session_expired',status_code=409)
    if body.action in {'accept_workload','dismiss_workload'}:
        return _decide_workload(db,_workload_target(db,session.id,body),body,now)
    rows = list(db.scalars(select(LearningTask).where(LearningTask.session_id == session.id)))
    replay = next((r for r in rows if (r.context or {}).get("home_request_key") == body.request_key), None)
    if replay:
        saved=(replay.context or {}).get('home_request_fingerprint')
        if (saved and saved!=request_fingerprint) or (not saved and replay.goal!=body.goal):
            raise AppError('learning_task_conflict',status_code=409)
        return _adjustment_view(db,replay)
    if body.action in {'adjust','default','restore','undo','redo'}:
        # Match confirm/create_initial_plan's transaction lock before reading
        # the current preview. A committed DailyPlan cannot become a new chat
        # draft, including when it was created through a legacy entry point.
        _serialize_daily_plan_mutation(db)
        _reject_materialized_daily_plan_mutation(db, now)
    latest=_latest(db,session.id)
    if (body.action=='adjust' and _workload_pending(latest)
            and re.fullmatch(r'(?:我确定|我确认|我同意|确定|确认)[。！!]?',body.goal.strip())):
        raise AppError('home_workload_confirmation_required',status_code=422)
    old = _effective_row(db,latest)
    # The workload card is still an editable draft. A subsequent unversioned
    # chat edit (or an edit naming that card's version) must build on it,
    # rather than silently discarding its quantity changes via the fallback.
    # Explicit edits against the accepted fallback retain their own version.
    if (body.action == 'adjust' and _workload_pending(latest)
            and (not body.expected_version or body.expected_version == _draft_version(latest))):
        old = latest
    if body.expected_version and (old is None or _draft_version(old) != body.expected_version):
        raise AppError("learning_task_conflict", status_code=409)
    cached_notice=(old.context or {}).get('intent_notices',{}).get(body.request_key) if old else None
    if cached_notice:
        if cached_notice['goal']!=body.goal:raise AppError('learning_task_conflict',status_code=409)
        return cached_notice['response']
    if old and (old.metrics or {}).get("commit"):
        raise AppError("plan_already_generated", status_code=409)
    if body.action == 'adjust':
        command = body.goal.strip()
        if re.fullmatch(r'(?:撤销(?:刚才(?:的)?|上一步)?(?:修改|操作|调整)?|再撤销(?:上一步|刚才的修改)?|撤回(?:最后一步|刚才的修改|上一步)?|回到上一步|恢复上一步|把刚才删除的题恢复)[。！!]?', command):
            body = body.model_copy(update={'action': 'undo'})
        elif re.search(r'撤回(?:最后一步|刚才的修改|上一步)|回到上一步|恢复上一步', command):
            body = body.model_copy(update={'action': 'undo'})
        elif re.fullmatch(r'(?:重做(?:刚才撤销的操作|上一步|刚才的修改)?)[。！!]?', command):
            body = body.model_copy(update={'action': 'redo'})
        elif re.fullmatch(r'(?:恢复今天最初的系统推荐|恢复今日最初系统推荐)[。！!]?', command):
            body = body.model_copy(update={'action': 'restore'})
    explain = body.action == "explain" or (bool(re.search(r"为什么|根据什么|哪些.*错题|推荐依据|推荐理由", body.goal))
        and not re.search(r'追加|增加|加入|删除|移除|替换|再.*加',body.goal))
    if explain:
        saved_facts = (old.context or {}).get("evidence", {}) if old else read_system(db, recommendations, now)["evidence"]
        facts = {**saved_facts, "self_reports": read_self_reports(db, session.id)}
        lines = ["推荐依据分为以下几类；题量不代表掌握程度。"]
        for state in facts.get("states", []):
            wrong = [a for a in state["recent_attempts"] if a["result"] == "wrong"]
            lines.append(f'{state["kp_name"]}：最近展示 {len(state["recent_attempts"])} 条作答，'
                f'其中错误观察 {len(wrong)} 条，已核验客观确认 {state["verified_objective_confirmation_count"]} 条。'
                f'系统策略：{recommendation_sentence(state["next_step"])}')
            if wrong:
                lines.append("错误观察记录：" + "、".join(a["attempt_id"] for a in wrong)
                    + "；辅助与答案可靠性详见依据面板，不能全部视为独立客观错误。")
        lines.append("学生自述单独保存在会话记录中，未经独立核验；不会直接改变掌握状态。"
            "没有客观记录时仅为初始诊断，不推测薄弱点。请展开推荐依据查看原始记录和时间。")
        message = "\n".join(lines)
        _record_request_dialogue(db,session,body,message)
        db.flush()
        return {"kind": "explanation", "session_id": str(session.id), "message": message}
    from backend.services.bank_selection_intent import bank_selection_request
    bank_request = bank_selection_request(body.goal) if body.action == 'adjust' else None
    previous_paper = (old.draft if old and old.status=='ready' and not _legacy_incomplete_addition(old)
                      else _retained_baseline(old) if old else None)
    baseline = (old.context or {}).get("baseline") if old else None
    system = [r.model_dump(mode="json") for r in recommendations]
    system_ids = [r.kp_id for r in recommendations]
    if (body.action == 'restore' and old and old.status == 'ready'
            and not (old.metrics or {}).get('commit') and baseline and old.draft
            and tuple(old.draft.get('selected_kp_ids', [])) == tuple(baseline.get('selected_kp_ids', []))
            and _paper_identity(old.draft) == _paper_identity(baseline)):
        # Repeated restore is a read-only no-op once the canonical snapshot is
        # already current. Do not create another LearningTask for repeated taps.
        return _adjustment_view(db,old)
    if baseline is None and (old is None or old.status!='ready') and system_ids:
        # Capture canonical A before any first manual/chat revision can fail.
        try:
            with db.begin_nested():
                # The first editable homepage draft must pin the exact adaptive
                # candidates already shown by read_system(). Re-ranking without
                # the FSRS projection here made the preview differ from the
                # student's visible recommendation before confirmation.
                baseline=_paper(db,system_ids,90,now,adaptive_schedule=True)
        except Exception as exc:
            logging.getLogger(__name__).warning('home baseline unavailable type=%s',type(exc).__name__)
            # Keep the failed attempt explicit. A later append branch must not
            # retry the same initial selector and accidentally turn a transient
            # failure into an apparently successful, incomplete plan.
            baseline={"selected_kp_ids":[str(k) for k in system_ids],
                "questions":[],"budget_minutes":90,"error":str(exc)[:160]}
    exact_intent=None
    intent=None
    exact_bank_used=False
    exact_edit_used=False
    scope_add_ids=None
    intent_trace=None
    exact_bank_evidence=None
    topic_count_summaries=[]
    subject_plan_summary=None
    subject_topic_summary=None
    topic_removal_summaries=[]
    initial_undo_stack=list((old.context or {}).get('home_undo_stack') or []) if old else []
    initial_redo_stack=list((old.context or {}).get('home_redo_stack') or []) if old else []
    undo_stack=list(initial_undo_stack)
    redo_stack=list(initial_redo_stack)
    history_transition=body.action in {'undo','redo'}
    difficulty_snapshot=False
    if history_transition:
        if not body.expected_version:
            raise AppError('learning_task_conflict', status_code=409)
        if db.scalar(select(DailyPlan).where(
            DailyPlan.study_date == now.astimezone(SHANGHAI).date().isoformat())):
            raise AppError('plan_already_generated', status_code=409)
        if old is None or old.status != 'ready' or old.draft is None or (old.metrics or {}).get('commit'):
            raise AppError('learning_task_history_empty', status_code=409)
        current_entry=_history_entry(old, old.draft)
        source_stack=undo_stack if body.action == 'undo' else redo_stack
        if not source_stack:
            raise AppError('learning_task_history_empty', status_code=409)
        target_entry=source_stack.pop()
        difficulty_snapshot=bool(isinstance(target_entry,dict) and target_entry.get('difficulty_snapshot'))
        if difficulty_snapshot:
            # 难度调整直接改当前 task 的 draft，task_id 引用会指向已被覆盖的
            # 新草稿；因此两个方向都保存完整快照，撤销/重做才能还原题面。
            current_entry={'snapshot': _json_value(deepcopy(old.draft)), 'difficulty_snapshot': True}
        target_paper=_history_paper(db, session.id, target_entry)
        if target_paper is None:
            raise AppError('learning_task_history_stale', status_code=409)
        if body.action == 'undo':
            redo_stack.append(current_entry)
        else:
            undo_stack.append(current_entry)
        exact_intent=target_paper
    def notice(message):
        response={'kind':'explanation','session_id':str(session.id),'message':message,'intent_trace':intent_trace}
        if old:
            notices=dict((old.context or {}).get('intent_notices',{}))
            notices[body.request_key]={'goal':original_body.goal,'response':response}
            old.context={**old.context,'intent_notices':dict(list(notices.items())[-20:])}
        _record_request_dialogue(db,session,original_body,message);db.flush()
        return response
    if body.action=='adjust':
        from backend.services.home_intent import resolve,exact_edit
        def history():
            messages=list(db.scalars(select(ChatMessage).where(ChatMessage.session_id==session.id,
                ChatMessage.status=='completed').order_by(ChatMessage.seq.desc()).limit(6)))
            return [{'role':m.role,'content':m.content[:500]} for m in reversed(messages)]
        continuation=dict(old.context or {}) if old else {}
        last_edit=continuation.get('home_last_edit') or {}
        continuation['last_topic_kp_id']=last_edit.get('last_topic_kp_id')
        continuation['last_topic_name']=last_edit.get('last_topic_name')
        intent,intent_trace=resolve(body.goal,previous_paper or baseline,intent_provider_factory,
            history_factory=history,context=continuation)
        if intent.operation=='append':
            # A named topic in the live proposal is a scoped plan adjustment.
            # The generic bank adapter's text matcher can miss display labels
            # with suffixes such as “(R46)”; resolve the existing plan alias
            # once here and use the same formally validated count revision.
            from backend.services.home_intent import _matched_topic_refs, HomeIntent
            named_scopes=_matched_topic_refs(body.goal,previous_paper or baseline)
            if len(named_scopes)==1 and intent.quantity:
                intent=HomeIntent(operation='topic_count',refs=[named_scopes[0][0]],
                    deltas=[intent.quantity],terms=body.goal)
                intent_trace['operation']='topic_count'
        logging.getLogger(__name__).info('home_intent request=%s source=%s operation=%s model_calls=%s elapsed_ms=%s failure=%s',
            body.request_key,intent_trace['source'],intent_trace['operation'],intent_trace['model_calls'],
            intent_trace['elapsed_ms'],intent_trace.get('failure','none'))
        if intent.operation=='summary':
            current=previous_paper or baseline
            if not current or not current.get('questions'):
                return notice('当前没有可读取的有效推荐方案，请先读取系统推荐；尚未创建今日卷。')
            names=list(dict.fromkeys(q.get('kp_name','') for q in current['questions'] if q.get('kp_name')))
            return notice(f"当前方案：{len(current['questions'])} 道题，预计 {current['total_minutes']} 分钟，预算 {current['budget_minutes']} 分钟。知识点：{'、'.join(names)}。尚未创建今日卷。")
        if intent.operation in {'subject_preference','constraint_total'}:
            if not old:
                return notice('当前没有可调整的方案，请先读取系统推荐。')
            constraints=dict((old.context or {}).get('adjustment_constraints') or {})
            if intent.operation=='constraint_total':
                total=len((previous_paper or baseline or {}).get('questions',[]))
                constraints['immutable_total']=total
                message=f'已记录：总题量不超过 {total} 道；后续调整不会增加题量。'
            else:
                constraints['subject_preference']=intent.terms
                message='已记录学科偏好。当前正式选题策略暂不支持按学科自动比例调整；请明确知识点和题量，我会在该范围内安排，不会擅自改变总题量。'
            old.context={**(old.context or {}),'adjustment_constraints':constraints}
            db.flush()
            return notice(message)
        if intent.operation=='reuse_preview':
            state=(old.context or {}).get('subject_topic_replacement') if old else None
            if not state or not previous_paper:
                return notice('当前没有可沿用的跨科目替换草案；原方案未改变。')
            topics='、'.join(row.get('name','') for row in state.get('destination_topics',[]) if row.get('name')) or '408知识点'
            return notice(f"当前待确认草案已按原目标题量替换为{topics}，其余知识点和预算保持不变；仍未生成正式今日卷。")
        if intent.operation=='restore_subject_source':
            current=previous_paper or baseline
            state=(old.context or {}).get('subject_topic_replacement') if old else None
            source_ids=set((state or {}).get('source_kp_ids') or [])
            destination_ids={row.get('kp_id') for row in (state or {}).get('destination_topics',[])}
            base=(old.context or {}).get('baseline') if old else None
            saved_source=(state or {}).get('source_questions_snapshot')
            source_questions=([q for q in saved_source if q.get('kp_id') in source_ids]
                if isinstance(saved_source,list) else
                [q for q in (base or {}).get('questions',[]) if q.get('kp_id') in source_ids])
            if not current or not source_questions:
                return notice('原知识点题目无法从基准方案中核验；当前替换草案保持不变。')
            restored=deepcopy(current)
            kept=[q for q in current.get('questions',[]) if q.get('kp_id') not in destination_ids]
            kept_ids={q.get('question_id') for q in kept}
            if any(q.get('question_id') in kept_ids for q in source_questions):
                return notice('原知识点题目与当前方案出现重复；当前方案未改变，请恢复系统推荐后重试。')
            restored['questions']=kept+source_questions
            restored['selected_kp_ids']=[key for key in current.get('selected_kp_ids',[]) if key not in destination_ids]
            restored['selected_kp_ids']=list(dict.fromkeys(restored['selected_kp_ids']+[str(key) for key in source_ids]))
            restored['allocation_kp_ids']=list(dict.fromkeys(q['kp_id'] for q in restored['questions']))
            restored['candidate_question_ids']=[q['question_id'] for q in restored['questions']]
            restored['question_limit']=len(restored['questions'])
            restored['total_minutes']=sum(int(q['minutes']) for q in restored['questions'])
            old_nodes={str(row.get('kp_id')):row for row in current.get('scope_nodes',[])}
            restored['scope_nodes']=[{'kp_id':key,
                'name':old_nodes.get(key,{}).get('name') or (db.get(KnowledgePoint,UUID(key)).name if db.get(KnowledgePoint,UUID(key)) else ''),
                'parent_id':str(db.get(KnowledgePoint,UUID(key)).parent_id) if db.get(KnowledgePoint,UUID(key)) and db.get(KnowledgePoint,UUID(key)).parent_id else None,
                'assigned_count':sum(q['kp_id']==key for q in restored['questions']),
                'allocation_status':'allocated' if any(q['kp_id']==key for q in restored['questions']) else 'no_eligible_questions',
                'allocation_reason':None} for key in restored['selected_kp_ids']]
            exact_intent=restored;exact_edit_used=True;bank_request=None
        if intent.operation in {'clarify','generate_guidance','accept','return'}:
            if intent.operation=='clarify' and re.search(r'删除|删掉|移除|去掉',body.goal):
                outside=_mentioned_outside_topic(db,body.goal,previous_paper or baseline)
                if outside:
                    return notice(f'{outside}当前不在今日方案范围内（今日安排 0 道），不需要再删除；原方案保持不变。'
                        f'如果想重新练它，请说“把{outside}加回来”。')
            return notice(intent.question or ('正式生成请使用首页“确定生成试卷”；接受或返回请使用当前方案卡片。'))
        if intent.operation=='topic_count':
            current=previous_paper or baseline
            try:
                with db.begin_nested():
                    exact_intent,topic_count_summaries,error=_topic_count_revision(
                        db,now,current,intent,body.goal,int(old.budget_minutes if old else ((current or {}).get('budget_minutes') or 90)))
            except Exception as exc:
                failure_id=uuid4().hex
                logging.getLogger(__name__).exception('home topic count adjustment failed id=%s stage=topic_count_revision type=%s',failure_id,type(exc).__name__)
                return notice(f'按知识点调整失败，服务分支 home_recommendation_service.topic_count_revision，原因类别 {type(exc).__name__}，错误编号 {failure_id}；原方案和旧预览保持有效。')
            if error:return notice(error)
            exact_edit_used=True
            # The generic bank intent sees the word “增加” and can otherwise
            # run a second, scope-wide append after this topic-scoped edit.
            bank_request=None
        if intent.operation=='topic_target':
            current=previous_paper or baseline
            if not current:return notice('当前没有可调整的有效方案；原方案已保留。')
            from backend.services.home_intent import HomeIntent
            from backend.services.home_intent import reference_map
            refs=reference_map(current);deltas=[]
            for ref in intent.refs:
                kp=refs.get(ref,{}).get('value')
                before=sum(q.get('kp_id')==str(kp) for q in current.get('questions',[]))
                deltas.append(int(intent.quantity)-before)
            if all(delta==0 for delta in deltas):
                return notice(f'当前目标知识点已经符合每个{intent.quantity}道的要求；方案保持不变，尚未生成今日卷。')
            if any(abs(delta)>20 for delta in deltas):
                return notice('该目标题量变化超出单次调整范围；原方案已保留，请分次调整。')
            intent=HomeIntent(operation='topic_count',refs=intent.refs,deltas=deltas,terms=body.goal)
            try:
                with db.begin_nested():
                    exact_intent,topic_count_summaries,error=_topic_count_revision(
                        db,now,current,intent,body.goal,int(old.budget_minutes if old else ((current or {}).get('budget_minutes') or 90)))
            except Exception as exc:
                failure_id=uuid4().hex
                logging.getLogger(__name__).exception('home topic target adjustment failed id=%s stage=topic_target_revision type=%s',failure_id,type(exc).__name__)
                return notice(f'按知识点设置目标题量失败，服务分支 home_recommendation_service.topic_target_revision，原因类别 {type(exc).__name__}，错误编号 {failure_id}；原方案保持有效。')
            if error:return notice(error)
            exact_edit_used=True;bank_request=None
        if intent.operation in {'topic_remove_questions','exclude_scope'}:
            current=previous_paper or baseline
            if not current:return notice('当前没有可调整的有效方案；原方案已保留。')
            from backend.services.home_intent import reference_map
            refs=reference_map(current);targets={refs[key]['value'] for key in intent.refs}
            for key in targets:
                node=db.get(KnowledgePoint,UUID(str(key)))
                current_items=[q for q in current.get('questions',[]) if q.get('kp_id')==str(key)]
                topic_removal_summaries.append({'kp_id':str(key),'name':node.name if node else '',
                    'before_count':len(current_items),'removed_question_ids':[q['question_id'] for q in current_items],
                    'protected_count':0,'after_count':0,'operation':intent.operation})
            if intent.operation=='topic_remove_questions' and not any(row['before_count'] for row in topic_removal_summaries):
                return notice('当前待确认方案中这些知识点没有题目可移除；原方案保持不变。')
            exact_intent=exact_edit(current,intent)
            exact_edit_used=True
            bank_request=None
            if not exact_intent['questions']:
                removed=sum(row['before_count'] for row in topic_removal_summaries)
                return notice(f'该批量移除会清空当前方案（计划移除{removed}道、受保护0道）；空方案不能生成今日卷。原预览保持有效，请先补入其他知识点或题目。')
        if intent.operation=='subject_topic_replace':
            current=previous_paper or baseline
            replace_minutes=int(current.get('budget_minutes') or (old.budget_minutes if old else 90)) if current else (old.budget_minutes if old else 90)
            diagnostic_id=uuid4().hex
            try:
                with db.begin_nested():
                    exact_intent,subject_topic_summary,error=_subject_topic_revision(
                        db,now,current,intent,replace_minutes)
            except Exception as exc:
                logging.getLogger(__name__).exception('home local subject replacement failed id=%s stage=subject_topic_revision type=%s',diagnostic_id,type(exc).__name__)
                return notice(f'局部跨科目替换失败，服务分支 home_recommendation_service.subject_topic_revision，原因类别 {type(exc).__name__}，错误编号 {diagnostic_id}；原方案保持有效，未生成今日卷。')
            if error:
                logging.getLogger(__name__).warning('home local subject replacement rejected id=%s stage=subject_topic_revision reason=%s',diagnostic_id,error)
                return notice(error)
            exact_edit_used=True;bank_request=None
        if intent.operation=='restore_recent_removed':
            current=previous_paper or baseline
            edit=(old.context or {}).get('home_last_edit') if old else None
            stack=list((old.context or {}).get('home_undo_stack') or []) if old else []
            source=_history_paper(db,session.id,stack[-1]) if stack else None
            removed_ids={row.get('question_id') for row in (edit or {}).get('removed_questions',[])}
            candidates=[q for q in (source or {}).get('questions',[]) if q.get('question_id') in removed_ids]
            if not current or not candidates or len(candidates)<int(intent.quantity or 1):
                return notice('无法从上一版有效方案核验要恢复的题目；当前预览保持不变。')
            add=candidates[:int(intent.quantity or 1)]
            restored=deepcopy(current)
            current_ids={q['question_id'] for q in current['questions']}
            add=[q for q in add if q['question_id'] not in current_ids]
            if len(add)!=int(intent.quantity or 1):return notice('待恢复题目已在当前方案中或版本不匹配；当前预览保持不变。')
            restored['questions']=[*current['questions'],*add]
            restored['selected_kp_ids']=list(dict.fromkeys([*current['selected_kp_ids'],*[q['kp_id'] for q in add]]))
            restored['allocation_kp_ids']=list(dict.fromkeys(q['kp_id'] for q in restored['questions']))
            restored['candidate_question_ids']=[q['question_id'] for q in restored['questions']]
            restored['question_limit']=len(restored['questions'])
            restored['total_minutes']=sum(int(q['minutes']) for q in restored['questions'])
            old_nodes={str(row.get('kp_id')):row for row in current.get('scope_nodes',[])}
            restored['scope_nodes']=[{'kp_id':key,
                'name':old_nodes.get(key,{}).get('name') or (db.get(KnowledgePoint,UUID(key)).name if db.get(KnowledgePoint,UUID(key)) else ''),
                'parent_id':str(db.get(KnowledgePoint,UUID(key)).parent_id) if db.get(KnowledgePoint,UUID(key)) and db.get(KnowledgePoint,UUID(key)).parent_id else None,
                'assigned_count':sum(q['kp_id']==key for q in restored['questions']),
                'allocation_status':'allocated' if any(q['kp_id']==key for q in restored['questions']) else 'no_eligible_questions',
                'allocation_reason':None} for key in restored['selected_kp_ids']]
            exact_intent=restored;exact_edit_used=True;bank_request=None
        if intent.operation=='subject_plan':
            current=previous_paper or baseline
            selected,selection_facts=_subject_plan_scope(db,now,subject=intent.terms,
                count=intent.quantity or 6,unattempted_only=intent.unattempted_only)
            if len(selected)!=(intent.quantity or 6):
                qualifier=('从未作答且仍处于未学习状态、符合正式准入的'
                    if intent.unattempted_only else '符合正式准入的')
                return notice(f'当前有{len(selected)}个{qualifier}{intent.terms}知识点可安排，'
                    f'少于所需{intent.quantity}个；原方案已保留。')
            if not 5<=int(intent.minutes or 0)<=240:
                return notice('请明确408学习预算；原方案已保留。')
            diagnostics={'diagnostic_id':uuid4().hex,'stage':'subject_replacement',
                'subject':intent.terms,'selected_topics':selection_facts}
            try:
                with db.begin_nested():
                    exact_intent=_subject_plan_paper(db,selected,int(intent.minutes),now,
                        diagnostics=diagnostics)
            except Exception as exc:
                logging.getLogger(__name__).exception('home subject replacement failed subject=%s type=%s',
                    intent.terms,type(exc).__name__)
                return notice('未能用满足正式准入的408题目完成完整方案，原方案已保留；没有生成正式卷。')
            exact_edit_used=True
            subject_plan_summary={'subject':intent.terms,'topic_count':len(selected),
                'topics':selection_facts,'budget_minutes':int(intent.minutes),
                'unattempted_only':intent.unattempted_only}
            bank_request=None
        if intent.operation in {'fill_time','replace_question'}:
            current=previous_paper or baseline
            if not current or not current.get('questions'):
                if intent.operation=='fill_time':
                    from backend.services.question_availability import question_availability
                    stock=question_availability(db,now=now,limit=0)
                    if stock['practice_eligible_count']==0:
                        return notice(f'当前符合正式准入条件的可用题为0道，无法补足{intent.minutes}分钟；未准入题已排除。请先补充已核验的正式题目，原方案和历史记录均已保留。')
                return notice('没有可调整的有效方案，请先读取系统推荐。')
            if db.scalar(select(DailyPlan).where(DailyPlan.study_date==now.astimezone(SHANGHAI).date().isoformat())):
                return notice('今日卷已生成，不能通过推荐调整修改正式卷；请使用独立练习。')
            edit_minutes=intent.minutes if intent.operation=='fill_time' else current['budget_minutes']
            diagnostic_id=uuid4().hex
            try:
                with db.begin_nested():
                    exact_intent,exact_bank_evidence,error=_bank_exact_revision(db,now,body.goal,current,
                        intent.operation,edit_minutes,intent.refs)
            except Exception as exc:
                logging.getLogger(__name__).exception('home exact bank revision id=%s operation=%s type=%s',
                    diagnostic_id,intent.operation,type(exc).__name__)
                return notice(f'题库调整暂时无法完成，原有效方案已保留。错误编号：{diagnostic_id}。')
            if error:return notice(error)
            exact_bank_used=True
            bank_request=None
        if intent.operation in {'remove_question','remove_scope','budget','count','reorder'}:
            if not previous_paper and not baseline:return notice('没有可调整的有效方案，请先读取系统推荐。')
            exact_intent=exact_edit(previous_paper or baseline,intent)
            exact_edit_used=True
            if not exact_intent['questions']:return notice('这次操作会移除全部题目，请重新选择范围；原方案已保留。')
        elif intent.operation=='restore':
            body=body.model_copy(update={'action':'restore'})
        elif intent.operation=='append':
            # Canonicalize only the validated operation/count, never the base.
            body=body.model_copy(update={'goal':f'加入{intent.quantity}道'+intent.terms})
            bank_request=bank_selection_request(body.goal)
        elif intent.operation=='replace':
            body=body.model_copy(update={'goal':'只练'+intent.terms})
        elif intent.operation=='scope_add':
            additional=resolve_scope(db,now,intent.terms,previous_paper or baseline,None)
            if not additional:return notice('没有唯一匹配的新增知识点，请明确名称；原方案已保留。')
            scope_add_ids=list(dict.fromkeys([UUID(k) for k in (previous_paper or baseline or {}).get('selected_kp_ids',[])]+additional))
    minutes_match = re.findall(r"(?<!\d)(\d{1,3})\s*分钟", body.goal) if body.action == "adjust" else []
    explicit_minutes = int(minutes_match[-1]) if minutes_match else None
    minutes = explicit_minutes if explicit_minutes is not None else body.budget_minutes or (old.budget_minutes if old else 90)
    if exact_intent:
        if explicit_minutes is not None:
            # A first-turn count/edit can be based on the canonical 90-minute
            # system baseline. Keep its exact question snapshot, but do not let
            # that baseline overwrite a budget stated in the same user request.
            exact_intent=deepcopy(exact_intent)
            exact_intent['budget_minutes']=minutes
        else:
            minutes=exact_intent['budget_minutes']
    if not 5 <= minutes <= 240:
        raise AppError("validation_failed", status_code=422)
    cancel_adjustment=body.action=='adjust' and bool(re.fullmatch(r"(?:算了[，, ]*)?(?:取消(?:调整)?|不用了|不练了)[。！!]?",body.goal))
    restoring = body.action == "restore" or cancel_adjustment or bool(re.search(r"按原来.*推荐|恢复.*推荐", body.goal))
    cancelling = body.action == "cancel"  # Explicit preview cancellation remains distinct.
    default = body.action == "default"
    count_match = re.search(r"(?:减少到|减到|最多|不超过|只做|只练)\s*(\d{1,3})\s*道", body.goal)
    question_limit = int(count_match.group(1)) if count_match else (old.draft or {}).get("question_limit") if old else None
    if question_limit is not None and not 1 <= question_limit <= 100:
        raise AppError("validation_failed", status_code=422)
    # 结构化多轮约束：总题量上限与学科偏好跨轮保留，不依赖聊天文本临时拼接。
    prior_constraints = dict((old.context or {}).get('adjustment_constraints') or {}) if old else {}
    if re.search(r'(?:总题量|题量|总题数).{0,8}(?:不要增加|不能增加|不变|保持不变|不要变)', body.goal):
        prior_constraints['immutable_total'] = len((previous_paper or baseline or {}).get('questions', []))
    if re.search(r'(?:高数|线代|概率|数学).{0,6}(?:多一点|多一些|少一点|少一些)', body.goal):
        prior_constraints['subject_preference'] = body.goal
    requested_total = (question_limit if question_limit is not None
                       else (intent.quantity if (intent is not None and getattr(intent, 'operation', None) == 'count') else None))
    if (prior_constraints.get('immutable_total') and requested_total is not None
            and requested_total > prior_constraints['immutable_total']):
        return notice(f'你已要求总题量不超过 {prior_constraints["immutable_total"]} 道；本次未调整，原方案已保留。')
    keep_system = bool(re.search(r"保留系统推荐", body.goal))
    if scope_add_ids:
        ids=scope_add_ids
    elif exact_intent:
        ids=[UUID(k) for k in exact_intent['selected_kp_ids']]
    elif restoring and baseline:
        # Restore the immutable snapshot, not merely its scope. Re-ranking here
        # can silently replace the questions the student originally saw.
        exact_intent = dict(baseline)
        ids = [UUID(k) for k in baseline["selected_kp_ids"]]
        minutes = baseline["budget_minutes"]
        question_limit = baseline.get("question_limit")
    elif keep_system:
        ids = [UUID(k) for k in baseline["selected_kp_ids"]] if baseline else [r.kp_id for r in recommendations]
    elif default:
        question_limit = None
        canonical_system_ids=[r.kp_id for r in recommendations]
        ids = (canonical_system_ids if body.selected_kp_ids is not None
            and set(body.selected_kp_ids)==set(canonical_system_ids)
            else body.selected_kp_ids if body.selected_kp_ids is not None else canonical_system_ids)
    else:
        ids = resolve_scope(db, now, body.goal, old.draft if old and old.draft else
            {"selected_kp_ids": [str(r.kp_id) for r in recommendations]}, body.selected_kp_ids)
    bank_scope_plan = None
    append_baseline_error = None
    if bank_request:
        bank_tools = _tools(db, now, body.goal, minutes)
        has_explicit_scope = bank_tools.explicit_scope is not None
        if bank_request.get('scope_mode') == 'append':
            if baseline is None:
                try:
                    # The read-only homepage recommendation uses a 90-minute
                    # initial paper. Capture that same baseline before applying
                    # the user's additional bank request.
                    with db.begin_nested():
                        baseline = _paper(db, system_ids, 90, now, adaptive_schedule=True)
                except ValueError as exc:
                    baseline = {"selected_kp_ids": [str(k) for k in system_ids],
                        "questions": [], "budget_minutes": 90, "error": str(exc)}
            base_paper = previous_paper or baseline
            base_scope_ids = [UUID(str(k)) for k in (base_paper or {}).get('selected_kp_ids', [])] or system_ids
            additional_scope_ids = ids if has_explicit_scope else base_scope_ids
            bank_scope_plan = _bank_scope_plan(base_scope_ids, additional_scope_ids,
                bank_request, explicit_scope=has_explicit_scope)
            ids = bank_scope_plan['selected_scope_ids']
            # On a first turn the system recommendation is transient, so pass
            # its real selected questions as retained candidates to the same
            # formal bank validation path used for an existing preview.
            previous_paper = base_paper
            if base_paper and base_paper.get("error") and not (old and old.status == "ready" and old.draft):
                append_baseline_error = base_paper["error"]
        else:
            if not has_explicit_scope:
                ids = [UUID(k) for k in previous_paper['selected_kp_ids']] if previous_paper else system_ids
            base_scope_ids = ([UUID(str(k)) for k in (baseline or {}).get('selected_kp_ids', [])]
                or [r.kp_id for r in recommendations])
            bank_scope_plan = _bank_scope_plan(base_scope_ids, ids, bank_request,
                explicit_scope=has_explicit_scope)
            ids = bank_scope_plan['selected_scope_ids']
    context = {"home_recommendation": True, "home_request_key": body.request_key,
        "home_request_fingerprint":request_fingerprint,
        "request_origin": _request_origin(original_body),
        "study_date": now.astimezone(SHANGHAI).date().isoformat(), "system_recommendations": system,
        "baseline": baseline, "previous_task_id": str(old.id) if old else None,
        "expires_at": (now + timedelta(minutes=30)).isoformat(), "evidence": {}}
    if intent_trace:context['intent_trace']=intent_trace
    if exact_edit_used:context['exact_edit']=True
    if topic_count_summaries:context['topic_count_changes']=topic_count_summaries
    if topic_removal_summaries:context['topic_removals']=topic_removal_summaries
    if subject_plan_summary:context['subject_plan']=subject_plan_summary
    if subject_topic_summary:
        prior_topic_state=(old.context or {}).get('subject_topic_replacement') if old else None
        if prior_topic_state:
            subject_topic_summary['source_kp_ids']=prior_topic_state.get('source_kp_ids') or subject_topic_summary['source_kp_ids']
            subject_topic_summary['source_questions_snapshot']=(
                prior_topic_state.get('source_questions_snapshot') or subject_topic_summary['source_questions_snapshot'])
        context['subject_topic_replacement']=subject_topic_summary
    elif ((intent is None or intent.operation not in {'restore_subject_source','restore'}) and body.action!='restore'
            and old and (old.context or {}).get('subject_topic_replacement')):
        context['subject_topic_replacement']=(old.context or {})['subject_topic_replacement']
    if exact_bank_used:context['exact_bank_revision']=True
    if prior_constraints:context['adjustment_constraints']=prior_constraints
    if bank_scope_plan:
        context['bank_scope'] = _json_value(bank_scope_plan)
    from backend.services.question_availability import question_availability
    context["inventory"] = _home_inventory(db,ids,now)
    viable_ids, unavailable = [], []
    for kp_id in ids:
        node = db.get(KnowledgePoint, kp_id)
        if node and node.is_active and node.is_assessable and any(
            question_eligibility(q, node).practice_eligible
            for q in db.scalars(select(Question).where(Question.kp_id == kp_id, Question.is_active.is_(True)))):
            viable_ids.append(kp_id)
        else:
            unavailable.append({"kp_id": str(kp_id), "name": node.name if node else "不存在的节点",
                "reason": "节点不可考核或没有符合正式可练资格的在线题"})
    context["requested_scope_ids"] = [str(k) for k in ids]
    context["unavailable_nodes"] = unavailable
    row = LearningTask(session_id=session.id, goal=original_body.goal or "查看系统推荐试卷", budget_minutes=minutes,
        status="needs_info", context=context, draft=None, trace=[], metrics={})
    db.add(row)
    candidate_ids, bank_error = None, None
    if exact_intent:
        if exact_bank_evidence is not None:
            context['bank_selection']=exact_bank_evidence
        candidate_ids=[UUID(q['question_id']) for q in exact_intent['questions']]
        viable_ids=list(dict.fromkeys(UUID(q['kp_id']) for q in exact_intent['questions']))
        if exact_intent['total_minutes']>minutes:
            context['workload']={'requested_budget_minutes':minutes,'effective_budget_minutes':exact_intent['total_minutes'],
                'extra_minutes':exact_intent['total_minutes']-minutes,'requires_confirmation':True}
    if bank_request and append_baseline_error and not cancelling:
        context['bank_selection'] = {
            'tool': 'find_questions', 'error': 'system_baseline_unavailable',
            'base_scope_ids': [str(k) for k in bank_scope_plan['base_scope_ids']],
            'additional_scope_ids': [str(k) for k in bank_scope_plan['additional_scope_ids']],
            'baseline_error': str(append_baseline_error)[:160],
        }
        bank_error = '当前系统初始推荐无法形成可保留的题目清单，因此没有追加题目或生成预览。请先重新读取推荐，或明确选择替换范围后再试。'
    elif bank_request and not cancelling:
        # This adapter changes a preview only. An existing formal paper must use
        # the established in-paper append/confirmation flow, never a second paper.
        existing_plan = db.scalar(select(DailyPlan).where(DailyPlan.study_date == context['study_date']))
        if existing_plan:
            bank_error='今日卷已经生成；请在今日学习的题目追加入口选择并确认追加。本次未覆盖或另建试卷。'
            context['bank_selection']={'error':'formal_plan_exists','plan_id':str(existing_plan.id)}
        else:
            try:
                query_scope = (bank_scope_plan['additional_scope_ids']
                    if bank_request.get('scope_mode') == 'append' else ids)
                diagnostics={'diagnostic_id':uuid4().hex,'stage':'bank_setup'}
                context['bank_diagnostics']=diagnostics
                with db.begin_nested():
                    candidate_ids, context['bank_selection'], bank_error = _bank_candidates(
                        db,now,body.goal,query_scope,previous_paper,bank_request,minutes,
                        base_scope_ids=bank_scope_plan['base_scope_ids'] if bank_scope_plan else None,
                        diagnostics=diagnostics)
                if candidate_ids:
                    workload=context['bank_selection'].get('workload')
                    if workload:
                        context['workload']=workload
                    ids=bank_scope_plan['selected_scope_ids'] if bank_scope_plan else list(dict.fromkeys(db.get(Question,k).kp_id for k in candidate_ids))
                    context['requested_scope_ids'] = [str(k) for k in ids]
                    allocated_scope={db.get(Question,k).kp_id for k in candidate_ids}
                    viable_ids=[k for k in ids if k in allocated_scope]
                    question_limit=len(candidate_ids)
            except Exception as exc:
                diagnostics=context.get('bank_diagnostics',{'stage':'bank_setup','diagnostic_id':uuid4().hex})
                code,hint=_bank_failure(exc,diagnostics['stage'])
                diagnostics['exception_type']=type(exc).__name__
                logging.getLogger(__name__).exception('home bank failure id=%s stage=%s type=%s',
                    diagnostics['diagnostic_id'],diagnostics['stage'],type(exc).__name__)
                row.status='failed'
                context['bank_selection']={'tool':'find_questions','error':code}
                bank_error=f"{hint}，本次未调整成功。原有效方案保留，请读取状态后重试。错误编号：{diagnostics['diagnostic_id']}。"
    if bank_error and context.get('bank_selection'):
        row.error_code=context['bank_selection'].get('error')
    if cancelling:
        row.status, row.message = "cancelled", "已取消预览；今日卷和作答记录未改变。"
    elif bank_error:
        row.message=bank_error
    elif not ids:
        row.message = "没有匹配到可考核知识点。请选择现有节点或补充范围；没有替换成其他知识点。"
    elif not viable_ids:
        row.message = "目标知识点存在，但没有符合正式可练资格的在线题。请查看库存原因、选择其他知识点或取消；未创建试卷。"
    else:
        ids = viable_ids
        try:
            # Savepoint protects workspace invalidation from selector errors;
            # selector itself performs no formal business writes.
            if context.get('bank_diagnostics'):context['bank_diagnostics']['stage']='formal_selection'
            with db.begin_nested():
                if exact_intent and (difficulty_snapshot or exact_bank_used or exact_edit_used or history_transition):
                    # 难度快照、逐题替换或撤销/重做恢复的纸面已逐题校验，不能再用
                    # 系统排序重建；直接使用已保存纸面，并再次校验版本与资格。
                    paper=deepcopy(exact_intent)
                    for item in paper['questions']:
                        question=db.get(Question,UUID(item['question_id']))
                        version=db.get(QuestionVersion,UUID(item['question_version_id']))
                        node=db.get(KnowledgePoint,question.kp_id) if question else None
                        if (question is None or version is None or version.question_id!=question.id
                                or not version.is_active or not question.is_active or question.is_hidden
                                or node is None or not question_eligibility(question,node).practice_eligible):
                            raise ValueError('difficulty_snapshot_stale')
                    paper['question_limit']=exact_intent.get('question_limit')
                    paper['candidate_question_ids']=[str(k) for k in candidate_ids]
                    paper['allocation_kp_ids']=[str(k) for k in ids]
                    paper['selected_kp_ids']=exact_intent['selected_kp_ids']
                elif exact_intent:
                    paper=_paper(db,ids,minutes,now,candidate_question_ids=candidate_ids,workload_preview=True)
                    before=[(q['question_id'],q['question_version_id'],q.get('version'),q['minutes']) for q in exact_intent['questions']]
                    after=[(q['question_id'],q['question_version_id'],q.get('version'),q['minutes']) for q in paper['questions']]
                    if before!=after:raise ValueError('exact_edit_candidate_changed')
                    paper['question_limit']=exact_intent.get('question_limit')
                    paper['candidate_question_ids']=[str(k) for k in candidate_ids]
                    paper['allocation_kp_ids']=[str(k) for k in ids]
                    paper['selected_kp_ids']=exact_intent['selected_kp_ids']
                    paper['scope_nodes']=[{**n,'assigned_count':sum(q['kp_id']==n['kp_id'] for q in paper['questions'])} for n in exact_intent.get('scope_nodes',[]) if n['kp_id'] in paper['selected_kp_ids']]
                elif scope_add_ids or (default and body.selected_kp_ids is not None
                        and set(body.selected_kp_ids)!={r.kp_id for r in recommendations}):
                    diagnostics={'diagnostic_id':uuid4().hex,'base_task_id':str(old.id) if old else None,
                        'base_draft_version':_draft_version(old) if old else None}
                    context['manual_allocation']=diagnostics
                    paper = _manual_scope_paper(db, scope_add_ids or body.selected_kp_ids, minutes, now, previous_paper or baseline,diagnostics=diagnostics)
                    ids = _allocation_ids(paper)
                    candidate_ids = [UUID(k) for k in paper['candidate_question_ids']]
                    context['unavailable_nodes']=[{'kp_id':n['kp_id'],'name':n['name'],'reason':n.get('allocation_reason') or '暂无合格题目'}
                        for n in paper['scope_nodes'] if n['allocation_status']!='allocated']
                    if paper['total_minutes']>minutes:
                        context['workload']={'requested_budget_minutes':minutes,'effective_budget_minutes':paper['total_minutes'],
                            'extra_minutes':paper['total_minutes']-minutes,'requires_confirmation':True}
                else:
                    paper = _paper(db, ids, minutes, now, question_limit, candidate_ids,
                        workload_preview=candidate_ids is not None,
                        adaptive_schedule=default)
                    if bank_request and previous_paper and bank_scope_plan:
                        # Preserve the full requested scope, including leaves
                        # that currently have no allocation. Only allocated
                        # leaves are fed to formal selection below.
                        requested=[UUID(k) for k in context['requested_scope_ids']]
                        paper['selected_kp_ids']=[str(k) for k in requested]
                        paper['allocation_kp_ids']=[str(k) for k in ids]
                        paper['scope_nodes']=[]
                        for k in requested:
                            node=db.get(KnowledgePoint,k)
                            count=sum(q['kp_id']==str(k) for q in paper['questions'])
                            paper['scope_nodes'].append({'kp_id':str(k),'name':node.name,
                                'parent_id':str(node.parent_id) if node.parent_id else None,
                                'assigned_count':count,'allocation_status':'allocated' if count else 'no_eligible_questions'})
                if candidate_ids is not None and {q["question_id"] for q in paper["questions"]} != {str(k) for k in candidate_ids}:
                    # 候选题与正式准入结果不一致时，不再用泛化错误码中断整次调整；
                    # 记录具体未准入原因并继续给出可用方案（用户仍可确认/继续调整）。
                    selected={q["question_id"] for q in paper["questions"]}
                    rejected=[]
                    for k in candidate_ids:
                        if str(k) in selected:
                            continue
                        cand=db.get(Question,k)
                        node=db.get(KnowledgePoint,cand.kp_id) if cand else None
                        reason="题目不存在或已失效"
                        if cand is not None and node is not None:
                            verdict=question_eligibility(cand,node)
                            reason=(verdict.public_dict().get("reason") or "未通过正式准入")
                        rejected.append({"question_id":str(k),"reason":reason})
                    diag=context.setdefault("bank_diagnostics",{})
                    diag["rejected_candidates"]=rejected
                    diag["formal_selected_ids"]=[q["question_id"] for q in paper["questions"]]
                    if rejected:
                        detail="；".join(f"{r['question_id'][:8]}：{r['reason']}" for r in rejected[:3])
                        context["bank_rejection_notice"]="部分候选题未通过正式准入（已改用合格题）："+detail
                if candidate_ids is not None and bank_request and bank_request.get('append') and previous_paper:
                    before=[(q['question_id'],q['question_version_id']) for q in previous_paper['questions']]
                    after=[(q['question_id'],q['question_version_id']) for q in paper['questions']]
                    if after[:len(before)]!=before:
                        raise ValueError('retained_question_identity_or_order_changed')
            if context.get('bank_diagnostics'):context['bank_diagnostics']['stage']='preview_assembly'
            if not paper["questions"]:
                row.message = "当前范围没有预算内的合格题；请增加预算或选择其他节点。"
            else:
                tools = _tools(db, now)
                tools.nodes.update(ids)
                evidence = []
                for k in ids:
                    evidence.extend(tools.get_learning_state(db, NodeIds(kp_ids=[k]))["states"])
                context["evidence"] = {"scope": [str(k) for k in ids], "states": evidence,
                    "captured_at": now.isoformat(),
                    "self_reports": read_self_reports(db, session.id),
                    "note": "最近每节点最多8条作答；客观记录、辅助观察、自述分开。缺少证据表示初始诊断，不代表薄弱。"}
                if baseline is None:
                    if default:
                        # The homepage's selected recommendation is the baseline
                        # the student actually saw, including manual tree choice.
                        baseline = paper.copy()
                    # A natural-language first turn derives its original
                    # baseline from the canonical system recommendation.
                    else:
                        try:
                            with db.begin_nested():
                                baseline = _paper(db, [r.kp_id for r in recommendations], minutes, now,
                                    adaptive_schedule=True)
                        except ValueError as exc:
                            baseline = {"selected_kp_ids": [str(r.kp_id) for r in recommendations],
                                "questions": [], "budget_minutes": minutes, "error": str(exc)}
                context["baseline"] = baseline
                before = {q["question_id"] for q in (baseline or {}).get("questions", [])}
                after = {q["question_id"] for q in paper["questions"]}
                paper["diff"] = {"added": sorted(after-before), "removed": sorted(before-after), "retained": sorted(after&before)}
                paper["scope_difference"] = {"system_kp_ids": [str(r.kp_id) for r in recommendations],
                    "requested_kp_ids": paper['selected_kp_ids'],
                    "different": set(paper['selected_kp_ids']) != {str(r.kp_id) for r in recommendations},
                    "mode": bank_scope_plan['scope_mode'] if bank_scope_plan else 'replace'}
                if candidate_ids is not None:
                    paper["candidate_question_ids"] = [str(k) for k in candidate_ids]
                prior_snapshot=previous_paper or baseline or {}
                prior_by_id={q.get('question_id'):q for q in prior_snapshot.get('questions',[])}
                next_by_id={q.get('question_id'):q for q in paper.get('questions',[])}
                removed_rows=[prior_by_id[key] for key in prior_by_id.keys()-next_by_id.keys()]
                added_rows=[next_by_id[key] for key in next_by_id.keys()-prior_by_id.keys()]
                prior_order={q.get('question_id'):index for index,q in enumerate(prior_snapshot.get('questions',[]))}
                removed_rows.sort(key=lambda q:prior_order.get(q.get('question_id'),0))
                changed_topic_ids={q.get('kp_id') for q in removed_rows+added_rows if q.get('kp_id')}
                last_topic_id=None;last_topic_name=None
                if subject_topic_summary and len(subject_topic_summary.get('destination_topics',[]))==1:
                    last_topic_id=subject_topic_summary['destination_topics'][0]['kp_id']
                    last_topic_name=subject_topic_summary['destination_topics'][0]['name']
                elif len(changed_topic_ids)==1:
                    last_topic_id=next(iter(changed_topic_ids))
                    last_node=db.get(KnowledgePoint,UUID(last_topic_id))
                    last_topic_name=last_node.name if last_node else None
                context['home_last_edit']={
                    'removed_questions':[{'question_id':q.get('question_id'),'question_version_id':q.get('question_version_id'),
                        'kp_id':q.get('kp_id')} for q in removed_rows],
                    'added_questions':[{'question_id':q.get('question_id'),'question_version_id':q.get('question_version_id'),
                        'kp_id':q.get('kp_id')} for q in added_rows],
                    'last_topic_kp_id':last_topic_id,'last_topic_name':last_topic_name,
                    'previous_task_id':str(old.id) if old else None,
                }
                paper=_ensure_scope_node_names(db,paper)
                row.draft, row.status = paper, "ready"
                shortage = minutes - paper["total_minutes"]
                row.message = f'试卷预览：{len(paper["questions"])} 道，预计 {paper["total_minutes"]} 分钟，预算 {minutes} 分钟。尚未创建今日卷。'
                if topic_count_summaries:
                    row.message+=' 知识点题量调整：'+'；'.join(
                        f"{item['name']} {item['before_count']}道→{item['count']}道，"
                        f"{'减少'+str(abs(item['delta']))+'道' if item['delta']<0 else '增加'+str(item['delta'])+'道'}，"
                        f"实际移除{len(item.get('removed_question_ids',[]))}道、加入{len(item.get('added_question_ids',[]))}道"
                        for item in topic_count_summaries)+'。'
                    if '[underspecified_quantities_defaulted_to_one]' in intent.terms:
                        row.message+=' 原话未给具体数量，每个“几道”先按1道拟成草案，可继续调整。'
                if subject_plan_summary:
                    selection_basis=('从未作答的' if subject_plan_summary['unattempted_only']
                        else '未学习或学习记录较少的')
                    row.message+=(f" 已按{selection_basis}{subject_plan_summary['subject']}知识点替换当前范围，"
                        f"安排{subject_plan_summary['topic_count']}个知识点，题目预计{paper['total_minutes']}分钟，预算{minutes}分钟；"
                        '原数学范围已从当前待确认方案移除，尚未生成正式今日卷。')
                if topic_removal_summaries:
                    row.message+=' 知识点批量调整：'+'；'.join(
                        f"{item['name']}原有{item['before_count']}道，计划移除{item['before_count']}道，"
                        f"受保护0道，调整后0道"
                        for item in topic_removal_summaries)+'；仍是待确认方案，尚未写入正式今日卷。'
                if subject_topic_summary:
                    src='、'.join(item['name'] for item in subject_topic_summary['source_topics'])
                    dest='、'.join(item['name'] for item in subject_topic_summary['destination_topics'])
                    row.message+=(f" 已将{src}的{subject_topic_summary['removed_count']}道题局部替换为{dest}的"
                        f"{subject_topic_summary['added_count']}道正式合格题；其他知识点题目保持原样，"
                        f"预算沿用{minutes}分钟，当前预计{paper['total_minutes']}分钟，尚未生成正式今日卷。")
                if context.get('workload'):
                    w=context['workload']
                    row.message+=f" 保留原题后预计{w['effective_budget_minutes']}分钟，比原预算{w['requested_budget_minutes']}分钟多{w['extra_minutes']}分钟；题量较大，生成前请确认是否继续。"
                elif shortage:
                    row.message += f' 当前正式选题策略与合格库存可安排这些题，少于预算 {shortage} 分钟；不会虚构题目凑时长。'
                if paper["scope_difference"]["different"]:
                    if paper["scope_difference"].get("mode") == "append":
                        row.message += " 已保留原系统推荐范围，并在此基础上追加真实题库题；原推荐范围没有被替换。"
                    else:
                        row.message += " 本次按你的专项范围调整，与原系统推荐范围不同；可恢复原推荐或继续调整范围。"
                if not any(s["recent_attempts"] for s in evidence):
                    row.message += " 尚无当前范围的客观作答记录；这是初始诊断卷，不能认定你的薄弱点。"
                if context.get('manual_allocation'):
                    diag=context['manual_allocation']
                    attempted=[n for n in diag['nodes'] if n['query_attempted']]
                    if attempted and not diag['new_assignment_count']:
                        row.message+=' 本次新增题目未能加入，原有已选题目已保留；请查看各知识点未分配原因。'
                    logging.getLogger(__name__).info('home manual assembled id=%s count=%s minutes=%s nodes=%s',
                        diag['diagnostic_id'],diag['total_count'],diag['total_minutes'],diag['nodes'])
        except ValueError as exc:
            if context.get('manual_allocation'):
                diag=context['manual_allocation'];diag.update(stage='selection_rejected',exception_type=type(exc).__name__,rejected_reason=str(exc))
                logging.getLogger(__name__).warning('home manual rejected id=%s stage=%s reason=%s',diag['diagnostic_id'],diag['stage'],diag['rejected_reason'])
            row.error_code="home_selection_rejected"
            row.message = f"当前范围无法形成正式试卷预览：{exc}。请检查题库资格/毕业题集或重新选择范围；旧预览已失效。"
            row.error_code = str(exc)[:60]
        except Exception as exc:
            # Keep the original server stack for diagnosis, never present a
            # selector outage as a successful paper or leave the old card active.
            logging.getLogger(__name__).exception("home recommendation selection failed")
            if context.get('manual_allocation'):
                context['manual_allocation'].update(stage='selection_exception',exception_type=type(exc).__name__)
            row.status, row.error_code = "failed", "home_selection_failed"
            row.draft = None
            row.message = "选题服务暂时失败，未生成试卷；旧预览已失效。请读取状态后重新调整。"
    workload_pending=row.status=='ready' and bool(context.get('workload',{}).get('requires_confirmation'))
    if workload_pending:
        context['workload_pending']=True
    if row.status in {'ready','cancelled'} and not workload_pending:
        # Supersede only after a successful replacement or explicit cancellation.
        for previous in rows:
            if ((previous.context or {}).get('home_recommendation') and previous.status=='ready'
                    and not (previous.metrics or {}).get('commit')):
                previous.status='cancelled'
    elif old is not None and old.status=='ready' and old.draft and not _legacy_incomplete_addition(old):
        # Editing a pending card must not promote that unaccepted card into
        # the fallback. Dismissing the new card restores the accepted plan.
        context['fallback_task_id']=str(_effective_row(db,old).id)
    elif baseline and baseline.get('questions') and not baseline.get('error'):
        # First adjustment can fail before any writable preview existed. Persist
        # the real read-only system paper as a usable fallback, never a formal plan.
        fallback_context={k:v for k,v in context.items() if k not in {'workload','workload_pending','bank_scope','bank_selection','bank_diagnostics','unavailable_nodes'}}
        fallback=LearningTask(session_id=session.id,goal='系统推荐',budget_minutes=baseline['budget_minutes'],
            status='ready',draft=baseline,trace=[],metrics={},message='原系统推荐仍保留，尚未生成正式卷。',
            context=_json_value({**fallback_context,'previous_task_id':None,'adjustment_notice':None if workload_pending else row.message,
                'home_request_key':body.request_key+':fallback','requested_scope_ids':baseline['selected_kp_ids']}))
        db.add(fallback);db.flush()
        context['fallback_task_id']=str(fallback.id)
    if row.status == 'ready' and not workload_pending:
        if history_transition:
            pass  # undo/redo stacks were moved only after the target snapshot was revalidated.
        elif body.action == 'restore' or restoring:
            undo_stack, redo_stack = [], []
        else:
            prior_entry = _history_entry(old, previous_paper or baseline)
            if prior_entry:
                undo_stack.append(prior_entry)
            redo_stack = []
    else:
        # A failed candidate or a not-yet-accepted budget card must not consume history.
        undo_stack, redo_stack = list(initial_undo_stack), list(initial_redo_stack)
    context['home_undo_stack'] = undo_stack[-30:]
    context['home_redo_stack'] = redo_stack[-30:]
    row.context = _json_value(context)
    # begin_nested() flushes the initial task. Later additions to its plain
    # JSON dict must be explicitly marked dirty (SQLAlchemy JSON is not mutable).
    flag_modified(row, "context")
    chat_message=row.message
    if row.status in {'failed','needs_info'} and context.get('fallback_task_id') and row.error_code in {
            'bank_lookup_failed','bank_parameter_contract_error','bank_query_error','bank_database_error',
            'bank_internal_error','home_selection_failed'}:
        chat_message='加入失败，原系统推荐已保留。'
    _record_request_dialogue(db,session,original_body,chat_message)
    db.flush()
    return _adjustment_view(db,row)


def confirm(db, task_id, body, now):
    _session(db, body.session_id)
    # Acquire the shared generation lock before the LearningTask row lock.
    # Adjustment takes the same order, avoiding stale successor confirmation
    # and lock-order deadlocks when a chat request races the button click.
    _serialize_daily_plan_mutation(db)
    row = db.get(LearningTask, task_id, with_for_update=True)
    if row is None or row.session_id != body.session_id or not (row.context or {}).get("home_recommendation"):
        raise AppError("learning_task_not_found", status_code=404)
    if body.draft_version != _draft_version(row):
        raise AppError("learning_task_conflict", status_code=409)
    if (row.metrics or {}).get("commit"):
        return _preview_view(db,row)
    _reject_materialized_daily_plan_mutation(db, now)
    if _legacy_incomplete_addition(row):
        raise AppError('learning_task_stale_draft', status_code=409)
    if _workload_pending(row):
        raise AppError('home_workload_confirmation_required',status_code=422)
    if ((row.context or {}).get('workload',{}).get('requires_confirmation')
            and not (row.context or {}).get('workload_accepted') and not body.accept_workload_increase):
        raise AppError('home_workload_confirmation_required', status_code=422)
    from datetime import datetime
    if row.status != "ready" or row.context["study_date"] != now.astimezone(SHANGHAI).date().isoformat() or datetime.fromisoformat(row.context["expires_at"]) <= now:
        raise AppError("learning_task_stale_draft", status_code=409)
    # A persisted successor is authoritative even if an old status projection
    # was left ready. Never substitute that successor as the confirmation target.
    successors = db.scalars(select(LearningTask).where(LearningTask.session_id == row.session_id,
        LearningTask.id != row.id))
    if any((item.context or {}).get("home_recommendation")
           and item.status in {'ready','answered','cancelled'} and not _workload_pending(item)
           and (item.context or {}).get('workload_decision')!='declined'
           and (item.context or {}).get("previous_task_id") == str(row.id) for item in successors):
        raise AppError("learning_task_stale_draft", status_code=409)
    paper = row.draft
    ids = _allocation_ids(paper)
    # The generation lock is already held; re-read candidates/versions under
    # the same transaction before materializing the official paper.
    db.scalars(select(KnowledgePoint).where(KnowledgePoint.id.in_(ids)).order_by(KnowledgePoint.id).with_for_update()).all()
    db.scalars(select(Question).where(Question.kp_id.in_(ids)).order_by(Question.id).with_for_update()).all()
    candidate_ids = [UUID(k) for k in paper["candidate_question_ids"]] if "candidate_question_ids" in paper else None
    # 难度调整是显式候选题替换，题集不由系统排序产生；逐题校验版本与资格，
    # 不再用 _paper 重建后要求完全相等。
    difficulty_paper = bool((row.context or {}).get("difficulty_adjusted")) or bool((row.context or {}).get("exact_edit")) or bool((row.context or {}).get("exact_bank_revision")) or any(
        str(item.get("reason", "")).startswith("难度") for item in paper["questions"])
    try:
        if difficulty_paper:
            for item in paper["questions"]:
                question = db.get(Question, UUID(item["question_id"]))
                version = db.get(QuestionVersion, UUID(item["question_version_id"]))
                node = db.get(KnowledgePoint, question.kp_id) if question else None
                if (question is None or version is None or version.question_id != question.id
                        or question.current_version_id != version.id
                        or not version.is_active or not question.is_active or question.is_hidden
                        or node is None or not question_eligibility(question, node).practice_eligible):
                    raise ValueError("difficulty_paper_stale")
        else:
            with db.begin_nested():
                current = _paper(db, ids, row.budget_minutes, now, paper.get("question_limit"), candidate_ids,
                    workload_preview=candidate_ids is not None,
                    adaptive_schedule=bool(paper.get("_adaptive_schedule", False)))
            if current["questions"] != paper["questions"]:
                raise AppError("learning_task_stale_draft", status_code=409)
    except AppError:
        raise
    except ValueError as exc:
        raise AppError("learning_task_stale_draft", status_code=409) from exc
    except Exception as exc:
        logging.getLogger(__name__).exception("home confirmation selection unavailable task=%s",row.id)
        raise AppError("home_selection_unavailable", status_code=503) from exc
    plan = create_initial_plan(db, study_date=now.astimezone(SHANGHAI).date(), selected_kp_ids=ids,
        now=now, budget=paper["preset"], minute_limit=None if candidate_ids is not None else row.budget_minutes, question_limit=None if candidate_ids is not None else paper.get("question_limit"),
        candidate_question_ids=candidate_ids, per_kp_limit=max(DEFAULT_PER_KP_LIMIT,len(candidate_ids)) if candidate_ids is not None else DEFAULT_PER_KP_LIMIT,
        adaptive_schedule=bool(paper.get("_adaptive_schedule", False)),
        exact_questions=[(UUID(q["question_id"]), UUID(q["question_version_id"])) for q in paper["questions"]] if difficulty_paper else None,
        confirm_legacy_set_transition_ids=body.confirm_legacy_set_transition_ids)
    db.flush()
    items = list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id == plan.id).order_by(PracticeItem.ordinal)))
    paper_pairs = [(q["question_id"], q["question_version_id"]) for q in paper["questions"]]
    item_pairs = [(str(i.question_id), str(i.question_version_id)) for i in items]
    if item_pairs != paper_pairs:
        # 难度调整保留原题面集合，但系统选题可能改变展示顺序；集合一致仍可确认。
        if not (difficulty_paper and len(item_pairs) == len(paper_pairs) and set(item_pairs) == set(paper_pairs)):
            raise AppError("learning_task_stale_draft", status_code=409)
    row.metrics = {**(row.metrics or {}), "memory_lifecycle": "closed",
        "commit": {"plan_id": str(plan.id), "item_ids": [str(i.id) for i in items], "draft_version": body.draft_version}}
    row.status = "answered"  # existing terminal status; commit distinguishes consumption
    # Legacy duplicate previews can survive in this same topic. Supersede only
    # equivalent homepage papers, never unrelated topics/history/tasks.
    for previous in db.scalars(select(LearningTask).where(LearningTask.session_id == row.session_id,
            LearningTask.id != row.id, LearningTask.status == "ready").order_by(LearningTask.id).with_for_update()):
        if ((previous.context or {}).get("home_recommendation")
                and not (previous.metrics or {}).get("commit")
                and _paper_identity(previous.draft) == _paper_identity(paper)):
            previous.status = "cancelled"
            previous.metrics = {**(previous.metrics or {}), "memory_lifecycle": "closed", "superseded_by": str(row.id)}
    row.message = f"已按最终预览生成 {len(items)} 道题的今日卷。"
    db.flush()
    return _preview_view(db,row)


def _paper_identity(paper):
    if not paper:
        return None
    return (paper.get("budget_minutes"), paper.get("total_minutes"),
        tuple((q.get("question_id"), q.get("question_version_id"), q.get("version"), q.get("minutes"))
            for q in paper.get("questions", [])))
