"""Real isolated PostgreSQL and assistant route: inverse changes preserve history."""
from uuid import UUID,uuid4
import pytest
from sqlalchemy import select
from tests.integration.test_r36_paper_chat_api import (
    session_factory,clean_database,clean_tasks,conversations,setup,client,talk,reply,NOW,NoModel,history,
)
from backend.models.learning import PracticeItem,Question,LearningEvent,QuestionAttempt
from backend.schemas.learning_assistant import AssistantRequest


def replacement(factory):
    sid,ctx,_=setup(factory);c=client(factory)
    with factory() as db:
        q=db.scalar(select(Question).where(Question.kp_id==ctx.knowledge_node_ids[0],Question.id!=ctx.question_id,
            Question.question_type=='single_choice').order_by(Question.id))
        ref={'question_id':str(q.id),'question_version_id':str(q.current_version_id)}
    proposal=c.post('/api/paper-adjustments',json={'session_id':str(sid),'plan_id':str(ctx.daily_plan_id),
        'remove_item_ids':[str(ctx.practice_item_id)],'replacements':[ref],'budget_minutes':60}).json()
    result=c.post(f"/api/paper-adjustments/{proposal['task_id']}/confirm",json={
        'session_id':str(sid),'draft_version':proposal['draft_version']})
    assert result.status_code==200,result.text
    with factory() as db:
        new=db.scalar(select(PracticeItem).where(PracticeItem.plan_id==ctx.daily_plan_id,PracticeItem.removed_at.is_(None)))
        new_id=new.id
    return sid,ctx,new_id,proposal


@pytest.mark.parametrize('state',['started','skipped','completed','submitted'])
def test_undo_rejects_protected_added_item_without_restoring_any_original(session_factory,state):
    sid,ctx,new_id,_=replacement(session_factory)
    with session_factory.begin() as db:
        item=db.get(PracticeItem,new_id)
        if state=='completed':item.completed_at=NOW
        elif state=='submitted':
            db.add(QuestionAttempt(practice_item_id=item.id,question_id=item.question_id,
                question_version_id=item.question_version_id,kp_id=item.kp_id,raw_answer='A',objective_result='unknown',
                submitted_at=NOW,idempotency_key=uuid4().hex,result_state='learning',reason_code='fixture_observation'))
        else:db.add(LearningEvent(kp_id=item.kp_id,source_id=item.id,question_version_id=item.question_version_id,
            event_type='scheduler_activity',payload={'kind':state},occurred_at=NOW,
            idempotency_key='undo-protection:'+uuid4().hex))
    before=history(session_factory)
    talk(session_factory,sid,AssistantRequest(question='撤销刚才的替换',study_context=ctx),NoModel())
    with session_factory() as db:
        assert db.get(PracticeItem,new_id).removed_at is None
        assert db.get(PracticeItem,ctx.practice_item_id).removed_at is not None
    assert history(session_factory)==before
    assert '保护' in reply(session_factory,sid).content or '学习记录' in reply(session_factory,sid).content


def test_undo_restores_original_item_and_version_and_replays_once(session_factory):
    from backend.services.paper_adjustment_reversal import undo_latest_replacement
    sid,ctx,new_id,_=replacement(session_factory)
    with session_factory() as db:version=db.get(PracticeItem,ctx.practice_item_id).question_version_id
    from concurrent.futures import ThreadPoolExecutor
    def undo(_):return undo_latest_replacement(session_factory,session_id=sid,plan_id=ctx.daily_plan_id,now=NOW)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(undo,range(2)))
    assert all(r['restored_count']==1 and r['total_count']==1 for r in results)
    assert sum(r.get('replayed',False) for r in results)==1
    with session_factory() as db:
        assert db.get(PracticeItem,ctx.practice_item_id).removed_at is None
        assert db.get(PracticeItem,ctx.practice_item_id).question_version_id==version
        assert db.get(PracticeItem,new_id).removed_at is not None


def test_viewed_undo_requires_bound_second_confirmation(session_factory):
    sid,ctx,new_id,_=replacement(session_factory)
    with session_factory.begin() as db:
        i=db.get(PracticeItem,new_id)
        db.add(LearningEvent(kp_id=i.kp_id,source_id=i.id,question_version_id=i.question_version_id,
            event_type='scheduler_activity',payload={'kind':'viewed'},occurred_at=NOW,idempotency_key=uuid4().hex))
    talk(session_factory,sid,AssistantRequest(question='撤销刚才的替换',study_context=ctx),NoModel())
    assert '待确认撤销' in reply(session_factory,sid).content
    with session_factory() as db:assert db.get(PracticeItem,new_id).removed_at is None
    talk(session_factory,sid,AssistantRequest(question='确认移除已浏览题目',study_context=ctx),NoModel())
    assert '已撤销' in reply(session_factory,sid).content
    with session_factory() as db:assert db.get(PracticeItem,new_id).removed_at is not None


