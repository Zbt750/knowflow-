"""Real-API batch quantities and frozen public-set bindings; synthetic inventory."""
from uuid import UUID,uuid4
import pytest
from sqlalchemy import select
from backend.models.learning import PracticeItem,Question,QuestionVersion
from tests.integration.test_learning_loop import session_factory,clean_database,client,clock
from tests.integration.test_learning_tasks import clean_tasks
from tests.integration.test_learning_assistant import conversations,setup,reply,NOW
from tests.integration.test_home_pre_generation_acceptance import _add_synthetic_topic
from tests.integration.test_generation_confirmation_recovery import events
from tests.integration.test_explore_student_repairs import business_rows


@pytest.fixture(autouse=True)
def isolated_business_dependencies(migrated_test_database,settings_guard,clean_database,clean_tasks,conversations):
    yield


@pytest.fixture
def batch_bank(session_factory):
    sid,ctx,_=setup(session_factory)
    topics=[];originals=[]
    with session_factory.begin() as db:
        for index,name in enumerate(['批量甲节点','批量乙节点']):
            node,questions=_add_synthetic_topic(db,code=f'synthetic.r40.mixed.{index}',name=name)
            topics.append(node.id)
            from backend.services.practice_service import append_questions_to_plan
            assert append_questions_to_plan(db,plan_id=ctx.daily_plan_id,question_ids=[q.id for q in questions[:2]],now=NOW)==2
            db.flush()
            originals.extend(db.scalars(select(PracticeItem.id).where(PracticeItem.plan_id==ctx.daily_plan_id,
                PracticeItem.kp_id==node.id).order_by(PracticeItem.ordinal)))
    return sid,ctx,topics,originals


def say(client,sid,ctx,text):
    frames=events(client.post(f'/api/chat/sessions/{sid}/assistant:stream',params={'purpose':'study'},
        json={'question':text,'request_key':str(uuid4()),'study_context':ctx.model_dump(mode='json')}))
    assert not any(event=='error' for event,data in frames),frames
    return frames


def test_short_remove_after_an_append_keeps_prior_other_topic_removal(client,session_factory,batch_bank):
    sid,ctx,topics,originals=batch_bank
    say(client,sid,ctx,'减少一道批量甲节点的题目。')
    first=reply(session_factory,sid).metadata_['paper_adjustment']['proposal']
    assert len(first['draft']['remove_item_ids'])==1
    say(client,sid,ctx,'增加一道批量乙节点的题目。')
    second=reply(session_factory,sid).metadata_['paper_adjustment']['proposal']
    assert second['draft']['remove_item_ids']==first['draft']['remove_item_ids']
    assert len(second['draft']['replacements'])==1
    say(client,sid,ctx,'减少一道吧。')
    third=reply(session_factory,sid).metadata_['paper_adjustment']['proposal']
    assert third['task_id']!=second['task_id'],reply(session_factory,sid).content
    assert third['draft']['remove_item_ids']==first['draft']['remove_item_ids']
    assert third['draft']['replacements']==[]
    say(client,sid,ctx,'确认调整')
    receipt=reply(session_factory,sid).metadata_['paper_adjustment']['receipt']
    assert receipt['total_count']==4 and receipt['added_count']==0
    assert len(receipt['removed_item_ids'])==1


def test_adjustment_api_rejects_a_qa_session_without_creating_draft(client,session_factory,batch_bank):
    from backend.models.chat import ChatSession
    sid,ctx,topics,originals=batch_bank
    with session_factory.begin() as db:
        db.get(ChatSession,sid).purpose='qa'
    before=business_rows(session_factory)
    response=client.post('/api/paper-adjustments',json={'session_id':str(sid),
        'plan_id':str(ctx.daily_plan_id),'remove_item_ids':[str(originals[0])],'budget_minutes':60})
    assert response.status_code==404,response.text
    assert business_rows(session_factory)==before


def test_expired_pending_adjustment_cannot_be_extended_by_followup_chat(client,session_factory,batch_bank,clock):
    from datetime import timedelta
    sid,ctx,topics,originals=batch_bank
    say(client,sid,ctx,'减少一道批量甲节点的题目。')
    prior=reply(session_factory,sid).metadata_['paper_adjustment']['proposal']
    before=business_rows(session_factory)
    clock.now=NOW+timedelta(minutes=31)
    say(client,sid,ctx,'增加一道批量乙节点的题目。')
    result=reply(session_factory,sid)
    assert '已过期' in result.content
    assert result.metadata_['paper_adjustment']['proposal']['task_id']==prior['task_id']
    assert business_rows(session_factory)==before


