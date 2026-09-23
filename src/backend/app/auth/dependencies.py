import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Request
from sqlalchemy.orm import Session as DBSession
from app.db.session import get_db
from app.db.models import Session as SessionModel, User
from app.auth import security
from app.core.config import settings
from app.core.errors import api_error

def get_current_session_and_user(
    request: Request,
    db: DBSession = Depends(get_db),
) -> tuple[SessionModel, User]:
    cookie_name = security.session_cookie_name()
    raw_token = request.cookies.get(cookie_name)
    if not raw_token:
        raise api_error(401, "AUTH_REQUIRED", "Sign in to continue.")

    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    session_row = db.get(SessionModel, token_hash)
    if session_row is None:
        raise api_error(401, "AUTH_REQUIRED", "Sign in to continue.")

    now = datetime.now(timezone.utc)
    if session_row.expires_at <= now:
        raise api_error(401, "SESSION_EXPIRED", "Your session has expired.")

    idle_cutoff = session_row.last_active_at + security.SESSION_IDLE_LIFETIME
    if now > idle_cutoff:
        raise api_error(401, "SESSION_EXPIRED", "Your session has expired.")

    user = db.get(User, session_row.user_id)
    if user is None:
        raise api_error(401, "AUTH_REQUIRED", "Sign in to continue.")

    return session_row, user


def touch_session_activity(db: DBSession, session_row: SessionModel) -> None:
    """Bump last_active_at, throttled to once/minute. Call ONLY from
    qualifying user-initiated domain reads/writes (per contract) —
    never from /health, auth bootstrap, /me, or operation-status checks."""
    now = datetime.now(timezone.utc)
    if (now - session_row.last_active_at) >= timedelta(minutes=1):
        session_row.last_active_at = now
        db.commit()


def touch_session_activity_by_token(db: DBSession, token_hash: str) -> None:
    """Refresh activity after a long-running operation using a fresh short transaction.

    Callers that spent time outside the database transaction must retain only the
    immutable token hash across that boundary.  The ORM session row may have been
    expired by rollback, so reusing it would trigger an implicit transaction.
    """
    session_row = db.get(SessionModel, token_hash)
    if session_row is None:
        return
    try:
        touch_session_activity(db, session_row)
    finally:
        if db.in_transaction():
            db.rollback()
def validate_unsafe_request(request: Request, session_row) -> None:
    origin = request.headers.get("origin")
    if origin != settings.app_origin:
        raise api_error(403, "CSRF_INVALID", "Origin not allowed.")

    csrf_header = request.headers.get("x-csrf-token")
    if not csrf_header or not security.constant_time_eq(csrf_header, session_row.csrf_token):
        raise api_error(403, "CSRF_INVALID", "CSRF token missing or mismatched.")
