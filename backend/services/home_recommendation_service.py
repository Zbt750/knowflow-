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

from sqlalchemy import select, text
from sqlalchemy.orm.attributes import flag_modified
from backend.errors import AppError
from backend.models.chat import ChatMessage, ChatSession
from backend.models.learning import DailyPlan, KnowledgePoint, PracticeItem, Question, QuestionVersion
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


def _result_view(db, row):
    active=_effective_row(db,row)
    result=view(active)
    if result is not None:
        notice=(row.message if active is not row and row.status in {'failed','needs_info'}
                else (row.context or {}).get('adjustment_notice'))
        if notice:
            result['adjustment_error']=notice
            if (row.context or {}).get('request_origin') in {'system','chat'}:
                result['adjustment_origin']=row.context['request_origin']
        if _workload_pending(row) and not result.get('receipt'):
            result['workload_candidate']=view(row)
        if active is row:
            retained=_retained_baseline(row)
            if retained:
                result['retained_baseline']=retained
                result['adjustment_error']=result['message']
                if (row.context or {}).get('request_origin') in {'system','chat'}:
                    result['adjustment_origin']=row.context['request_origin']
    return result


def _adjustment_view(db, row):
    result=view(row)
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


def _paper(db, ids, minutes, now, question_limit=None, candidate_question_ids=None, *, workload_preview=False, coverage_preview=False, selection_diagnostics=None):
    # Ranking and eligibility remain shared. Exact bank additions retain their
    # complete candidate collection; workload is confirmed rather than truncated.
    preset = "deep" if minutes > 90 else "standard"
    picked = preview_initial_questions(db, selected_kp_ids=ids, now=now,
        budget=preset, minute_limit=None if workload_preview or coverage_preview else minutes, question_limit=None if workload_preview else question_limit,
        candidate_question_ids=candidate_question_ids,
        per_kp_limit=max(DEFAULT_PER_KP_LIMIT, len(candidate_question_ids)) if candidate_question_ids is not None else DEFAULT_PER_KP_LIMIT,
        require_active_version=True,
        **({'selection_diagnostics':selection_diagnostics} if selection_diagnostics is not None else {}))
    questions = []
    for kp_id, selection, _, question_id, _ in picked:
        q = db.get(Question, question_id)
        node = db.get(KnowledgePoint, kp_id)
        version=db.get(QuestionVersion,q.current_version_id) if q.current_version_id else None
        if not version or not version.is_active or not question_eligibility(q, node).practice_eligible:
            raise ValueError("question_version_or_eligibility_invalid")
        questions.append({"question_id": str(q.id), "question_version_id": str(q.current_version_id),
            "version": question_version_reference(q), "kp_id": str(kp_id), "kp_name": node.name,
            "stem": q.stem, "options": q.options, "difficulty": q.difficulty, "minutes": selection.estimated_minutes,
            "reason": selection.reason, "eligibility": question_eligibility(q, node).public_dict()})
    return {"questions": _json_value(questions), "selected_kp_ids": [str(k) for k in ids],
        "budget_minutes": minutes, "total_minutes": sum(q["minutes"] for q in questions),
        "preset": preset, "question_limit": question_limit}


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
    if paper['questions']!=chosen:
        diagnostics.update(stage='formal_revalidation',rejected_reason='manual_retained_question_identity_or_order_changed')
        raise ValueError('manual_retained_question_identity_or_order_changed')
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


