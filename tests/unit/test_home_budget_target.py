from datetime import datetime,timezone,timedelta
from types import SimpleNamespace as NS
from uuid import uuid4
import pytest
from backend.errors import AppError
from backend.schemas.home_recommendation import HomeRecommendationRequest
from backend.services import home_recommendation_service as home


def test_missing_target_never_silently_selects_the_latest_task():
    with pytest.raises(AppError) as exc:
        home._workload_target(NS(get=lambda *a,**kw:pytest.fail('no implicit lookup')),
            uuid4(),NS(target_task_id=None))
    assert exc.value.status_code==422


@pytest.mark.parametrize('wrong_session',[True,False])
def test_target_is_ownership_checked_and_must_be_the_current_pending_proposal(monkeypatch,wrong_session):
    sid=uuid4();row=NS(id=uuid4(),session_id=uuid4() if wrong_session else sid,context={'home_recommendation':True})
    monkeypatch.setattr(home,'_latest',lambda *a:NS(id=uuid4()))
    with pytest.raises(AppError) as exc:
        home._workload_target(NS(get=lambda *a,**kw:row),sid,NS(target_task_id=row.id))
    assert exc.value.status_code==(404 if wrong_session else 409)


def test_button_action_enters_exact_acceptance_without_scope_parsing_bank_query_chat_or_formal_write(monkeypatch):
    now=datetime.now(timezone.utc);sid=uuid4();node=uuid4();qid=uuid4();vid=uuid4()
    def policies(db, ids, *, include_missing):
        assert ids==[node] and include_missing
        return {node:NS(graduation_binding_pending=False)},None
    monkeypatch.setattr('backend.services.study_read_context.policies_for_nodes',policies)
    row=NS(id=uuid4(),session_id=sid,status='ready',goal='增加一题',metrics={},error_code=None,message='预算提醒',budget_minutes=90,
        draft={'selected_kp_ids':[str(node)],'questions':[{'question_id':str(qid),'question_version_id':str(vid)}],'total_minutes':95},
        context={'home_recommendation':True,'workload_pending':True,'study_date':now.astimezone(home.SHANGHAI).date().isoformat(),
                 'expires_at':(now+timedelta(minutes=30)).isoformat(),'workload':{'requires_confirmation':True}})
    monkeypatch.setattr(home,'_session',lambda *a:NS(id=sid,study_date=now.astimezone(home.SHANGHAI).date().isoformat()));monkeypatch.setattr(home,'_latest',lambda *a:row)
    monkeypatch.setattr(home,'_draft_version',lambda *a:'a'*64)
    for name in ('resolve_scope','_tools','create_initial_plan','_record_request_dialogue'):
        monkeypatch.setattr(home,name,lambda *a,**kw:pytest.fail('button must not re-enter chat/matching/generation'))
    seen=[]
    def validate(db,ids,budget,at,limit,candidates,**kw):
        seen.append((ids,candidates));assert candidates==[qid] and kw['workload_preview'] is True
        return row.draft
    monkeypatch.setattr(home,'_paper',validate)
    db=NS(get=lambda *a,**kw:row,scalars=lambda *a:[row],flush=lambda:None)
    body=HomeRecommendationRequest(session_id=sid,request_key=uuid4().hex,action='accept_workload',target_task_id=row.id,expected_version='a'*64)
    result=home.adjust(db,body,[],now)
    assert result['task_id']==str(row.id) and result['context']['workload_accepted'] is True
    assert seen==[([node],[qid])]
    repeated=home.adjust(db,body,[],now)
    assert repeated['task_id']==result['task_id'] and len(seen)==1


@pytest.mark.parametrize('status,expired',[('cancelled',False),('ready',True)])
def test_expired_or_cancelled_candidate_cannot_be_accepted(monkeypatch,status,expired):
    now=datetime.now(timezone.utc)
    row=NS(status=status,draft={'questions':['existing']},metrics={},context={'workload_pending':True,
        'study_date':now.astimezone(home.SHANGHAI).date().isoformat(),
        'expires_at':(now-timedelta(seconds=1) if expired else now+timedelta(minutes=30)).isoformat()})
    monkeypatch.setattr(home,'_draft_version',lambda *a:'a'*64)
    with pytest.raises(AppError) as exc:
        home._decide_workload(NS(flush=lambda:pytest.fail('invalid candidate must not change')),
            row,NS(action='accept_workload',expected_version='a'*64),now)
    assert exc.value.status_code==409 and row.status==status


def test_old_client_text_confirmation_cannot_reenter_knowledge_matching(monkeypatch):
    now=datetime.now(timezone.utc);sid=uuid4();kp=uuid4();qid=uuid4();version=uuid4()
    row=NS(id=uuid4(),session_id=sid,status='ready',draft={'selected_kp_ids':[str(kp)],'questions':[
        {'question_id':str(qid),'question_version_id':str(version),'kp_id':str(kp),'version':str(version),'minutes':5}]},
        goal='增加一题',budget_minutes=90,metrics={},context={'home_recommendation':True,'workload_pending':True})
    monkeypatch.setattr(home,'_session',lambda *a:NS(id=sid,study_date=now.astimezone(home.SHANGHAI).date().isoformat()));monkeypatch.setattr(home,'_latest',lambda *a:row)
    monkeypatch.setattr(home,'resolve_scope',lambda *a:pytest.fail('confirmation text must not match knowledge points'))
    lock_calls=[]
    db=NS(scalars=lambda *a:[row],scalar=lambda *a:None,
          execute=lambda statement,*a,**kw:lock_calls.append(str(statement)))
    body=HomeRecommendationRequest(session_id=sid,request_key=uuid4().hex,action='adjust',goal='我确定')
    with pytest.raises(AppError) as exc:
        home.adjust(db,body,[],now)
    assert exc.value.code=='home_workload_confirmation_required' and row.status=='ready'
    assert len(lock_calls)==1 and 'pg_advisory_xact_lock' in lock_calls[0]
