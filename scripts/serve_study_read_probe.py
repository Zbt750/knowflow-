"""Serve real application routes over a rollback-isolated clone for UI smoke tests.

Lifespan/jobs/model loading are intentionally disabled: this is not a full
product startup test and cannot mutate imported learner history.
"""
import argparse
import json
import os
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
import uvicorn


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--owner', type=Path, required=True)
    args = parser.parse_args()
    from sqlalchemy.engine import make_url
    parsed = make_url(os.environ.get('TEST_DATABASE_URL', ''))
    if (os.environ.get('APP_ENV') != 'test' or parsed.host != '127.0.0.1'
            or parsed.port != 59328 or parsed.database != 'kaoyan_perf_clone_test'):
        raise RuntimeError('Only the owned isolated 59328 clone is allowed')
    engine = create_engine(parsed, connect_args={'connect_timeout': 5})
    owner = json.loads(args.owner.read_text(encoding='utf-8-sig'))
    with engine.connect() as connection:
        identity = connection.execute(text("""SELECT system_identifier::text AS identifier,
            current_setting('data_directory') AS data_directory FROM pg_control_system()""")).mappings().one()
        if (identity['identifier'] != owner['system_identifier']
                or Path(identity['data_directory']).resolve() != Path(owner['data_directory']).resolve()):
            raise RuntimeError('Isolated clone ownership mismatch')
    from backend.app import create_app
    from backend.config import get_settings
    app = create_app()
    class RollbackProbeSession(Session):
        def __init__(self, **kwargs):
            # Existing GET /practice-requests legitimately takes row locks for
            # maintenance. A strictly READ ONLY transaction rejects that even
            # with no rows. An outer transaction permits real route semantics
            # while ensuring every session's changes are discarded on close.
            self._probe_connection = engine.connect()
            self._probe_transaction = self._probe_connection.begin()
            kwargs.pop('bind', None)
            super().__init__(bind=self._probe_connection,
                             join_transaction_mode='create_savepoint', **kwargs)

        def close(self):
            try:
                super().close()
            finally:
                if self._probe_transaction.is_active:
                    self._probe_transaction.rollback()
                self._probe_connection.close()

    app.state.session_factory = sessionmaker(class_=RollbackProbeSession,
        autoflush=False, expire_on_commit=False)
    app.state.settings = get_settings().model_copy(update={
        'llm_api_key': None, 'llm_base_url': None, 'llm_model': None,
        'model_settings_path': Path('storage/quality-audits/study-read-performance-20261016/no-model.bin')})
    app.state.retrieval_stack = None
    app.state.job_runner = None
    uvicorn.run(app, host='127.0.0.1', port=18086, lifespan='off', log_level='warning')


if __name__ == '__main__':
    main()
