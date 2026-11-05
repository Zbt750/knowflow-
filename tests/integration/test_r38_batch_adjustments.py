"""Real chat and PostgreSQL with explicitly synthetic eligible topic fixtures."""
import pytest
from sqlalchemy import select
from backend.models.learning import PracticeItem
from backend.schemas.learning_assistant import AssistantRequest
from tests.integration.test_student_uiv2_repairs import session_factory,clean_database,setup,talk,reply,NoModel
from tests.integration.test_learning_assistant import conversations
from tests.integration.test_learning_tasks import clean_tasks
from tests.integration.test_home_pre_generation_acceptance import _add_synthetic_topic

@pytest.mark.parametrize('shortage',[False,True])
def test_multitopic_whole_replacement_keeps_topic_pools_and_commits_atomically(session_factory,shortage):
    sid,ctx,_=setup(session_factory)
    originals=[];topic_ids=[]
    with session_factory.begin() as db:
        for index,name in enumerate(['批量甲节点','批量乙节点']):
            node,questions=_add_synthetic_topic(db,code=f'synthetic.r38.batch.{index}',name=name)
            topic_ids.append(node.id)
            for offset,q in enumerate(questions[:2]):
                item=PracticeItem(plan_id=ctx.daily_plan_id,question_id=q.id,kp_id=node.id,ordinal=2+index*2+offset)
                db.add(item);db.flush();originals.append(item.id)
            if shortage and index==1:
                for q in questions[2:]:q.is_active=False
    talk(session_factory,sid,AssistantRequest(question='把批量甲节点和批量乙节点的全部题目分别替换。',study_context=ctx),NoModel())
    view=reply(session_factory,sid)
    metadata=view.metadata_['paper_adjustment']
    with session_factory() as db:
        assert all(db.get(PracticeItem,i).removed_at is None for i in originals)
    if shortage:
        assert not metadata.get('proposal'),metadata
        assert '缺少2道' in view.content and '整项调整未提交' in view.content
        return
    proposal=metadata['proposal'];assert proposal,view.content
    assert set(proposal['draft']['remove_item_ids'])==set(map(str,originals))
    assert len(proposal['draft']['replacements'])==4
    talk(session_factory,sid,AssistantRequest(question='确认调整',study_context=ctx),NoModel())
    receipt=reply(session_factory,sid).metadata_['paper_adjustment']['receipt']
    assert receipt['added_count']==4 and receipt['total_count']==5
    with session_factory() as db:
        assert all(db.get(PracticeItem,i).removed_at is not None for i in originals)
        rows=list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id==ctx.daily_plan_id,PracticeItem.removed_at.is_(None))))
        assert all(sum(i.kp_id==kp for i in rows)==2 for kp in topic_ids)
        from backend.services.question_versions import question_for_practice_item
        expected=sum(question_for_practice_item(db,i).estimated_minutes for i in rows if i.completed_at is None)
        assert receipt['remaining_minutes']==expected
        content=reply(session_factory,sid).content
        assert f'预计剩余{expected}分钟' in content
        assert all(item['question_version_id'] in content for item in receipt['added_items'])
        assert db.get(PracticeItem,ctx.practice_item_id).removed_at is None
    talk(session_factory,sid,AssistantRequest(question='确认调整',study_context=ctx),NoModel())
    with session_factory() as db:
        assert len(list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id==ctx.daily_plan_id,PracticeItem.removed_at.is_(None)))))==5


from tests.integration.test_learning_loop import client,clock

def test_last_self_assessment_completes_paper_with_soft_removed_unfinished_item(client,session_factory):
    from uuid import UUID,uuid4
    from backend.models.learning import DailyPlan,QuestionAttempt
    from backend.schemas.paper_adjustment import PaperAdjustmentRequest,PaperAdjustmentConfirmation
    from backend.services.paper_adjustment_service import propose_adjustment,confirm_adjustment
    from tests.integration.test_student_uiv2_repairs import NOW
    sid,ctx,_=setup(session_factory)
    with session_factory.begin() as db:
        node,questions=_add_synthetic_topic(db,code='synthetic.r38.removed.completion',name='已移除收尾回归节点')
        item=PracticeItem(plan_id=ctx.daily_plan_id,question_id=questions[0].id,kp_id=node.id,ordinal=2)
        db.add(item);db.flush();removed_id=item.id
    preview=propose_adjustment(session_factory,PaperAdjustmentRequest(session_id=sid,plan_id=ctx.daily_plan_id,remove_item_ids=[removed_id],budget_minutes=60),now=NOW)
    confirm_adjustment(session_factory,UUID(preview['task_id']),PaperAdjustmentConfirmation(session_id=sid,draft_version=preview['draft_version']),now=NOW)
    payload={'self_grade':'partial','idempotency_key':uuid4().hex}
    response=client.post(f'/api/practice-items/{ctx.practice_item_id}/self-assessments',json=payload)
    assert response.status_code==200,response.text
    assert client.post(f'/api/practice-items/{ctx.practice_item_id}/self-assessments',json=payload).status_code==200
    with session_factory() as db:
        assert db.get(DailyPlan,ctx.daily_plan_id).status=='completed'
        removed=db.get(PracticeItem,removed_id)
        assert removed.removed_at is not None and removed.completed_at is None
        attempts=list(db.scalars(select(QuestionAttempt).where(QuestionAttempt.practice_item_id==ctx.practice_item_id)))
        assert len(attempts)==1 and attempts[0].objective_result=='unknown'
