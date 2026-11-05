"""Pure in-memory read-path regression. No database, socket, model or fake API."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from uuid import uuid4
import pytest
from backend.services.practice_request_service import list_requests

@pytest.mark.parametrize('state,task_state,expected',[
 ('proposed','ready','expired'),('planning','failed','failed'),('planning','cancelled','failed'),
 ('planning','ready','proposed'),('draft','ready','draft'),('planning','failed','expired')])
def test_get_list_derives_state_without_mutating_saved_rows(state,task_state,expected):
    now=datetime(2040,3,3,tzinfo=timezone.utc)
    row=SimpleNamespace(id=uuid4(),status=state,source_conversation_id=uuid4(),source_message_id=uuid4(),
        user_request='saved historical request',request={},planner_task_id=uuid4(),daily_plan_id=None,
        error_code=None,created_at=now-timedelta(days=1),expires_at=now-timedelta(seconds=1) if state=='planning' and expected=='expired' else now+timedelta(days=1),handled_at=None)
    task=SimpleNamespace(id=row.planner_task_id,status=task_state,draft={'questions':[{}]},context={'current_plan':{'study_date':'2040-03-02' if state=='proposed' else '2040-03-03'}},error_code='test_dependency')
    original=deepcopy(vars(row))
    class DB:
        def scalars(self,query):
            from backend.models.practice_request import PracticeRequest
            return [row] if query.column_descriptions[0]['entity'] is PracticeRequest else [task]
        def get(self,*args):return task
    class Factory:
        @contextmanager
        def __call__(self):yield DB()
        def begin(self):raise AssertionError('GET must not open a committing transaction')
    response=list_requests(Factory(),now=now)
    assert response[0]['status']==expected
    assert vars(row)==original
