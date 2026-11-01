from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Request, Depends, Query
from sqlalchemy import select
from backend.api.deps import get_db, get_time_provider
from backend.errors import AppError
from backend.models.learning import Question
from backend.models.personal_generation import PersonalGenerationBatch
from backend.schemas.personal_questions import PersonalGenerationRequest, HiddenRequest, PersonalAppendRequest
from backend.services.personal_question_service import run_generation, bank_rows, append_personal, result_message
from backend.services.generation_diagnostics import with_diagnostics
from backend.services.generation_outcomes import with_outcomes
from backend.services.question_generation import (configured_provider, Budget, GENERATION_OUTPUT_LIMIT,
    PERSONAL_C6_OUTPUT_LIMIT, PERSONAL_C7_OUTPUT_LIMIT)

router = APIRouter(tags=["personal-questions"])


@router.get("/question-bank")
def read_bank(scope: Literal["public","personal"] = "personal", kp_id: UUID | None = None,
              search: str = Query(default="", max_length=100), include_hidden: bool = False,
              limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0), db=Depends(get_db)):
    return bank_rows(db, scope=scope, kp_id=kp_id, search=search, include_hidden=include_hidden, limit=limit, offset=offset)


@router.post("/personal-questions/generate")
def generate_questions(request: Request, body: PersonalGenerationRequest, clock=Depends(get_time_provider)):
    # Provider injection is shared by API and assistant. Never automatic stock fallback.
    provider = getattr(request.app.state, "personal_generation_provider", None)
    if body.generation_mode == "deterministic_fast":
        provider = None
    elif provider is None:
        output_limit = (PERSONAL_C7_OUTPUT_LIMIT if body.generation_mode == "ai_generated" else
                        GENERATION_OUTPUT_LIMIT if body.reference_question_id else PERSONAL_C6_OUTPUT_LIMIT)
        try: provider = configured_provider(request.app.state.settings,
                Budget(max_calls=5, max_output_tokens=output_limit), real_call_authorized=True)
        except ValueError as exc: raise AppError("llm_not_configured") from exc
    return run_generation(request.app.state.session_factory, body, provider, now=clock())


@router.get("/personal-questions/batches/{request_key}")
def batch_status(request_key: UUID, db=Depends(get_db)):
    row = db.scalar(select(PersonalGenerationBatch).where((PersonalGenerationBatch.request_key == str(request_key)) | (PersonalGenerationBatch.id == request_key)))
    if not row: raise AppError("question_not_found", status_code=404)
    result={**row.result,'status':row.status}
    from backend.services.today_append_result import read_append_result
    result['append_results']=[value for receipt in (result.get('append_operations') or {}).values()
        if (value:=read_append_result(db,**receipt)) is not None]
    return {**with_outcomes(with_diagnostics(result)), "batch_id": str(row.id), "status": row.status, "message": result_message(result)}


@router.patch("/personal-questions/{question_id}/visibility")
def hide(question_id: UUID, body: HiddenRequest, db=Depends(get_db)):
    q = db.get(Question, question_id, with_for_update=True)
    if not q or q.bank_scope != "personal": raise AppError("question_not_found", status_code=404)
    q.is_hidden = body.hidden
    db.commit()
    return {"id": str(q.id), "hidden": q.is_hidden}


@router.post("/personal-questions/append")
def append(request: Request, body: PersonalAppendRequest, clock=Depends(get_time_provider)):
    try: return append_personal(request.app.state.session_factory, question_ids=body.question_ids, plan_id=body.plan_id, now=clock())
    except ValueError as exc:
        if str(exc) == "plan_not_today": raise AppError("plan_not_today", status_code=409) from exc
        if str(exc) == "plan_already_generated": raise AppError("plan_already_generated", status_code=409) from exc
        raise AppError("question_not_practice_eligible", status_code=409) from exc
