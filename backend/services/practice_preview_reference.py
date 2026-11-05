"""Resolve only persisted same-conversation business previews, never model prose."""
import re
from datetime import datetime,timedelta
from uuid import UUID
from sqlalchemy import select
from backend.models.chat import ChatMessage, ChatSession
from backend.models.practice_request import PracticeRequest
from backend.models.learning_task import LearningTask
from backend.models.learning import DailyPlan, KnowledgePoint, PracticeItem, Question, QuestionAttempt, QuestionVersion
from backend.services.question_eligibility import question_eligibility
from backend.services.question_versions import question_version_reference
from zoneinfo import ZoneInfo


def _preview_is_current(evidence, now):
    try:
        stamp=datetime.fromisoformat(evidence.get('preview_generated_at') or '')
        return timedelta(0)<=now-stamp<=timedelta(minutes=30)
    except (ValueError, TypeError, OverflowError):
        return False


def latest_preview(factory, session_id, message, now):
    with factory() as db:
        session=db.get(ChatSession,session_id)
        if session and session.purpose=='study':
            today=now.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
            formal_plan=db.scalar(select(DailyPlan).where(DailyPlan.study_date==today))
            if formal_plan is None:
                return None,'今日正式学习卷尚未生成；生成前不会引用或展示具体题目。请先调整知识点、合格题量和预算，再由你确认生成今日卷。'
        row = db.scalar(select(ChatMessage).where(ChatMessage.session_id == session_id,
            ChatMessage.role == 'assistant', ChatMessage.status == 'completed')
            .order_by(ChatMessage.seq.desc()).limit(1))
        if not row:
            return None, '没有可确定的上一轮题目，请先查询或预览一道题。'
        meta = row.metadata_ or {}
        antecedent=meta.get('preview_antecedent_message_id')
        if antecedent:
            prior=db.get(ChatMessage,UUID(antecedent))
            if prior and prior.session_id==session_id and prior.role=='assistant' and prior.status=='completed':
                row=prior;meta=row.metadata_ or {}
        evidence = meta.get('read_only_data_query') or {}
        refs = evidence.get('preview_questions') or []
        state = evidence.get('query_state') or {}
        request_id = meta.get('practice_request_id')
        committed=False
        if refs:
            if not _preview_is_current(evidence, now):
                return None, '这份题库预览已过期或缺少有效期，请重新查询后再选择。'
        if request_id:
            request = db.get(PracticeRequest, UUID(request_id))
            if not request or request.source_conversation_id != session_id or request.status in {'declined','expired'} or (request.status!='accepted' and request.expires_at<=now):
                return None, '上一方案已取消、失效或已入卷；不会删除原卷题目。请重新预览需要安排的题。'
            refs = (request.request.get('preview_draft') or {}).get('questions') or []
            state = (request.request.get('constraints') or {}).get('preview_query_state') or {}
            committed=request.status=='accepted'
        if not refs:
            # 追加/作答回复会覆盖“最近一条”；向前回溯到最近含预览的消息。
            older_rows = list(db.scalars(select(ChatMessage).where(
                ChatMessage.session_id == session_id, ChatMessage.role == 'assistant',
                ChatMessage.status == 'completed').order_by(ChatMessage.seq.desc()).limit(20)))
            for older in older_rows:
                older_evidence = (older.metadata_ or {}).get('read_only_data_query') or {}
                if older_evidence.get('preview_questions'):
                    row = older
                    meta = older.metadata_ or {}
                    evidence = older_evidence
                    refs = evidence.get('preview_questions') or []
                    state = evidence.get('query_state') or {}
                    request_id = meta.get('practice_request_id')
                    break
        if not refs and meta.get('planner_task_id'):
            task=db.get(LearningTask,UUID(meta['planner_task_id']))
            if task and task.session_id==session_id and (task.metrics or {}).get('commit'):
                refs=(task.draft or {}).get('questions') or []
                state=(((task.context or {}).get('planner_handoff') or {}).get('constraints') or {}).get('preview_query_state') or {}
                committed=True
        if not refs:
            return None, '上一轮没有可引用的有效题目预览，请先选一道题。'
        # Historical fallback must satisfy exactly the same TTL as the latest
        # message. A later unrelated answer cannot renew an old preview.
        if evidence.get('preview_questions') and not request_id and not committed:
            if not _preview_is_current(evidence, now):
                return None, '这份题库预览已过期或缺少有效期，请重新查询后再选择。'
        match = re.search(r'第\s*([一二两三四五六七八九十\d]+)\s*道', message)
        if match:
            token = match.group(1)
            number = int(token) if token.isdigit() else {'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}.get(token, 0)
            if not 1 <= number <= len(refs):
                return None, '这个题号不在上一轮预览中，请明确预览中的题号。'
            refs = [refs[number-1]]
        elif len(refs) != 1:
            return None, '上一轮展示了多道题，请明确第几道；尚未创建安排方案。'
        ref = refs[0]
        return {'question_id':ref['question_id'], 'question_version':ref.get('question_version') or ref.get('question_version_id'),
            'kp_id':ref['kp_id'], 'question_type':ref.get('question_type'), 'query_state':state,
            'request_id':request_id, 'source_message_id':str(row.id),'committed_reference':committed}, None


def preview_question_state(factory, reference, ctx, now):
    """Check the exact preview version against live eligibility and the displayed paper."""
    try:
        question_id=UUID(str(reference['question_id']))
        version_id=UUID(str(reference['question_version']))
    except (KeyError,TypeError,ValueError):
        return {'state':'stale_preview','message':'上一轮题目预览缺少有效题目版本；请重新查询，未创建安排。'}
    with factory() as db:
        question=db.get(Question,question_id)
        version=db.get(QuestionVersion,version_id)
        node=db.get(KnowledgePoint,question.kp_id) if question else None
        if (not question or not version or version.question_id!=question_id
                or question_version_reference(question)!=str(version_id)):
            return {'state':'stale_preview','message':'上一轮预览的题目版本已变化或失效；请重新查询最新版本，未创建安排。'}
        assessment=question_eligibility(question,node) if node else None
        if not assessment or not assessment.practice_eligible:
            return {'state':'stale_preview','message':'上一轮预览的题目当前不符合在线可练资格；请重新查询，未创建安排。'}
        today=now.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
        plan=db.get(DailyPlan,ctx.daily_plan_id) if ctx.daily_plan_id else None
        # A page may still carry yesterday's plan identifier after midnight.
        # Only a plan whose business date is today can establish that this
        # exact preview is already on today's paper.
        if plan is not None and plan.study_date!=today:
            plan=None
        if plan is None:
            plan=db.scalar(select(DailyPlan).where(DailyPlan.study_date==today))
        if not plan:
            if reference.get('committed_reference'):
                return {'state':'stale_preview','message':'原选题操作已确认，但当前今日卷未找到该操作对应题目；请核对原卷记录，不会自动重复加入。'}
            return None
        paper_items=list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id==plan.id)
            .order_by(PracticeItem.ordinal,PracticeItem.id)))
        items=[item for item in paper_items if item.question_id==question_id]
        if not items:
            if reference.get('committed_reference'):
                return {'state':'stale_preview','message':'原选题操作已确认，但当前今日卷未找到该题；请核对原卷记录，不会自动重复加入。'}
            return None
        item=items[0]
        from backend.services.question_versions import question_for_practice_item
        from backend.services.practice_display_order import display_key
        bound={row.id:question_for_practice_item(db,row) for row in paper_items}
        ordered=sorted(paper_items,key=lambda row:display_key(
            bound[row.id].question_type if bound[row.id] else 'external_exam',row.ordinal))
        number=next(index for index,row in enumerate(ordered,1) if row.id==item.id)
        attempts=list(db.scalars(select(QuestionAttempt.id).where(QuestionAttempt.practice_item_id==item.id)))
        completed=item.completed_at is not None or bool(attempts)
        name=node.name if node else '该知识点'
        answer=(f'刚才预览的「{name}」题目已经在当前今日卷第 {number} 题；'
            +('该题已有作答记录，可以回到今日卷查看结果或解析。' if completed
              else '该题尚未作答，可以直接回到今日卷继续完成。')
            +'我没有重复添加，也没有创建新的安排。')
        return {'state':'already_in_today_plan','question_id':str(question_id),
            'question_version_id':str(item.question_version_id),'preview_version_id':str(version_id),
            'practice_item_id':str(item.id),'ordinal':item.ordinal,'display_number':number,'attempt_count':len(attempts),
            'completed':completed,'message':answer}
