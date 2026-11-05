from uuid import uuid4
import pytest
from pydantic import ValidationError
from backend.schemas.home_recommendation import HomeBankQuery
from backend.schemas.learning_task import FindQuestions


def test_home_scope_does_not_inherit_public_model_tool_eight_node_cap():
    ids=[uuid4() for _ in range(9)]
    assert HomeBankQuery(kp_ids=ids).kp_ids==ids
    with pytest.raises(ValidationError):
        FindQuestions(kp_ids=ids)