def test_inverse_transaction_failure_rolls_back_both_sides(session_factory,monkeypatch):
    import backend.services.paper_adjustment_reversal as service
    sid,ctx,new_id,_=replacement(session_factory)
    def fail(*args,**kwargs):raise RuntimeError('injected receipt readback failure')
    monkeypatch.setattr(service,'_receipt',fail)
    with pytest.raises(RuntimeError,match='readback failure'):
        service.undo_latest_replacement(session_factory,session_id=sid,plan_id=ctx.daily_plan_id,now=NOW)
    with session_factory() as db:
        assert db.get(PracticeItem,new_id).removed_at is None
        assert db.get(PracticeItem,ctx.practice_item_id).removed_at is not None


def test_denial_cancels_pending_undo_without_writing(session_factory):
    sid,ctx,new_id,_=replacement(session_factory)
    with session_factory.begin() as db:
        i=db.get(PracticeItem,new_id)
        db.add(LearningEvent(kp_id=i.kp_id,source_id=i.id,question_version_id=i.question_version_id,
            event_type='scheduler_activity',payload={'kind':'viewed'},occurred_at=NOW,idempotency_key=uuid4().hex))
    for phrase in ['撤销刚才的替换','不要撤销刚才的替换','确认移除已浏览题目']:
        talk(session_factory,sid,AssistantRequest(question=phrase,study_context=ctx),NoModel())
    with session_factory() as db:
        assert db.get(PracticeItem,new_id).removed_at is None
        assert db.get(PracticeItem,ctx.practice_item_id).removed_at is not None


def test_restore_original_keeps_identity_and_rechecks_admission(session_factory):
    from backend.services.paper_adjustment_reversal import restore_removed_items
    from backend.errors import AppError
    sid,ctx,_=setup(session_factory);c=client(session_factory)
    proposal=c.post('/api/paper-adjustments',json={'session_id':str(sid),'plan_id':str(ctx.daily_plan_id),
        'remove_item_ids':[str(ctx.practice_item_id)],'budget_minutes':60}).json()
    r=c.post(f"/api/paper-adjustments/{proposal['task_id']}/confirm",json={'session_id':str(sid),'draft_version':proposal['draft_version']})
    assert r.status_code==200,r.text
    with session_factory() as db: original_version=db.get(Question,ctx.question_id).current_version_id
    with session_factory.begin() as db:db.get(Question,ctx.question_id).is_active=False
    with pytest.raises(AppError,match='paper_restore_not_admitted'):
        restore_removed_items(session_factory,session_id=sid,plan_id=ctx.daily_plan_id,now=NOW,recent_only=True)
    with session_factory.begin() as db:
        assert db.get(PracticeItem,ctx.practice_item_id).removed_at is not None
        q=db.get(Question,ctx.question_id)
        q.is_active=True
    # Reactivating a question creates another immutable version. It must not
    # silently make an old frozen item restorable under the new version.
    with pytest.raises(AppError,match='paper_restore_not_admitted'):
        restore_removed_items(session_factory,session_id=sid,plan_id=ctx.daily_plan_id,now=NOW,recent_only=True)
    # Restore the exact original pointer only as an isolated fixture setup;
    # production recovery never rewrites question-version pointers.
    from sqlalchemy import update
    with session_factory.begin() as db:
        db.execute(update(Question).where(Question.id==ctx.question_id).values(current_version_id=original_version))
    before=history(session_factory)
    talk(session_factory,sid,AssistantRequest(question='恢复刚才删除的一道题',study_context=ctx),NoModel())
    assert '已恢复1道' in reply(session_factory,sid).content
    with session_factory() as db:
        i=db.get(PracticeItem,ctx.practice_item_id)
        assert i.removed_at is None and i.question_id==ctx.question_id
    assert history(session_factory)==before


