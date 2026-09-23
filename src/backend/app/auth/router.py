from fastapi import APIRouter, Depends, Request, Response, Header
from datetime import datetime, timezone
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import select
import hashlib
from app.db.session import get_db
from app.db.models import User, Session as SessionModel
from app.core.config import settings
from app.auth import security
from app.auth.google_verify import verify_google_credential, InvalidGoogleCredential
from app.core.errors import api_error
from app.auth.dependencies import validate_unsafe_request

router = APIRouter(prefix="/api/auth")

BOOTSTRAP_COOKIE_NAME = "pre_login"


def _validate_origin(request: Request):
    origin = request.headers.get("origin")
    if origin != settings.app_origin:
        raise api_error(403, "CSRF_INVALID", "Origin not allowed.")


@router.get("/bootstrap")
def bootstrap(response: Response):
    nonce, signed = security.issue_bootstrap_nonce()
    response.set_cookie(
        key=BOOTSTRAP_COOKIE_NAME,
        value=signed,
        httponly=True,
        secure=not settings.is_dev,
        samesite="lax",
        path="/",
        max_age=security.BOOTSTRAP_MAX_AGE_SECONDS,
    )
    return {"csrf_token": nonce}


@router.post("/google")
def google_exchange(
    request: Request,
    response: Response,
    body: dict,
    x_csrf_token: str = Header(..., alias="X-CSRF-Token"),
    db: DBSession = Depends(get_db),
):
    _validate_origin(request)

    signed_cookie = request.cookies.get(BOOTSTRAP_COOKIE_NAME)
    if not signed_cookie:
        raise api_error(401, "AUTH_REQUIRED", "Sign in to continue.")

    nonce = security.verify_bootstrap_cookie(signed_cookie)
    if not nonce or not security.constant_time_eq(nonce, x_csrf_token):
        raise api_error(403, "CSRF_INVALID", "CSRF token missing or mismatched.")

    credential = body.get("credential")
    if not credential:
        raise api_error(400, "BAD_REQUEST", "A Google credential is required.")

    try:
        sub = verify_google_credential(credential)
    except InvalidGoogleCredential:
        raise api_error(401, "AUTH_REQUIRED", "Google sign-in could not be verified.")
    finally:
        credential = None  # erase reference; nothing persists it

    # Find or create user by verified sub
    user = db.execute(select(User).where(User.google_sub == sub)).scalar_one_or_none()
    if user is None:
        user = User(google_sub=sub)
        db.add(user)
        db.flush()  # get user_id without committing yet

    # Rotate session: revoke the incoming application session before issuing a new one.
    incoming = request.cookies.get(security.session_cookie_name())
    if incoming:
        old_hash = hashlib.sha256(incoming.encode()).hexdigest()
        old_session = db.get(SessionModel, old_hash)
        if old_session is not None:
            db.delete(old_session)

    raw_token, token_hash = security.new_session_token()
    csrf_token = security.new_csrf_token()
    session_row = SessionModel(
        token_hash=token_hash,
        user_id=user.user_id,
        csrf_token=csrf_token,
        expires_at=security.session_expiry(),
    )
    db.add(session_row)
    db.commit()

    response.delete_cookie(BOOTSTRAP_COOKIE_NAME, path="/")
    response.set_cookie(
        key=security.session_cookie_name(),
        value=raw_token,
        httponly=True,
        secure=not settings.is_dev,
        samesite="lax",
        path="/",
        max_age=int(security.SESSION_ABSOLUTE_LIFETIME.total_seconds()),
    )

    return {
        "user": {"user_id": str(user.user_id), "display_name": user.display_name},
        "csrf_token": csrf_token,
    }
@router.post("/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    db: DBSession = Depends(get_db),
):
    _validate_origin(request)

    cookie_name = security.session_cookie_name()
    raw_token = request.cookies.get(cookie_name)

    if raw_token:
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        session_row = db.get(SessionModel, token_hash)
        if session_row is not None:
            now = datetime.now(timezone.utc)
            idle_cutoff = session_row.last_active_at + security.SESSION_IDLE_LIFETIME
            if session_row.expires_at > now and idle_cutoff >= now:
                validate_unsafe_request(request, session_row)
            db.delete(session_row)
            db.commit()

    response.delete_cookie(cookie_name, path="/")
    response.status_code = 204
    return response
