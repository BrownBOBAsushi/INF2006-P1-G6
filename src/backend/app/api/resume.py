from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.auth.dependencies import (
    get_current_session_and_user,
    touch_session_activity,
    touch_session_activity_by_token,
    validate_unsafe_request,
)
from app.core.errors import BodyLimitExceeded, api_error
from app.db.models import ResumeChunk, ResumeProfile, SaveOperation, Session as SessionModel, User
from app.db.session import SessionLocal, get_db
from app.processing.config import EMBEDDING_VERSION, MAX_PDF_BYTES
from app.processing.errors import CONTRACT_ERRORS, ProcessingError, RETRYABLE_CODES
from app.processing.content import content_hash, validate_resume_content, validate_review_draft

router = APIRouter(prefix="/api")
log = logging.getLogger(__name__)
JSON_BODY_LIMIT = 256 * 1024
MULTIPART_BODY_LIMIT = 6 * 1024 * 1024
SAVE_OPERATION_RETENTION = timedelta(hours=24)


class DeleteResumeRequest(BaseModel):
    expected_revision: int = Field(ge=0)


class SaveResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    content: dict


class PrepareResumeResponse(BaseModel):
    draft: dict
    unassigned_text: str
    warnings: list[dict]


class ResumeProfileResponse(BaseModel):
    revision: int
    content: dict
    embedding_version: str
    has_matchable_resume: bool


class SaveResumeResponse(BaseModel):
    operation_id: uuid.UUID
    result_revision: int
    changed: bool


class DeleteResumeResponse(BaseModel):
    resume_revision: int
    has_resume: bool


class OperationStatusResponse(BaseModel):
    operation_id: uuid.UUID
    state: str
    result_revision: int | None
    failure_code: str | None


def _processing_service():
    # Import lazily to keep the API module importable for schema and pure tests.
    from app.main import processing_service
    return processing_service


def _raise_processing(exc: ProcessingError, *, details: dict | None = None):
    headers = {"Retry-After": str(exc.retry_after_seconds)} if exc.retry_after_seconds else None
    raise api_error(exc.status_code, exc.code, exc.message, retryable=exc.retryable, details=details, headers=headers)


def _payload_hash(expected_revision: int, content: dict) -> str:
    payload = {"expected_revision": expected_revision, "content": content, "embedding_version": EMBEDDING_VERSION}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _record_failure(db: DBSession, user_id, operation_id: uuid.UUID, code: str) -> None:
    db.rollback()
    op = db.get(SaveOperation, {"user_id": user_id, "operation_id": operation_id})
    if op is not None and op.state == "PROCESSING":
        op.state = "FAILED"
        op.failure_code = code
        op.updated_at = datetime.now(timezone.utc)
        db.commit()


def _record_failure_isolated(user_id, operation_id: uuid.UUID, code: str) -> None:
    """Terminalize a cancelled request with a session independent of its request scope."""
    db = SessionLocal()
    try:
        _record_failure(db, user_id, operation_id, code)
    except Exception:
        # Preserve the cancellation signal.  Startup recovery still repairs a
        # row if the database became unavailable during this final update.
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


def _parse_single_pdf(body: bytes, content_type: str) -> bytes:
    """Parse one in-memory multipart file after the middleware's byte cap."""
    if not content_type.startswith("multipart/") or "\r" in content_type or "\n" in content_type:
        raise ProcessingError("PDF_REQUIRED", "multipart_file")
    try:
        headers = (
            b"Content-Type: " + content_type.encode("ascii") +
            b"\r\nMIME-Version: 1.0\r\n\r\n"
        )
        message = BytesParser(policy=policy.default).parsebytes(headers + body)
    except (UnicodeEncodeError, ValueError):
        raise ProcessingError("PDF_REQUIRED", "multipart_file") from None
    if not message.is_multipart():
        raise ProcessingError("PDF_REQUIRED", "multipart_file")
    files: list[bytes] = []
    file_names: list[str | None] = []
    for part in message.iter_parts():
        if part.get_content_disposition() != "form-data":
            continue
        filename = part.get_param("filename", header="content-disposition")
        if filename is None:
            continue
        files.append(part.get_payload(decode=True) or b"")
        file_names.append(part.get_param("name", header="content-disposition"))
    if len(files) != 1 or file_names[0] != "file":
        raise ProcessingError("PDF_REQUIRED", "exactly_one_file")
    return files[0]


