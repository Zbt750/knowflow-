"""Explicit formal-paper changes; never delete item or learning history rows."""
from datetime import timedelta
from hashlib import sha256
import json
from uuid import UUID
from zoneinfo import ZoneInfo
from sqlalchemy import select, text
from backend.errors import AppError
from backend.models.chat import ChatSession
from backend.models.learning import DailyPlan, PracticeItem, Question, QuestionAttempt, LearningEvent
from backend.models.learning_task import LearningTask
from backend.services.practice_service import DAILY_PLAN_MATERIALIZATION_LOCK_KEY, append_questions_to_plan
from backend.services.question_versions import question_version_reference

PAPER_ADJUSTMENT_LOCK_KEY = 6482097143307121


def _lock_adjustment_workflow(db):
    """Serialize proposal supersession and confirmation before task/plan locks."""
    db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key':PAPER_ADJUSTMENT_LOCK_KEY})


def protection_state(item, kinds, has_attempt):
    if item.removed_at is not None: return 'removed'
    if item.completed_at is not None: return 'completed'
    if has_attempt: return 'submitted'
    if 'started' in kinds or item.answer_revealed_at is not None: return 'started'
    if 'skipped' in kinds: return 'skipped'
    if 'viewed' in kinds: return 'viewed'
    return 'planned'


def require_removable(state, *, viewed_confirmed=False):
    if state not in {'planned', 'viewed'}:
        raise AppError('paper_item_protected', status_code=409)
    if state == 'viewed' and not viewed_confirmed:
        raise AppError('paper_viewed_confirmation_required', status_code=409)


def _version(draft):
    return sha256(json.dumps(draft, sort_keys=True).encode()).hexdigest()


def _items(db, plan_id):
    return list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id == plan_id)
        .order_by(PracticeItem.id).with_for_update().execution_options(populate_existing=True)))


def _signature(items):
    return _version([{'id':str(i.id), 'version':str(i.question_version_id),
        'removed':i.removed_at.isoformat() if i.removed_at else None} for i in items])


def _state(db, item):
    kinds = {e.payload.get('kind') for e in db.scalars(select(LearningEvent).where(
        LearningEvent.source_id == item.id, LearningEvent.event_type == 'scheduler_activity'))}
    attempt = db.scalar(select(QuestionAttempt.id).where(QuestionAttempt.practice_item_id == item.id).limit(1))
    return protection_state(item, kinds, attempt is not None)


def _session(db, session_id):
    row = db.get(ChatSession, session_id)
    if row is None or row.archived_at is not None or row.mode != 'builtin':
        raise AppError('chat_session_not_found', status_code=404)


def propose_adjustment(factory, body, *, now):
    with factory.begin() as db:
        _lock_adjustment_workflow(db)
        _session(db, body.session_id)
        pending=[row for row in db.scalars(select(LearningTask).where(
            LearningTask.session_id==body.session_id).order_by(LearningTask.id).with_for_update())
            if row.status=='ready' and (row.context or {}).get('paper_adjustment')
            and not (row.metrics or {}).get('commit')]
        plan = db.scalar(select(DailyPlan).where(DailyPlan.id == body.plan_id).with_for_update())
        if (plan is None or plan.status != 'active'
                or plan.study_date != now.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()):
            raise AppError('learning_task_conflict', status_code=409, detail='plan_state_changed')
        items = _items(db, plan.id)
        selected = {i.id:i for i in items if i.id in body.remove_item_ids}
        if len(selected) != len(body.remove_item_ids) or (not selected and not body.replacements):
            raise AppError('learning_task_conflict', status_code=409, detail='selection_changed_or_empty')
        states = {str(i.id):_state(db,i) for i in selected.values()}
        for state in states.values(): require_removable(state, viewed_confirmed=True)
        existing = {i.question_id for i in items}
        replacements=[]
        for ref in body.replacements:
            question=db.get(Question, ref.question_id)
            if question is None:
                raise AppError('learning_task_stale_draft',status_code=409,
                    detail='replacement_question_missing')
            if question.id in existing:
                raise AppError('learning_task_stale_draft',status_code=409,
                    detail='replacement_already_in_plan')
            if question.bank_scope != 'public':
                raise AppError('learning_task_stale_draft',status_code=409,
                    detail='replacement_not_public')
            if question_version_reference(question) != str(ref.question_version_id):
                raise AppError('learning_task_stale_draft',status_code=409,
                    detail='replacement_version_changed')
            from backend.models.learning import KnowledgePoint
            from backend.services.question_eligibility import question_eligibility
            if not question_eligibility(question, db.get(KnowledgePoint,question.kp_id)).practice_eligible:
                raise AppError('learning_task_stale_draft',status_code=409,
                    detail='replacement_not_formally_eligible')
            replacements.append(ref.model_dump(mode='json'))
        if len({r['question_id'] for r in replacements}) != len(replacements):
            raise AppError('learning_task_conflict',status_code=409,detail='duplicate_replacements')
        draft={'kind':'paper_adjustment', 'plan_id':str(plan.id), 'signature':_signature(items),
            'remove_item_ids':list(map(str,body.remove_item_ids)), 'replacements':replacements,
            'states':states, 'expires_at':(now+timedelta(minutes=30)).isoformat()}
        row=LearningTask(session_id=body.session_id,goal='正式卷受控调整',budget_minutes=body.budget_minutes,
            status='ready',draft=draft,context={'paper_adjustment':True},metrics={})
        db.add(row);db.flush()
        for old in pending:
            old.status='cancelled'
            old.context={**(old.context or {}),'superseded_by':str(row.id),'superseded_at':now.isoformat()}
            old.message='该待确认方案已被同一会话中的更新方案取代。'
        return {'task_id':str(row.id),'draft_version':_version(draft),'draft':draft,
            'requires_viewed_confirmation':'viewed' in states.values()}


