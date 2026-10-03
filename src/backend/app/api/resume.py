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
from app.db.models import ProcessingTask, ResumeChunk, ResumeProfile, SaveOperation, Session as SessionModel, User
from app.db.session import get_db
from app.processing.config import EMBEDDING_VERSION, MAX_PDF_BYTES
from app.processing.errors import CONTRACT_ERRORS, ProcessingError, RETRYABLE_CODES
from app.processing.content import content_hash, validate_resume_content, validate_review_draft
from app.processing.cloud_adapters import make_storage
from app.processing.tasks import cancel_owner_tasks, enqueue_task

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
    extraction_task_id: uuid.UUID | None = None


class PrepareResumeResponse(BaseModel):
    draft: dict
    unassigned_text: str
    warnings: list[dict]


class ResumeProfileResponse(BaseModel):
    revision: int
    content: dict
    embedding_version: str
    has_matchable_resume: bool
    embedding_state: str


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


class PrepareTaskResponse(BaseModel):
    task_id: uuid.UUID
    state: str
    revision: int


class ProcessingTaskResponse(BaseModel):
    task_id: uuid.UUID
    kind: str
    state: str
    revision: int
    failure_code: str | None
    result: dict | None = None
    expires_at: datetime | None = None


def _raise_processing(exc: ProcessingError, *, details: dict | None = None):
    headers = {"Retry-After": str(exc.retry_after_seconds)} if exc.retry_after_seconds else None
    raise api_error(exc.status_code, exc.code, exc.message, retryable=exc.retryable, details=details, headers=headers)


def _payload_hash(expected_revision: int, content: dict, extraction_task_id: uuid.UUID | None = None) -> str:
    payload = {"expected_revision": expected_revision, "content": content,
               "extraction_task_id": str(extraction_task_id) if extraction_task_id else None,
               "embedding_version": EMBEDDING_VERSION}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _temp_storage(request: Request | None = None):
    if request is not None and hasattr(request.app.state, "processing_storage"):
        return request.app.state.processing_storage
    return make_storage()


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


def _privacy_recheck(content: dict) -> tuple[bool, dict]:
    # Privacy is the only synchronous processing requirement on the save path.
    # This path never imports or initializes the embedding model.
    from app.processing.pipeline import recheck_privacy

    return recheck_privacy(content)


async def _replay_review_required(body: SaveResumeRequest, operation_id: uuid.UUID):
    try:
        _changed, cleaned = await asyncio.to_thread(_privacy_recheck, body.content)
    except Exception:
        raise api_error(500, "INTERNAL_ERROR", "The resume could not be saved.", retryable=True) from None
    try:
        validate_review_draft(cleaned)
    except Exception:
        raise api_error(500, "INTERNAL_ERROR", "The resume could not be saved.", retryable=True) from None
    details = {"cleaned_draft": cleaned}
    raise api_error(422, "REVIEW_REQUIRED", CONTRACT_ERRORS["REVIEW_REQUIRED"][1], details=details)


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
    embedding_task = db.scalar(select(ProcessingTask).where(
        ProcessingTask.owner_id == user.user_id,
        ProcessingTask.kind == "EMBEDDING",
        ProcessingTask.revision == profile.revision,
    ).order_by(ProcessingTask.created_at.desc()).limit(1))
    if has_matchable_resume:
        embedding_state = "READY"
    elif embedding_task is not None and embedding_task.state in {"PENDING", "PROCESSING", "RETRY_WAIT"}:
        embedding_state = "PENDING"
    elif embedding_task is not None and embedding_task.state == "FAILED":
        embedding_state = "FAILED"
    else:
        embedding_state = "NOT_READY"
    response = {
        "revision": profile.revision,
        "content": profile.content,
        "embedding_version": profile.embedding_version,
        "has_matchable_resume": has_matchable_resume,
        "embedding_state": embedding_state,
    }
    touch_session_activity(db, session_row)
    return response


