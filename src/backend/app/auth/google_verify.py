import logging

from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from app.core.config import settings


log = logging.getLogger(__name__)
GOOGLE_CLOCK_SKEW_SECONDS = 10


class InvalidGoogleCredential(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _classify_verification_error(error: ValueError) -> str:
    """Map third-party verifier text to a fixed, content-free diagnostic code."""
    message = str(error).casefold()
    if "audience" in message:
        return "audience_mismatch"
    if ("issued-at" in message or "issued at" in message or "not yet valid" in message
            or "used too early" in message):
        return "issued_in_future"
    if "expired" in message or "expiration" in message:
        return "expired"
    if "signature" in message:
        return "signature_invalid"
    if "issuer" in message:
        return "issuer_invalid"
    if any(marker in message for marker in ("segment", "malformed", "decode", "jwt")):
        return "malformed"
    return "verification_failed"


def _reject(reason: str) -> None:
    log.warning("google_credential_rejected reason=%s", reason)
    raise InvalidGoogleCredential(reason)


def verify_google_credential(credential: str) -> str:
    """Verifies signature, issuer, expiry, and audience. Returns the verified sub."""
    try:
        idinfo = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            audience=settings.google_client_id,
            # Allow at most 10 seconds of drift for issue-time and expiry checks.
            clock_skew_in_seconds=GOOGLE_CLOCK_SKEW_SECONDS,
        )
    except ValueError as exc:
        reason = _classify_verification_error(exc)
        log.warning("google_credential_rejected reason=%s", reason)
        raise InvalidGoogleCredential(reason) from None

    if idinfo.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        _reject("issuer_invalid")

    sub = idinfo.get("sub")
    if not sub:
        _reject("missing_subject")

    return sub
