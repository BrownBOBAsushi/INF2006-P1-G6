import uuid
from fastapi import HTTPException


def api_error(status_code: int, code: str, message: str, retryable: bool = False, details: dict | None = None):
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
    )