"""Six inspected synthetic photos, actual multipart endpoint, at most two text reviews.

Requires explicit live authorization. Never retries or sends private development data.
"""
from __future__ import annotations
import argparse
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def select_cases(dataset, identifiers, skip_reviews=False):
    available = {case['id']: case for case in dataset['cases']}
    selected = identifiers or list(available)
    if len(selected) != len(set(selected)) or any(key not in available for key in selected):
        raise ValueError('Unknown or duplicate synthetic case identifier')
    return [dict(available[key], review=False if skip_reviews else bool(available[key].get('review')))
            for key in selected]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--allow-synthetic-images', action='store_true')
    parser.add_argument('--samples', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--case', action='append', dest='case_ids', help='Select an existing fixture; repeat as needed')
    parser.add_argument('--skip-reviews', action='store_true', help='Only transcribe; no text review model calls')
    args = parser.parse_args()
    if not args.live or not args.allow_synthetic_images:
        parser.error('Explicit --live --allow-synthetic-images required after human authorization')
    if args.output.exists():
        parser.error('Refuse to overwrite an existing report')
    dataset = json.loads((ROOT / 'eval/photo-handwriting-v1.json').read_text(encoding='utf-8'))
    if len(dataset['cases']) != 6 or sum(bool(c.get('review')) for c in dataset['cases']) > 2:
        parser.error('Authorization budget exceeded')
    try:
        selected_cases = select_cases(dataset, args.case_ids, args.skip_reviews)
    except ValueError as error:
        parser.error(str(error))
    from backend.config import get_settings
    from backend.services.model_settings_service import load_local_settings
    from backend.services.vision_settings_service import effective_vision_settings
    from backend.services.vision_recognition_service import normalized_image, PROMPT_VERSION
    from backend.errors import AppError, register_error_handlers
    from backend.chat.service import provider_from_settings
    from backend.api.routes import study
    from backend.models.learning import KnowledgePoint, KpState, Question, DailyPlan, PracticeItem, QuestionAttempt, LearningEvent
    from scripts.run_learning_agent_eval import isolated_factory
    from sqlalchemy import func, select
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    dev = load_local_settings(get_settings())
    if not dev.test_database_url:
        parser.error('TEST_DATABASE_URL required; never use development database')
    effective = effective_vision_settings(dev)
    # Preflight ALL images before any external model request.
    images = {}
    for case in selected_cases:
        path = args.samples / (case['id'] + '.png')
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != dataset['image_sha256'].get(case['id']):
            parser.error('Image does not match the inspected synthetic fixture; refuse to send')
        normalized_image(data)
        images[case['id']] = data
    report = {'dataset_version':dataset['version'], 'synthetic_only':True,
              'prompt_version':PROMPT_VERSION, 'vision_model':effective.llm_model,
              'vision_endpoint_host':urlsplit(effective.llm_base_url).hostname,
              'review_model':dev.llm_model, 'vision_output_budget':min(effective.llm_max_output_tokens,4000),
              'timeout_seconds':min(effective.llm_timeout_seconds,60),
              'max_recognition_requests':len(selected_cases),
              'max_review_requests':sum(c['review'] for c in selected_cases),
              'selected_case_ids':[c['id'] for c in selected_cases], 'automatic_retry':False,
              'cases':[], 'complete':False, 'database_cleanup_completed':False,
              'quality_claim':'Human comparison required; no aggregate accuracy claim from a small synthetic sample.'}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    def save():
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    save()
    provider = provider_from_settings(dev)
    class OnceProvider:
        model = provider.model
        def complete(self, messages, *, attempt=1):
            if attempt != 1: raise AppError('generation_failed')
            try: return provider.complete(messages, attempt=1)
            except Exception: raise AppError('generation_failed', retryable=False) from None
    previous_provider_factory = study.provider_from_settings
    study.provider_from_settings = lambda settings: OnceProvider()
    try:
        with isolated_factory(str(dev.test_database_url)) as factory:
            @asynccontextmanager
            async def lifespan(app):
                app.state.settings = dev
                app.state.session_factory = factory
                yield
            app = FastAPI(lifespan=lifespan)
            register_error_handlers(app)
            app.include_router(study.router,prefix='/api')
            with TestClient(app) as client:
                for index, case in enumerate(selected_cases):
                    with factory.begin() as db:
                        kp = KnowledgePoint(code='photo.eval.'+case['id'],name='合成照片'+case['id'],subject='合成')
                        db.add(kp); db.flush(); db.add(KpState(kp_id=kp.id))
                        question = Question(kp_id=kp.id,question_type=case['type'],stem=case['stem'],
                                            correct_answer=None,explanation='合成未核验题，非正式题库',estimated_minutes=10)
                        plan = DailyPlan(study_date=f'2099-02-{index+1:02d}',status='active')
                        db.add_all([question,plan]); db.flush()
                        item = PracticeItem(plan_id=plan.id,question_id=question.id,kp_id=kp.id,ordinal=1)
                        db.add(item); db.flush(); item_id,kp_id = item.id,kp.id
                    record = {'id':case['id'],'image_sha256':hashlib.sha256(images[case['id']]).hexdigest(),
                              'visible_reference':case['visible_reference'],'human_review':None}
                    report['cases'].append(record); save()
                    started = time.monotonic()
                    response = client.post(f'/api/practice-items/{item_id}/recognize-work',
                        data={'consent':'true'},files={'file':(case['id']+'.png',images[case['id']],'image/png')})
                    record.update(status=response.status_code,total_latency_ms=round((time.monotonic()-started)*1000),response=response.json())
                    with factory() as db:
                        record['recognition_no_writes'] = (db.scalar(select(func.count()).select_from(LearningEvent)) == sum('review' in r and r['review']['status']==200 for r in report['cases'])
                                                           and db.scalar(select(func.count()).select_from(QuestionAttempt)) == 0
                                                           and db.get(PracticeItem,item_id).completed_at is None)
                    save(); print(f"{case['id']}: recognition HTTP {response.status_code}",flush=True)
                    if response.status_code != 200:
                        report['stopped_after_error']=case['id']; break
                    if case.get('review'):
                        # This automation confirms exact returned text without editing it. Human review follows.
                        result = client.post(f'/api/practice-items/{item_id}/process-reviews',json={
                            'work_text':response.json()['text'],'subjective_kind':case.get('subjective_kind'),
                            'idempotency_key':'photo-synthetic-'+case['id']+'-'+uuid4().hex})
                        record['review']={'status':result.status_code,'response':result.json(),
                                          'expected_points':case['review_points']}
                        with factory() as db:
                            event=db.scalar(select(LearningEvent).where(LearningEvent.source_id==item_id))
                            record['review']['trace']=event.payload.get('model_trace') if event else None
                            record['review']['no_objective_evidence']=(db.scalar(select(func.count()).select_from(QuestionAttempt))==0
                                and db.get(KpState,kp_id).evidence_window==[] and db.get(PracticeItem,item_id).completed_at is None)
                        save(); print(f"{case['id']}: review HTTP {result.status_code}",flush=True)
        report['database_cleanup_completed']=True
        report['complete']=len(report['cases'])==len(selected_cases) and all(c['status']==200 for c in report['cases'])
        save()
    finally:
        study.provider_from_settings=previous_provider_factory
        save()
    print('Report: '+str(args.output),flush=True)
    return 0 if report['complete'] else 1


if __name__=='__main__': raise SystemExit(main())
