"""Top-K recommendations with evidence: exact aggregation over every job, then explain only the returned page."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.matching.explain import MatchExplanation, explain_job
from app.matching.scoring import JobMatch, JobVectors, RankingDiagnostics, rank_jobs
from app.processing.errors import ProcessingError


@dataclass(frozen=True)
class Recommendation:
    rank: int                     # 1-based position in the full ranking (offset + index + 1)
    job_id: str
    match: JobMatch               # INTERNAL scores; the API must expose only `explanation.to_public()`
    explanation: MatchExplanation


@dataclass(frozen=True)
class RecommendationPage:
    items: list[Recommendation]
    total: int
    diagnostics: RankingDiagnostics


def recommend(chunk_vectors: np.ndarray, chunk_meta: list[dict], jobs: list[JobVectors], confirmed_skills: list[str],
              top_k: int = 5, offset: int = 0) -> RecommendationPage:
    """Rank all jobs by the contract formula and explain the requested page.

    Raises ProcessingError("INSUFFICIENT_RESUME_INFORMATION") when the profile has no chunks (a skills-only or
    education-only profile can be saved but cannot be matched). Returns fewer than `top_k` items when fewer jobs exist.
    """
    if chunk_vectors.ndim != 2 or chunk_vectors.shape[0] == 0 or len(chunk_meta) != chunk_vectors.shape[0]:
        raise ProcessingError("INSUFFICIENT_RESUME_INFORMATION", "no_chunks")
    page, total, diag = rank_jobs(chunk_vectors, jobs, top_k=top_k, offset=offset)
    by_id = {j.job_id: j for j in jobs}
    items = [Recommendation(offset + i + 1, m.job_id, m, explain_job(by_id[m.job_id], chunk_vectors, chunk_meta, confirmed_skills))
             for i, m in enumerate(page)]
    return RecommendationPage(items, total, diag)
