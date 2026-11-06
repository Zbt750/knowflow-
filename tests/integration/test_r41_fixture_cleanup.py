"""Known owned test data must not leak personal generation batches across cases."""
from uuid import uuid4
from sqlalchemy import select,func
from backend.models.personal_generation import PersonalGenerationBatch
from tests.integration.test_learning_loop import session_factory,clean_database


def test_clean_database_clears_orphan_personal_generation_batches(session_factory):
    with session_factory.begin() as db:
        db.add(PersonalGenerationBatch(request_key=str(uuid4()),input_sha256='0'*64,
            status='failed',study_date='2026-01-01',reserved_calls=0,request={},result={}))
    reset=clean_database.__wrapped__(session_factory)
    try:
        next(reset)
        with session_factory() as db:
            assert db.scalar(select(func.count()).select_from(PersonalGenerationBatch))==0
    finally:
        reset.close()