def test_short_quantity_correction_preserves_other_topic_removal(client,session_factory,batch_bank):
    sid,ctx,topics,originals=batch_bank
    say(client,sid,ctx,'减少一道批量甲节点的题目。')
    first=reply(session_factory,sid).metadata_['paper_adjustment']['proposal']
    say(client,sid,ctx,'减少两道批量乙节点的题目。')
    second=reply(session_factory,sid).metadata_['paper_adjustment']['proposal']
    assert len(second['draft']['remove_item_ids'])==3
    say(client,sid,ctx,'减少一道吧。')
    third=reply(session_factory,sid).metadata_['paper_adjustment']['proposal']
    assert len(third['draft']['remove_item_ids'])==2
    assert set(first['draft']['remove_item_ids'])<=set(third['draft']['remove_item_ids'])
    with session_factory() as db:
        counts={kp:sum(db.get(PracticeItem,UUID(value)).kp_id==kp for value in third['draft']['remove_item_ids']) for kp in topics}
        assert list(counts.values())==[1,1]
    say(client,sid,ctx,'确认调整')
    receipt=reply(session_factory,sid).metadata_['paper_adjustment']['receipt']
    assert receipt['total_count']==3 and len(receipt['removed_item_ids'])==2


def test_removing_only_a_pending_addition_cancels_the_noop_proposal(client,session_factory,batch_bank):
    from backend.models.learning_task import LearningTask
    sid,ctx,topics,originals=batch_bank
    before=business_rows(session_factory)
    say(client,sid,ctx,'增加一道批量乙节点的题目。')
    prior=reply(session_factory,sid).metadata_['paper_adjustment']['proposal']
    assert len(prior['draft']['replacements'])==1
    say(client,sid,ctx,'减少一道批量乙节点的题目。')
    result=reply(session_factory,sid)
    assert result.metadata_['paper_adjustment']['proposal'] is None,result.content
    with session_factory() as db:
        assert db.get(LearningTask,UUID(prior['task_id'])).status=='cancelled'
    say(client,sid,ctx,'确认调整')
    assert reply(session_factory,sid).metadata_['paper_adjustment']['receipt'] is None
    after=business_rows(session_factory)
    assert {k:v for k,v in after.items() if k!='learning_tasks'}=={k:v for k,v in before.items() if k!='learning_tasks'}


def test_quantity_correction_restores_virtual_candidates_only_from_last_removal(client,session_factory,batch_bank):
    sid,ctx,topics,originals=batch_bank
    say(client,sid,ctx,'减少一道批量甲节点的题目。')
    first=reply(session_factory,sid).metadata_['paper_adjustment']['proposal']
    say(client,sid,ctx,'增加两道批量乙节点的题目。')
    additions=reply(session_factory,sid).metadata_['paper_adjustment']['proposal']['draft']['replacements']
    assert len(additions)==2
    say(client,sid,ctx,'减少两道批量乙节点的题目。')
    removed=reply(session_factory,sid).metadata_['paper_adjustment']['proposal']
    assert removed['draft']['replacements']==[]
    say(client,sid,ctx,'改成减少一道吧。')
    corrected=reply(session_factory,sid).metadata_['paper_adjustment']['proposal']
    assert corrected['draft']['remove_item_ids']==first['draft']['remove_item_ids']
    assert len(corrected['draft']['replacements'])==1
    assert corrected['draft']['replacements'][0] in additions
    say(client,sid,ctx,'确认调整')
    receipt=reply(session_factory,sid).metadata_['paper_adjustment']['receipt']
    assert receipt['total_count']==5 and receipt['added_count']==1 and len(receipt['removed_item_ids'])==1


