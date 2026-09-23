import re

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session as DBSession
from pydantic import BaseModel, field_validator
from sqlalchemy import select

from app.db.session import get_db
from app.db.models import User, Session as SessionModel, ResumeChunk, ResumeProfile
from app.auth.dependencies import get_current_session_and_user, touch_session_activity, validate_unsafe_request
from app.processing.config import EMBEDDING_VERSION

router = APIRouter(prefix="/api")
# Keep this value coupled to the processing worker's pinned model contract so
# the UI only advertises matching when current chunks use the active version.
ACTIVE_EMBEDDING_VERSION = EMBEDDING_VERSION


@router.get("/me")
def get_me(
    session_and_user: tuple[SessionModel, User] = Depends(get_current_session_and_user),
    db: DBSession = Depends(get_db),
):
    session_row, user = session_and_user

    profile = db.get(ResumeProfile, user.user_id)
    has_resume = profile is not None

    if has_resume:
        has_matchable_resume = profile.embedding_version == ACTIVE_EMBEDDING_VERSION and db.execute(
            select(ResumeChunk.chunk_id).where(
                ResumeChunk.user_id == user.user_id,
                ResumeChunk.profile_revision == profile.revision,
                ResumeChunk.embedding_version == ACTIVE_EMBEDDING_VERSION,
            ).limit(1)
        ).first() is not None
    else:
        has_matchable_resume = False

    return {
        "user": {"user_id": str(user.user_id), "display_name": user.display_name},
        "resume_revision": user.resume_revision,
        "has_resume": has_resume,
        "has_matchable_resume": has_matchable_resume,
        "csrf_token": session_row.csrf_token,
    }
class UpdateDisplayNameRequest(BaseModel):
    display_name: str

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, v: str) -> str:
        trimmed = v.strip()
        if not (1 <= len(trimmed) <= 100):
            raise ValueError("display_name must be 1-100 characters after trimming")
        if re.search(r"[\x00-\x1f\x7f]", trimmed):
            raise ValueError("display_name must not contain control characters")
        return trimmed


@router.patch("/me")
def update_me(
    body: UpdateDisplayNameRequest,
    request: Request,
    session_and_user: tuple[SessionModel, User] = Depends(get_current_session_and_user),
    db: DBSession = Depends(get_db),
):
    session_row, user = session_and_user
    validate_unsafe_request(request, session_row)

    user.display_name = body.display_name
    db.commit()
    db.refresh(user)

    # This is a genuine user-initiated domain write, unlike GET /me — bump activity.
    touch_session_activity(db, session_row)

    return {
        "user": {"user_id": str(user.user_id), "display_name": user.display_name},
        "resume_revision": user.resume_revision,
    }
