from pydantic import ValidationError
from sqlalchemy.exc import OperationalError
from backend.schemas.learning_task import ValidatePlan
from backend.schemas.home_recommendation import HomePaperValidation
from backend.services.home_recommendation_service import _bank_failure
from uuid import uuid4

def test_exact_nineteen_question_runtime_failure_is_parameter_error_and_home_accepts_collection():
    ids=[uuid4() for _ in range(19)]
    try:ValidatePlan(question_ids=ids)
    except ValidationError as exc:
        assert _bank_failure(exc,'validation_parameters')[0]=='bank_parameter_contract_error'
    else:raise AssertionError('public chat tool must retain its own contract')
    assert HomePaperValidation(question_ids=ids).question_ids==ids

def test_database_query_and_merge_exceptions_are_not_stock_shortages():
    assert _bank_failure(OperationalError('select',{},Exception('synthetic')),'query')[0]=='bank_database_error'
    assert _bank_failure(RuntimeError('synthetic'),'query')[0]=='bank_query_error'
    assert _bank_failure(RuntimeError('synthetic'),'candidate_merge')[0]=='bank_internal_error'
