from types import SimpleNamespace
from uuid import UUID
from unittest.mock import Mock
import pytest
from tests.fixtures.naiwa_factory import NaiwaFactory, create_test_user, NOW

NS=UUID("13000000-0000-4000-8000-000000000001")

def test_deterministic_identity_is_scoped():
    a=NaiwaFactory(Mock(),NS)
    assert a.identity("x")==NaiwaFactory(Mock(),NS).identity("x")
    assert a.identity("x")!=a.identity("y")
    assert a.identity("x")!=NaiwaFactory(Mock(),UUID(int=14)).identity("x")

def test_actor_is_not_a_forged_orm_account():
    actor=create_test_user(NS)
    assert actor.namespace==NS and not hasattr(actor,"__table__")

@pytest.mark.parametrize("field",["id","kp_id","current_version_id","current_version","content_trust","answer_reliability","answer_verification_event_id"])
def test_factory_refuses_version_and_trust_shortcuts(field):
    session=Mock();f=NaiwaFactory(session,NS)
    with pytest.raises(ValueError):f.create_test_question(SimpleNamespace(id=UUID(int=1)),**{field:"forged"})
    session.add.assert_not_called()

def test_add_flushes_but_never_commits():
    session=Mock();f=NaiwaFactory(session,NS);obj=object()
    assert f.add(obj) is obj
    session.add.assert_called_once_with(obj);session.flush.assert_called_once()
    session.commit.assert_not_called()

def test_item_requires_real_version_before_write():
    session=Mock();f=NaiwaFactory(session,NS)
    with pytest.raises(ValueError):f.create_test_practice_item(SimpleNamespace(),SimpleNamespace(current_version_id=None))
    session.add.assert_not_called()


@pytest.mark.parametrize("url",[
    "postgresql+psycopg://x@127.0.0.1:5433/naiwa_experience_test",
    "postgresql+psycopg://x@127.0.0.1:63047/production",
    "postgresql+psycopg://x@remote:63047/naiwa_experience_test",
])
def test_rollback_fixture_refuses_wrong_target_without_connecting(url):
    from tests.fixtures.pg63047 import rollback_factory
    with pytest.raises(RuntimeError,match="target_mismatch"):
        with rollback_factory(url,expected_system_identifier="7703578443208394676",expected_data_directory="tmp/pg63047"):
            raise AssertionError("must not yield")