@router.post("/resume/prepare", response_model=PrepareTaskResponse, status_code=202)
async def prepare_resume(
    request: Request,
    session_and_user: tuple[SessionModel, User] = Depends(get_current_session_and_user),
    db: DBSession = Depends(get_db),
):
    session_row, user = session_and_user
    validate_unsafe_request(request, session_row)
    user_id = user.user_id
    session_token_hash = session_row.token_hash
    db.rollback()
    storage = _temp_storage(request)
    payload_ref = None
    try:
        raw = await request.body()
        data = _parse_single_pdf(raw, request.headers.get("content-type", ""))
        if len(data) > MAX_PDF_BYTES:
            raise ProcessingError("FILE_TOO_LARGE", "byte_limit")
        payload_ref = await asyncio.to_thread(storage.store, data)
        del data, raw
        locked_user = db.execute(
            select(User).where(User.user_id == user_id).with_for_update().execution_options(populate_existing=True)
        ).scalar_one()
        task = enqueue_task(db, owner_id=user_id, kind="EXTRACTION", task_key=payload_ref,
                            revision=locked_user.resume_revision, payload_ref=payload_ref)
        db.commit()
    except BodyLimitExceeded:
        db.rollback()
        raise api_error(413, "BODY_TOO_LARGE", "The request body is too large.")
    except ProcessingError as exc:
        db.rollback()
        await asyncio.to_thread(storage.delete, payload_ref)
        _raise_processing(exc)
    except Exception:
        db.rollback()
        await asyncio.to_thread(storage.delete, payload_ref)
        raise api_error(500, "INTERNAL_ERROR", "The upload could not be queued.", retryable=True) from None
    touch_session_activity_by_token(db, session_token_hash)
    return {"task_id": task.task_id, "state": task.state, "revision": task.revision}


def _task_response(task: ProcessingTask) -> dict:
    now = datetime.now(timezone.utc)
    result = task.result_data if task.state == "SUCCEEDED" and task.expires_at and task.expires_at > now else None
    return {"task_id": task.task_id, "kind": task.kind, "state": task.state, "revision": task.revision,
            "failure_code": task.failure_code, "result": result,
            "expires_at": task.expires_at if result is not None else None}


@router.get("/resume/tasks/active", response_model=ProcessingTaskResponse | None)
def get_active_extraction(
    session_and_user: tuple[SessionModel, User] = Depends(get_current_session_and_user),
    db: DBSession = Depends(get_db),
):
    _session, user = session_and_user
    task = db.scalar(select(ProcessingTask).where(
        ProcessingTask.owner_id == user.user_id,
        ProcessingTask.kind == "EXTRACTION",
        ProcessingTask.revision == user.resume_revision,
        ProcessingTask.state.in_({"PENDING", "PROCESSING", "RETRY_WAIT", "SUCCEEDED"}),
        (ProcessingTask.state != "SUCCEEDED") | (ProcessingTask.expires_at > datetime.now(timezone.utc)),
    ).order_by(ProcessingTask.created_at.desc()).limit(1))
    return _task_response(task) if task is not None else None


@router.get("/resume/tasks/{task_id}", response_model=ProcessingTaskResponse)
def get_processing_task(
    task_id: str,
    session_and_user: tuple[SessionModel, User] = Depends(get_current_session_and_user),
    db: DBSession = Depends(get_db),
):
    _session, user = session_and_user
    try:
        parsed = uuid.UUID(task_id)
    except ValueError:
        raise api_error(404, "TASK_NOT_FOUND", "This processing task is no longer available.") from None
    task = db.scalar(select(ProcessingTask).where(
        ProcessingTask.task_id == parsed, ProcessingTask.owner_id == user.user_id,
    ))
    if task is None or (task.kind == "EXTRACTION" and task.state == "SUCCEEDED"
                         and (task.expires_at is None or task.expires_at <= datetime.now(timezone.utc))):
        raise api_error(404, "TASK_NOT_FOUND", "This processing task is no longer available.")
    return _task_response(task)


