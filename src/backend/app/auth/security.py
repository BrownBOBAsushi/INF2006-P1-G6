import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from app.core.config import settings

BOOTSTRAP_MAX_AGE_SECONDS = 300  # 5 minutes
SESSION_ABSOLUTE_LIFETIME = timedelta(hours=8)
SESSION_IDLE_LIFETIME = timedelta(minutes=30)

_serializer = URLSafeTimedSerializer(settings.app_signing_key, salt="auth-bootstrap")


def issue_bootstrap_nonce() -> tuple[str, str]:
    """Returns (nonce, signed_cookie_value)."""
    nonce = secrets.token_urlsafe(32)
    signed = _serializer.dumps({"nonce": nonce})
    return nonce, signed


def verify_bootstrap_cookie(signed_value: str) -> str | None:
    """Returns the nonce if valid and unexpired, else None."""
    try:
        data = _serializer.loads(signed_value, max_age=BOOTSTRAP_MAX_AGE_SECONDS)
        return data["nonce"]
    except (BadSignature, SignatureExpired, KeyError):
        return None


def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


def new_session_token() -> tuple[str, str]:
    """Returns (raw_token, token_hash). Raw goes in the cookie; hash goes to DB."""
    raw = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    return raw, token_hash


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def session_cookie_name() -> str:
    return "session" if settings.is_dev else "__Host-session"


def session_expiry() -> datetime:
    return datetime.now(timezone.utc) + SESSION_ABSOLUTE_LIFETIME