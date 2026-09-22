"""ResumeContent validation and canonical hashing (DATA_API_CONTRACT.md "resume_profiles").

Fixed shape, extra fields rejected. Limits: 100 unique skills of <=100 chars; <=20 projects, <=20 experience,
<=10 education; titles/qualifications <=200; descriptions/details <=5,000; technologies <=30 x 100; whole
canonical text <=50,000 characters. All arrays may be empty but not all content may be blank.
"""
from __future__ import annotations

import hashlib
import json

from app.processing.errors import ProcessingError

_ENTRY_KEYS = {"title", "description", "technologies"}
_EDU_KEYS = {"qualification", "details"}
_TOP_KEYS = {"skills", "projects", "experience", "education"}


def _bad(reason: str) -> ProcessingError:
    return ProcessingError("INVALID_CONTENT", reason)


def _check_str(value, limit: int, reason: str) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise _bad(reason)
    return value


def validate_resume_content(content: dict) -> dict:
    """Return the content unchanged if valid; raise ProcessingError('INVALID_CONTENT', reason) otherwise."""
    if not isinstance(content, dict) or set(content) != _TOP_KEYS:
        raise _bad("shape")
    skills = content["skills"]
    if not isinstance(skills, list) or len(skills) > 100:
        raise _bad("skills_count")
    seen = set()
    for s in skills:
        _check_str(s, 100, "skill_length")
        seen.add(s.casefold())
    if len(seen) != len(skills):
        raise _bad("skills_duplicate")
    for key, cap in (("projects", 20), ("experience", 20)):
        entries = content[key]
        if not isinstance(entries, list) or len(entries) > cap:
            raise _bad(f"{key}_count")
        for e in entries:
            if not isinstance(e, dict) or set(e) != _ENTRY_KEYS:
                raise _bad(f"{key}_shape")
            _check_str(e["title"], 200, f"{key}_title")
            _check_str(e["description"], 5000, f"{key}_description")
            tech = e["technologies"]
            if not isinstance(tech, list) or len(tech) > 30:
                raise _bad(f"{key}_technologies")
            for t in tech:
                _check_str(t, 100, f"{key}_technology")
    edu = content["education"]
    if not isinstance(edu, list) or len(edu) > 10:
        raise _bad("education_count")
    for e in edu:
        if not isinstance(e, dict) or set(e) != _EDU_KEYS:
            raise _bad("education_shape")
        _check_str(e["qualification"], 200, "education_qualification")
        _check_str(e["details"], 5000, "education_details")
    if len(canonical_text(content)) > 50_000:
        raise _bad("total_length")
    if not canonical_text(content).strip():
        raise _bad("blank")
    return content


def canonical_text(content: dict) -> str:
    parts = list(content.get("skills", []))
    for key in ("projects", "experience"):
        for e in content.get(key, []):
            parts += [e.get("title", ""), e.get("description", ""), *e.get("technologies", [])]
    for e in content.get("education", []):
        parts += [e.get("qualification", ""), e.get("details", "")]
    return "\n".join(parts)


def content_hash(content: dict) -> str:
    """SHA-256 of the canonical JSON serialisation (sorted keys, no whitespace variance)."""
    blob = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