@router.delete("/resume/tasks/{task_id}")
def discard_extraction_task(
    task_id: str,
    request: Request,
    session_and_user: tuple[SessionModel, User] = Depends(get_current_session_and_user),
    db: DBSession = Depends(get_db),
):
    """Discard a user's temporary extraction input or reviewed draft."""
    session_row, user = session_and_user
    validate_unsafe_request(request, session_row)
    try:
        parsed = uuid.UUID(task_id)
    except ValueError:
        raise api_error(404, "TASK_NOT_FOUND", "This processing task is no longer available.") from None
    storage = _temp_storage(request)
    db.flush()
    locked_user = db.execute(select(User).where(User.user_id == user.user_id).with_for_update()
                             .execution_options(populate_existing=True)).scalar_one()
    task = db.scalar(select(ProcessingTask).where(
        ProcessingTask.task_id == parsed,
        ProcessingTask.owner_id == user.user_id,
        ProcessingTask.kind == "EXTRACTION",
    ).with_for_update().execution_options(populate_existing=True))
    if task is None:
        raise api_error(404, "TASK_NOT_FOUND", "This processing task is no longer available.")
    from app.processing.tasks import _cancel_outbox
    payload_ref = task.payload_ref
    task.state = "CANCELLED"
    task.failure_code = "CANCELLED_BY_OWNER"
    task.payload_ref = None
    task.result_data = None
    task.expires_at = None
    task.lease_token = None
    task.lease_expires_at = None
    task.updated_at = datetime.now(timezone.utc)
    _cancel_outbox(db, task.task_id)
    db.commit()
    storage.delete(payload_ref)
    touch_session_activity(db, session_row)
    return {"task_id": str(parsed), "state": "CANCELLED", "revision": locked_user.resume_revision}


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
    payload_hash = _payload_hash(body.expected_revision, body.content, body.extraction_task_id)
    requested_hash = content_hash(body.content)
    existing = db.get(SaveOperation, {"user_id": user.user_id, "operation_id": operation_id})
    if existing is not None:
        if (existing.state == "FAILED" and existing.failure_code == "REVIEW_REQUIRED"
                and existing.payload_hash == payload_hash and existing.expires_at > datetime.now(timezone.utc)):
            db.rollback()
            return await _replay_review_required(body, operation_id)
        return _replay_or_raise(existing, payload_hash)
    if user.resume_revision != body.expected_revision:
        raise api_error(409, "REVISION_CONFLICT", "Resume has changed since you last saw it.",
                        details={"current_revision": user.resume_revision})

    # Recheck privacy before any permanent profile write. The API may load the
    # local privacy analyzer, but this path never loads the embedding model.
    db.rollback()
    try:
        changed_by_cleanup, cleaned = await asyncio.to_thread(_privacy_recheck, body.content)
    except Exception as exc:
        log.warning("resume_privacy_recheck_failed exception_class=%s", type(exc).__name__)
        raise api_error(503, "SERVICE_UNAVAILABLE", "Resume privacy checks are temporarily unavailable.", retryable=True) from None
    if changed_by_cleanup:
        try:
            validate_review_draft(cleaned)
        except Exception:
            raise api_error(500, "INTERNAL_ERROR", "The resume could not be saved.", retryable=True) from None
        db.add(SaveOperation(user_id=user.user_id, operation_id=operation_id, payload_hash=payload_hash,
                             state="FAILED", expected_revision=body.expected_revision,
                             failure_code="REVIEW_REQUIRED",
                             expires_at=datetime.now(timezone.utc) + SAVE_OPERATION_RETENTION))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            concurrent = db.get(SaveOperation, {"user_id": user.user_id, "operation_id": operation_id})
            if concurrent is not None:
                if concurrent.payload_hash != payload_hash:
                    raise api_error(409, "IDEMPOTENCY_CONFLICT", "This idempotency key was already used for another request.")
                if concurrent.state == "FAILED" and concurrent.failure_code == "REVIEW_REQUIRED":
                    return await _replay_review_required(body, operation_id)
                return _replay_or_raise(concurrent, payload_hash)
        raise api_error(422, "REVIEW_REQUIRED", CONTRACT_ERRORS["REVIEW_REQUIRED"][1],
                        details={"cleaned_draft": cleaned})

    user_id, session_token_hash = user.user_id, session_row.token_hash
    db.rollback()
    try:
        locked_user = db.execute(select(User).where(User.user_id == user_id).with_for_update()
                                 .execution_options(populate_existing=True)).scalar_one()
        concurrent = db.get(SaveOperation, {"user_id": user_id, "operation_id": operation_id})
        if concurrent is not None:
            db.rollback()
            if (concurrent.state == "FAILED" and concurrent.failure_code == "REVIEW_REQUIRED"
                    and concurrent.payload_hash == payload_hash):
                return await _replay_review_required(body, operation_id)
            return _replay_or_raise(concurrent, payload_hash)
        if locked_user.resume_revision != body.expected_revision:
            raise api_error(409, "REVISION_CONFLICT", "Resume has changed since you last saw it.",
                            details={"current_revision": locked_user.resume_revision})
        if body.extraction_task_id is not None:
            extraction = db.scalar(select(ProcessingTask).where(
                ProcessingTask.task_id == body.extraction_task_id,
                ProcessingTask.owner_id == user_id,
                ProcessingTask.kind == "EXTRACTION",
                ProcessingTask.state == "SUCCEEDED",
                ProcessingTask.revision == body.expected_revision,
                ProcessingTask.expires_at > datetime.now(timezone.utc),
            ))
            if extraction is None:
                raise api_error(409, "TASK_NOT_FOUND", "The reviewed extraction draft has expired or changed.")

        profile = db.get(ResumeProfile, user_id)
        changed = (profile is None or profile.content_hash != requested_hash
                   or profile.embedding_version != EMBEDDING_VERSION)
        new_revision = locked_user.resume_revision + 1 if changed else locked_user.resume_revision
        if changed:
            db.execute(delete(ResumeChunk).where(ResumeChunk.user_id == user_id))
            if profile is None:
                profile = ResumeProfile(user_id=user_id, revision=new_revision, content=body.content,
                                        content_hash=requested_hash, embedding_version=EMBEDDING_VERSION)
                db.add(profile)
                db.flush()
            else:
                profile.revision, profile.content = new_revision, body.content
                profile.content_hash, profile.embedding_version = requested_hash, EMBEDDING_VERSION
                profile.updated_at = datetime.now(timezone.utc)
            locked_user.resume_revision = new_revision
            enqueue_task(db, owner_id=user_id, kind="EMBEDDING",
                         task_key=f"save:{operation_id}", revision=new_revision)
        else:
            failed_embedding = db.scalar(select(ProcessingTask).where(
                ProcessingTask.owner_id == user_id, ProcessingTask.kind == "EMBEDDING",
                ProcessingTask.revision == new_revision, ProcessingTask.state == "FAILED",
            ).order_by(ProcessingTask.created_at.desc()).limit(1))
            if failed_embedding is not None:
                enqueue_task(db, owner_id=user_id, kind="EMBEDDING",
                             task_key=f"retry:{operation_id}", revision=new_revision)

        db.add(SaveOperation(user_id=user_id, operation_id=operation_id, payload_hash=payload_hash,
                             state="SUCCEEDED", expected_revision=body.expected_revision,
                             result_revision=new_revision,
                             expires_at=datetime.now(timezone.utc) + SAVE_OPERATION_RETENTION))
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        concurrent = db.get(SaveOperation, {"user_id": user_id, "operation_id": operation_id})
        if concurrent is not None:
            return _replay_or_raise(concurrent, payload_hash)
        raise api_error(500, "INTERNAL_ERROR", "The resume could not be saved.", retryable=True) from None
    except Exception as exc:
        db.rollback()
        log.warning("resume_save_failed exception_class=%s", type(exc).__name__)
        raise api_error(500, "INTERNAL_ERROR", "The resume could not be saved.", retryable=True) from None
    touch_session_activity_by_token(db, session_token_hash)
    return {"operation_id": str(operation_id), "result_revision": new_revision, "changed": changed}


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
    temp_refs = list(db.scalars(select(ProcessingTask.payload_ref).where(
        ProcessingTask.owner_id == user.user_id,
        ProcessingTask.kind == "EXTRACTION",
        ProcessingTask.payload_ref.is_not(None),
    )))
    cancelled = cancel_owner_tasks(db, owner_id=user.user_id)
    if profile is not None:
        db.delete(profile)
    if profile is not None or cancelled > 0:
        locked_user.resume_revision += 1
    revision = locked_user.resume_revision
    db.commit()
    storage = _temp_storage(request)
    for ref in temp_refs:
        storage.delete(ref)
    touch_session_activity(db, session_row)
    return {"resume_revision": revision, "has_resume": False}


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
