"""R37 read-only bank inventory and persisted paper-adjustment coverage."""
import json
import os
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import select, func

from tests.integration.test_student_uiv2_repairs import (
    session_factory, clean_database, clean_tasks, setup, talk, reply, NOW, NoModel,
)
from tests.integration.test_policy_origin_semantics import make_origin_slice, DAY
from backend.models.learning import PracticeItem, Question
from backend.models.learning_task import LearningTask
from backend.schemas.learning_assistant import AssistantRequest
from backend.services.public_subject_inventory import audit_public_subject_inventory
from backend.services.question_versions import question_version_reference


def test_408_inventory_audit_uses_live_admission_and_separates_scopes(session_factory, record_property):
    with session_factory.begin() as db:
        node, _policy, _questions = make_origin_slice(db)
        node.subject='408'
        audit=audit_public_subject_inventory(db,subject='408')
    assert audit['knowledge_point_count'] >= 1
    topic=next(row for row in audit['topics'] if row['kp_id']==str(node.id))
    assert topic['public_formal_question_count'] >= topic['eligible_public_count'] >= 1
    assert topic['personal_question_count'] == 0
    assert topic['pending_recheck_count'] == topic['public_formal_question_count']-topic['eligible_public_count']
    record_property('408_inventory_totals',json.dumps(audit['totals'],ensure_ascii=False))
    output=Path(os.environ['PHASE45I_CLOSE_OUTPUT'])/'408-inventory-isolated-database.json'
    output.write_text(json.dumps({'scope':'runner-owned isolated PostgreSQL only; synthetic eligibility fixture',
        'production_database_accessed':False,'synthetic_inventory':True,'audit':audit},ensure_ascii=False,indent=2),encoding='utf-8')


def _eligible_alternative(factory, kp_id, exclude):
    from backend.services.question_eligibility import question_eligibility
    with factory() as db:
        node=db.get(__import__('backend.models.learning',fromlist=['KnowledgePoint']).KnowledgePoint,kp_id)
        rows=db.scalars(select(Question).where(Question.kp_id==kp_id,
            Question.bank_scope=='public',Question.id!=exclude).order_by(Question.id)).all()
        q=next(row for row in rows if row.current_version_id and question_eligibility(row,node).practice_eligible)
        return q.id,question_version_reference(q)


def test_append_only_chat_adjustment_commits_real_eligible_item(session_factory):
    sid,ctx,_=setup(session_factory)
    qid,version=_eligible_alternative(session_factory,ctx.knowledge_node_ids[0],ctx.question_id)
    talk(session_factory,sid,AssistantRequest(question='给我增加一道洛必达法则的题目。',study_context=ctx),NoModel())
    draft=reply(session_factory,sid)
    proposal=draft.metadata_['paper_adjustment']['proposal']
    assert proposal and proposal['draft']['remove_item_ids']==[],json.dumps(
        {'content':draft.content,'context':draft.metadata_['paper_adjustment'].get('context'),
         'error_code':draft.metadata_['paper_adjustment'].get('error_code'),
         'error_detail':draft.metadata_['paper_adjustment'].get('error_detail')},ensure_ascii=False)
    assert len(proposal['draft']['replacements'])==1
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(PracticeItem).where(
            PracticeItem.plan_id==ctx.daily_plan_id,PracticeItem.removed_at.is_(None)))==1
    talk(session_factory,sid,AssistantRequest(question='确认调整',study_context=ctx),NoModel())
    receipt=reply(session_factory,sid).metadata_['paper_adjustment']['receipt']
    assert receipt['added_count']==1 and receipt['total_count']==2
    assert str(qid)==receipt['added_items'][0]['question_id']
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(PracticeItem).where(
            PracticeItem.plan_id==ctx.daily_plan_id,PracticeItem.removed_at.is_(None)))==2


