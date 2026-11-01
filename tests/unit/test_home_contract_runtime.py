from uuid import uuid4
import json
import pytest
from pydantic import ValidationError
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.schemas.learning_task import PaperValidation, ValidatePlan
from backend.schemas.home_recommendation import HomePaperValidation
from backend.services.runtime_version import capture_runtime_version
from backend.api.routes.health import router

def test_transport_limit_is_not_reused_as_persisted_paper_limit():
    ids=[uuid4() for _ in range(19)]
    with pytest.raises(ValidationError):ValidatePlan(question_ids=ids)
    assert PaperValidation(question_ids=ids).question_ids==ids
    assert HomePaperValidation(question_ids=ids).question_ids==ids
    assert ValidatePlan.model_json_schema()['properties']['question_ids']['maxItems']==12
    assert 'maxItems' not in PaperValidation.model_json_schema()['properties']['question_ids']

def test_runtime_snapshot_is_frozen_and_has_loaded_contracts(tmp_path,monkeypatch):
    import backend.services.runtime_version as runtime
    monkeypatch.setattr(runtime,'SOURCE_FILES',('version.py',))
    path=tmp_path/'version.py';path.write_text('before')
    snapshot=capture_runtime_version(tmp_path);original=dict(snapshot['source_hashes_at_app_creation'])
    path.write_text('after')
    assert snapshot['source_hashes_at_app_creation']==original
    assert snapshot['loaded_question_id_limits']=={'whole_paper':None,'home_paper':None,'chat_tool':12}
    assert snapshot['home_loaded_parameter_model']=='HomePaperValidation'
    assert all(snapshot['loaded_function_hashes'].values())
    assert {'home_manual_scope_paper','home_adjust','home_paper'}.issubset(snapshot['loaded_function_hashes'])

def test_version_route_does_not_start_app_or_touch_database():
    app=FastAPI();app.state.runtime_version={'pid':123,'diagnostic_version':'test'};app.include_router(router,prefix='/api')
    with TestClient(app,base_url='http://127.0.0.1') as client:
        response=client.get('/api/runtime-version')
    assert response.status_code==200 and response.json()['pid']==123
    assert not any(key in response.json() for key in ('database_url','password','api_key','environment_variables'))


def test_real_app_registers_frozen_diagnosis_without_starting_lifespan():
    from backend.app import create_app
    app = create_app()
    assert '/api/runtime-version' in app.openapi()['paths']
    assert app.state.runtime_version['loaded_question_id_limits']['whole_paper'] is None
    assert app.state.runtime_version['home_loaded_parameter_model'] == 'HomePaperValidation'


def test_internal_full_paper_entry_keeps_shared_validation_and_database_scope():
    from contextlib import nullcontext
    from types import SimpleNamespace
    from backend.services.learning_task_tools import TaskTools
    ids = [uuid4() for _ in range(19)]
    db = object()
    seen = []
    def validate(connection, args):
        seen.append((connection, args))
        return {'valid': False, 'errors': ['question_version_missing']}
    tools = SimpleNamespace(factory=lambda: nullcontext(db), validate_plan=validate)
    result = TaskTools.validate_paper_candidates(tools, {'question_ids': ids})
    assert seen[0][0] is db and seen[0][1].question_ids == ids
    assert type(seen[0][1]) is PaperValidation
    assert result == {'valid': False, 'errors': ['question_version_missing']}
