"""Load catalogue vectors from the database into the exact in-memory matcher's input shape."""
from __future__ import annotations

from collections import defaultdict

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalogue.models import Job, JobRequirement, RequirementEmbedding
from app.matching.scoring import JobVectors, RequirementVectors


def load_job_vectors(session: Session, embedding_version: str, *, active_only: bool = True) -> list[JobVectors]:
    """All (active) jobs with their requirements and the vectors stored for `embedding_version`.

    A requirement whose stored alternative vectors are missing (or from another version) gets a short vector
    matrix, which the scorer treats as incomplete and omits the job instead of averaging what is left.
    """
    jq = select(Job.job_id).order_by(Job.job_id)
    if active_only:
        jq = jq.where(Job.is_active.is_(True))
    job_ids = [r[0] for r in session.execute(jq)]
    reqs = session.execute(select(JobRequirement).where(JobRequirement.job_id.in_(job_ids))
                           .order_by(JobRequirement.job_id, JobRequirement.ordinal)).scalars().all()
    emb = defaultdict(dict)
    for e in session.execute(select(RequirementEmbedding).where(RequirementEmbedding.embedding_version == embedding_version)).scalars():
        emb[e.requirement_id][e.alternative_index] = np.asarray(e.embedding, dtype=np.float32)
    by_job: dict = defaultdict(list)
    for r in reqs:
        texts = tuple(r.alternatives) if r.alternatives else (r.requirement_text,)
        got = [emb[r.requirement_id][i] for i in range(len(texts)) if i in emb[r.requirement_id]]
        mat = np.stack(got) if len(got) == len(texts) else np.zeros((len(got), 384), dtype=np.float32)
        by_job[r.job_id].append(RequirementVectors(str(r.requirement_id), r.ordinal, r.importance, r.requirement_text,
                                                   texts, mat, tuple(r.evidence_skills), r.source_quote))
    return [JobVectors(str(j), tuple(by_job[j])) for j in job_ids]
