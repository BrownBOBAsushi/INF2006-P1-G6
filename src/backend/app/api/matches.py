from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DBSession

from app.api.jobs import (
    JobSummaryResponse,
    _revision,
    _summary,
    _escape_like,
    _consistent_snapshot,
    _end_snapshot_before_activity,
    _validate_query,
)
from app.auth.dependencies import get_current_session_and_user, touch_session_activity
from app.catalogue.models import Job, JobRequirement
from app.core.errors import api_error
from app.db.models import ResumeChunk, ResumeProfile, Session as SessionModel, User
from app.db.session import get_db
from app.matching.skill_gap import analyse_skill_gap
from app.matching.sql import closest_passages_sql, rank_jobs_sql
from app.processing.config import EMBEDDING_VERSION

router = APIRouter(prefix="/api")
log = logging.getLogger(__name__)


class ClosestPassageResponse(BaseModel):
    text: str
    section: str
    entry_index: int


class MatchRequirementResponse(BaseModel):
    requirement_id: str
    requirement_text: str
    importance: str
    closest_passage: ClosestPassageResponse
    explicit_skill_evidence: list[str]
    named_skills_not_evidenced: list[str]


class MatchItemResponse(BaseModel):
    job: JobSummaryResponse
    requirements: list[MatchRequirementResponse]
    eligibility_notes: list[dict]


class MatchPageResponse(BaseModel):
    items: list[MatchItemResponse]
    total: int
    limit: int
    offset: int
    catalogue_revision: int
    profile_revision: int


def _matching_resume(db: DBSession, user: User, requested_revision: int | None) -> tuple[ResumeProfile, int]:
    profile = db.get(ResumeProfile, user.user_id)
    if profile is None:
        raise api_error(422, "RESUME_REQUIRED", "Save a resume before viewing recommendations.")
    if requested_revision is not None and requested_revision != profile.revision:
        raise api_error(409, "RESULTS_CHANGED", "Your resume changed. Please restart recommendations.")
    if profile.embedding_version != EMBEDDING_VERSION:
        raise api_error(503, "MODEL_VERSION_UNAVAILABLE", "Recommendations are temporarily unavailable.", retryable=True)
    chunk_count = int(db.execute(
        select(func.count()).select_from(ResumeChunk).where(
            ResumeChunk.user_id == user.user_id,
            ResumeChunk.profile_revision == profile.revision,
            ResumeChunk.embedding_version == EMBEDDING_VERSION,
        )
    ).scalar_one())
    if chunk_count == 0:
        raise api_error(422, "INSUFFICIENT_RESUME_INFORMATION", "Add a project or experience entry to get recommendations.")
    return profile, int(profile.revision)


@router.get("/matches", response_model=MatchPageResponse)
def list_matches(
    q: str | None = Query(default=None),
    job_type: list[str] | None = Query(default=None),
    employment_time: list[str] | None = Query(default=None),
    work_arrangement: list[str] | None = Query(default=None),
    limit: int = Query(default=20),
    offset: int = Query(default=0),
    catalogue_revision: int | None = Query(default=None),
    profile_revision: int | None = Query(default=None),
    session_and_user: tuple[SessionModel, User] = Depends(get_current_session_and_user),
    db: DBSession = Depends(get_db),
):
    session_row, user = session_and_user
    _consistent_snapshot(db)
    terms = _validate_query(q, limit, offset, job_type=job_type, employment_time=employment_time, work_arrangement=work_arrangement)
    # The SQL ranking helper accepts only the three indexed dimensions. Apply
    # literal search here as a candidate restriction in a separate query.
    catalogue_rev = _revision(db, catalogue_revision)
    profile, current_profile_revision = _matching_resume(db, user, profile_revision)
    search_job_ids = None
    if terms:
        search_job_ids = None
        for term in terms:
            pattern = f"%{_escape_like(term)}%"
            rows = db.execute(select(Job.job_id).where(
                Job.is_active.is_(True),
                func.concat_ws(" ", Job.title, Job.company_name, Job.description).ilike(pattern, escape="\\"),
            )).scalars().all()
            current = set(rows)
            search_job_ids = current if search_job_ids is None else search_job_ids & current
        if not search_job_ids:
            _end_snapshot_before_activity(db)
            touch_session_activity(db, session_row)
            return {"items": [], "total": 0, "limit": limit, "offset": offset,
                    "catalogue_revision": catalogue_rev, "profile_revision": current_profile_revision}

    # rank_jobs_sql handles active/filter predicates and exact aggregate-before-page.
    page = rank_jobs_sql(
        db, user_id=user.user_id, profile_revision=current_profile_revision, embedding_version=EMBEDDING_VERSION,
        limit=limit, offset=offset, job_types=job_type, employment_times=employment_time,
        work_arrangements=work_arrangement,
        job_ids=[str(i) for i in search_job_ids] if search_job_ids is not None else None,
    )
    ranked, total = page.rows, page.total
    log.info("matches_omitted_incomplete_or_unscorable count=%d", page.omitted_incomplete_or_unscorable)
    ids = [row.job_id for row in ranked]
    jobs = db.execute(select(Job).where(Job.job_id.in_(ids))).scalars().all() if ids else []
    by_id = {str(job.job_id): job for job in jobs}
    reqs = db.execute(
        select(JobRequirement).where(JobRequirement.job_id.in_(ids)).order_by(JobRequirement.job_id, JobRequirement.ordinal)
    ).scalars().all() if ids else []
    reqs_by_job: dict[str, list[JobRequirement]] = {}
    for req in reqs:
        reqs_by_job.setdefault(str(req.job_id), []).append(req)
    passages = closest_passages_sql(db, user_id=user.user_id, profile_revision=current_profile_revision,
                                    embedding_version=EMBEDDING_VERSION, job_ids=ids) if ids else []
    passage_by_req = {str(row.requirement_id): row for row in passages}
    skills = (profile.content or {}).get("skills", [])
    items = []
    for row in ranked:
        job = by_id.get(row.job_id)
        if job is None:
            continue
        requirements = reqs_by_job.get(row.job_id, [])
        evidence = analyse_skill_gap(requirements, skills)
        # ORM UUIDs and the SQL page identifiers have different concrete
        # types; normalize both at the response boundary.
        evidence_by_id = {str(item.requirement_id): item for group in (evidence.matched, evidence.missing, evidence.unassessed) for item in group}
        public_requirements = []
        for req in requirements:
            passage = passage_by_req.get(str(req.requirement_id))
            if passage is None:
                continue
            ev = evidence_by_id[str(req.requirement_id)]
            public_requirements.append({
                "requirement_id": str(req.requirement_id), "requirement_text": req.requirement_text,
                "importance": req.importance,
                "closest_passage": {"text": passage.text, "section": passage.section, "entry_index": passage.entry_index},
                "explicit_skill_evidence": list(ev.explicit_skill_evidence),
                "named_skills_not_evidenced": list(ev.named_skills_not_evidenced),
            })
        items.append({"job": _summary(job), "requirements": public_requirements,
                      "eligibility_notes": job.eligibility_notes or []})
    _end_snapshot_before_activity(db)
    touch_session_activity(db, session_row)
    return {"items": items, "total": total, "limit": limit, "offset": offset,
            "catalogue_revision": catalogue_rev, "profile_revision": current_profile_revision}
