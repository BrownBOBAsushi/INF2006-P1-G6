"""Match explanations built only from matching evidence (closest passages, exact skill matches, gaps).

Every statement names the requirement and passage it comes from. Nothing is inferred beyond that: closest
passages are labelled as closest passages (not proof), skill evidence is labelled self-reported, and the text
never says a candidate is qualified or likely to succeed. The public projection has no numeric scores
(contract: "Do not return numeric cosine or invent strength labels"); the internal trace keeps them.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.matching.scoring import JobVectors, requirement_match
from app.matching.skill_gap import SkillGapReport, analyse_skill_gap

DISCLAIMER = ("This is a recommendation to support your own decision. It is not an assessment of your suitability "
              "and not a hiring decision. Check the job requirements yourself.")
_EXCERPT_CHARS = 200


@dataclass(frozen=True)
class MatchExplanation:
    job_id: str
    requirements: tuple[dict, ...]        # public per-requirement evidence (contract MatchPage shape)
    statements: tuple[str, ...]           # human-readable, each traceable to a requirement
    skill_gap: SkillGapReport
    trace: tuple[dict, ...]               # INTERNAL: similarity per requirement, chunk and alternative index

    def to_public(self) -> dict:
        return {"job_id": self.job_id, "requirements": list(self.requirements),
                "statements": list(self.statements), "disclaimer": DISCLAIMER}


def _excerpt(chunk_text: str) -> str:
    body = chunk_text.split("\n", 1)[1] if "\n" in chunk_text else chunk_text   # drop the "Project: title" heading
    body = " ".join(body.split())
    return body if len(body) <= _EXCERPT_CHARS else body[:_EXCERPT_CHARS].rstrip() + "..."


def explain_job(job: JobVectors, chunks: np.ndarray, chunk_meta: list[dict], confirmed_skills: list[str]) -> MatchExplanation:
    """chunk_meta[i] = {"text", "section", "entry_index"} for row i of `chunks`."""
    gap = analyse_skill_gap(job.requirements, confirmed_skills)
    evidence = {e.requirement_id: e for group in (gap.matched, gap.missing, gap.unassessed) for e in group}
    public, statements, trace = [], [], []
    for r in job.requirements:
        m = requirement_match(chunks, r)
        meta = chunk_meta[m.chunk_index]
        ev = evidence[r.requirement_id]
        public.append({
            "requirement_id": r.requirement_id, "importance": r.importance,
            "closest_passage": {"text": meta["text"], "section": meta["section"], "entry_index": meta["entry_index"]},
            "explicit_skill_evidence": list(ev.explicit_skill_evidence),
            "named_skills_not_evidenced": list(ev.named_skills_not_evidenced),
        })
        trace.append({"requirement_id": r.requirement_id, "similarity": round(m.score, 4),
                      "chunk_index": m.chunk_index, "alternative_index": m.alternative_index})
        kind = "required" if r.importance == "REQUIRED" else "preferred"
        statements.append(
            f"Closest passage for the {kind} requirement \"{r.requirement_text}\" is from your "
            f"{meta['section'].lower()} entry {meta['entry_index'] + 1}: \"{_excerpt(meta['text'])}\" "
            "This is only the closest passage, not proof that the requirement is fulfilled.")
        if ev.status == "matched":
            statements.append(f"For \"{r.requirement_text}\", your confirmed skills include "
                              f"{', '.join(ev.explicit_skill_evidence)} (self-reported).")
        elif ev.status == "not_evidenced":
            statements.append(f"For \"{r.requirement_text}\", none of {', '.join(ev.named_skills_not_evidenced)} "
                              "appears in your confirmed skills.")
    statements.append(DISCLAIMER)
    return MatchExplanation(job.job_id, tuple(public), tuple(statements), gap, tuple(trace))
