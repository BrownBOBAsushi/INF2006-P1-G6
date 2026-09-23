from contextlib import asynccontextmanager
import logging
import os

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, text
from fastapi.middleware.cors import CORSMiddleware

from app.auth.router import router as auth_router
from app.api.me import router as me_router
from app.api.resume import recover_interrupted_operations, router as resume_router
from app.api.jobs import router as jobs_router
from app.api.matches import router as matches_router
from app.core.config import settings
from app.core.errors import BodyLimitExceeded, error_body
from app.db.session import configure_transaction_timeouts
from app.processing.slot import ProcessingService

log = logging.getLogger(__name__)

if os.environ.get("TEST_AUTH_BYPASS") == "true" and not settings.is_dev:
    raise RuntimeError(
        "TEST_AUTH_BYPASS is enabled but the APP_ENV is not 'development'. Refusing to start."
    )

processing_service = ProcessingService()
recovery_failed = False


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global recovery_failed
    try:
        recover_interrupted_operations()
    except Exception as exc:
        recovery_failed = True
        log.error("processing_recovery_failed exception_class=%s", type(exc).__name__)
    try:
        processing_service.start()
    except Exception as exc:  # model/cache availability is reported by readiness
        log.error("processing_service_start_failed exception_class=%s", type(exc).__name__)
    try:
        yield
    finally:
        processing_service.stop()


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.app_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token", "Idempotency-Key"],
)


@app.middleware("http")
async def enforce_body_limits(request: Request, call_next):
    def private_response(response):
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    content_type = request.headers.get("content-type", "").lower()
    media_type = content_type.split(";", 1)[0].strip()
    is_prepare = request.url.path == "/api/resume/prepare" and request.method == "POST"
    is_json = media_type == "application/json" or (
        media_type.startswith("application/") and media_type.endswith("+json")
    )
    is_resume_json = request.url.path == "/api/resume" and request.method == "PUT"
    limit = 6 * 1024 * 1024 if is_prepare and content_type.startswith("multipart/") else 256 * 1024
    if is_prepare or is_json or is_resume_json:
        raw_length = request.headers.get("content-length")
        if raw_length is not None:
            try:
                declared = int(raw_length)
            except (TypeError, ValueError):
                return private_response(JSONResponse(status_code=400, content=error_body(
                    "INVALID_CONTENT", "The request could not be validated.", details={"fields": ["Content-Length"]}
                )))
            if declared < 0:
                return private_response(JSONResponse(status_code=400, content=error_body(
                    "INVALID_CONTENT", "The request could not be validated.", details={"fields": ["Content-Length"]}
                )))
            if declared > limit:
                return private_response(JSONResponse(status_code=413, content=error_body("BODY_TOO_LARGE", "The request body is too large.")))

        # JSON requests are completely buffered and replayed only after the
        # cap passes. This prevents a valid prefix plus an oversized tail from
        # reaching a mutating handler before a post-hoc 413 is returned.
        original_receive = request.receive
        if is_json or is_resume_json:
            messages = []
            received = 0
            while True:
                message = await original_receive()
                messages.append(message)
                if message.get("type") == "http.request":
                    received += len(message.get("body", b""))
                    if received > limit:
                        return private_response(JSONResponse(status_code=413, content=error_body("BODY_TOO_LARGE", "The request body is too large.")))
                    if not message.get("more_body", False):
                        break
                elif message.get("type") == "http.disconnect":
                    break
            replay = iter(messages)

            async def replay_receive():
                try:
                    return next(replay)
                except StopIteration:
                    return {"type": "http.request", "body": b"", "more_body": False}

            request._receive = replay_receive
            return private_response(await call_next(request))

        # Multipart preparation stays admission-first: the route acquires the
        # processing lease before it calls request.body(). Raise into that
        # route so no truncated body reaches the parser or child.
        received = 0

        async def limited_receive():
            nonlocal received
            message = await original_receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise BodyLimitExceeded
            return message

        request._receive = limited_receive
        return private_response(await call_next(request))
    return private_response(await call_next(request))


def _validation_fields(exc: RequestValidationError) -> list[str]:
    fields: list[str] = []
    # FastAPI/Pydantic versions in the supported range expose errors() without
    # keyword arguments.  Only loc is copied; input values and messages can
    # contain resume text and must never enter the public envelope.
    for item in exc.errors():
        loc = [str(part) for part in item.get("loc", ()) if part not in ("body", "query", "path", "header")]
        field = ".".join(loc) or "request"
        if field not in fields:
            fields.append(field)
    return fields[:20]


@app.exception_handler(HTTPException)
async def handle_http_exception(_request: Request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict) and isinstance(detail.get("error"), dict):
        body = detail
    elif isinstance(detail, dict) and isinstance(detail.get("code"), str):
        body = error_body(detail["code"], detail.get("message", "Request could not be completed."))
    else:
        code = "AUTH_REQUIRED" if exc.status_code == 401 else "BAD_REQUEST"
        body = error_body(code, "Request could not be completed.")
    headers = {"Cache-Control": "no-store", **(exc.headers or {})}
    return JSONResponse(status_code=exc.status_code, content=body, headers=headers)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(_request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content=error_body(
            "INVALID_CONTENT",
            "The request could not be validated.",
            details={"fields": _validation_fields(exc)},
        ),
        headers={"Cache-Control": "no-store"},
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(_request: Request, _exc: Exception):
    log.error("api_request_failed exception_class=%s", type(_exc).__name__)
    return JSONResponse(status_code=500, content=error_body("INTERNAL_ERROR", "Something went wrong. Please try again.", retryable=True),
                        headers={"Cache-Control": "no-store"})


engine = create_engine(os.environ["DATABASE_URL"])
configure_transaction_timeouts(engine)
REQUIRED_TABLES = {
    "users", "sessions", "resume_profiles", "resume_chunks", "save_operations",
    "jobs", "job_requirements", "requirement_embeddings", "app_state",
}
EXPECTED_EMBEDDING_DIM = 384


@app.get("/health/live")
def live():
    return {"status": "alive"}


@app.get("/health/ready")
def ready():
    if recovery_failed or not processing_service.is_ready():
        return Response(status_code=503)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            existing_tables = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public' AND table_name = ANY(:names)"
                    ),
                    {"names": list(REQUIRED_TABLES)},
                )
            }
            if existing_tables != REQUIRED_TABLES:
                return Response(status_code=503)
            if not conn.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).first():
                return Response(status_code=503)
            dim = conn.execute(
                text(
                    "SELECT atttypmod FROM pg_attribute "
                    "WHERE attrelid = 'resume_chunks'::regclass AND attname = 'embedding'"
                )
            ).scalar()
            if dim != EXPECTED_EMBEDDING_DIM:
                return Response(status_code=503)
        return {"status": "ready"}
    except Exception:
        return Response(status_code=503)


app.include_router(auth_router)
app.include_router(me_router)
app.include_router(resume_router)
app.include_router(jobs_router)
app.include_router(matches_router)