def test_replacement_pool_excludes_soft_removed_question_history(session_factory):
    """A soft-removed question must not be re-selected into the same paper."""
    sid,ctx,_=setup(session_factory)
    old_question_id=ctx.question_id
    talk(session_factory,sid,AssistantRequest(question='减少一道洛必达法则题目。',study_context=ctx),NoModel())
    removal=reply(session_factory,sid).metadata_['paper_adjustment']['proposal']
    assert removal and removal['draft']['remove_item_ids']==[str(ctx.practice_item_id)]
    talk(session_factory,sid,AssistantRequest(question='确认调整',study_context=ctx),NoModel())
    assert reply(session_factory,sid).metadata_['paper_adjustment']['receipt']['total_count']==0

    talk(session_factory,sid,AssistantRequest(question='给我增加一道洛必达法则题目。',study_context=ctx),NoModel())
    addition=reply(session_factory,sid).metadata_['paper_adjustment']['proposal']
    assert addition and addition['draft']['remove_item_ids']==[]
    assert len(addition['draft']['replacements'])==1
    assert addition['draft']['replacements'][0]['question_id']!=str(old_question_id)
    talk(session_factory,sid,AssistantRequest(question='确认调整',study_context=ctx),NoModel())
    receipt=reply(session_factory,sid).metadata_['paper_adjustment']['receipt']
    assert receipt,reply(session_factory,sid).content
    assert receipt['added_count']==1 and receipt['total_count']==1
    assert receipt['before_count']==0
    assert receipt['remaining_minutes']==addition['workload']['remaining_minutes']
    assert receipt['added_items'][0]['question_id']!=str(old_question_id)
    with session_factory() as db:
        old=db.get(PracticeItem,ctx.practice_item_id)
        active=list(db.scalars(select(PracticeItem).where(
            PracticeItem.plan_id==ctx.daily_plan_id,PracticeItem.removed_at.is_(None))))
        assert old.removed_at is not None
        assert len(active)==1 and active[0].question_id!=old_question_id


def test_same_topic_single_replacement_uses_public_eligible_question(session_factory):
    sid,ctx,_=setup(session_factory)
    old_question_id=ctx.question_id
    replacement_id,_version=_eligible_alternative(session_factory,ctx.knowledge_node_ids[0],old_question_id)
    talk(session_factory,sid,AssistantRequest(question='给我换一道洛必达法则题目。',study_context=ctx),NoModel())
    proposal=reply(session_factory,sid).metadata_['paper_adjustment']['proposal']
    assert proposal
    assert proposal['draft']['remove_item_ids']==[str(ctx.practice_item_id)]
    assert proposal['draft']['replacements'][0]['question_id']==str(replacement_id)
    with session_factory() as db:
        assert db.get(PracticeItem,ctx.practice_item_id).removed_at is None
    talk(session_factory,sid,AssistantRequest(question='确认调整',study_context=ctx),NoModel())
    receipt=reply(session_factory,sid).metadata_['paper_adjustment']['receipt']
    assert receipt['removed_item_ids']==[str(ctx.practice_item_id)]
    assert receipt['added_count']==1 and receipt['total_count']==1
    assert receipt['added_items'][0]['question_id']==str(replacement_id)
    with session_factory() as db:
        old=db.get(PracticeItem,ctx.practice_item_id)
        active=list(db.scalars(select(PracticeItem).where(
            PracticeItem.plan_id==ctx.daily_plan_id,PracticeItem.removed_at.is_(None))))
        assert old.removed_at is not None
        assert len(active)==1 and active[0].question_id==replacement_id


def test_new_adjustment_invalidates_older_pending_proposal(session_factory):
    from .test_r36_paper_chat_api import client
    sid,ctx,_=setup(session_factory)
    qid,version=_eligible_alternative(session_factory,ctx.knowledge_node_ids[0],ctx.question_id)
    c=client(session_factory)
    old=c.post('/api/paper-adjustments',json={'session_id':str(sid),'plan_id':str(ctx.daily_plan_id),
        'remove_item_ids':[str(ctx.practice_item_id)],'budget_minutes':60}).json()
    new=c.post('/api/paper-adjustments',json={'session_id':str(sid),'plan_id':str(ctx.daily_plan_id),
        'remove_item_ids':[],'replacements':[{'question_id':str(qid),'question_version_id':version}],
        'budget_minutes':60})
    assert new.status_code==201,new.text
    old_status=c.post(f"/api/paper-adjustments/{old['task_id']}/confirm",json={
        'session_id':str(sid),'draft_version':old['draft_version']})
    assert old_status.status_code==409
    with session_factory() as db:
        old_task=db.get(LearningTask,UUID(old['task_id']))
        assert old_task.status=='cancelled' and old_task.context['superseded_by']==new.json()['task_id']
        original=db.get(PracticeItem,ctx.practice_item_id)
        assert original.removed_at is None
    committed=c.post(f"/api/paper-adjustments/{new.json()['task_id']}/confirm",json={
        'session_id':str(sid),'draft_version':new.json()['draft_version']})
    assert committed.status_code==200,committed.text
    assert committed.json()['added_count']==1 and committed.json()['total_count']==2


def test_whole_topic_remove_uses_current_topic_and_reports_count(session_factory):
    sid,ctx,_=setup(session_factory)
    talk(session_factory,sid,AssistantRequest(question='删除洛必达法则的全部题目。',study_context=ctx),NoModel())
    preview=reply(session_factory,sid).metadata_['paper_adjustment']
    assert preview['proposal'] and len(preview['proposal']['draft']['remove_item_ids'])==1
    assert preview['receipt'] is None
    with session_factory() as db:
        assert db.get(PracticeItem,ctx.practice_item_id).removed_at is None


