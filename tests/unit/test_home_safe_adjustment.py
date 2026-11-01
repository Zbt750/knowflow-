from types import SimpleNamespace
from uuid import uuid4
from backend.services import home_recommendation_service as home

def test_failed_adjustment_recovers_same_session_active_paper_without_mutating_rows(monkeypatch):
    sid=uuid4();base=SimpleNamespace(id=uuid4(),session_id=sid,status='ready',draft={'questions':[{'question_id':'base'}]},context={'home_recommendation':True,'bank_scope':{'scope_mode':'append'}},goal='系统推荐',metrics={},message='原方案',error_code=None,budget_minutes=90)
    failed=SimpleNamespace(session_id=sid,status='failed',context={'fallback_task_id':str(base.id)},message='检索异常')
    monkeypatch.setattr(home,'_draft_version',lambda r:'v')
    result=home._result_view(SimpleNamespace(get=lambda *a:base),failed)
    assert result['task_id']==str(base.id) and result['draft']==base.draft and result['draft_version']=='v'
    assert result['adjustment_error']=='检索异常' and base.status=='ready' and failed.status=='failed'

def test_failed_adjustment_never_recovers_other_session_or_cancelled_paper():
    failed=SimpleNamespace(session_id=uuid4(),status='failed',context={'fallback_task_id':str(uuid4())})
    wrong=SimpleNamespace(session_id=uuid4(),status='ready')
    assert home._effective_row(SimpleNamespace(get=lambda *a:wrong),failed) is failed
    cancelled=SimpleNamespace(session_id=failed.session_id,status='cancelled')
    assert home._effective_row(SimpleNamespace(get=lambda *a:cancelled),failed) is failed

def test_exact_large_candidate_paper_does_not_pass_count_or_time_caps_to_selector(monkeypatch):
    ids=[uuid4() for _ in range(150)];kp=uuid4();calls=[]
    monkeypatch.setattr(home,'preview_initial_questions',lambda *a,**kw:calls.append(kw) or [])
    home._paper(None,[kp],90,None,150,ids,workload_preview=True)
    assert calls[0]['candidate_question_ids']==ids
    assert calls[0]['question_limit'] is None and calls[0]['minute_limit'] is None
    assert calls[0]['per_kp_limit']==150


def test_legacy_failed_adjustment_exposes_saved_baseline_without_faking_ready_or_writes(monkeypatch):
    sid=uuid4()
    baseline={'selected_kp_ids':['kp'], 'questions':[{'question_id':str(uuid4()),
        'question_version_id':str(uuid4()),'kp_id':'kp','minutes':5} for _ in range(18)],
        'budget_minutes':90,'total_minutes':90}
    failed=SimpleNamespace(id=uuid4(),session_id=sid,status='failed',draft=None,
        context={'home_recommendation':True,'baseline':baseline},goal='给我加入一道深度优先搜索的题目。',
        metrics={},message='题库查询异常',error_code='bank_lookup_failed',budget_minutes=90)
    monkeypatch.setattr(home,'_draft_version',lambda row:'failed-version')
    result=home._result_view(SimpleNamespace(get=lambda *a:None),failed)
    assert result['status']=='failed' and result['draft'] is None
    assert result['retained_baseline']==baseline
    assert result['retained_baseline']['questions'] is baseline['questions']
    assert failed.status=='failed' and failed.draft is None


def test_legacy_failure_uses_explicit_previous_ready_task_without_cross_session_recovery(monkeypatch):
    sid=uuid4();base=SimpleNamespace(id=uuid4(),session_id=sid,status='ready',
        draft={'questions':[]},metrics={},goal='系统推荐',context={'home_recommendation':True})
    failed=SimpleNamespace(session_id=sid,status='failed',context={'previous_task_id':str(base.id)})
    assert home._effective_row(SimpleNamespace(get=lambda *a:base),failed) is base
    base.session_id=uuid4()
    assert home._effective_row(SimpleNamespace(get=lambda *a:base),failed) is failed


def test_cancelled_or_malformed_saved_baseline_is_not_exposed_as_recoverable():
    q={'question_id':'q','question_version_id':'v','minutes':5}
    paper={'selected_kp_ids':['k'],'questions':[q],'total_minutes':5,'budget_minutes':90}
    row=SimpleNamespace(status='cancelled',context={'home_recommendation':True,'baseline':paper},metrics={})
    assert home._retained_baseline(row) is None
    row.status='failed';paper['questions']=[q,q];paper['total_minutes']=10
    assert home._retained_baseline(row) is None
    paper['questions']=[{**q,'question_version_id':None}];paper['total_minutes']=5
    assert home._retained_baseline(row) is None