def recover_interrupted_operations() -> None:
    """Single-worker restart recovery: terminalize rows left by a dead child/API."""
    db = SessionLocal()
    try:
        rows = db.execute(select(SaveOperation).where(SaveOperation.state == "PROCESSING")).scalars().all()
        for op in rows:
            op.state, op.failure_code = "FAILED", "PROCESS_INTERRUPTED"
            op.updated_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()


def _replay_or_raise(op: SaveOperation, payload_hash: str):
    if op.payload_hash != payload_hash:
        raise api_error(409, "IDEMPOTENCY_CONFLICT", "This idempotency key was already used for another request.")
    if op.expires_at <= datetime.now(timezone.utc):
        raise api_error(404, "OPERATION_EXPIRED", "This operation is no longer available.")
    if op.state == "PROCESSING":
        raise api_error(409, "SAVE_IN_PROGRESS", "This save is still processing.", retryable=True,
                        headers={"Retry-After": "3"})
    if op.state == "FAILED":
        code = op.failure_code or "INTERNAL_ERROR"
        if code == "REVIEW_REQUIRED":
            raise api_error(422, code, "Privacy cleanup changed your resume. Please review and confirm again.")
        if code == "REVISION_CONFLICT":
            status, message = 409, "Resume has changed since you last saw it."
        elif code in CONTRACT_ERRORS:
            status, message = CONTRACT_ERRORS[code]
        else:
            status, message = 500, "The resume could not be saved."
        headers = {"Retry-After": "3"} if code == "PROCESSING_BUSY" else None
        raise api_error(status, code, message, retryable=code in RETRYABLE_CODES, headers=headers)
    return {"operation_id": str(op.operation_id), "result_revision": op.result_revision, "changed": False}


async def _replay_review_required(body: SaveResumeRequest, operation_id: uuid.UUID):
    """Re-derive the review draft without storing resume text in the operation row."""
    try:
        lease = _processing_service().try_acquire()
    except ProcessingError as exc:
        _raise_processing(exc)
    processing_future = None
    try:
        loop = asyncio.get_running_loop()
        processing_future = loop.run_in_executor(
            None,
            lambda: lease.run("save", {
                "content": body.content,
                "skip_embedding": True,
                "embedding_version": EMBEDDING_VERSION,
            }),
        )
        result = await asyncio.shield(processing_future)
    except asyncio.CancelledError:
        if processing_future is not None:
            try:
                await asyncio.shield(processing_future)
            except BaseException:
                pass
        raise
    except ProcessingError as exc:
        _raise_processing(exc)
    except Exception:
        raise api_error(500, "INTERNAL_ERROR", "The resume could not be saved.", retryable=True)
    finally:
        lease.release()
    cleaned = result.get("cleaned") if isinstance(result, dict) else None
    if not isinstance(cleaned, dict):
        raise api_error(500, "INTERNAL_ERROR", "The resume could not be saved.", retryable=True)
    try:
        validate_review_draft(cleaned)
    except Exception:
        raise api_error(500, "INTERNAL_ERROR", "The resume could not be saved.", retryable=True) from None
    details = {"cleaned_draft": cleaned}
    raise api_error(422, "REVIEW_REQUIRED", CONTRACT_ERRORS["REVIEW_REQUIRED"][1], details=details)


