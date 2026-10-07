"""Snapshot-bound AI content correction; default preview, never verification."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.config import get_settings
from backend.db import create_db_engine, create_session_factory
from backend.models.learning import KnowledgePoint, Question
from backend.services.golden_learning_slice import digest
from backend.services.question_answer_revision import revise_transcription_content
from backend.services.question_verification_upgrade import snapshot, source_identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("draft", type=Path)
    parser.add_argument("--question-id", required=True)
    parser.add_argument("--expected-snapshot-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    from uuid import UUID
    qid = UUID(args.question_id)
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to((ROOT / 'eval/reports').resolve()):
        parser.error('Use a new local eval/reports output; never overwrite prior evidence')
    if args.draft.stat().st_size > 1024*1024:
        parser.error('Draft exceeds bounded size')
    draft = json.loads(args.draft.read_text(encoding='utf-8'))
    if (draft.get('version') != 'ai-source-correction-draft-v1'
            or any(draft.get(k) is not False for k in ('verified', 'can_import', 'human_review_confirmed', 'database_written'))):
        parser.error('Only explicit unverified AI correction drafts allowed')
    settings = get_settings()
    if settings.app_env != 'dev':
        parser.error('This maintainer command requires the development profile')
    engine = create_db_engine(str(settings.active_database_url))
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with create_session_factory(engine)() as db:
            row = db.get(Question, qid)
            if row is None:
                raise ValueError('Target missing')
            node = db.get(KnowledgePoint, row.kp_id)
            provenance = (row.grading_config or {}).get('provenance', {})
            subject, kind, year, number = source_identity(provenance.get('source', {}))
            candidate_id = f'{subject}-{year}-q{number:03d}' if isinstance(number, int) else None
            if (candidate_id != draft.get('candidate_id') or kind != 'exam'
                    or node.code != draft.get('proposed_kp_code')
                    or row.question_type != draft.get('question_type')
                    or draft.get('source_pdf_sha256', 'missing') not in provenance.get('source', {}).get('citation', '')):
                raise ValueError('Draft source identity, mapping or source hash differs from target')
            before = snapshot(row)
            changes = {k: draft[f'proposed_{k}'] for k in ('stem', 'correct_answer', 'explanation')}
            basis = f"AI local PDF comparison (not human verification); SHA256 {draft['source_pdf_sha256']}, page {draft['source_page']}"
            result = revise_transcription_content(db, qid, args.expected_snapshot_sha256, changes, basis=basis, apply=args.apply)
            report = {'status': 'prepared_outcome_not_confirmed', 'before': before,
                      'draft_sha256': digest(draft), 'result': result}
            # Reserve a new report before commit. A crash here must not be
            # misreported as committed; inspect DB before any fresh command.
            with output.open('x', encoding='utf-8') as target:
                json.dump(report, target, ensure_ascii=False, indent=2)
            if args.apply:
                db.commit()
            else:
                db.rollback()
            report['status'] = 'applied_unverified' if args.apply else 'preview_no_database_write'
            report['after_snapshot_sha256'] = digest(snapshot(db.get(Question, qid)))
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'status': report['status'], 'corrected': result['corrected'], 'verified_upgrades': 0}))
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