def read_system(db, recommendations, now):
    """Read the canonical recommendation without creating a conversation or task."""
    from backend.services.question_availability import question_availability
    ids = [r.kp_id for r in recommendations]
    inventory = question_availability(db, now=now, kp_ids=ids, limit=24) if ids else None
    paper, blockers = None, []
    if ids:
        try:
            paper = _paper(db, ids, 90, now)
        except ValueError as exc:
            blockers.append(f"正式选题暂不能形成初案：{exc}；请核对题库资格或选择其他范围。")
    else:
        blockers.append("当前没有可推荐的考核节点，请在知识树选择现有范围。")
    tools = _tools(db, now)
    tools.nodes.update(ids)
    states = []
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
        if re.fullmatch(r'(?:撤销(?:刚才的)?(?:修改|操作|调整)?|再撤销(?:上一步|刚才的修改)?|撤回(?:最后一步|刚才的修改|上一步)?|回到上一步|恢复上一步|把刚才删除的题恢复)[。！!]?', command):
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
        if old:
            old.context = {**old.context, "evidence": facts}
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
        if old:
            old.message = message
        _record_request_dialogue(db,session,body,message)
        db.flush()
        return view(old) if old else {"kind": "explanation", "session_id": str(session.id), "message": message}
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
        return view(old)
    if baseline is None and (old is None or old.status!='ready') and system_ids:
        # Capture canonical A before any first manual/chat revision can fail.
        try:
            with db.begin_nested():
                baseline=_paper(db,system_ids,90,now)
        except Exception as exc:
            logging.getLogger(__name__).warning('home baseline unavailable type=%s',type(exc).__name__)
            baseline=None
    exact_intent=None
    intent=None
    exact_bank_used=False
    exact_edit_used=False
    scope_add_ids=None
    intent_trace=None
    exact_bank_evidence=None
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
        intent,intent_trace=resolve(body.goal,previous_paper or baseline,intent_provider_factory,history_factory=history)
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
        if intent.operation in {'clarify','generate_guidance','accept','return'}:
            return notice(intent.question or ('正式生成请使用首页“确定生成试卷”；接受或返回请使用当前方案卡片。'))
        if intent.operation in {'fill_time','replace_question'}:
            current=previous_paper or baseline
            if not current or not current.get('questions'):
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
    minutes = int(minutes_match[-1]) if minutes_match else body.budget_minutes or (old.budget_minutes if old else 90)
    if exact_intent:minutes=exact_intent['budget_minutes']
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
        ids = body.selected_kp_ids if body.selected_kp_ids is not None else [r.kp_id for r in recommendations]
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
                        baseline = _paper(db, system_ids, 90, now)
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
    if prior_constraints:context['adjustment_constraints']=prior_constraints
    if bank_scope_plan:
        context['bank_scope'] = _json_value(bank_scope_plan)
    from backend.services.question_availability import question_availability
    context["inventory"] = question_availability(db, now=now, kp_ids=ids, limit=24) if ids else None
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
        if bank_error:
            row.error_code=context['bank_selection']['error']
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
                elif scope_add_ids or (default and body.selected_kp_ids is not None):
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
                    paper = _paper(db, ids, minutes, now, question_limit, candidate_ids, workload_preview=candidate_ids is not None)
                    if bank_request and previous_paper and previous_paper.get('scope_nodes'):
                        # An explicitly retained empty leaf is still part of the
                        # user's scope, but cannot be fed to formal selection.
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
                    context.setdefault("bank_selection",{})["formal_selected_ids"]=[q["question_id"] for q in paper["questions"]]
                    raise ValueError("bank_candidates_not_selected_by_formal_policy")
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
                                baseline = _paper(db, [r.kp_id for r in recommendations], minutes, now)
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
                row.draft, row.status = paper, "ready"
                shortage = minutes - paper["total_minutes"]
                row.message = f'试卷预览：{len(paper["questions"])} 道，预计 {paper["total_minutes"]} 分钟，预算 {minutes} 分钟。尚未创建今日卷。'
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
        context['fallback_task_id']=str(old.id)
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
        return view(row)
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
    difficulty_paper = bool((row.context or {}).get("difficulty_adjusted")) or bool((row.context or {}).get("exact_edit")) or any(
        str(item.get("reason", "")).startswith("难度") for item in paper["questions"])
    try:
        if difficulty_paper:
            for item in paper["questions"]:
                question = db.get(Question, UUID(item["question_id"]))
                version = db.get(QuestionVersion, UUID(item["question_version_id"]))
                node = db.get(KnowledgePoint, question.kp_id) if question else None
                if (question is None or version is None or version.question_id != question.id
                        or not version.is_active or not question.is_active or question.is_hidden
                        or node is None or not question_eligibility(question, node).practice_eligible):
                    raise ValueError("difficulty_paper_stale")
        else:
            with db.begin_nested():
                current = _paper(db, ids, row.budget_minutes, now, paper.get("question_limit"), candidate_ids, workload_preview=candidate_ids is not None)
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
    return view(row)


def _paper_identity(paper):
    if not paper:
        return None
    return (paper.get("budget_minutes"), paper.get("total_minutes"),
        tuple((q.get("question_id"), q.get("question_version_id"), q.get("version"), q.get("minutes"))
            for q in paper.get("questions", [])))
