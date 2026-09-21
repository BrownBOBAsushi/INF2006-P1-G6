"""Deterministic, explicit skill evidence and skill gaps (DATA_API_CONTRACT.md, "Public response shapes").

No model and no LLM. A requirement carries `evidence_skills`: the canonical skills that would evidence it, where
several entries mean OR. It is evidenced when any of them exactly matches (after normalisation and a small
versioned alias map) a WHOLE skill from the student's confirmed skills array; prose is never substring-searched
("go" must not match "google"). Evidence is self-reported and is not verified competence.

Requirements without `evidence_skills` are reported as `unassessed`: they have no explicit-skill check, only
a closest passage, and are never claimed as missing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

ALIAS_MAP_VERSION = 1
_ALIASES = {
    "postgres": "postgresql", "psql": "postgresql", "js": "javascript", "ts": "typescript", "node": "node.js",
    "nodejs": "node.js", "reactjs": "react", "react.js": "react", "vuejs": "vue", "vue.js": "vue", "k8s": "kubernetes",
    "golang": "go", "py": "python", "sklearn": "scikit-learn", "scikit learn": "scikit-learn", "tf": "tensorflow",
    "amazon web services": "aws", "gh actions": "github actions", "ci cd": "ci/cd", "cicd": "ci/cd",
    "rest api": "rest", "restful": "rest", "restful api": "rest", "rest apis": "rest", "ms excel": "excel",
    "microsoft excel": "excel", "powerbi": "power bi", "power-bi": "power bi",
}


def normalise_skill(skill: str) -> str:
    s = re.sub(r"\s+", " ", skill).strip().casefold()
    return _ALIASES.get(s, s)


@dataclass(frozen=True)
class RequirementEvidence:
    requirement_id: str
    requirement_text: str
    importance: str
    status: str                                   # "matched" | "not_evidenced" | "unassessed"
    explicit_skill_evidence: tuple[str, ...]      # confirmed skills (as the student wrote them) that evidence it
    named_skills_not_evidenced: tuple[str, ...]   # the OR group, only when nothing matched


@dataclass(frozen=True)
class SkillGapReport:
    matched: tuple[RequirementEvidence, ...]
    missing: tuple[RequirementEvidence, ...]      # contract term: named_skills_not_evidenced
    unassessed: tuple[RequirementEvidence, ...]

    def missing_skill_groups(self) -> list[tuple[str, ...]]:
        return [m.named_skills_not_evidenced for m in self.missing]


def assess_requirement(requirement_id: str, requirement_text: str, importance: str,
                       evidence_skills: tuple[str, ...] | list[str], confirmed_skills: list[str]) -> RequirementEvidence:
    if not evidence_skills:
        return RequirementEvidence(requirement_id, requirement_text, importance, "unassessed", (), ())
    by_norm: dict[str, str] = {}
    for s in confirmed_skills:
        by_norm.setdefault(normalise_skill(s), s)
    hits = tuple(dict.fromkeys(by_norm[n] for n in (normalise_skill(e) for e in evidence_skills) if n in by_norm))
    if hits:
        return RequirementEvidence(requirement_id, requirement_text, importance, "matched", hits, ())
    return RequirementEvidence(requirement_id, requirement_text, importance, "not_evidenced", (), tuple(evidence_skills))


def analyse_skill_gap(requirements, confirmed_skills: list[str]) -> SkillGapReport:
    """`requirements`: iterable of objects with requirement_id, requirement_text, importance, evidence_skills."""
    matched, missing, unassessed = [], [], []
    for r in requirements:
        ev = assess_requirement(r.requirement_id, r.requirement_text, r.importance, tuple(r.evidence_skills), confirmed_skills)
        {"matched": matched, "not_evidenced": missing, "unassessed": unassessed}[ev.status].append(ev)
    return SkillGapReport(tuple(matched), tuple(missing), tuple(unassessed))