async def _save_after_admission(
    *,
    body: SaveResumeRequest,
    session_token_hash: str,
    user_id,
    db: DBSession,
    operation_id: uuid.UUID,
    payload_hash: str,
    requested_content_hash: str,
    lease,
):
    """Run one admitted save while its lease is owned by the caller's finally block."""
    stage = "operation_insert"
    op = SaveOperation(user_id=user_id, operation_id=operation_id, payload_hash=payload_hash,
                       state="PROCESSING", expected_revision=body.expected_revision,
                       expires_at=datetime.now(timezone.utc) + SAVE_OPERATION_RETENTION)
    try:
        db.add(op)
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = db.get(SaveOperation, {"user_id": user_id, "operation_id": operation_id})
        if concurrent is None:
            raise api_error(500, "INTERNAL_ERROR", "The save could not be started.", retryable=True)
        return _replay_or_raise(concurrent, payload_hash)
    except Exception as exc:
        db.rollback()
        log.warning("resume_save_failed stage=%s exception_class=%s", stage, type(exc).__name__)
        raise api_error(500, "INTERNAL_ERROR", "The save could not be started.", retryable=True)

    try:
        stage = "existing_profile_read"
        existing_profile = db.get(ResumeProfile, user_id)
        existing_content_hash = existing_profile.content_hash if existing_profile is not None else None
        existing_embedding_version = existing_profile.embedding_version if existing_profile is not None else None
        # The child must never inherit the request transaction or an expired
        # ORM object that could reopen one during the await.
        db.rollback()
    except Exception as exc:
        # The operation row is already durable. Keep its lifecycle terminal
        # when the request session fails before the child can start.
        log.warning("resume_save_failed stage=%s exception_class=%s", stage, type(exc).__name__)
        _record_failure(db, user_id, operation_id, "INTERNAL_ERROR")
        raise api_error(500, "INTERNAL_ERROR", "The resume could not be saved.", retryable=True)
    skip_embedding = bool(
        existing_content_hash == requested_content_hash
        and existing_embedding_version == EMBEDDING_VERSION
    )
    processing_future = None
    try:
        loop = asyncio.get_running_loop()
        processing_future = loop.run_in_executor(
            None,
            lambda: lease.run("save", {
                "content": body.content,
                "skip_embedding": skip_embedding,
                "embedding_version": EMBEDDING_VERSION,
            }),
        )
        result = await asyncio.shield(processing_future)
    except asyncio.CancelledError:
        # Shielding keeps the executor call alive.  Wait for the child to
        # finish before the caller releases the lease, then terminalize the
        # operation through a fresh session because the request session may close.
        if processing_future is not None:
            try:
                await asyncio.shield(processing_future)
            except BaseException:
                pass
        _record_failure_isolated(user_id, operation_id, "PROCESS_INTERRUPTED")
        raise
    except ProcessingError as exc:
        _record_failure(db, user_id, operation_id, exc.code)
        _raise_processing(exc)
    except Exception as exc:
        log.warning("resume_save_failed stage=processing_child exception_class=%s", type(exc).__name__)
        _record_failure(db, user_id, operation_id, "INTERNAL_ERROR")
        raise api_error(500, "INTERNAL_ERROR", "The resume could not be saved.", retryable=True)

    if result.get("review_required"):
        _record_failure(db, user_id, operation_id, "REVIEW_REQUIRED")
        raise api_error(422, "REVIEW_REQUIRED", "Privacy cleanup changed your resume. Please review and confirm again.",
                        details={"cleaned_draft": result.get("cleaned")})
    try:
        stage = "validate_processing_result"
        validate_resume_content(body.content)
        vectors = result.get("vectors")
        chunks = result.get("chunks") or []
        if len(chunks) != len(vectors):
            raise ValueError("chunk_vector_count")
        stage = "lock_user"
        db.rollback()
        locked_user = db.execute(
            select(User).where(User.user_id == user_id).with_for_update().execution_options(populate_existing=True)
        ).scalar_one()
        if locked_user.resume_revision != body.expected_revision:
            op = db.get(SaveOperation, {"user_id": user_id, "operation_id": operation_id})
            op.state, op.failure_code = "FAILED", "REVISION_CONFLICT"
            db.commit()
            raise api_error(409, "REVISION_CONFLICT", "Resume has changed since you last saw it.",
                            details={"current_revision": locked_user.resume_revision})
        profile = db.get(ResumeProfile, locked_user.user_id)
        stage = "prepare_profile"
        changed = profile is None or profile.content_hash != requested_content_hash or profile.embedding_version != result["version"]
        if result.get("no_op") and changed:
            raise ValueError("no_op_profile_changed")
        new_revision = locked_user.resume_revision + 1 if changed else locked_user.resume_revision
        if changed:
            db.execute(delete(ResumeChunk).where(ResumeChunk.user_id == locked_user.user_id))
            if profile is None:
                profile = ResumeProfile(user_id=locked_user.user_id, revision=new_revision, content=body.content,
                                        content_hash=requested_content_hash, embedding_version=result["version"])
                db.add(profile)
                # ResumeChunk.user_id references resume_profiles.user_id.  The
                # explicit flush keeps this FK ordering deterministic even
                # when the ORM has no relationship configured for these rows.
                stage = "flush_profile"
                db.flush()
            else:
                profile.revision, profile.content, profile.content_hash = new_revision, body.content, requested_content_hash
                profile.embedding_version, profile.updated_at = result["version"], datetime.now(timezone.utc)
            locked_user.resume_revision = new_revision
            stage = "insert_chunks"
            for chunk, vector in zip(chunks, vectors):
                db.add(ResumeChunk(user_id=locked_user.user_id, profile_revision=new_revision,
                                   section=chunk["section"], entry_index=chunk["entry_index"],
                                   chunk_index=chunk["chunk_index"], text=chunk["text"],
                                   embedding=[float(x) for x in vector], embedding_version=result["version"]))
        stage = "commit_result"
        op = db.get(SaveOperation, {"user_id": user_id, "operation_id": operation_id})
        op.state, op.result_revision, op.failure_code = "SUCCEEDED", new_revision, None
        db.commit()
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        log.warning("resume_save_failed stage=%s exception_class=%s", stage, type(exc).__name__)
        _record_failure(db, user_id, operation_id, "INTERNAL_ERROR")
        raise api_error(500, "INTERNAL_ERROR", "The resume could not be saved.", retryable=True)
    touch_session_activity_by_token(db, session_token_hash)
    return {"operation_id": str(operation_id), "result_revision": new_revision, "changed": changed}


