"""Exact requirement-level scoring (DATA_API_CONTRACT.md "Ranking implementation contract").

    requirement_score(r) = max over alternatives a in A(r) and resume chunks c in C of cosine(a, c)
    job_score            = mean of requirement_score(r) over the job's REQUIRED requirements

- OR: alternatives of one requirement are combined by max, so "Python OR Java" needs only one of them.
- AND: separate requirements are separate rows; each contributes to the mean, so all are needed for a high score.
- PREFERRED requirements never affect ranking.
- Ranking sorts by score descending, job_id ascending, and only THEN takes the page. There is no early
  top-k over raw vector similarities: that would change the result.
- A job with no REQUIRED requirement, or whose requirement/alternative vectors are incomplete, is omitted
  and counted in the diagnostics; the mean is never taken over "just the available" requirements.
- Logically duplicate requirements (same normalised text and alternatives) count once.

Vectors are expected to be unit-normalised, so cosine is a dot product.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass

import numpy as np

SCORE_TIE_DECIMALS = 9   # scores equal to this many decimals tie, then job_id ascending decides


@dataclass(frozen=True)
class RequirementVectors:
    requirement_id: str
    ordinal: int
    importance: str                         # "REQUIRED" | "PREFERRED"
    requirement_text: str
    alternatives: tuple[str, ...]           # texts that were embedded (the alternatives, or requirement_text alone)
    vectors: np.ndarray                     # (len(alternatives), dim) unit vectors
    evidence_skills: tuple[str, ...] = ()
    source_quote: str = ""


@dataclass(frozen=True)
class JobVectors:
    job_id: str
    requirements: tuple[RequirementVectors, ...]


@dataclass(frozen=True)
class RequirementMatch:
    requirement_id: str
    ordinal: int
    importance: str
    score: float                            # internal only; never returned to the browser
    chunk_index: int                        # index into the chunk list (closest passage)
    alternative_index: int


@dataclass(frozen=True)
class JobMatch:
    job_id: str
    score: float                            # internal only
    requirements: tuple[RequirementMatch, ...]   # REQUIRED requirements that produced the score


@dataclass(frozen=True)
class RankingDiagnostics:
    considered: int = 0
    omitted_no_required: int = 0
    omitted_incomplete: int = 0


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _dedupe_key(r: RequirementVectors) -> tuple:
    return _norm(r.requirement_text), tuple(sorted(_norm(a) for a in r.alternatives))


def requirement_match(chunks: np.ndarray, req: RequirementVectors) -> RequirementMatch:
    """max over alternatives x chunks of cosine similarity; ties resolve to the lowest indexes."""
    sims = req.vectors @ chunks.T                      # (alternatives, chunks)
    flat = int(np.argmax(sims))                        # first maximum in row-major order: deterministic
    a_idx, c_idx = divmod(flat, sims.shape[1])
    return RequirementMatch(req.requirement_id, req.ordinal, req.importance, float(sims[a_idx, c_idx]), c_idx, a_idx)


def score_job(chunks: np.ndarray, job: JobVectors) -> tuple[JobMatch | None, str]:
    """Return (JobMatch, "") or (None, reason) with reason in {"no_required", "incomplete"}."""
    required, seen = [], set()
    for r in job.requirements:
        if r.importance != "REQUIRED":
            continue
        key = _dedupe_key(r)
        if key in seen:
            continue
        seen.add(key)
        required.append(r)
    if not required:
        return None, "no_required"
    for r in required:
        if r.vectors.ndim != 2 or r.vectors.shape[0] == 0 or r.vectors.shape[0] != len(r.alternatives) \
                or r.vectors.shape[1] != chunks.shape[1]:
            return None, "incomplete"
    matches = tuple(requirement_match(chunks, r) for r in required)
    return JobMatch(job.job_id, statistics.fmean(m.score for m in matches), matches), ""


def rank_key(m: JobMatch) -> tuple:
    return (-round(m.score, SCORE_TIE_DECIMALS), m.job_id)


def rank_jobs(chunks: np.ndarray, jobs: list[JobVectors], top_k: int = 5, offset: int = 0
              ) -> tuple[list[JobMatch], int, RankingDiagnostics]:
    """Aggregate every job first, sort, then slice. Returns (page, total_ranked, diagnostics)."""
    if chunks.ndim != 2 or chunks.shape[0] == 0:
        raise ValueError("at least one resume chunk vector is required")
    scored, no_req, incomplete = [], 0, 0
    for job in jobs:
        m, why = score_job(chunks, job)
        if m is not None:
            scored.append(m)
        elif why == "no_required":
            no_req += 1
        else:
            incomplete += 1
    scored.sort(key=rank_key)
    return scored[offset:offset + top_k], len(scored), RankingDiagnostics(len(jobs), no_req, incomplete)
