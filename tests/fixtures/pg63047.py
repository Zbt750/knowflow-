"""Identity-first transaction fixture for R13; no initialization or migrations.

Do not use until live SQL identity can be verified. Each factory.begin() uses
savepoints under an outer rollback. This is SERIAL per connection: it is not
an actual multi-connection race fixture.
"""
from contextlib import contextmanager
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker


@contextmanager
def rollback_factory(test_url, *, expected_system_identifier, expected_data_directory):
    url = make_url(test_url)
    if (url.get_backend_name() != "postgresql" or url.host != "127.0.0.1" or url.port != 63047
            or url.database != "naiwa_experience_test" or not expected_system_identifier):
        raise RuntimeError("r13_test_target_mismatch")
    engine = create_engine(url, connect_args={"connect_timeout": 5})
    try:
        with engine.connect() as connection:
            row = connection.execute(text("SELECT current_database(), inet_server_port(), "
                "current_setting('data_directory'), (SELECT system_identifier::text FROM pg_control_system())")).one()
            if (row[0] != url.database or row[1] != 63047 or row[3] != str(expected_system_identifier)
                    or Path(row[2]).resolve() != Path(expected_data_directory).resolve()):
                raise RuntimeError("r13_live_database_identity_mismatch")
            revisions = list(connection.scalars(text("SELECT version_num FROM alembic_version")))
            if revisions != ["f58d22ab41c7"]:
                raise RuntimeError("r13_schema_revision_mismatch")
            connection.rollback()  # End the read-only identity probe before outer transaction.
            transaction = connection.begin()
            try:
                yield sessionmaker(bind=connection, expire_on_commit=False,
                                   join_transaction_mode="create_savepoint")
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