@router.get("/resume", response_model=ResumeProfileResponse)
def get_resume(
    session_and_user: tuple[SessionModel, User] = Depends(get_current_session_and_user),
    db: DBSession = Depends(get_db),
):
    session_row, user = session_and_user
    profile = db.get(ResumeProfile, user.user_id)
    if profile is None:
        raise api_error(404, "RESUME_NOT_FOUND", "No resume has been saved yet.")
    has_matchable_resume = profile.embedding_version == EMBEDDING_VERSION and db.execute(
        select(ResumeChunk.chunk_id).where(
            ResumeChunk.user_id == user.user_id,
            ResumeChunk.profile_revision == profile.revision,
            ResumeChunk.embedding_version == EMBEDDING_VERSION,
        ).limit(1)
    ).first() is not None
    response = {
        "revision": profile.revision,
        "content": profile.content,
        "embedding_version": profile.embedding_version,
        "has_matchable_resume": has_matchable_resume,
    }
    touch_session_activity(db, session_row)
    return response


@router.post("/resume/prepare", response_model=PrepareResumeResponse)
async def prepare_resume(
    request: Request,
    session_and_user: tuple[SessionModel, User] = Depends(get_current_session_and_user),
    db: DBSession = Depends(get_db),
):
    session_row, _user = session_and_user
    validate_unsafe_request(request, session_row)
    session_token_hash = session_row.token_hash
    # Authentication opened a read transaction. Close it before admission,
    # upload buffering, and the child call; activity is refreshed afterwards.
    db.rollback()
    try:
        lease = _processing_service().try_acquire()
    except ProcessingError as exc:
        _raise_processing(exc)
    try:
        raw = await request.body()
        data = _parse_single_pdf(raw, request.headers.get("content-type", ""))
        if len(data) > MAX_PDF_BYTES:
            raise ProcessingError("FILE_TOO_LARGE", "byte_limit")
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, lambda: lease.run("prepare", {"pdf": data}))
    except BodyLimitExceeded:
        raise api_error(413, "BODY_TOO_LARGE", "The request body is too large.")
    except ProcessingError as exc:
        _raise_processing(exc)
    finally:
        lease.release()
    touch_session_activity_by_token(db, session_token_hash)
    return result


