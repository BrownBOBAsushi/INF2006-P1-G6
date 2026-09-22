from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import select

from app.db.session import get_db
from app.db.models import User, Session as SessionModel, ResumeProfile, SaveOperation
from app.auth.dependencies import (
    get_current_session_and_user,
    touch_session_activity,
    validate_unsafe_request,
)
from app.core.errors import api_error
from app.api.me import ACTIVE_EMBEDDING_VERSION  # shared stub, see TODO in me.py

router = APIRouter(prefix="/api")


@router.get("/resume")
def get_resume(
    session_and_user: tuple[SessionModel, User] = Depends(get_current_session_and_user),
    db: DBSession = Depends(get_db),
):
    session_row, user = session_and_user

    profile = db.get(ResumeProfile, user.user_id)
    if profile is None:
        raise api_error(404, "RESUME_NOT_FOUND", "No resume has been saved yet.")

    has_matchable_resume = (
        bool(ACTIVE_EMBEDDING_VERSION)
        and profile.embedding_version == ACTIVE_EMBEDDING_VERSION
    )

    touch_session_activity(db, session_row)

    return {
        "revision": profile.revision,
        "content": profile.content,
        "embedding_version": profile.embedding_version,
        "has_matchable_resume": has_matchable_resume,
    }


class DeleteResumeRequest(BaseModel):
    expected_revision: int


@router.delete("/resume")
def delete_resume(
    body: DeleteResumeRequest,
    request: Request,
    session_and_user: tuple[SessionModel, User] = Depends(get_current_session_and_user),
    db: DBSession = Depends(get_db),
):
    session_row, user = session_and_user
    validate_unsafe_request(request, session_row)

    # Lock the users row for the duration of this check-and-update.
    locked_user = db.execute(
        select(User).where(User.user_id == user.user_id).with_for_update()
    ).scalar_one()

    if locked_user.resume_revision != body.expected_revision:
        raise api_error(409, "REVISION_CONFLICT", "Resume has changed since you last saw it.")

    profile = db.get(ResumeProfile, user.user_id)
    if profile is None:
        # Nothing to delete; revision already matches what caller expected.
        db.commit()
        touch_session_activity(db, session_row)
        return {"resume_revision": locked_user.resume_revision, "has_resume": False}

    db.delete(profile)  # cascades to resume_chunks via ON DELETE CASCADE
    locked_user.resume_revision += 1
    db.commit()

    touch_session_activity(db, session_row)

    return {"resume_revision": locked_user.resume_revision, "has_resume": False}


@router.get("/resume/operations/{operation_id}")
def get_resume_operation(
    operation_id: str,
    session_and_user: tuple[SessionModel, User] = Depends(get_current_session_and_user),
    db: DBSession = Depends(get_db),
):
    session_row, user = session_and_user

    op = db.get(SaveOperation, {"user_id": user.user_id, "operation_id": operation_id})
    if op is None or op.expires_at <= datetime.now(timezone.utc):
        raise api_error(404, "OPERATION_EXPIRED", "This operation is no longer available.")

    # Explicitly no touch_session_activity here — operation-status checks
    # are excluded from extending inactivity per the contract.
    return {
        "operation_id": str(op.operation_id),
        "state": op.state,
        "result_revision": op.result_revision,
        "failure_code": op.failure_code,
    }