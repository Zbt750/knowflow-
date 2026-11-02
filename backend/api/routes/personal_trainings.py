from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.api.deps import get_db, get_time_provider
from backend.errors import AppError
from backend.schemas.personal_training import (
    PersonalTrainingAction,
    PersonalTrainingAnswer,
    PersonalTrainingAppend,
    PersonalTrainingCreate,
    PersonalTrainingDraft,
    PersonalTrainingNext,
)
from backend.services.personal_training_service import (
    PersonalTrainingError,
    append_training_questions,
    create_next_training,
    create_training,
    list_trainings,
    read_training,
    submit_training_answer,
    save_training_draft,
    training_report,
    transition_training,
)

router = APIRouter(tags=["personal-training"])


# 临时停用专项练习（2026-11-02）：只关闭 API 入口，保留实现与历史数据，便于恢复。
def _disabled():
    raise AppError("personal_training_disabled", status_code=409)


router.dependencies = [Depends(_disabled)]


def _write(call, db: Session):
    try:
        result = call()
        db.commit()
        return result
    except PersonalTrainingError as exc:
        db.rollback()
        raise AppError(exc.code, status_code=exc.status_code) from exc
    except ValueError as exc:
        db.rollback()
        message = str(exc)
        if message == "selected_option_invalid":
            raise AppError("personal_training_answer_invalid", status_code=422) from exc
        raise AppError("personal_training_request_invalid", status_code=422) from exc
    except IntegrityError as exc:
        db.rollback()
        raise AppError("personal_training_idempotency_conflict", status_code=409) from exc


def _translate(call):
    try:
        return call()
    except PersonalTrainingError as exc:
        raise AppError(exc.code, status_code=exc.status_code) from exc


@router.post("/practice-trainings", status_code=201)
def create(body: PersonalTrainingCreate, db: Session = Depends(get_db), clock=Depends(get_time_provider)):
    return _write(lambda: create_training(db, owner_session_id=body.owner_session_id,
        request_key=body.request_key, title=body.title, kp_ids=body.knowledge_point_ids,
        question_count=body.question_count, target_minutes=body.target_minutes,
        difficulty=body.difficulty, question_type=body.question_type,
        selection_basis=body.basis, question_ids=body.question_ids, now=clock()), db)


@router.get("/practice-trainings")
def list_owned(owner_session_id: UUID, db: Session = Depends(get_db)):
    return _translate(lambda: list_trainings(db, owner_session_id=owner_session_id))


@router.get("/practice-trainings/{training_id}")
def read(training_id: UUID, owner_session_id: UUID, db: Session = Depends(get_db)):
    return _translate(lambda: read_training(db, training_id=training_id, owner_session_id=owner_session_id))


@router.post("/practice-trainings/{training_id}/items")
def append(training_id: UUID, body: PersonalTrainingAppend,
           db: Session = Depends(get_db), clock=Depends(get_time_provider)):
    return _write(lambda: append_training_questions(db, training_id=training_id,
        owner_session_id=body.owner_session_id, request_key=body.request_key,
        expected_version=body.expected_version, question_count=body.question_count, now=clock()), db)


def _transition(training_id: UUID, body: PersonalTrainingAction, action: str,
                 db: Session, now):
    return _write(lambda: transition_training(db, training_id=training_id,
        owner_session_id=body.owner_session_id, request_key=body.request_key,
        expected_version=body.expected_version, action=action, now=now), db)


@router.post("/practice-trainings/{training_id}/pause")
def pause(training_id: UUID, body: PersonalTrainingAction,
          db: Session = Depends(get_db), clock=Depends(get_time_provider)):
    return _transition(training_id, body, "pause", db, clock())


@router.post("/practice-trainings/{training_id}/resume")
def resume(training_id: UUID, body: PersonalTrainingAction,
           db: Session = Depends(get_db), clock=Depends(get_time_provider)):
    return _transition(training_id, body, "resume", db, clock())


@router.post("/practice-trainings/{training_id}/finish")
def finish(training_id: UUID, body: PersonalTrainingAction,
           db: Session = Depends(get_db), clock=Depends(get_time_provider)):
    return _transition(training_id, body, "finish", db, clock())


@router.post("/practice-trainings/{training_id}/items/{item_id}/answers")
def answer(training_id: UUID, item_id: UUID, body: PersonalTrainingAnswer,
           db: Session = Depends(get_db), clock=Depends(get_time_provider)):
    return _write(lambda: submit_training_answer(db, training_id=training_id, item_id=item_id,
        owner_session_id=body.owner_session_id, idempotency_key=body.idempotency_key,
        expected_version=body.expected_version, raw_answer=body.raw_answer,
        selected_option=body.selected_option, now=clock()), db)


@router.patch("/practice-trainings/{training_id}/items/{item_id}/draft")
def save_draft(training_id: UUID, item_id: UUID, body: PersonalTrainingDraft,
               db: Session = Depends(get_db), clock=Depends(get_time_provider)):
    return _write(lambda: save_training_draft(db, training_id=training_id, item_id=item_id,
        owner_session_id=body.owner_session_id,
        expected_draft_revision=body.expected_draft_revision,
        draft_answer=body.draft_answer, draft_selected_option=body.draft_selected_option,
        now=clock()), db)


@router.get("/practice-trainings/{training_id}/report")
def report(training_id: UUID, owner_session_id: UUID, db: Session = Depends(get_db)):
    return _translate(lambda: training_report(db, training_id=training_id, owner_session_id=owner_session_id))


@router.post("/practice-trainings/{training_id}/next", status_code=201)
def next_round(training_id: UUID, body: PersonalTrainingNext,
               db: Session = Depends(get_db), clock=Depends(get_time_provider)):
    return _write(lambda: create_next_training(db, training_id=training_id,
        owner_session_id=body.owner_session_id, request_key=body.request_key,
        question_count=body.question_count, target_minutes=body.target_minutes, now=clock()), db)