@router.put("/resume", response_model=SaveResumeResponse)
async def save_resume(
    body: SaveResumeRequest,
    request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    session_and_user: tuple[SessionModel, User] = Depends(get_current_session_and_user),
    db: DBSession = Depends(get_db),
):
    session_row, user = session_and_user
    validate_unsafe_request(request, session_row)
    if request.headers.get("content-length") and int(request.headers["content-length"]) > JSON_BODY_LIMIT:
        raise api_error(413, "BODY_TOO_LARGE", "The request body is too large.")
    try:
        operation_id = uuid.UUID(idempotency_key)
    except ValueError:
        raise api_error(422, "INVALID_CONTENT", "Idempotency-Key must be a UUID.", details={"fields": ["Idempotency-Key"]}) from None
    try:
        validate_resume_content(body.content)
    except ProcessingError as exc:
        _raise_processing(exc)
    payload_hash = _payload_hash(body.expected_revision, body.content)
    requested_content_hash = content_hash(body.content)
    user_id = user.user_id
    session_token_hash = session_row.token_hash
    existing = db.get(SaveOperation, {"user_id": user.user_id, "operation_id": operation_id})
    if existing is not None:
        if (existing.state == "FAILED" and existing.failure_code == "REVIEW_REQUIRED"
                and existing.payload_hash == payload_hash
                and existing.expires_at > datetime.now(timezone.utc)):
            db.rollback()
            return await _replay_review_required(body, operation_id)
        return _replay_or_raise(existing, payload_hash)
    if user.resume_revision != body.expected_revision:
        raise api_error(409, "REVISION_CONFLICT", "Resume has changed since you last saw it.",
                        details={"current_revision": user.resume_revision})

    # Admission precedes the durable operation row so a busy request can be
    # retried with the same key without creating a phantom operation.
    # No ORM attributes are needed after this point except the captured scalar
    # identifiers. Keep the processing interval outside any DB transaction.
    db.rollback()
    try:
        service = _processing_service()
        lease = service.try_acquire()
    except ProcessingError as exc:
        _raise_processing(exc)
    try:
        return await _save_after_admission(
            body=body,
            session_token_hash=session_token_hash,
            user_id=user_id,
            db=db,
            operation_id=operation_id,
            payload_hash=payload_hash,
            requested_content_hash=requested_content_hash,
            lease=lease,
        )
    finally:
        lease.release()



@router.delete("/resume", response_model=DeleteResumeResponse)
def delete_resume(
    body: DeleteResumeRequest,
    request: Request,
    session_and_user: tuple[SessionModel, User] = Depends(get_current_session_and_user),
    db: DBSession = Depends(get_db),
):
    session_row, user = session_and_user
    validate_unsafe_request(request, session_row)
    locked_user = db.execute(
        select(User).where(User.user_id == user.user_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one()
    if locked_user.resume_revision != body.expected_revision:
        raise api_error(409, "REVISION_CONFLICT", "Resume has changed since you last saw it.",
                        details={"current_revision": locked_user.resume_revision})
    profile = db.get(ResumeProfile, user.user_id)
    if profile is None:
        db.commit()
        touch_session_activity(db, session_row)
        return {"resume_revision": locked_user.resume_revision, "has_resume": False}
    db.delete(profile)
    locked_user.resume_revision += 1
    db.commit()
    touch_session_activity(db, session_row)
    return {"resume_revision": locked_user.resume_revision, "has_resume": False}


@router.get("/resume/operations/{operation_id}", response_model=OperationStatusResponse)
def get_resume_operation(
    operation_id: str,
    session_and_user: tuple[SessionModel, User] = Depends(get_current_session_and_user),
    db: DBSession = Depends(get_db),
):
    _session_row, user = session_and_user
    try:
        parsed_id = uuid.UUID(operation_id)
    except ValueError:
        raise api_error(404, "OPERATION_EXPIRED", "This operation is no longer available.") from None
    op = db.get(SaveOperation, {"user_id": user.user_id, "operation_id": parsed_id})
    if op is None or op.expires_at <= datetime.now(timezone.utc):
        raise api_error(404, "OPERATION_EXPIRED", "This operation is no longer available.")
    return {"operation_id": str(op.operation_id), "state": op.state, "result_revision": op.result_revision,
            "failure_code": op.failure_code}
