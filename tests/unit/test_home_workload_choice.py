from types import SimpleNamespace as NS
from uuid import UUID,uuid4
from datetime import datetime,timezone,timedelta
import pytest
from backend.errors import AppError
from backend.services import home_recommendation_service as home


def rows():
    sid=uuid4();base=NS(id=uuid4(),session_id=sid,status='ready',draft={'questions':[{'question_id':'base'}]},
        context={'home_recommendation':True},goal='系统推荐',metrics={},message='原方案',error_code=None,budget_minutes=90)
    candidate=NS(id=uuid4(),session_id=sid,status='ready',draft={'questions':[{'question_id':'base'},{'question_id':'new'}]},
        context={'home_recommendation':True,'workload_pending':True,'fallback_task_id':str(base.id),
                 'workload':{'requires_confirmation':True}},goal='追加一题',metrics={},message='预计超出预算',error_code=None,budget_minutes=90)
    return base,candidate


def test_pending_workload_does_not_replace_the_active_paper_or_become_failure(monkeypatch):
    base,candidate=rows();monkeypatch.setattr(home,'_draft_version',lambda row:str(row.id))
    result=home._result_view(NS(get=lambda *a:base),candidate)
    assert result['task_id']==str(base.id) and result['draft']==base.draft
    assert result['workload_candidate']['task_id']==str(candidate.id)
    assert 'adjustment_error' not in result
    assert base.status=='ready' and candidate.status=='ready'


def test_workload_candidate_cannot_be_confirmed_before_acceptance_even_with_legacy_flag(monkeypatch):
    base,candidate=rows();monkeypatch.setattr(home,'_session',lambda *a:None)
    monkeypatch.setattr(home,'_draft_version',lambda row:'a'*64)
    lock_calls=[]
    with pytest.raises(AppError) as exc:
        home.confirm(NS(get=lambda *a,**kw:candidate,scalar=lambda *a:None,
            execute=lambda statement,*a,**kw:lock_calls.append(str(statement))),candidate.id,
            NS(session_id=candidate.session_id,draft_version='a'*64,accept_workload_increase=True),
            datetime(2026,11,5,tzinfo=timezone.utc))
    assert exc.value.code=='home_workload_confirmation_required'
    assert len(lock_calls)==1 and 'pg_advisory_xact_lock' in lock_calls[0]


def test_declining_workload_restores_original_without_cancelling_it(monkeypatch):
    base,candidate=rows();candidate.status='cancelled'
    candidate.context.update(workload_pending=False,workload_decision='declined')
    assert home._effective_row(NS(get=lambda *a:base),candidate) is base
    assert base.status=='ready'


def test_first_turn_fallback_insert_order_does_not_hide_the_budget_choice():
    base,candidate=rows()
    db=NS(scalars=lambda *a:[base,candidate])
    assert home._latest(db,candidate.session_id) is candidate


@pytest.mark.parametrize('accept',[True,False])
def test_workload_decision_preserves_exact_candidate_and_never_calls_formal_creation(monkeypatch,accept):
    base,candidate=rows();now=datetime.now(timezone.utc)
    candidate.context.update(study_date=now.astimezone(home.SHANGHAI).date().isoformat(),expires_at=(now+timedelta(minutes=30)).isoformat())
    candidate.draft={'selected_kp_ids':[str(uuid4())], 'questions':[
        {'question_id':str(uuid4()),'question_version_id':str(uuid4()),'minutes':5} for _ in range(19)],'total_minutes':95}
    monkeypatch.setattr(home,'_draft_version',lambda row:'a'*64)
    checks=[];flushes=[]
    def paper(db,ids,budget,at,limit,candidates,**kw):
        checks.append(candidates)
        assert kw=={'workload_preview':True}
        return candidate.draft
    monkeypatch.setattr(home,'_paper',paper)
    monkeypatch.setattr(home,'create_initial_plan',lambda *a,**kw:pytest.fail('acceptance is not formal generation'))
    db=NS(scalars=lambda *a:[base,candidate],get=lambda *a:base,flush=lambda:flushes.append(True))
    body=NS(action='accept_workload' if accept else 'dismiss_workload',expected_version='a'*64)
    result=home._decide_workload(db,candidate,body,now)
    assert len(flushes)==1
    if accept:
        assert result['task_id']==str(candidate.id) and len(result['draft']['questions'])==19
        assert checks[0]==[UUID(q['question_id']) for q in candidate.draft['questions']]
        assert base.status=='cancelled' and candidate.context['workload_accepted'] is True
    else:
        assert result['task_id']==str(base.id) and base.status=='ready'
        assert candidate.status=='cancelled' and checks==[]
    # Same version repeated: return persisted decision without another change.
    home._decide_workload(db,candidate,body,now)
    assert len(flushes)==1


def test_changed_candidate_version_keeps_original_active_and_pending_candidate_unaccepted(monkeypatch):
    base,candidate=rows();now=datetime.now(timezone.utc)
    candidate.context.update(study_date=now.astimezone(home.SHANGHAI).date().isoformat(),expires_at=(now+timedelta(minutes=30)).isoformat())
    candidate.draft.update(selected_kp_ids=[str(uuid4())],total_minutes=95)
    candidate.draft['questions']=[{'question_id':str(uuid4()),'question_version_id':str(uuid4())}]
    monkeypatch.setattr(home,'_draft_version',lambda row:'a'*64)
    monkeypatch.setattr(home,'_paper',lambda *a,**kw:{'questions':[{'question_version_id':'changed'}],'total_minutes':95})
    db=NS(flush=lambda:pytest.fail('no state change may be flushed'))
    with pytest.raises(AppError) as exc:
        home._decide_workload(db,candidate,NS(action='accept_workload',expected_version='a'*64),now)
    assert exc.value.code=='learning_task_stale_draft'
    assert base.status=='ready' and candidate.context['workload_pending'] is True


@pytest.mark.parametrize('previously_accepted_workload',[False,True])
def test_pending_budget_suggestion_does_not_block_confirmation_of_the_original(monkeypatch,previously_accepted_workload):
    base,candidate=rows();now=datetime.now(timezone.utc)
    base.context.update(study_date=now.astimezone(home.SHANGHAI).date().isoformat(),expires_at=(now+timedelta(minutes=30)).isoformat())
    if previously_accepted_workload:
        base.context.update(workload={'requires_confirmation':True},workload_accepted=True)
    base.draft['selected_kp_ids']=[str(uuid4())]
    monkeypatch.setattr(home,'_session',lambda *a:None)
    monkeypatch.setattr(home,'_draft_version',lambda row:'a'*64)
    def stop_before_db_write(*a):raise RuntimeError('reached formal validation')
    db=NS(get=lambda *a,**kw:base,scalars=lambda *a:[candidate],execute=stop_before_db_write)
    with pytest.raises(RuntimeError,match='reached formal validation'):
        home.confirm(db,base.id,NS(session_id=base.session_id,draft_version='a'*64,accept_workload_increase=False),now)
    assert base.status=='ready' and base.metrics=={}


def test_original_confirmed_while_suggestion_pending_recovers_formal_receipt_not_candidate(monkeypatch):
    base,candidate=rows();base.status='answered';base.metrics={'commit':{'plan_id':'formal-A'}}
    monkeypatch.setattr(home,'_draft_version',lambda row:'a'*64)
    result=home._result_view(NS(get=lambda *a:base),candidate)
    assert result['task_id']==str(base.id) and result['receipt']=={'plan_id':'formal-A'}
    assert 'workload_candidate' not in result