def test_named_multi_topic_replacement_keeps_both_source_scopes(session_factory):
    from tests.integration.test_policy_origin_semantics import make_origin_slice
    sid,ctx,_=setup(session_factory)
    with session_factory.begin() as db:
        source,_,questions=make_origin_slice(db)
        source.name='独立源知识点'
        item=PracticeItem(plan_id=ctx.daily_plan_id,kp_id=source.id,question_id=questions[0].id,ordinal=2)
        db.add(item);db.flush();source_item_id=item.id
        target,_,_=make_origin_slice(db)
        target.name='独立408候选';target.subject='408'
    before=history(session_factory)
    talk(session_factory,sid,AssistantRequest(question='把洛必达法则和独立源知识点的题目全部换成408题目，题量和原来一样，预算60分钟，其他不动，先看方案。',study_context=ctx),NoModel())
    message=reply(session_factory,sid)
    proposal=message.metadata_['paper_adjustment']['proposal']
    assert proposal,message.content
    assert set(proposal['draft']['remove_item_ids'])=={str(ctx.practice_item_id),str(source_item_id)}
    assert len(proposal['draft']['replacements'])==2
    assert proposal['workload']['budget_minutes']==60
    assert proposal['workload']['requires_confirmation'] is False
    with session_factory() as db:
        assert db.get(PracticeItem,ctx.practice_item_id).removed_at is None
        assert db.get(PracticeItem,source_item_id).removed_at is None
    assert history(session_factory)==before
    talk(session_factory,sid,AssistantRequest(question='确认调整',study_context=ctx),NoModel())
    receipt=reply(session_factory,sid).metadata_['paper_adjustment']['receipt']
    assert receipt,reply(session_factory,sid).content
    assert set(receipt['removed_item_ids'])=={str(ctx.practice_item_id),str(source_item_id)}
    assert receipt['total_count']==2 and receipt['added_count']==2
    assert history(session_factory)==before


@pytest.mark.parametrize('budget',[5,60])
def test_scoped_cross_subject_replacement_inherits_confirmed_plan_budget(session_factory,budget):
    from tests.integration.test_policy_origin_semantics import make_origin_slice
    from backend.models.learning_task import LearningTask
    sid,ctx,_=setup(session_factory)
    with session_factory.begin() as db:
        db.add(LearningTask(session_id=sid,goal='生成今日卷',budget_minutes=budget,status='answered',
            context={'home_recommendation':True},metrics={'commit':{'plan_id':str(ctx.daily_plan_id)}},draft={}))
        target,_,qs=make_origin_slice(db)
        target.name='独立408预算节点';target.subject='408'
        for q in qs:q.estimated_minutes=10
    talk(session_factory,sid,AssistantRequest(question='把洛必达法则的题目换成408题目，题量和原来一样，预算沿用当前正式卷，先预览。',study_context=ctx),NoModel())
    message=reply(session_factory,sid)
    proposal=message.metadata_['paper_adjustment']['proposal']
    assert proposal,message.content
    assert proposal['workload']['budget_minutes']==budget
    assert proposal['workload']['remaining_minutes']==10
    assert proposal['workload']['requires_confirmation']==(budget<10)
    with session_factory() as db:assert db.get(PracticeItem,ctx.practice_item_id).removed_at is None


@pytest.mark.parametrize('question',[
 '给今天的408卷增加两道堆的题、增加两道二叉搜索树的题，其他不变，先给我看待确认方案。',
 '堆增加2道，二叉搜索树增加2道，其他不变，先预览。',
])
def test_real_formal_batch_add_reduce_single_character_topic(session_factory,question):
    from tests.integration.test_policy_origin_semantics import make_origin_slice
    sid,ctx,_=setup(session_factory)
    with session_factory.begin() as db:
        heap,_,_=make_origin_slice(db);heap.name='堆';heap.subject='408';heap_id=heap.id
        tree,_,_=make_origin_slice(db);tree.name='二叉搜索树';tree.subject='408';tree_id=tree.id
        original_version=db.get(PracticeItem,ctx.practice_item_id).question_version_id
    before=history(session_factory)
    talk(session_factory,sid,AssistantRequest(question=question,study_context=ctx),NoModel())
    message=reply(session_factory,sid);draft=message.metadata_['paper_adjustment']['proposal']
    assert draft,message.content
    assert draft['draft']['remove_item_ids']==[]
    assert len(draft['draft']['replacements'])==4
    with session_factory() as db:
        assert len(list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id==ctx.daily_plan_id))))==1
    talk(session_factory,sid,AssistantRequest(question='确认调整',study_context=ctx),NoModel())
    addition_receipt=reply(session_factory,sid).metadata_['paper_adjustment']['receipt']
    assert addition_receipt['total_count']==5
    talk(session_factory,sid,AssistantRequest(question='堆减少一道、二叉搜索树减少一道，先看方案。',study_context=ctx),NoModel())
    removal=reply(session_factory,sid).metadata_['paper_adjustment']['proposal']
    assert removal and len(removal['draft']['remove_item_ids'])==2
    assert removal['workload']['budget_minutes']==addition_receipt['remaining_minutes']
    talk(session_factory,sid,AssistantRequest(question='确认调整',study_context=ctx),NoModel())
    assert reply(session_factory,sid).metadata_['paper_adjustment']['receipt']['total_count']==3
    with session_factory() as db:
        active=list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id==ctx.daily_plan_id,PracticeItem.removed_at.is_(None))))
        assert sum(i.kp_id==heap_id for i in active)==1
        assert sum(i.kp_id==tree_id for i in active)==1
        original=db.get(PracticeItem,ctx.practice_item_id)
        assert original.removed_at is None and original.question_version_id==original_version
    assert history(session_factory)==before


