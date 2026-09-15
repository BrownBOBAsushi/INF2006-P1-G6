import os

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession

from app.db.session import get_db
from app.db.models import User, Session as SessionModel, ResumeProfile
from app.auth.dependencies import get_current_session_and_user

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