"""Atomic inverse changes to a formal paper; original item/version identities survive."""
from uuid import UUID
from zoneinfo import ZoneInfo
from sqlalchemy import select
from backend.errors import AppError
from backend.models.learning import DailyPlan,Question,KnowledgePoint,LearningEvent
from backend.models.learning_task import LearningTask
from backend.services.paper_adjustment_service import (
    _lock_adjustment_workflow,_session,_items,_signature,_state,require_removable,
)
from backend.services.today_append_result import paper_time_estimates


class ReversalConfirmationRequired(AppError):
    def __init__(self,operation_id,signature,workload,viewed,restored,removed):
        super().__init__('paper_reversal_confirmation_required',status_code=409)
        self.pending={'task_id':str(operation_id),'signature':signature,'workload':workload,
                      'viewed':viewed,'restored_count':restored,'removed_count':removed}


def _plan(db,plan_id,now):
    plan=db.scalar(select(DailyPlan).where(DailyPlan.id==plan_id).with_for_update())
    if (plan is None or plan.status!='active'
            or plan.study_date!=now.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()):
        raise AppError('learning_task_conflict',status_code=409)
    return plan


def _eligible_original(db,item):
    from backend.services.question_eligibility import question_eligibility
    q=db.get(Question,item.question_id) if item.question_id else None
    if (q is None or q.current_version_id!=item.question_version_id
            or not question_eligibility(q,db.get(KnowledgePoint,item.kp_id)).practice_eligible):
        raise AppError('paper_restore_not_admitted',status_code=409)
    if q.bank_scope=='personal' and (q.grading_config or {}).get('math_verification',{}).get('status') != 'verified':
        raise AppError('paper_restore_not_admitted',status_code=409)


def _receipt(db,plan,items,*,operation_id,before,restored,removed):
    active=[i for i in items if i.removed_at is None]
    if len({i.question_id for i in active})!=len(active):
        raise AppError('learning_task_stale_draft',status_code=409)
    return {'task_id':str(operation_id),'plan_id':str(plan.id),'operation':'paper_reversal',
        'before_count':before,'removed_item_ids':[str(i.id) for i in removed],
        'restored_item_ids':[str(i.id) for i in restored],'restored_count':len(restored),
        'added_count':0,'total_count':len(active),'active_item_ids':[str(i.id) for i in active],
        **paper_time_estimates(db,active)}


