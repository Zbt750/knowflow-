"""Read-only study endpoint benchmark against an explicitly owned isolated clone.

Does not start the application lifespan, seed data or call a model provider.
"""
from __future__ import annotations

import argparse
import cProfile
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import pstats
import time

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', required=True)
    parser.add_argument('--owner', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--no-profile', action='store_true')
    args = parser.parse_args()
    url = os.environ.get('TEST_DATABASE_URL', '')
    parsed = make_url(url)
    if (os.environ.get('APP_ENV') != 'test' or parsed.host != '127.0.0.1'
            or parsed.port != 59328 or parsed.database != 'kaoyan_perf_clone_test'):
        raise RuntimeError('Explicit owned 59328 clone is required; production is forbidden')
    owner = json.loads(args.owner.read_text(encoding='utf-8-sig'))
    engine = create_engine(url, connect_args={'connect_timeout': 5})
    with engine.connect() as connection:
        connection.exec_driver_sql('SET TRANSACTION READ ONLY')
        identity = connection.execute(text("""SELECT system_identifier::text AS identifier,
            current_setting('data_directory') AS data_directory FROM pg_control_system()""")).mappings().one()
        if (identity['identifier'] != owner['system_identifier']
                or Path(identity['data_directory']).resolve() != Path(owner['data_directory']).resolve()
                or owner['port'] != parsed.port):
            raise RuntimeError('Clone identity mismatch')
    from backend.api.routes.study import read_knowledge_tree, read_today_plan
    from backend.services.question_availability import question_availability
    now = datetime(2026, 10, 16, 12, 48, tzinfo=timezone.utc)
    args.output.mkdir(parents=True, exist_ok=True)
    results = {'label': args.label, 'identity': dict(identity), 'endpoints': {}}
    tables = ('questions', 'question_versions', 'question_auto_review_events',
              'kp_graduation_question_set_versions', 'question_attempts',
              'learning_events', 'kp_states', 'daily_plans', 'practice_items')
    with engine.connect() as connection:
        results['counts'] = {table: connection.exec_driver_sql(f'SELECT count(*) FROM {table}').scalar_one()
                             for table in tables}
    for name, call in (
        ('knowledge_tree', lambda db: read_knowledge_tree(db=db, time_provider=lambda: now)),
        ('today', lambda db: read_today_plan(db=db, time_provider=lambda: now)),
        ('availability', lambda db: question_availability(db, now=now)),
    ):
        statements = []
        def count_sql(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        event.listen(engine, 'before_cursor_execute', count_sql)
        profile = cProfile.Profile()
        try:
            with Session(engine, autoflush=False) as db:
                db.execute(text('SET TRANSACTION READ ONLY'))
                started, cpu = time.perf_counter(), time.process_time()
                if not args.no_profile:
                    profile.enable()
                payload = call(db)
                profile.disable()
                elapsed, cpu_used = time.perf_counter() - started, time.process_time() - cpu
                if hasattr(payload, 'model_dump'):
                    payload = payload.model_dump(mode='json')
                encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
                digest = hashlib.sha256(encoded.encode()).hexdigest()
                db.rollback()
            (args.output / f'{args.label}-{name}.json').write_text(encoded, encoding='utf-8')
            if not args.no_profile:
                profile.dump_stats(str(args.output / f'{args.label}-{name}.prof'))
                with (args.output / f'{args.label}-{name}-profile.txt').open('w', encoding='utf-8') as report:
                    pstats.Stats(profile, stream=report).sort_stats('cumulative').print_stats(35)
            results['endpoints'][name] = {
                'seconds_profiled': elapsed if not args.no_profile else None,
                'seconds_wall': elapsed, 'cpu_seconds': cpu_used,
                'sql_statements': len(statements), 'response_sha256': digest,
            }
            print(name, json.dumps(results['endpoints'][name]), flush=True)
        finally:
            profile.disable()
            event.remove(engine, 'before_cursor_execute', count_sql)
    with engine.connect() as connection:
        results['history_fingerprints'] = {
            table: connection.exec_driver_sql(
                f"SELECT md5(COALESCE(string_agg(row_to_json(t)::text, E'\\n' "
                f"ORDER BY row_to_json(t)::text), '')) FROM {table} AS t"
            ).scalar_one()
            for table in ('question_attempts', 'learning_events', 'kp_states', 'daily_plans', 'practice_items')
        }
    (args.output / f'{args.label}-summary.json').write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    engine.dispose()


if __name__ == '__main__':
    main()
