from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session as DBSession

from app.auth.dependencies import get_current_session_and_user, touch_session_activity
from app.catalogue.models import AppState, Job, JobRequirement
from app.core.errors import api_error
from app.db.models import Session as SessionModel, User
from app.db.session import get_db

router = APIRouter(prefix="/api")

JOB_TYPES = frozenset({"INTERNSHIP", "OTHER", "UNKNOWN"})
EMPLOYMENT_TIMES = frozenset({"FULL_TIME", "PART_TIME", "UNKNOWN"})
WORK_ARRANGEMENTS = frozenset({"ON_SITE", "HYBRID", "REMOTE", "UNKNOWN"})


class JobSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: uuid.UUID
    title: str
    company_name: str
    country_code: str
    location: str
    job_type: str
    employment_time: str
    work_arrangement: str
    posted_at: datetime | None
    last_imported_at: datetime
    is_active: bool


class JobPageResponse(BaseModel):
    items: list[JobSummaryResponse]
    total: int
    limit: int
    offset: int
    catalogue_revision: int


class EligibilityNoteResponse(BaseModel):
    text: str
    source_quote: str


class RequirementResponse(BaseModel):
    requirement_id: uuid.UUID
    requirement_text: str
    importance: str
    alternatives: list[str]
    source_quote: str


class JobDetailResponse(JobSummaryResponse):
    description: str
    apply_url: str
    source: str
    source_url: str
    last_verified_at: datetime | None
    eligibility_notes: list[EligibilityNoteResponse]
    requirements: list[RequirementResponse]


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _validate_query(q: str | None, limit: int, offset: int, **filters: list[str] | None) -> list[str]:
    if q is None:
        terms: list[str] = []
    else:
        q = q.strip()
        if len(q) > 200:
            raise api_error(422, "INVALID_CONTENT", "Search text is too long.", details={"fields": ["q"]})
        terms = q.casefold().split()
        if len(terms) > 10:
            raise api_error(422, "INVALID_CONTENT", "Search text has too many terms.", details={"fields": ["q"]})
    if not 1 <= limit <= 50:
        raise api_error(422, "INVALID_CONTENT", "Limit must be between 1 and 50.", details={"fields": ["limit"]})
    if not 0 <= offset <= 10_000:
        raise api_error(422, "INVALID_CONTENT", "Offset must be between 0 and 10000.", details={"fields": ["offset"]})
    allowed = {
        "job_type": JOB_TYPES,
        "employment_time": EMPLOYMENT_TIMES,
        "work_arrangement": WORK_ARRANGEMENTS,
    }
    for name, values in filters.items():
        if values is None:
            continue
        if any(value not in allowed[name] for value in values):
            raise api_error(422, "INVALID_CONTENT", "One or more filters are invalid.", details={"fields": [name]})
    return terms


def _revision(db: DBSession, requested: int | None) -> int:
    current = db.execute(select(AppState.catalogue_revision).where(AppState.id == 1)).scalar_one_or_none()
    if current is None:
        raise api_error(503, "SERVICE_UNAVAILABLE", "The catalogue is not ready.", retryable=True)
    current = int(current)
    if requested is not None and requested != current:
        raise api_error(409, "RESULTS_CHANGED", "The catalogue changed. Please restart your search.")
    return current


def _consistent_snapshot(db: DBSession) -> None:
    """Use one PostgreSQL snapshot for revision, count and page rows."""
    db.rollback()
    db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
    db.execute(text("SET LOCAL statement_timeout = '5s'"))
    db.execute(text("SET LOCAL lock_timeout = '5s'"))


def _end_snapshot_before_activity(db: DBSession) -> None:
    """Do session activity maintenance in a fresh short transaction."""
    db.rollback()


def _summary(job: Job) -> dict:
    return {
        "job_id": job.job_id,
        "title": job.title,
        "company_name": job.company_name,
        "country_code": job.country_code,
        "location": job.location,
        "job_type": job.job_type,
        "employment_time": job.employment_time,
        "work_arrangement": job.work_arrangement,
        "posted_at": job.posted_at,
        "last_imported_at": job.last_imported_at,
        "is_active": job.is_active,
    }


@router.get("/jobs", response_model=JobPageResponse)
def list_jobs(
    q: str | None = Query(default=None),
    job_type: list[str] | None = Query(default=None),
    employment_time: list[str] | None = Query(default=None),
    work_arrangement: list[str] | None = Query(default=None),
    limit: int = Query(default=20),
    offset: int = Query(default=0),
    catalogue_revision: int | None = Query(default=None),
    session_and_user: tuple[SessionModel, User] = Depends(get_current_session_and_user),
    db: DBSession = Depends(get_db),
):
    session_row, _user = session_and_user
    _consistent_snapshot(db)
    terms = _validate_query(q, limit, offset, job_type=job_type, employment_time=employment_time, work_arrangement=work_arrangement)
    revision = _revision(db, catalogue_revision)
    conditions = [Job.is_active.is_(True)]
    for term in terms:
        pattern = f"%{_escape_like(term)}%"
        conditions.append(
            func.concat_ws(" ", Job.title, Job.company_name, Job.description).ilike(pattern, escape="\\")
        )
    for column, values in ((Job.job_type, job_type), (Job.employment_time, employment_time), (Job.work_arrangement, work_arrangement)):
        if values:
            conditions.append(column.in_(values))
    base = select(Job.job_id).where(*conditions).subquery()
    total = int(db.execute(select(func.count()).select_from(base)).scalar_one())
    jobs = db.execute(
        select(Job).where(*conditions).order_by(Job.posted_at.desc().nulls_last(), Job.job_id.asc()).limit(limit).offset(offset)
    ).scalars().all()
    items = [_summary(job) for job in jobs]
    _end_snapshot_before_activity(db)
    touch_session_activity(db, session_row)
    return {"items": items, "total": total, "limit": limit, "offset": offset,
            "catalogue_revision": revision}


@router.get("/jobs/{job_id}", response_model=JobDetailResponse)
def get_job(
    job_id: str,
    session_and_user: tuple[SessionModel, User] = Depends(get_current_session_and_user),
    db: DBSession = Depends(get_db),
):
    session_row, _user = session_and_user
    _consistent_snapshot(db)
    try:
        parsed_id = uuid.UUID(job_id)
    except ValueError:
        raise api_error(404, "JOB_NOT_FOUND", "Job not found.") from None
    job = db.get(Job, parsed_id)
    if job is None:
        raise api_error(404, "JOB_NOT_FOUND", "Job not found.")
    requirements = db.execute(
        select(JobRequirement).where(JobRequirement.job_id == parsed_id).order_by(JobRequirement.ordinal)
    ).scalars().all()
    response = {
        **_summary(job), "description": job.description, "apply_url": job.apply_url, "source": job.source,
        "source_url": job.source_url, "last_verified_at": job.last_verified_at,
        "eligibility_notes": job.eligibility_notes or [],
        "requirements": [{"requirement_id": r.requirement_id, "requirement_text": r.requirement_text,
                          "importance": r.importance, "alternatives": r.alternatives or [],
                          "source_quote": r.source_quote} for r in requirements],
    }
    _end_snapshot_before_activity(db)
    touch_session_activity(db, session_row)
    return response
