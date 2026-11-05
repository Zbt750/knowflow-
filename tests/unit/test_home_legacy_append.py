from types import SimpleNamespace
from uuid import uuid4
from datetime import datetime, timezone
from backend.services import home_recommendation_service as home

def legacy_row():
    qid=str(uuid4()); extra=str(uuid4())
    return SimpleNamespace(id=uuid4(),session_id=uuid4(),goal='帮我加入1道隐函数的题目',status='ready',message='试卷预览',error_code=None,draft={'questions':[{'question_id':extra}]},budget_minutes=90,context={'home_recommendation':True,'baseline':{'questions':[{'question_id':qid}]}},metrics={},updated_at=None)

def test_old_additive_draft_missing_baseline_is_not_confirmable_or_mutated(monkeypatch):
    row=legacy_row();monkeypatch.setattr(home,'_draft_version',lambda r:'a'*64)
    result=home.view(row)
    assert result['status']=='needs_info' and result['draft'] is None
    assert result['error_code']=='legacy_incomplete_addition'
    assert row.status=='ready' and row.draft is not None

def test_old_addition_cannot_pass_formal_confirmation(monkeypatch):
    row=legacy_row();monkeypatch.setattr(home,'_session',lambda *a:None);monkeypatch.setattr(home,'_draft_version',lambda r:'a'*64)
    from backend.errors import AppError
    import pytest
    lock_calls=[]
    with pytest.raises(AppError) as error:
        home.confirm(SimpleNamespace(get=lambda *a,**k:row, scalar=lambda *a:None,
            execute=lambda statement,*a,**kw:lock_calls.append(str(statement))),
            row.id,SimpleNamespace(session_id=row.session_id,draft_version='a'*64),
            datetime(2026, 11, 5, tzinfo=timezone.utc))
    assert error.value.status_code==409
    assert len(lock_calls)==1 and 'pg_advisory_xact_lock' in lock_calls[0]


def test_guard_does_not_reopen_commits_or_override_explicit_new_scope():
    cancelled=legacy_row();cancelled.status='cancelled'
    assert home._legacy_incomplete_addition(cancelled) is False
    row=legacy_row();row.metrics={'commit':{'plan_id':'existing'}}
    assert home._legacy_incomplete_addition(row) is False
    row.metrics={};row.context['bank_scope']={'scope_mode':'append','base_scope_ids':[]}
    assert home._legacy_incomplete_addition(row) is False
    row.context.pop('bank_scope');row.goal='只练隐函数求导'
    assert home._legacy_incomplete_addition(row) is False
