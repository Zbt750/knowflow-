"""Formal adjustment budget acknowledgment via real API/owned PostgreSQL.
Synthetic trusted content is a regression fixture, not real408 acceptance.
"""
from uuid import UUID,uuid4
from datetime import timedelta
import pytest
from sqlalchemy import select
from backend.models.learning import PracticeItem,Question
from backend.models.learning_task import LearningTask
from tests.integration.test_r40_post_batch_quantities import (
    batch_bank,isolated_business_dependencies,client,clock,session_factory,clean_database,clean_tasks,conversations,say,reply,NOW)
from tests.integration.test_explore_student_repairs import business_rows
from backend.services.question_versions import question_version_reference


def prepare(client,session_factory,batch_bank,budget=5,remove=None):
    sid,ctx,topics,originals=batch_bank
    with session_factory() as db:
        used=set(db.scalars(select(PracticeItem.question_id).where(PracticeItem.plan_id==ctx.daily_plan_id)))
        question=next(q for q in db.scalars(select(Question).where(Question.kp_id==topics[0])) if q.id not in used)
        ref={'question_id':str(question.id),'question_version_id':question_version_reference(question)}
    response=client.post('/api/paper-adjustments',json={'session_id':str(sid),'plan_id':str(ctx.daily_plan_id),
        'remove_item_ids':[str(remove)] if remove else [],'replacements':[ref],'budget_minutes':budget})
    assert response.status_code==201,response.text
    return sid,ctx,response.json()


@pytest.mark.parametrize('budget',[5,15])
def test_over_budget_proposal_requires_separate_explicit_acceptance(client,session_factory,batch_bank,budget):
    sid,ctx,proposal=prepare(client,session_factory,batch_bank,budget=budget)
    workload=proposal.get('workload')
    assert workload and workload['requires_confirmation'] is True and workload['remaining_minutes']>budget,proposal
    body={'session_id':str(sid),'draft_version':proposal['draft_version']}
    before=business_rows(session_factory)
    endpoint='/api/paper-adjustments/'+proposal['task_id']+'/confirm'
    denied=client.post(endpoint,json=body)
    assert denied.status_code==409 and denied.json()['error']['code']=='paper_budget_confirmation_required',denied.text
    assert business_rows(session_factory)==before
    accepted=client.post(endpoint,json={**body,'accept_budget_overrun':True})
    assert accepted.status_code==200,accepted.text
    receipt=accepted.json()
    assert receipt['budget_overrun_accepted'] is True and receipt['remaining_minutes']>receipt['budget_minutes']==budget
    assert receipt['before_count']+1==receipt['total_count']
    replay=client.post(endpoint,json=body)
    assert replay.status_code==200 and replay.json()==receipt


def test_chat_budget_inquiry_negation_and_plain_confirm_cannot_authorize_overrun(client,session_factory,batch_bank):
    sid,ctx,topics,originals=batch_bank
    say(client,sid,ctx,'预算5分钟，增加一道批量甲节点的题目。')
    draft=reply(session_factory,sid)
    assert '超出预算' in draft.content and draft.metadata_['paper_adjustment']['proposal']
    before=business_rows(session_factory)
    for message in ['确认调整','能不能确认超预算调整？','先不要确认超预算调整。']:
        say(client,sid,ctx,message)
        assert business_rows(session_factory)==before,message
        assert not reply(session_factory,sid).metadata_['paper_adjustment'].get('receipt')
    say(client,sid,ctx,'确认超预算调整')
    accepted=reply(session_factory,sid)
    receipt=accepted.metadata_['paper_adjustment']['receipt']
    assert receipt['budget_overrun_accepted'] is True and receipt['before_count']+1==receipt['total_count']
    say(client,sid,ctx,'确认超预算调整')
    assert reply(session_factory,sid).metadata_['paper_adjustment']['receipt']==receipt


def test_viewed_and_budget_permissions_are_independent(client,session_factory,batch_bank):
    sid,ctx,topics,originals=batch_bank
    viewed=client.post(f'/api/practice-items/{originals[0]}/activity',json={'kind':'viewed','idempotency_key':uuid4().hex})
    assert viewed.status_code==200,viewed.text
    sid,ctx,proposal=prepare(client,session_factory,batch_bank,remove=originals[0])
    body={'session_id':str(sid),'draft_version':proposal['draft_version']}
    endpoint='/api/paper-adjustments/'+proposal['task_id']+'/confirm'
    before=business_rows(session_factory)
    for flags,code in [({'accept_budget_overrun':True},'paper_viewed_confirmation_required'),({'confirm_viewed':True},'paper_budget_confirmation_required')]:
        denied=client.post(endpoint,json={**body,**flags})
        assert denied.status_code==409 and denied.json()['error']['code']==code,denied.text
        assert business_rows(session_factory)==before
    accepted=client.post(endpoint,json={**body,'confirm_viewed':True,'accept_budget_overrun':True})
    assert accepted.status_code==200,accepted.text
    assert accepted.json()['removed_item_ids']==[str(originals[0])]


@pytest.mark.parametrize('invalid',['session','version','expired'])
def test_budget_acceptance_cannot_bypass_other_confirmation_guards(client,session_factory,batch_bank,clock,invalid):
    sid,ctx,proposal=prepare(client,session_factory,batch_bank)
    body={'session_id':str(sid),'draft_version':proposal['draft_version'],'accept_budget_overrun':True}
    if invalid=='session':body['session_id']=str(uuid4())
    elif invalid=='version':body['draft_version']='f'*64
    else:clock.now=NOW+timedelta(minutes=31)
    before=business_rows(session_factory)
    response=client.post('/api/paper-adjustments/'+proposal['task_id']+'/confirm',json=body)
    assert response.status_code==(404 if invalid=='session' else 409),response.text
    assert response.json()['error']['code']=={'session':'learning_task_not_found','version':'learning_task_conflict','expired':'learning_task_stale_draft'}[invalid]
    assert business_rows(session_factory)==before
    with session_factory() as db:assert not (db.get(LearningTask,UUID(proposal['task_id'])).metrics or {}).get('commit')


def test_budget_acceptance_requires_a_real_boolean(client,session_factory,batch_bank):
    sid,ctx,proposal=prepare(client,session_factory,batch_bank)
    before=business_rows(session_factory)
    response=client.post('/api/paper-adjustments/'+proposal['task_id']+'/confirm',json={
        'session_id':str(sid),'draft_version':proposal['draft_version'],'accept_budget_overrun':'true'})
    assert response.status_code==422,response.text
    assert business_rows(session_factory)==before