def confirm_adjustment(factory, task_id, body, *, now):
    with factory.begin() as db:
        _lock_adjustment_workflow(db)
        row=db.scalar(select(LearningTask).where(LearningTask.id==task_id).with_for_update())
        if row is None or row.session_id != body.session_id:
            raise AppError('learning_task_not_found',status_code=404)
        _session(db,body.session_id)
        draft=row.draft or {}
        if not (row.context or {}).get('paper_adjustment') or body.draft_version != _version(draft):
            raise AppError('learning_task_conflict',status_code=409)
        if (row.metrics or {}).get('commit'): return row.metrics['commit']
        from datetime import datetime
        if row.status != 'ready' or now >= datetime.fromisoformat(draft['expires_at']):
            raise AppError('learning_task_stale_draft',status_code=409)
        db.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':DAILY_PLAN_MATERIALIZATION_LOCK_KEY})
        plan=db.scalar(select(DailyPlan).where(DailyPlan.id==UUID(draft['plan_id'])).with_for_update())
        if (plan is None or plan.status != 'active'
                or plan.study_date != now.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()):
            raise AppError('learning_task_conflict',status_code=409)
        items=_items(db,plan.id)
        if _signature(items)!=draft['signature']:raise AppError('learning_task_stale_draft',status_code=409)
        selected=[i for i in items if str(i.id) in draft['remove_item_ids']]
        for item in selected:
            state=_state(db,item)
            if state != draft['states'][str(item.id)]:
                raise AppError('learning_task_stale_draft',status_code=409)
            require_removable(state,viewed_confirmed=body.confirm_viewed)
        replacement_ids=[];minutes=0
        for ref in draft['replacements']:
            q=db.get(Question,UUID(ref['question_id']))
            if q is None or question_version_reference(q)!=ref['question_version_id']:
                raise AppError('learning_task_stale_draft',status_code=409)
            minutes+=q.estimated_minutes
            replacement_ids.append(q.id)
        if minutes>row.budget_minutes:raise AppError('learning_task_conflict',status_code=409)
        try:
            added=append_questions_to_plan(db,plan_id=plan.id,question_ids=replacement_ids) if replacement_ids else 0
        except ValueError:
            raise AppError('learning_task_stale_draft',status_code=409) from None
        if added!=len(replacement_ids):raise AppError('learning_task_stale_draft',status_code=409)
        for ref in draft['replacements']:
            q=db.get(Question,UUID(ref['question_id']),populate_existing=True)
            if q.bank_scope != 'public' or question_version_reference(q)!=ref['question_version_id']:
                raise AppError('learning_task_stale_draft',status_code=409)
        for item in selected:
            item.removed_at=now
            db.add(LearningEvent(kp_id=item.kp_id,source_id=item.id,question_version_id=item.question_version_id,
                event_type='paper_item_removed',occurred_at=now,idempotency_key=f'paper-remove:{row.id}:{item.id}',
                payload={'task_id':str(row.id),'plan_id':str(plan.id),'changes_mastery':False}))
        db.flush()
        active=list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id==plan.id,PracticeItem.removed_at.is_(None))))
        receipt={'task_id':str(row.id),'plan_id':str(plan.id),'removed_item_ids':draft['remove_item_ids'],
            'added_count':added,'total_count':len(active),'active_item_ids':[str(i.id) for i in active]}
        from backend.services.today_append_result import paper_time_estimates
        receipt.update(paper_time_estimates(db,active))
        if replacement_ids:
            from backend.services.today_append_result import read_append_result
            new_ids=[i.id for i in active if i.question_id in replacement_ids]
            added_receipt=read_append_result(db,operation_id=row.id,plan_id=plan.id,
                item_ids=new_ids,added_count=added)
            if added_receipt is None:raise AppError('learning_task_stale_draft',status_code=409)
            receipt['added_items']=added_receipt['items']
        row.metrics={'commit':receipt};row.message=f'已移除{len(selected)}道，新增{added}道，当前共{len(active)}道。'
    return receipt
