"""Catalogue import: validate whole batch, compute embeddings, then upsert atomically.

Behaviour required by DATA_API_CONTRACT.md:
- The whole batch is validated (and every text checked against the token limit) BEFORE any write; an invalid
  batch or embedding failure leaves the previous catalogue untouched.
- Identity is (source, source_job_id): re-importing the same file creates nothing and rewrites nothing.
- `content_hash` covers every imported field. A changed hash updates the job; vectors are reused whenever the
  text that was embedded is unchanged, so display-only changes (title, dates, URLs) regenerate no vectors.
- Absence from a file never deactivates a job; `is_active=false` in the file is the only way to close one.
- Identical normalised requirements within a job are deduplicated (REQUIRED wins over PREFERRED).
- `catalogue_revision` is incremented once, in the same transaction, only if something changed.
- `last_verified_at` is only what the file says; the importer never fills it.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol, Sequence

import numpy as np
from sqlalchemy import delete, select, tuple_
from sqlalchemy.orm import Session

from app.catalogue.models import AppState, Job, JobRequirement, RequirementEmbedding
from app.catalogue.schema import DEFAULT_ALLOWED_SOURCES, ImportIssue, JobIn, RequirementIn, normalise_ws, validate_import
from app.processing.errors import EmptyTextError, TokenLimitError


class Embedder(Protocol):
    version: str

    def validate_text(self, text: str) -> None: ...
    def embed(self, texts: Sequence[str]) -> np.ndarray: ...


@dataclass
class ImportSummary:
    ok: bool
    dry_run: bool
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    embeddings_computed: int = 0
    embeddings_reused: int = 0
    requirements_deduplicated: int = 0
    catalogue_revision: int | None = None
    issues: list[ImportIssue] = field(default_factory=list)


@dataclass
class _Existing:
    job_id: uuid.UUID
    content_hash: str
    vectors: dict[str, tuple[np.ndarray, str]]      # embedded text -> (vector, embedding_version)


def requirement_texts(req: RequirementIn) -> list[str]:
    """Texts embedded for a requirement: its OR alternatives, or requirement_text once."""
    return list(req.alternatives) if req.alternatives else [req.requirement_text]


def dedupe_requirements(job: JobIn) -> tuple[JobIn, int]:
    kept: list[RequirementIn] = []
    index: dict[tuple, int] = {}
    for r in job.requirements:
        key = (normalise_ws(r.requirement_text).casefold(), tuple(sorted(normalise_ws(a).casefold() for a in r.alternatives)))
        if key not in index:
            index[key] = len(kept)
            kept.append(r)
        elif r.importance == "REQUIRED" and kept[index[key]].importance == "PREFERRED":
            kept[index[key]] = kept[index[key]].model_copy(update={"importance": "REQUIRED"})
    return job.model_copy(update={"requirements": kept}), len(job.requirements) - len(kept)


def job_content_hash(job: JobIn) -> str:
    blob = json.dumps(job.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _load_existing(session: Session, keys: list[tuple[str, str]]) -> dict[tuple[str, str], _Existing]:
    if not keys:
        return {}
    jobs = session.execute(select(Job.job_id, Job.source, Job.source_job_id, Job.content_hash)
                           .where(tuple_(Job.source, Job.source_job_id).in_(keys))).all()
    by_id = {j.job_id: _Existing(j.job_id, j.content_hash, {}) for j in jobs}
    rows = session.execute(
        select(JobRequirement.job_id, RequirementEmbedding.text, RequirementEmbedding.embedding,
               RequirementEmbedding.embedding_version)
        .join(RequirementEmbedding, RequirementEmbedding.requirement_id == JobRequirement.requirement_id)
        .where(JobRequirement.job_id.in_(list(by_id)))).all()
    for job_id, text_, vec, version in rows:
        by_id[job_id].vectors[text_] = (np.asarray(vec, dtype=np.float32), version)
    return {(j.source, j.source_job_id): by_id[j.job_id] for j in jobs}


def import_catalogue(session: Session | None, raw: bytes | str | dict, embedder: Embedder | None, *,
                     allowed_sources: tuple[str, ...] = DEFAULT_ALLOWED_SOURCES, dry_run: bool = False) -> ImportSummary:
    """Validate and import a catalogue file. `session=None` (dry-run only) skips the database comparison."""
    if not dry_run and (session is None or embedder is None):
        raise ValueError("a database session and an embedder are required for a real import")
    jobs, issues = validate_import(raw, allowed_sources)
    if issues:
        return ImportSummary(ok=False, dry_run=dry_run, issues=issues)

    deduped, removed = [], 0
    for j in jobs:
        dj, n = dedupe_requirements(j)
        deduped.append(dj)
        removed += n
    keys = [(j.source, j.source_job_id) for j in deduped]
    existing = _load_existing(session, keys) if session is not None else {}

    plan: list[tuple[JobIn, str, _Existing | None, str]] = []   # (job, hash, existing, status)
    version = embedder.version if embedder is not None else None
    for j in deduped:
        h = job_content_hash(j)
        ex = existing.get((j.source, j.source_job_id))
        wanted = {t for r in j.requirements for t in requirement_texts(r)}
        if ex is None:
            status = "created"
        elif ex.content_hash == h and version is not None and all(
                t in ex.vectors and ex.vectors[t][1] == version for t in wanted):
            status = "unchanged"
        else:
            status = "updated"
        plan.append((j, h, ex, status))

    summary = ImportSummary(ok=True, dry_run=dry_run, requirements_deduplicated=removed,
                            created=sum(p[3] == "created" for p in plan), updated=sum(p[3] == "updated" for p in plan),
                            unchanged=sum(p[3] == "unchanged" for p in plan))
    if embedder is None:                                    # dry-run without a model: counts only
        return summary

    # Embeddings first (outside any transaction): reuse by embedded text, compute the rest in one batch.
    reuse: dict[str, np.ndarray] = {}
    needed: dict[str, None] = {}
    for idx, (j, _, ex, status) in enumerate(plan):
        if status == "unchanged":
            continue
        for ri, r in enumerate(j.requirements):
            for t in requirement_texts(r):
                if ex is not None and t in ex.vectors and ex.vectors[t][1] == version:
                    reuse.setdefault(t, ex.vectors[t][0])
                elif t not in reuse and t not in needed:
                    try:
                        embedder.validate_text(t)
                    except (TokenLimitError, EmptyTextError) as e:
                        code = "token_limit_exceeded" if isinstance(e, TokenLimitError) else "empty_text"
                        summary.issues.append(ImportIssue(index=idx, source_job_id=j.source_job_id,
                                                          field=f"requirements.{ri}", code=code))
                    needed[t] = None
    if summary.issues:
        summary.ok = False
        return summary
    new_vectors = dict(zip(needed, embedder.embed(list(needed)))) if needed else {}
    for t in list(new_vectors):
        if t in reuse:
            del new_vectors[t]
    vectors = {**reuse, **new_vectors}
    summary.embeddings_computed = len(new_vectors)
    summary.embeddings_reused = len(reuse)
    if dry_run:
        return summary

    try:
        state = session.execute(select(AppState).where(AppState.id == 1).with_for_update()).scalar_one_or_none()
        if state is None:
            state = AppState(id=1, catalogue_revision=0)
            session.add(state)
            session.flush()
        now = datetime.now(timezone.utc)
        for j, h, ex, status in plan:
            if status == "unchanged":
                continue
            fields = dict(title=j.title, company_name=j.company_name, country_code=j.country_code, location=j.location,
                          description=j.description, apply_url=j.apply_url, source_url=j.source_url, job_type=j.job_type,
                          employment_time=j.employment_time, work_arrangement=j.work_arrangement,
                          eligibility_notes=[n.model_dump() for n in j.eligibility_notes], posted_at=j.posted_at,
                          last_verified_at=j.last_verified_at, is_active=j.is_active, content_hash=h, last_imported_at=now)
            if ex is None:
                row = Job(job_id=uuid.uuid4(), source=j.source, source_job_id=j.source_job_id, **fields)
                session.add(row)
            else:
                row = session.get(Job, ex.job_id)
                for k, v in fields.items():
                    setattr(row, k, v)
                session.execute(delete(JobRequirement).where(JobRequirement.job_id == row.job_id))  # cascades to vectors
            session.flush()
            for ordinal, r in enumerate(j.requirements):
                req = JobRequirement(requirement_id=uuid.uuid4(), job_id=row.job_id, ordinal=ordinal,
                                     requirement_text=r.requirement_text, importance=r.importance,
                                     alternatives=list(r.alternatives), source_quote=r.source_quote,
                                     evidence_skills=list(r.evidence_skills))
                session.add(req)
                session.flush()
                for alt_index, t in enumerate(requirement_texts(r)):
                    session.add(RequirementEmbedding(embedding_id=uuid.uuid4(), requirement_id=req.requirement_id,
                                                     alternative_index=alt_index, text=t, embedding=vectors[t],
                                                     embedding_version=version))
        if summary.created or summary.updated:
            state.catalogue_revision += 1
        session.commit()
        summary.catalogue_revision = int(state.catalogue_revision)
    except Exception:
        session.rollback()
        raise
    return summary