def test_remove_two_named_topic_questions_uses_actual_topic_count(session_factory):
    from backend.services.question_eligibility import question_eligibility
    from backend.models.learning import KnowledgePoint
    sid,ctx,_=setup(session_factory)
    with session_factory.begin() as db:
        node=db.get(KnowledgePoint,ctx.knowledge_node_ids[0])
        existing={ctx.question_id}
        candidates=[q for q in db.scalars(select(Question).where(Question.kp_id==node.id,
            Question.bank_scope=='public').order_by(Question.id))
            if q.id not in existing and question_eligibility(q,node).practice_eligible]
        assert len(candidates)>=2
        for index,q in enumerate(candidates[:2],start=2):
            db.add(PracticeItem(plan_id=ctx.daily_plan_id,question_id=q.id,kp_id=node.id,ordinal=index))
    talk(session_factory,sid,AssistantRequest(question='减少两道洛必达法则题目。',study_context=ctx),NoModel())
    draft=reply(session_factory,sid).metadata_['paper_adjustment']['proposal']
    assert draft and len(draft['draft']['remove_item_ids'])==2
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(PracticeItem).where(
            PracticeItem.plan_id==ctx.daily_plan_id,PracticeItem.removed_at.is_(None)))==3


def test_multiturn_remove_then_add_composes_one_confirmable_draft(session_factory):
    sid,ctx,_=setup(session_factory)
    talk(session_factory,sid,AssistantRequest(question='减少一道洛必达法则题目。',study_context=ctx),NoModel())
    first=reply(session_factory,sid).metadata_['paper_adjustment']['proposal']
    assert first and len(first['draft']['remove_item_ids'])==1
    talk(session_factory,sid,AssistantRequest(question='再增加一道洛必达法则题目。',study_context=ctx),NoModel())
    second=reply(session_factory,sid).metadata_['paper_adjustment']['proposal']
    assert second and len(second['draft']['remove_item_ids'])==1
    assert len(second['draft']['replacements'])==1
    with session_factory() as db:
        assert db.get(PracticeItem,ctx.practice_item_id).removed_at is None
        assert db.get(LearningTask,UUID(first['task_id'])).status=='cancelled'
    talk(session_factory,sid,AssistantRequest(question='确认调整',study_context=ctx),NoModel())
    receipt=reply(session_factory,sid).metadata_['paper_adjustment']['receipt']
    assert receipt['total_count']==1 and receipt['added_count']==1
    with session_factory() as db:
        assert db.get(PracticeItem,ctx.practice_item_id).removed_at is not None


def test_six_topic_sixty_minute_cross_subject_planner_with_synthetic_qualified_inventory(session_factory):
    """Exercise the successful selector path without claiming real 408 stock."""
    sid,ctx,_=setup(session_factory)
    with session_factory.begin() as db:
        topics=[]
        for _ in range(6):
            node,_policy,_questions=make_origin_slice(db)
            node.subject='408'
            topics.append(node.id)
    talk(session_factory,sid,AssistantRequest(question=(
        '把今天数学题全部换成408，根据没做过的知识点安排6个知识点，预算60分钟左右。'),
        study_context=ctx),NoModel())
    preview=reply(session_factory,sid)
    payload=preview.metadata_['paper_adjustment']
    proposal=payload['proposal']
    assert proposal is not None,preview.content
    assert len(proposal['draft']['remove_item_ids'])==1
    assert len(proposal['draft']['replacements'])==12
    assert preview.metadata_['paper_adjustment']['context']['estimated_minutes']==60
    chosen=preview.metadata_['paper_adjustment']['context']['selected_408_topics']
    assert len(chosen)==6 and {UUID(row['kp_id']) for row in chosen}==set(topics)
    with session_factory() as db:assert db.get(PracticeItem,ctx.practice_item_id).removed_at is None
    talk(session_factory,sid,AssistantRequest(question='确认调整',study_context=ctx),NoModel())
    receipt=reply(session_factory,sid).metadata_['paper_adjustment']['receipt']
    assert receipt['removed_item_ids']==[str(ctx.practice_item_id)]
    assert receipt['added_count']==12 and receipt['total_count']==12
    with session_factory() as db:
        rows=list(db.scalars(select(PracticeItem).where(
            PracticeItem.plan_id==ctx.daily_plan_id,PracticeItem.removed_at.is_(None))))
        assert len(rows)==12 and {row.kp_id for row in rows}==set(topics)
        assert db.get(PracticeItem,ctx.practice_item_id).removed_at is not None
        assert len({row.question_id for row in rows})==12