def undo_latest_replacement(factory,*,session_id,plan_id,now,operation_id=None,
                            expected_signature=None,confirm_viewed=False,accept_budget_overrun=False):
    with factory.begin() as db:
        _lock_adjustment_workflow(db);_session(db,session_id);plan=_plan(db,plan_id,now)
        tasks=list(db.scalars(select(LearningTask).where(LearningTask.session_id==session_id)
            .order_by(LearningTask.created_at.desc(),LearningTask.id).with_for_update()))
        task=next((t for t in tasks if (t.context or {}).get('paper_adjustment')
            and (t.draft or {}).get('plan_id')==str(plan.id)
            and (t.draft or {}).get('remove_item_ids') and (t.draft or {}).get('replacements')
            and (t.metrics or {}).get('commit')),None)
        if task is None:raise AppError('paper_undo_no_operation',status_code=409)
        if operation_id is not None and str(task.id)!=str(operation_id):
            raise AppError('learning_task_stale_draft',status_code=409)
        if (task.metrics or {}).get('undo_commit'):
            return {**task.metrics['undo_commit'],'replayed':True}
        items=_items(db,plan.id);signature=_signature(items)
        if expected_signature is not None and signature!=expected_signature:
            raise AppError('learning_task_stale_draft',status_code=409)
        active=[i for i in items if i.removed_at is None]
        commit=task.metrics['commit']
        if {str(i.id) for i in active}!=set(commit.get('active_item_ids') or []):
            raise AppError('learning_task_stale_draft',status_code=409)
        old_ids=set(task.draft['remove_item_ids']);new_qids={r['question_id'] for r in task.draft['replacements']}
        originals=[i for i in items if str(i.id) in old_ids]
        added=[i for i in active if str(i.question_id) in new_qids]
        if len(originals)!=len(old_ids) or len(added)!=len(new_qids) or any(i.removed_at is None for i in originals):
            raise AppError('learning_task_stale_draft',status_code=409)
        viewed=False
        for item in added:
            state=_state(db,item);require_removable(state,viewed_confirmed=True)
            viewed=viewed or state=='viewed'
        for item in originals:_eligible_original(db,item)
        kept=[i for i in active if i not in added]
        remaining=paper_time_estimates(db,kept+originals)['remaining_minutes']
        if remaining is None:raise AppError('paper_budget_unknown',status_code=409)
        budget=task.budget_minutes
        workload={'remaining_minutes':remaining,'budget_minutes':budget,'excess_minutes':max(0,remaining-budget)}
        if (viewed and not confirm_viewed) or (remaining>budget and not accept_budget_overrun):
            raise ReversalConfirmationRequired(task.id,signature,workload,viewed,len(originals),len(added))
        # All scope, admission, protection and budget checks precede either side
        # of the inverse. Exceptions roll back both sides and their audit facts.
        for item in originals:
            item.removed_at=None
            db.add(LearningEvent(kp_id=item.kp_id,source_id=item.id,question_version_id=item.question_version_id,
                event_type='paper_item_restored',occurred_at=now,
                idempotency_key=f'paper-undo-restore:{task.id}:{item.id}',
                payload={'changes_mastery':False,'undo_of_task':str(task.id)}))
        for item in added:
            item.removed_at=now
            db.add(LearningEvent(kp_id=item.kp_id,source_id=item.id,question_version_id=item.question_version_id,
                event_type='paper_item_removed',occurred_at=now,
                idempotency_key=f'paper-undo-remove:{task.id}:{item.id}',
                payload={'changes_mastery':False,'undo_of_task':str(task.id)}))
        db.flush()
        result=_receipt(db,plan,items,operation_id=task.id,before=len(active),restored=originals,removed=added)
        result.update(budget_minutes=budget,budget_overrun_minutes=workload['excess_minutes'],
                      budget_overrun_accepted=remaining>budget)
        task.metrics={**task.metrics,'undo_commit':result}
        return result


def restore_removed_items(factory,*,session_id,plan_id,now,count=1,recent_only=False):
    with factory.begin() as db:
        _lock_adjustment_workflow(db);_session(db,session_id);plan=_plan(db,plan_id,now)
        items=_items(db,plan.id)
        tasks=[t for t in db.scalars(select(LearningTask).where(LearningTask.session_id==session_id)
            .order_by(LearningTask.created_at.desc(),LearningTask.id).with_for_update())
            if (t.context or {}).get('paper_adjustment') and (t.draft or {}).get('plan_id')==str(plan.id)
            and (t.metrics or {}).get('commit')]
        pool=sorted((i for i in items if i.removed_at is not None),key=lambda i:(i.removed_at,str(i.id)),reverse=True)
        if recent_only:
            ids=set((tasks[0].draft or {}).get('remove_item_ids',[])) if tasks else set()
            pool=[i for i in pool if str(i.id) in ids]
        chosen=pool[:min(int(count),len(pool))]
        if not chosen:return None
        active=[i for i in items if i.removed_at is None]
        active_questions={i.question_id for i in active}
        for item in chosen:
            _eligible_original(db,item)
            if item.question_id in active_questions:raise AppError('learning_task_stale_draft',status_code=409)
            active_questions.add(item.question_id)
        remaining=paper_time_estimates(db,active+chosen)['remaining_minutes']
        if remaining is None:raise AppError('paper_budget_unknown',status_code=409)
        budget=tasks[0].budget_minutes if tasks else 90
        if remaining>budget:raise AppError('paper_budget_confirmation_required',status_code=409)
        for item in chosen:
            item.removed_at=None
            db.add(LearningEvent(kp_id=item.kp_id,source_id=item.id,question_version_id=item.question_version_id,
                event_type='paper_item_restored',occurred_at=now,
                idempotency_key=f'paper-restore:{item.id}:{int(now.timestamp()*1000000)}',
                payload={'changes_mastery':False,'plan_id':str(plan.id)}))
        db.flush()
        result=_receipt(db,plan,items,operation_id=tasks[0].id if tasks else plan.id,
            before=len(active),restored=chosen,removed=[])
        return result