@pytest.mark.parametrize('text,deltas',[
    ('减少一道批量甲节点的题目，增加两道批量乙节点的题目。',(-1,2)),
    ('增加一道批量甲节点的题目，增加两道批量乙节点的题目。',(1,2)),
    ('减少一道批量甲节点的题目，减少两道批量乙节点的题目。',(-1,-2)),
])
def test_each_topic_quantity_is_applied_once_after_explicit_confirmation(client,session_factory,batch_bank,text,deltas):
    sid,ctx,topics,originals=batch_bank
    before=business_rows(session_factory)
    say(client,sid,ctx,text)
    pending=reply(session_factory,sid).metadata_['paper_adjustment']['proposal']
    assert pending,reply(session_factory,sid).content
    after=business_rows(session_factory)
    assert {k:v for k,v in after.items() if k!='learning_tasks'}=={k:v for k,v in before.items() if k!='learning_tasks'}
    assert len(pending['draft']['remove_item_ids'])==sum(-d for d in deltas if d<0)
    assert len(pending['draft']['replacements'])==sum(d for d in deltas if d>0)
    with session_factory() as db:
        for kp,delta in zip(topics,deltas):
            targets=[ref for ref in pending['draft']['replacements'] if db.get(Question,UUID(ref['question_id'])).kp_id==kp]
            assert len(targets)==max(0,delta)
        assert all(db.get(PracticeItem,item_id).removed_at is None for item_id in originals)
    say(client,sid,ctx,'确认调整')
    confirmation=reply(session_factory,sid)
    if pending['workload']['requires_confirmation']:
        assert confirmation.metadata_['paper_adjustment']['receipt'] is None
        assert '超出预算' in confirmation.content
        assert business_rows(session_factory)==after
        say(client,sid,ctx,'确认超预算调整')
    receipt=reply(session_factory,sid).metadata_['paper_adjustment']['receipt']
    assert receipt,reply(session_factory,sid).content
    assert receipt['plan_id']==str(ctx.daily_plan_id) and receipt['total_count']==5+sum(deltas)
    with session_factory() as db:
        rows=list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id==ctx.daily_plan_id,PracticeItem.removed_at.is_(None))))
        assert len({item.question_id for item in rows})==len(rows)
        for kp,delta in zip(topics,deltas):assert sum(i.kp_id==kp for i in rows)==2+delta
        for item in receipt.get('added_items',[]):
            version=db.get(QuestionVersion,UUID(item['question_version_id']))
            assert str(version.question_id)==item['question_id'] and version.stem==item['stem']
    stable=business_rows(session_factory)
    say(client,sid,ctx,'确认调整')
    assert business_rows(session_factory)==stable
    refreshed=client.get('/api/plans/today').json()
    assert refreshed['plan_id']==str(ctx.daily_plan_id) and refreshed['total_count']==5+sum(deltas)


@pytest.mark.parametrize('text',[
    '减少一道批量甲节点的题，增加两道不存在的知识点的题。',
    '增加两道不存在的知识点的题，减少一道批量甲节点的题。',
    '能不能减少一道批量甲节点的题，增加两道批量乙节点的题？',
    '不要减少一道批量甲节点的题，也不要增加两道批量乙节点的题。',
    '减少批量甲节点的题，增加一道批量乙节点的题。',
    '如果减少一道批量甲节点的题，增加两道批量乙节点的题呢？',
])
def test_unresolved_or_unauthorized_batch_never_silently_executes_a_subset(client,session_factory,batch_bank,text):
    sid,ctx,topics,originals=batch_bank
    before=business_rows(session_factory)
    say(client,sid,ctx,text)
    assert not (reply(session_factory,sid).metadata_.get('paper_adjustment') or {}).get('proposal')
    assert business_rows(session_factory)==before


def test_batch_shortage_does_not_save_a_partial_removal_or_addition(client,session_factory,batch_bank):
    sid,ctx,topics,originals=batch_bank
    with session_factory.begin() as db:
        present=set(db.scalars(select(PracticeItem.question_id).where(PracticeItem.plan_id==ctx.daily_plan_id)))
        for q in db.scalars(select(Question).where(Question.kp_id==topics[1])):
            if q.id not in present:q.is_active=False
    before=business_rows(session_factory)
    say(client,sid,ctx,'减少一道批量甲节点的题目，增加两道批量乙节点的题目。')
    saved=reply(session_factory,sid)
    assert not saved.metadata_['paper_adjustment'].get('proposal')
    assert '不足' in saved.content and '批量乙节点' in saved.content
    assert business_rows(session_factory)==before


