"""Homepage workflow guard and compatibility import for the shared planner view."""
from backend.errors import AppError
from backend.models.learning_task import LearningTask
from backend.services.planning_public_view import public_task


def reject_generic_home_mutation(factory, task_id):
    with factory() as db:
        row = db.get(LearningTask, task_id)
        if row is not None and (row.context or {}).get('home_recommendation'):
            raise AppError('home_planning_workflow_required', status_code=409,
                           detail='Use the session-bound homepage planning and confirmation workflow')
