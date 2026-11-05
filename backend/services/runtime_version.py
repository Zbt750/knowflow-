"""Non-secret process snapshot, captured once when the app is constructed."""
import hashlib
import marshal
import os
from datetime import datetime, timezone
from pathlib import Path

SOURCE_FILES = (
    'backend/app.py', 'backend/api/routes/study.py',
    'backend/services/home_recommendation_service.py',
    'backend/services/home_intent.py',
    'backend/services/bank_selection_intent.py',
    'backend/services/learning_task_tools.py',
    'backend/services/learning_task_service.py',
    'backend/services/practice_service.py',
    'backend/services/study_preview_revision.py', 'backend/services/composite_bank_plan.py',
    'backend/schemas/learning_task.py', 'backend/schemas/home_recommendation.py',
    'backend/services/runtime_version.py', 'backend/api/routes/health.py',
)


def capture_runtime_version(root=None):
    from backend.services import home_recommendation_service as home
    from backend.services.bank_selection_intent import bank_selection_request
    from backend.schemas.learning_task import PaperValidation, ValidatePlan
    from backend.schemas.home_recommendation import HomePaperValidation
    from backend.services import practice_service as practice
    from backend.services import home_intent
    root = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    files = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
             for name in SOURCE_FILES if (root / name).is_file()}
    functions = {'home_manual_scope_paper':home._manual_scope_paper,
                 'home_adjust':home.adjust,'home_paper':home._paper,
                 'home_bank_candidates': home._bank_candidates,
                 'home_confirm': home.confirm, 'bank_intent': bank_selection_request,
                 'home_intent_resolve':home_intent.resolve,'home_intent_validate':home_intent.validate,
                 'formal_preview': practice.preview_initial_questions,
                 'formal_candidate_order': practice._order_paper_items}
    code = {name: hashlib.sha256(marshal.dumps(fn.__code__)).hexdigest()
            for name, fn in functions.items()}
    models = {'whole_paper': PaperValidation, 'home_paper': HomePaperValidation,
              'chat_tool': ValidatePlan}
    return {'diagnostic_version': 'home-contract-runtime-v1', 'pid': os.getpid(),
            'captured_at': datetime.now(timezone.utc).isoformat(),
            'source_hashes_at_app_creation': files, 'loaded_function_hashes': code,
            'loaded_question_id_limits': {
                name: model.model_json_schema()['properties']['question_ids'].get('maxItems')
                for name, model in models.items()},
            'home_loaded_parameter_model': 'HomePaperValidation'
                if 'HomePaperValidation' in home._bank_candidates.__code__.co_names else 'unknown'}