def test_batch_protected_answer_rejects_the_whole_change_and_preserves_attempt(client,session_factory,batch_bank):
    sid,ctx,topics,originals=batch_bank
    protected_id=originals[1]
    submitted=client.post(f'/api/practice-items/{protected_id}/answer-submissions',json={
        'selected_option':'A','idempotency_key':str(uuid4())})
    assert submitted.status_code==200,submitted.text
    before=business_rows(session_factory)
    say(client,sid,ctx,'减少一道批量甲节点的题目，增加两道批量乙节点的题目。')
    saved=reply(session_factory,sid)
    assert not saved.metadata_['paper_adjustment'].get('proposal')
    assert '历史记录' in saved.content
    assert business_rows(session_factory)==before
    with session_factory() as db:
        from backend.models.learning import QuestionAttempt
        assert db.get(PracticeItem,protected_id).removed_at is None
        attempt=db.get(QuestionAttempt,UUID(submitted.json()['attempt_id']))
        assert attempt.practice_item_id==protected_id and attempt.question_version_id


def test_formal_public_append_pins_new_topic_before_first_answer_without_faking_mastery(client,session_factory):
    from backend.models.learning import KpState,KpMasteryPolicy,QuestionAttempt
    sid,ctx,_=setup(session_factory)
    with session_factory.begin() as db:
        node,questions=_add_synthetic_topic(db,code='synthetic.r40.first.append.answer',name='追加后首次作答节点')
        kp_id=node.id;qid=questions[0].id
        version=db.get(KpMasteryPolicy,kp_id).graduation_set_version
    added=client.post(f'/api/plans/{ctx.daily_plan_id}/questions',json={'question_ids':[str(qid)]})
    assert added.status_code==200,added.text
    item=next(i for i in added.json()['items'] if i['question_id']==str(qid))
    with session_factory() as db:
        state=db.get(KpState,kp_id)
        assert state and state.graduation_set_version==version and state.graduation_set_binding_status=='bound'
        assert state.graduation_set_started_at==NOW
        assert state.state=='unseen' and not state.evidence_window and state.mastered_at is None
    answer=client.post(f"/api/practice-items/{item['id']}/answer-submissions",json={
        'selected_option':'A','idempotency_key':str(uuid4())})
    assert answer.status_code==200,answer.text
    with session_factory() as db:
        attempt=db.get(QuestionAttempt,UUID(answer.json()['attempt_id']))
        assert attempt.practice_item_id==UUID(item['id']) and str(attempt.question_version_id)==item['question_version_id']


def test_multiturn_batch_edits_supersede_old_proposals_without_changing_the_paper(client,session_factory,batch_bank):
    sid,ctx,topics,originals=batch_bank
    say(client,sid,ctx,'减少一道批量甲节点的题目，增加两道批量乙节点的题目。')
    old=reply(session_factory,sid).metadata_['paper_adjustment']['proposal']
    say(client,sid,ctx,'增加一道批量甲节点的题。')
    say(client,sid,ctx,'减少一道批量乙节点的题。')
    pending=reply(session_factory,sid).metadata_['paper_adjustment']['proposal']
    assert pending['task_id']!=old['task_id']
    assert len(pending['draft']['remove_item_ids'])==1 and len(pending['draft']['replacements'])==2
    before=business_rows(session_factory)
    rejected=client.post(f"/api/paper-adjustments/{old['task_id']}/confirm",json={
        'session_id':str(sid),'draft_version':old['draft_version']})
    assert rejected.status_code==409,rejected.text
    assert business_rows(session_factory)==before
    assert client.get('/api/plans/today').json()['total_count']==5
    say(client,sid,ctx,'确认调整')
    with session_factory() as db:
        rows=list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id==ctx.daily_plan_id,PracticeItem.removed_at.is_(None))))
        assert len(rows)==6
        assert [sum(i.kp_id==kp for i in rows) for kp in topics]==[2,3]


