import uuid
from fastapi import HTTPException


class BodyLimitExceeded(Exception):
    """Internal signal raised before a capped request reaches a handler."""


def api_error(status_code: int, code: str, message: str, retryable: bool = False, details: dict | None = None,
              headers: dict[str, str] | None = None):
    return HTTPException(
        status_code=status_code,
        detail={
            "error": {
                "code": code,
                "message": message,
                "request_id": str(uuid.uuid4()),
                "retryable": retryable,
                "details": details or {},
            }
        },
        headers=headers,
    )


def error_body(code: str, message: str, *, retryable: bool = False, details: dict | None = None) -> dict:
    """Build the only error shape exposed by the API."""
    return {"error": {
        "code": code,
        "message": message,
        "request_id": str(uuid.uuid4()),
        "retryable": retryable,
        "details": details or {},
    }}
