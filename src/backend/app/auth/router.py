from fastapi import APIRouter, Depends, Request, Response, HTTPException, Header
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import select
from fastapi import Response as FastAPIResponse
import hashlib
from app.db.session import get_db
from app.db.models import User, Session as SessionModel
from app.core.config import settings
from app.auth import security
from app.auth.google_verify import verify_google_credential, InvalidGoogleCredential

router = APIRouter(prefix="/api/auth")

BOOTSTRAP_COOKIE_NAME = "pre_login"


def _validate_origin(request: Request):
    origin = request.headers.get("origin")
    if origin != settings.app_origin:
        raise HTTPException(status_code=403, detail={"code": "CSRF_INVALID"})


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
        raise HTTPException(status_code=401, detail={"code": "AUTH_REQUIRED"})

    nonce = security.verify_bootstrap_cookie(signed_cookie)
    if not nonce or not security.constant_time_eq(nonce, x_csrf_token):
        raise HTTPException(status_code=403, detail={"code": "CSRF_INVALID"})

    credential = body.get("credential")
    if not credential:
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST"})

    try:
        sub = verify_google_credential(credential)
    except InvalidGoogleCredential:
        raise HTTPException(status_code=401, detail={"code": "AUTH_REQUIRED"})
    finally:
        credential = None  # erase reference; nothing persists it

    # Find or create user by verified sub
    user = db.execute(select(User).where(User.google_sub == sub)).scalar_one_or_none()
    if user is None:
        user = User(google_sub=sub)
        db.add(user)
        db.flush()  # get user_id without committing yet

    # Rotate session: issue a new one
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
            db.delete(session_row)
            db.commit()

    response.delete_cookie(cookie_name, path="/")
    return FastAPIResponse(status_code=204)