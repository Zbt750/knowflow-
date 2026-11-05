from types import SimpleNamespace
from uuid import uuid4
from datetime import datetime, timezone
import pytest
from pydantic import ValidationError
from backend.services import home_recommendation_service as home
from backend.services.bank_selection_intent import bank_selection_request

@pytest.mark.parametrize('budget,unit_minutes,addition_count',[(120,5,2),(90,5,2),(90,20,2),(90,5,1)])
def test_large_home_addition_reaches_whole_paper_validation_without_dropping_baseline(monkeypatch,budget,unit_minutes,addition_count):
    kp=uuid4();ids=[uuid4() for _ in range(18+addition_count)];versions={qid:uuid4() for qid in ids}
    rows={qid:SimpleNamespace(current_version_id=versions[qid],estimated_minutes=unit_minutes) for qid in ids}
    retained=[{'question_id':str(qid),'question_version_id':str(versions[qid]),'kp_id':str(kp),'version':'stable'} for qid in ids[:18]]
    seen=[]
    def validate(db,args):
        seen.append(args.question_ids)
        return {'valid':tools.budget_minutes>=len(ids)*unit_minutes,'errors':[] if tools.budget_minutes>=len(ids)*unit_minutes else ['time_budget_exceeded']}
    tools=SimpleNamespace(budget_minutes=budget,nodes=set(),questions=set(),get_learning_state=lambda *a:{},find_questions=lambda *a:{'questions':[{'question_id':str(qid),'question_version':'stable','in_today_plan':False,'source_category':'development_original'} for qid in ids[18:]],'candidate_list_complete':True},validate_plan=validate)
    monkeypatch.setattr(home,'_tools',lambda *a,**k:tools)
    monkeypatch.setattr(home,'question_version_reference',lambda q:'stable')
    goal='帮我加入一道洛必达的题目进来' if addition_count==1 else '帮我加入两道隐函数的题目'
    result,evidence,error=home._bank_candidates(SimpleNamespace(get=lambda cls,qid:rows[qid]),None,goal,[kp],{'questions':retained},bank_selection_request(goal),budget,base_scope_ids=[kp])
    assert seen==([ids,ids] if budget<len(ids)*unit_minutes else [ids])
    assert tools.handoff['constraints']['existing_bank_only'] is True
    assert evidence['base_question_ids']==[str(qid) for qid in ids[:18]]
    assert result==ids and error is None
    if budget<len(ids)*unit_minutes:
        assert evidence['workload']['extra_minutes']==len(ids)*unit_minutes-budget
        assert evidence['workload']['requires_confirmation'] is True
        assert evidence['workload']['effective_budget_minutes']==len(ids)*unit_minutes


def test_home_validation_boundary_does_not_expand_chat_tool_contract():
    from backend.schemas.home_recommendation import HomePaperValidation
    from backend.schemas.learning_task import ValidatePlan
    with pytest.raises(ValidationError):ValidatePlan(question_ids=[uuid4() for _ in range(20)])
    ids=[uuid4() for _ in range(150)]
    assert HomePaperValidation(question_ids=ids).question_ids==ids


def test_workload_consent_is_required_by_server_before_formal_writes(monkeypatch):
    from types import SimpleNamespace
    from backend.errors import AppError
    from backend.services import home_recommendation_service as service
    import pytest
    row=SimpleNamespace(session_id='session',context={'home_recommendation':True,'workload':{'requires_confirmation':True}},metrics={},status='ready',draft={'questions':[]},goal='增加一道题')
    monkeypatch.setattr(service,'_session',lambda *a:None)
    monkeypatch.setattr(service,'_draft_version',lambda r:'a'*64)
    lock_calls=[]
    with pytest.raises(AppError) as error:
        service.confirm(SimpleNamespace(get=lambda *a,**k:row, scalar=lambda *a:None,
            execute=lambda statement,*a,**kw:lock_calls.append(str(statement))),
            'task',SimpleNamespace(session_id='session',draft_version='a'*64,accept_workload_increase=False),
            datetime(2026, 11, 5, tzinfo=timezone.utc))
    assert error.value.code=='home_workload_confirmation_required'
    assert len(lock_calls)==1 and 'pg_advisory_xact_lock' in lock_calls[0]

@pytest.mark.parametrize('attempted,expected',[(3,'bank_unattempted_exhausted'),(0,'bank_candidates_insufficient')])
def test_exhaustion_is_not_tool_failure_or_automatic_repractice(monkeypatch,attempted,expected):
    kp=uuid4();qid=uuid4();version=uuid4()
    previous={'questions':[{'question_id':str(qid),'question_version_id':str(version),'kp_id':str(kp),'version':'stable'}]}
    tools=SimpleNamespace(nodes=set(),questions=set(),get_learning_state=lambda *a:{},find_questions=lambda *a:{'questions':[],'home_attempted_excluded_count':attempted,'candidate_list_complete':True})
    monkeypatch.setattr(home,'_tools',lambda *a,**k:tools);monkeypatch.setattr(home,'question_version_reference',lambda q:'stable')
    result,evidence,message=home._bank_candidates(SimpleNamespace(get=lambda *a:SimpleNamespace(current_version_id=version)),None,'帮我加入一道洛必达的题目进来',[kp],previous,bank_selection_request('帮我加入一道洛必达的题目进来'),90,base_scope_ids=[kp])
    assert result is None and evidence['error']==expected
    assert ('都已做过' in message) if attempted else ('已安排' in message)
    assert tools.handoff['constraints']['home_unattempted_only'] is True
