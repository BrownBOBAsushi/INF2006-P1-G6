import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session as DBSession

from app.db.session import get_db
from app.db.models import Session as SessionModel, User
from app.auth import security


def get_current_session_and_user(
    request: Request,
    db: DBSession = Depends(get_db),
) -> tuple[SessionModel, User]:
    cookie_name = security.session_cookie_name()
    raw_token = request.cookies.get(cookie_name)
    if not raw_token:
        raise HTTPException(status_code=401, detail={"code": "AUTH_REQUIRED"})

    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    session_row = db.get(SessionModel, token_hash)
    if session_row is None:
        raise HTTPException(status_code=401, detail={"code": "AUTH_REQUIRED"})

    now = datetime.now(timezone.utc)
    if session_row.expires_at <= now:
        raise HTTPException(status_code=401, detail={"code": "SESSION_EXPIRED"})

    idle_cutoff = session_row.last_active_at + security.SESSION_IDLE_LIFETIME
    if now > idle_cutoff:
        raise HTTPException(status_code=401, detail={"code": "SESSION_EXPIRED"})

    user = db.get(User, session_row.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail={"code": "AUTH_REQUIRED"})

    return session_row, user


def touch_session_activity(db: DBSession, session_row: SessionModel) -> None:
    """Bump last_active_at, throttled to once/minute. Call ONLY from
    qualifying user-initiated domain reads/writes (per contract) —
    never from /health, auth bootstrap, /me, or operation-status checks."""
    now = datetime.now(timezone.utc)
    if (now - session_row.last_active_at) >= timedelta(minutes=1):
        session_row.last_active_at = now
        db.commit()