def test_batch_state_change_after_preview_prevents_all_partial_writes(client,session_factory,batch_bank):
    sid,ctx,topics,originals=batch_bank
    say(client,sid,ctx,'减少一道批量甲节点的题目，增加两道批量乙节点的题目。')
    proposal=reply(session_factory,sid).metadata_['paper_adjustment']['proposal']
    selected=proposal['draft']['remove_item_ids'][0]
    activity=client.post(f'/api/practice-items/{selected}/activity',json={
        'kind':'started','idempotency_key':str(uuid4())})
    assert activity.status_code==200,activity.text
    before=business_rows(session_factory)
    rejected=client.post(f"/api/paper-adjustments/{proposal['task_id']}/confirm",json={
        'session_id':str(sid),'draft_version':proposal['draft_version']})
    assert rejected.status_code==409,rejected.text
    assert business_rows(session_factory)==before


def test_failed_append_rolls_back_the_new_public_set_binding_and_paper_together(client,session_factory):
    from sqlalchemy import event
    from sqlalchemy.engine import Engine
    from backend.models.learning import KpState
    sid,ctx,_=setup(session_factory)
    with session_factory.begin() as db:
        node,questions=_add_synthetic_topic(db,code='synthetic.r40.binding.rollback',name='追加回滚节点')
        kp_id=node.id
    say(client,sid,ctx,'增加一道追加回滚节点的题。')
    proposal=reply(session_factory,sid).metadata_['paper_adjustment']['proposal']
    before=business_rows(session_factory);injections=[]
    owned_database=session_factory.kw['bind'].url.database
    def fail_item_insert(conn,cursor,statement,parameters,context,executemany):
        if conn.engine.url.database==owned_database and statement.lstrip().lower().startswith('insert into practice_items'):
            injections.append(statement)
            raise RuntimeError('SYNTHETIC R40 controlled insert failure')
    event.listen(Engine,'before_cursor_execute',fail_item_insert)
    try:
        rejected=client.post(f"/api/paper-adjustments/{proposal['task_id']}/confirm",json={
            'session_id':str(sid),'draft_version':proposal['draft_version']})
    finally:event.remove(Engine,'before_cursor_execute',fail_item_insert)
    assert injections and rejected.status_code==500,rejected.text
    assert business_rows(session_factory)==before
    with session_factory() as db:assert db.get(KpState,kp_id) is None


def test_append_does_not_silently_bind_preexisting_legacy_unbound_items(client,session_factory):
    from backend.models.learning import KpState
    sid,ctx,_=setup(session_factory)
    with session_factory.begin() as db:
        node,questions=_add_synthetic_topic(db,code='synthetic.r40.legacy.unbound',name='历史未绑定节点')
        kp_id=node.id;next_id=questions[1].id
        # Deliberately malformed legacy state, unlike normal official append.
        db.add(PracticeItem(plan_id=ctx.daily_plan_id,question_id=questions[0].id,kp_id=kp_id,ordinal=2))
    before=business_rows(session_factory)
    rejected=client.post(f'/api/plans/{ctx.daily_plan_id}/questions',json={'question_ids':[str(next_id)]})
    assert rejected.status_code==409,rejected.text
    assert rejected.json()['error']['code']=='graduation_set_binding_missing_for_started_learner'
    assert business_rows(session_factory)==before
    with session_factory() as db:assert db.get(KpState,kp_id) is None

@pytest.mark.parametrize('action,delta',[('增加',1),('减少',-1),('替换',0)])
def test_adjustment_receipt_keeps_real_before_and_after_counts_on_replay(client,session_factory,batch_bank,action,delta):
    sid,ctx,topics,originals=batch_bank
    def active_ids():
        with session_factory() as db:
            return set(db.scalars(select(PracticeItem.id).where(PracticeItem.plan_id==ctx.daily_plan_id,PracticeItem.removed_at.is_(None))))
    before=active_ids()
    say(client,sid,ctx,f'{action}一道批量甲节点的题目。')
    assert active_ids()==before
    say(client,sid,ctx,'确认调整')
    first=reply(session_factory,sid)
    receipt=first.metadata_['paper_adjustment']['receipt']
    after=active_ids()
    assert receipt['before_count']==len(before)
    assert receipt['total_count']==len(after)==len(before)+delta
    assert receipt['before_count']-len(receipt['removed_item_ids'])+receipt['added_count']==receipt['total_count']
    assert f'原有{len(before)}道' in first.content and f'当前共{len(after)}道' in first.content
    say(client,sid,ctx,'确认调整')
    repeated=reply(session_factory,sid).metadata_['paper_adjustment']['receipt']
    assert repeated==receipt and active_ids()==after
