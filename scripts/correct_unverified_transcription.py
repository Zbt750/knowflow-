"""Snapshot-bound AI content correction; default preview, never verification."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.config import get_settings
from backend.db import create_db_engine, create_session_factory
from backend.models.learning import KnowledgePoint, Question
from backend.services.golden_learning_slice import digest
from backend.services.question_answer_revision import revise_transcription_content
from backend.services.question_pack import QuestionPack, _source_dump, fingerprint
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
    if (draft.get('version') != 'source-transcription-correction-v2'
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
                    or row.question_type != draft.get('question_type')):
                raise ValueError('Draft source identity, mapping or source hash differs from target')
            citation = provenance.get('source', {}).get('citation', '')
            source_pdf_sha256 = draft.get('source_pdf_sha256', '')
            if not re.fullmatch(r'[a-f0-9]{64}', draft.get('supersedes_source_transcription_sha256', '')):
                raise ValueError('Previous transcription fingerprint is required for the correction chain')
            source_pdf = Path(draft.get('source_pdf_path', '')).expanduser().resolve(strict=True)
            if (source_pdf.suffix.lower() != '.pdf' or not source_pdf.is_file()
                    or source_pdf.stat().st_size > 50 * 1024 * 1024
                    or not isinstance(draft.get('source_page'), int) or draft['source_page'] < 1
                    or source_pdf.name not in citation):
                raise ValueError('Correction PDF must be a bounded PDF named in the saved source citation')
            hasher = hashlib.sha256()
            with source_pdf.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    hasher.update(chunk)
            if hasher.hexdigest() != source_pdf_sha256:
                raise ValueError('Correction PDF SHA-256 changed; regenerate the review draft')
            transcription_path = (ROOT / draft.get('source_transcription_path', '')).resolve(strict=True)
            correction_root = (ROOT / 'storage/answer-trust').resolve()
            if (not transcription_path.is_relative_to(correction_root) or not transcription_path.is_file()
                    or transcription_path.stat().st_size > 1024 * 1024):
                raise ValueError('Corrected transcription must be a bounded file inside ignored storage/answer-trust')
            transcription_hasher = hashlib.sha256()
            with transcription_path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    transcription_hasher.update(chunk)
            if transcription_hasher.hexdigest() != draft.get('source_transcription_sha256'):
                raise ValueError('Corrected transcription SHA-256 changed; regenerate the review draft')
            if set(k for k in draft if k.startswith('proposed_')) != {
                'proposed_kp_code', 'proposed_options', 'proposed_pack_version'
            }:
                raise ValueError('This correction draft may change only options and its candidate version')
            source_pack_path = (ROOT / draft.get('source_pack_path', '')).resolve(strict=True)
            intake_root = (ROOT / 'storage/question-intake').resolve()
            if (not source_pack_path.is_relative_to(intake_root) or not source_pack_path.is_file()
                    or source_pack_path.stat().st_size > 16 * 1024 * 1024):
                raise ValueError('Source pack must be a bounded file inside ignored storage/question-intake')
            source_pack_hasher = hashlib.sha256()
            with source_pack_path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    source_pack_hasher.update(chunk)
            if source_pack_hasher.hexdigest() != draft.get('source_pack_sha256'):
                raise ValueError('Source pack SHA-256 changed; regenerate the correction draft')
            source_pack_data = json.loads(source_pack_path.read_text(encoding='utf-8'))
            source_pack = QuestionPack.model_validate(source_pack_data)
            source_key = provenance.get('key', '')
            prefix = f"{source_pack.pack_id}:"
            if not source_key.startswith(prefix):
                raise ValueError('Source pack does not match the imported source identity')
            source_id = source_key[len(prefix):]
            original = next((item for item in source_pack.questions if item.source_id == source_id), None)
            if (original is None or source_pack.version != (row.grading_config or {}).get('version')
                    or fingerprint(original) != provenance.get('sha256')
                    or original.kp_code != node.code
                    or _source_dump(original.source) != provenance.get('source')
                    or any(getattr(row, field) != getattr(original, field) for field in (
                        'question_type', 'stem', 'options', 'correct_answer', 'explanation',
                        'question_role', 'difficulty', 'skill_tags', 'estimated_minutes', 'is_variant'))):
                raise ValueError('Stored question no longer matches its exact imported source-pack version')
            corrected_pack_data = json.loads(source_pack_path.read_text(encoding='utf-8'))
            corrected_item = next(item for item in corrected_pack_data['questions']
                                  if item.get('source_id') == source_id)
            corrected_item['options'] = draft['proposed_options']
            corrected_pack = QuestionPack.model_validate(corrected_pack_data)
            candidate = next(item for item in corrected_pack.questions if item.source_id == source_id)
            proposed_source_pack_sha256 = fingerprint(candidate)
            if proposed_source_pack_sha256 == provenance.get('sha256'):
                raise ValueError('Correction did not produce a new source-pack fingerprint')
            before = snapshot(row)
            changes = {'options': draft['proposed_options']}
            basis = (f"User-reported transcription correction; local PDF visually cross-checked, "
                     f"not a six-aspect human verification; PDF SHA256 {source_pdf_sha256}, "
                     f"page {draft['source_page']}; corrected transcription {draft['source_transcription_path']} "
                     f"SHA256 {draft['source_transcription_sha256']}; supersedes transcription SHA256 "
                     f"{draft['supersedes_source_transcription_sha256']}; source-pack candidate SHA256 "
                     f"{proposed_source_pack_sha256}")
            result = revise_transcription_content(db, qid, args.expected_snapshot_sha256, changes,
                basis=basis, proposed_source_pack_sha256=proposed_source_pack_sha256,
                proposed_pack_version=draft['proposed_pack_version'], apply=args.apply)
            report = {'status': 'prepared_outcome_not_confirmed', 'before': before,
                      'draft_sha256': digest(draft), 'proposed_changes': changes, 'result': result}
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