@pytest.mark.parametrize('kept_cost',[30,40])
def test_whole_408_budget_includes_kept_nonmath_items(session_factory,kept_cost):
    from tests.integration.test_policy_origin_semantics import make_origin_slice
    sid,ctx,_=setup(session_factory)
    with session_factory.begin() as db:
        kept,_,qs=make_origin_slice(db);kept.name='保留的408知识点';kept.subject='408'
        qs[0].estimated_minutes=kept_cost;db.flush()
        item=PracticeItem(plan_id=ctx.daily_plan_id,kp_id=kept.id,question_id=qs[0].id,ordinal=2)
        db.add(item);db.flush();kept_id=item.id;kept_version=item.question_version_id
        for index in range(6):
            node,_,_=make_origin_slice(db);node.subject='408';node.name=f'目标408知识点{index}'
    before=history(session_factory)
    talk(session_factory,sid,AssistantRequest(question='把今天数学题全部换成408，安排6个没有做过的知识点，预算60分钟，先预览。',study_context=ctx),NoModel())
    message=reply(session_factory,sid);proposal=message.metadata_['paper_adjustment']['proposal']
    if kept_cost==40:
        assert proposal is None
        assert '保留题目预计仍需40分钟' in message.content
        assert '剩余预算20分钟不足' in message.content
        with session_factory() as db:
            active=list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id==ctx.daily_plan_id,PracticeItem.removed_at.is_(None))))
            assert {i.id for i in active}=={ctx.practice_item_id,kept_id}
        assert history(session_factory)==before
        return
    assert proposal,message.content
    assert proposal['workload']['budget_minutes']==60
    assert proposal['workload']['remaining_minutes']==60
    assert proposal['workload']['requires_confirmation'] is False
    assert len(proposal['draft']['replacements'])==6
    with session_factory() as db:assert db.get(PracticeItem,ctx.practice_item_id).removed_at is None
    talk(session_factory,sid,AssistantRequest(question='确认调整',study_context=ctx),NoModel())
    result=reply(session_factory,sid).metadata_['paper_adjustment']['receipt']
    assert result and result['total_count']==7 and result['remaining_minutes']==60
    with session_factory() as db:
        kept_item=db.get(PracticeItem,kept_id)
        assert kept_item.removed_at is None and kept_item.question_version_id==kept_version
    assert history(session_factory)==before


def test_cancel_removal_proposal_keeps_original_and_invalidates_confirmation(session_factory):
    from backend.models.learning_task import LearningTask
    sid,ctx,_=setup(session_factory)
    before=history(session_factory)
    talk(session_factory,sid,AssistantRequest(question='删除当前第1题，先预览。',study_context=ctx),NoModel())
    proposal=reply(session_factory,sid).metadata_['paper_adjustment']['proposal']
    assert proposal,reply(session_factory,sid).content
    talk(session_factory,sid,AssistantRequest(question='取消这次删除方案，保留当前正式卷。',study_context=ctx),NoModel())
    cancelled=reply(session_factory,sid)
    assert '本次调整方案已取消' in cancelled.content
    assert cancelled.metadata_['paper_adjustment']['proposal'] is None
    with session_factory() as db:
        assert db.get(LearningTask,UUID(proposal['task_id'])).status=='cancelled'
        assert db.get(PracticeItem,ctx.practice_item_id).removed_at is None
    talk(session_factory,sid,AssistantRequest(question='确认调整',study_context=ctx),NoModel())
    assert not reply(session_factory,sid).metadata_['paper_adjustment'].get('receipt')
    with session_factory() as db:assert db.get(PracticeItem,ctx.practice_item_id).removed_at is None
    assert history(session_factory)==before


def test_generate_personal_but_do_not_append_reaches_generation_confirmation(session_factory):
    sid,ctx,_=setup(session_factory)
    before=history(session_factory)
    talk(session_factory,sid,AssistantRequest(question='给我生成一道洛必达法则练习题，先保存为个人参考，不加入今日卷。',study_context=ctx),NoModel())
    message=reply(session_factory,sid)
    assert message.metadata_.get('personal_generation_confirmation'),message.content
    assert not message.metadata_.get('paper_adjustment')
    with session_factory() as db:
        items=list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id==ctx.daily_plan_id)))
        assert len(items)==1 and items[0].removed_at is None
    assert history(session_factory)==before
