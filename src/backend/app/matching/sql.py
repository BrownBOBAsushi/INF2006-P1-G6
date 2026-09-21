"""The contract's ranking computed inside PostgreSQL/pgvector (exact, no ANN index).

Pipeline in one statement (DATA_API_CONTRACT.md "Ranking implementation contract"):
  1. filter jobs first (active + optional job_type / employment_time / work_arrangement);
  2. for every alternative vector of every REQUIRED requirement, MAX cosine similarity over the authenticated
     user's current chunks (`1 - (a <=> b)`);
  3. per requirement, MAX over its alternatives (OR); a requirement missing any alternative vector, or vectors
     of another embedding_version, makes the job incomplete and it is omitted;
  4. per job, AVG over REQUIRED requirements (AND);
  5. ORDER BY score DESC, job_id ASC; only NOW LIMIT/OFFSET. There is no LIMIT before step 4.

The same computation exists in app.matching.scoring; tests assert both give the same ranking.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

RANK_SQL = text("""
WITH cand AS (
    SELECT j.job_id FROM jobs j
    WHERE j.is_active
      AND (CAST(:job_types AS text[]) IS NULL OR j.job_type = ANY(CAST(:job_types AS text[])))
      AND (CAST(:employment_times AS text[]) IS NULL OR j.employment_time = ANY(CAST(:employment_times AS text[])))
      AND (CAST(:work_arrangements AS text[]) IS NULL OR j.work_arrangement = ANY(CAST(:work_arrangements AS text[])))
),
req AS (
    SELECT r.job_id, r.requirement_id, GREATEST(jsonb_array_length(r.alternatives), 1) AS expected_alts
    FROM job_requirements r JOIN cand USING (job_id)
    WHERE r.importance = 'REQUIRED'
),
alt_best AS (
    SELECT re.requirement_id, re.alternative_index, MAX(1 - (re.embedding <=> c.embedding)) AS sim
    FROM requirement_embeddings re
    JOIN req ON req.requirement_id = re.requirement_id
    JOIN resume_chunks c ON c.user_id = :user_id
                        AND c.profile_revision = :profile_revision
                        AND c.embedding_version = :embedding_version
    WHERE re.embedding_version = :embedding_version
    GROUP BY re.requirement_id, re.alternative_index
),
req_score AS (
    SELECT req.job_id, req.requirement_id, req.expected_alts,
           COUNT(ab.alternative_index) AS have_alts, MAX(ab.sim) AS score
    FROM req LEFT JOIN alt_best ab ON ab.requirement_id = req.requirement_id
    GROUP BY req.job_id, req.requirement_id, req.expected_alts
),
job_score AS (
    SELECT job_id, AVG(score) AS score
    FROM req_score
    GROUP BY job_id
    HAVING BOOL_AND(have_alts = expected_alts)
)
SELECT job_id, score, COUNT(*) OVER () AS total,
       (SELECT COUNT(DISTINCT job_id) FROM req) AS considered
FROM job_score
ORDER BY ROUND(score::numeric, 9) DESC, job_id ASC
LIMIT :limit OFFSET :offset
""")

CONSIDERED_SQL = text("""
SELECT COUNT(DISTINCT r.job_id) FROM job_requirements r JOIN jobs j ON j.job_id = r.job_id
WHERE j.is_active AND r.importance = 'REQUIRED'
  AND (CAST(:job_types AS text[]) IS NULL OR j.job_type = ANY(CAST(:job_types AS text[])))
  AND (CAST(:employment_times AS text[]) IS NULL OR j.employment_time = ANY(CAST(:employment_times AS text[])))
  AND (CAST(:work_arrangements AS text[]) IS NULL OR j.work_arrangement = ANY(CAST(:work_arrangements AS text[])))
""")

CLOSEST_PASSAGE_SQL = text("""
SELECT DISTINCT ON (r.requirement_id)
       r.requirement_id, r.job_id, c.section, c.entry_index, c.chunk_index, c.text,
       1 - (re.embedding <=> c.embedding) AS sim
FROM job_requirements r
JOIN requirement_embeddings re ON re.requirement_id = r.requirement_id AND re.embedding_version = :embedding_version
JOIN resume_chunks c ON c.user_id = :user_id AND c.profile_revision = :profile_revision
                    AND c.embedding_version = :embedding_version
WHERE r.job_id = ANY(CAST(:job_ids AS uuid[]))
ORDER BY r.requirement_id, sim DESC, c.section, c.entry_index, c.chunk_index, re.alternative_index
""")


@dataclass(frozen=True)
class SqlRankRow:
    job_id: str
    score: float


@dataclass(frozen=True)
class SqlRankPage:
    rows: list[SqlRankRow]
    total: int
    omitted_incomplete_or_unscorable: int


def rank_jobs_sql(session: Session, *, user_id, profile_revision: int, embedding_version: str,
                  limit: int = 5, offset: int = 0, job_types: list[str] | None = None,
                  employment_times: list[str] | None = None, work_arrangements: list[str] | None = None) -> SqlRankPage:
    res = session.execute(RANK_SQL, {
        "user_id": user_id, "profile_revision": profile_revision, "embedding_version": embedding_version,
        "limit": limit, "offset": offset, "job_types": job_types, "employment_times": employment_times,
        "work_arrangements": work_arrangements}).all()
    probe = res
    if not res and offset > 0:      # offset past the end: fetch one row from the start only to learn the totals
        probe = session.execute(RANK_SQL, {
            "user_id": user_id, "profile_revision": profile_revision, "embedding_version": embedding_version,
            "limit": 1, "offset": 0, "job_types": job_types, "employment_times": employment_times,
            "work_arrangements": work_arrangements}).all()
    total = int(probe[0].total) if probe else 0
    if probe:
        considered = int(probe[0].considered)
    else:  # nothing ranks at all (every job incomplete or no candidates): count candidates separately
        considered = int(session.execute(CONSIDERED_SQL, {
            "job_types": job_types, "employment_times": employment_times, "work_arrangements": work_arrangements}).scalar() or 0)
    return SqlRankPage([SqlRankRow(str(r.job_id), float(r.score)) for r in res], total, max(considered - total, 0))


def closest_passages_sql(session: Session, *, user_id, profile_revision: int, embedding_version: str, job_ids: list[str]):
    """Closest chunk per requirement (REQUIRED and PREFERRED) for the returned page only."""
    return session.execute(CLOSEST_PASSAGE_SQL, {
        "user_id": user_id, "profile_revision": profile_revision, "embedding_version": embedding_version,
        "job_ids": job_ids}).all()
