import os
import re

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession
from pydantic import BaseModel, field_validator

from app.db.session import get_db
from app.db.models import User, Session as SessionModel, ResumeProfile
from app.auth.dependencies import get_current_session_and_user, touch_session_activity

router = APIRouter(prefix="/api")
# TODO(jiaxin/chuying): This must become the actual pinned/active embedding
# model version once Chuying's processing interface exposes it. Until that
# coordination happens, has_matchable_resume is a stub that always reports
# False rather than guessing — a wrong "true" here would be worse than an
# honest "not yet determinable."
ACTIVE_EMBEDDING_VERSION = os.environ.get("ACTIVE_EMBEDDING_VERSION")


@router.get("/me")
def get_me(
    session_and_user: tuple[SessionModel, User] = Depends(get_current_session_and_user),
    db: DBSession = Depends(get_db),
):
    session_row, user = session_and_user

    profile = db.get(ResumeProfile, user.user_id)
    has_resume = profile is not None

    if has_resume and ACTIVE_EMBEDDING_VERSION:
        has_matchable_resume = profile.embedding_version == ACTIVE_EMBEDDING_VERSION
    else:
        has_matchable_resume = False  # stub — see TODO above

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
    session_and_user: tuple[SessionModel, User] = Depends(get_current_session_and_user),
    db: DBSession = Depends(get_db),
):
    session_row, user = session_and_user

    user.display_name = body.display_name
    db.commit()
    db.refresh(user)

    # This is a genuine user-initiated domain write, unlike GET /me — bump activity.
    touch_session_activity(db, session_row)

    return {
        "user": {"user_id": str(user.user_id), "display_name": user.display_name},
        "resume_revision": user.resume_revision,
    }
