from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from app.core.config import settings


class InvalidGoogleCredential(Exception):
    pass


def verify_google_credential(credential: str) -> str:
    """Verifies signature, issuer, expiry, and audience. Returns the verified sub."""
    try:
        idinfo = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            audience=settings.google_client_id,
        )
    except ValueError as exc:
        raise InvalidGoogleCredential(str(exc)) from exc

    if idinfo.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise InvalidGoogleCredential("unexpected issuer")

    sub = idinfo.get("sub")
    if not sub:
        raise InvalidGoogleCredential("missing sub")

    return sub