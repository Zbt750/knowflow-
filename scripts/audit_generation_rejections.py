"""Read-only diagnostics for the application's existing generation ledger.

No provider invocation, schema change, privilege change or business write.
Never emit credentials, full chat history or arbitrary exception messages.
"""
import json
from pathlib import Path
import sys
import argparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from backend.config import get_settings
from backend.services.model_settings_service import load_local_settings

parser=argparse.ArgumentParser()
parser.add_argument('--output-dir',type=Path,default=ROOT/'storage/quality-audits/generation-rejection-20261019')
parser.add_argument('--skip-sessions',action='store_true')
args=parser.parse_args()
out=args.output_dir.resolve()
if not out.is_relative_to((ROOT/'storage/quality-audits').resolve()):
    raise SystemExit('Audit output must stay under storage/quality-audits.')

settings = load_local_settings(get_settings())
url = make_url(str(settings.database_url))
if (url.host, url.port, url.database, url.username) != ('127.0.0.1', 5433, 'kaoyan', 'kaoyan'):
    raise SystemExit('Unexpected application database identity; read aborted.')
engine = create_engine(url, connect_args={'options': '-c default_transaction_read_only=on', 'connect_timeout': 5})
with engine.connect() as db:
    db.execute(text('BEGIN READ ONLY'))
    identity = dict(db.execute(text('SELECT current_database() AS database, current_user AS role, inet_server_port() AS port, current_schema() AS schema')).mappings().one())
    rows = db.execute(text('SELECT id, created_at, status, request, result FROM personal_generation_batches ORDER BY created_at DESC LIMIT 18')).mappings().all()
    records = []
    for row in rows:
        request, result = row['request'], row['result']
        source=db.execute(text("SELECT m.metadata, u.content AS original_message FROM chat_messages m LEFT JOIN chat_messages u ON u.id::text=m.metadata->>'source_user_message_id' WHERE m.metadata->'personal_generation'->>'batch_id'=:bid LIMIT 1"),{'bid':str(row['id'])}).mappings().first()
        records.append({'batch_id': str(row['id']), 'created_at': row['created_at'].isoformat(), 'status': row['status'],
            'targets': request.get('targets'), 'has_parent': bool(request.get('reference_question_id')),
            'reference_length': len(request.get('reference_text') or ''),
            'reference_source_kind': (request.get('reference_source') or {}).get('kind'),
            'requested': result.get('requested'), 'saved_count': len(result.get('question_ids', [])),
            'failures': result.get('failures'), 'provider_error': result.get('provider_error'),
            'failure_stage': result.get('failure_stage'), 'calls': result.get('calls'),
            'request_instruction': request.get('user_requirement'),
            'original_message': source['original_message'] if source else None,
            'conversation_instruction': ((source['metadata'] or {}).get('generation_context') or {}).get('instruction') if source else None})
    sessions = []
    for session in ([] if args.skip_sessions else db.execute(text("SELECT id, title, purpose, mode, study_date FROM chat_sessions WHERE archived_at IS NULL ORDER BY updated_at DESC LIMIT 30")).mappings()):
        messages = db.execute(text('SELECT metadata FROM chat_messages WHERE session_id=:sid ORDER BY seq LIMIT 200'),{'sid':session['id']}).scalars().all()
        contexts = [((m or {}).get('study_context') or {}) for m in messages]
        sessions.append({'id':str(session['id']),'title':session['title'],'purpose':session['purpose'],'mode':session['mode'],
            'study_date':session['study_date'],'message_count':len(messages),
            'surfaces':sorted({c.get('surface') for c in contexts if c.get('surface')}),
            'has_explicit_handoff':any((m or {}).get('qa_handoff') or (m or {}).get('deep_qa_request_key') for m in messages)})
    db.rollback()
out.mkdir(parents=True, exist_ok=True)
(out / 'existing-batches-readonly.json').write_text(json.dumps({'identity': identity, 'records': records}, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'identity': identity, 'records': records}, ensure_ascii=False, indent=2))
(out / 'existing-sessions-readonly.json').write_text(json.dumps({'sessions':sessions},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'sessions':sessions},ensure_ascii=False,indent=2))
engine.dispose()
