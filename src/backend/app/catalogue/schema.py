"""Validation of the catalogue import file (DATA_API_CONTRACT.md "Catalogue import contract").

`{"schema_version": 1, "jobs": [...]}`, at most 1,000 jobs per batch. The whole batch is validated before any
write. Issues carry only the job index, source_job_id, field path and an error code, never descriptions or
input values, so dry-run output and logs cannot leak job text.

Requirement semantics: `alternatives` are OR (0-10 strings; empty means requirement_text is embedded once); an AND
is expressed as separate requirement rows; the importance is REQUIRED or PREFERRED. The contract defines no
free-text operator syntax, so none is parsed.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

MAX_BATCH_JOBS = 1000
DEFAULT_ALLOWED_SOURCES = ("SYNTHETIC",)   # other sources need explicit provenance/permission (allowed_sources=...)
# ISO 3166-1 alpha-2 codes available to the catalogue. ``ZZ`` is the contract's
# explicit unknown sentinel and is accepted separately below.
_ISO_ALPHA2 = frozenset("""
AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ
BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR
CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR
GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU
ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ
LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ
MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF
PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI
SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR
TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW
""".split())


def normalise_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _text(v: str, limit: int, blank_ok: bool = False) -> str:
    if not isinstance(v, str) or (not blank_ok and not v.strip()) or len(v) > limit:
        raise ValueError("invalid_text")
    return v


def _https(v: str) -> str:
    if len(v) > 2048:
        raise ValueError("url_too_long")
    p = urlparse(v)
    if p.scheme != "https" or not p.hostname or p.username or p.password:
        raise ValueError("url_must_be_https_without_credentials")
    return v


class EligibilityNote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    source_quote: str

    @field_validator("text", "source_quote")
    @classmethod
    def _v_text(cls, v):
        return _text(v, 2000)


class RequirementIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirement_text: str
    importance: Literal["REQUIRED", "PREFERRED"]
    alternatives: list[str] = []
    source_quote: str
    evidence_skills: list[str] = []

    @field_validator("requirement_text", "source_quote")
    @classmethod
    def _v_text(cls, v):
        return _text(v, 2000)

    @field_validator("alternatives")
    @classmethod
    def _v_alts(cls, v):
        if len(v) > 10:
            raise ValueError("too_many_alternatives")
        for a in v:
            _text(a, 2000)
        if len({normalise_ws(a).casefold() for a in v}) != len(v):
            raise ValueError("duplicate_alternatives")
        return v

    @field_validator("evidence_skills")
    @classmethod
    def _v_skills(cls, v):
        if len(v) > 20:
            raise ValueError("too_many_evidence_skills")
        for s in v:
            _text(s, 100)
        return v


class JobIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    source_job_id: str
    title: str
    company_name: str
    country_code: str
    location: str
    description: str
    apply_url: str
    source_url: str
    job_type: Literal["INTERNSHIP", "OTHER", "UNKNOWN"]
    employment_time: Literal["FULL_TIME", "PART_TIME", "UNKNOWN"]
    work_arrangement: Literal["ON_SITE", "HYBRID", "REMOTE", "UNKNOWN"]
    eligibility_notes: list[EligibilityNote] = []
    posted_at: datetime | None = None
    last_verified_at: datetime | None = None
    is_active: bool = True
    requirements: list[RequirementIn]

    @field_validator("source")
    @classmethod
    def _v_source(cls, v):
        return _text(v, 80)

    @field_validator("source_job_id")
    @classmethod
    def _v_sjid(cls, v):
        return _text(v, 200)

    @field_validator("title")
    @classmethod
    def _v_title(cls, v):
        return _text(v, 300)

    @field_validator("company_name")
    @classmethod
    def _v_company(cls, v):
        return _text(v, 200)

    @field_validator("location")
    @classmethod
    def _v_location(cls, v):
        return _text(v, 300)

    @field_validator("description")
    @classmethod
    def _v_description(cls, v):
        return _text(v, 50_000)

    @field_validator("country_code")
    @classmethod
    def _v_cc(cls, v):
        if v != "ZZ" and v not in _ISO_ALPHA2:
            raise ValueError("country_code_must_be_uppercase_iso_or_ZZ")
        return v

    @field_validator("apply_url", "source_url")
    @classmethod
    def _v_urls(cls, v):
        return _https(v)

    @field_validator("posted_at", "last_verified_at")
    @classmethod
    def _v_tz(cls, v):
        if v is not None and v.tzinfo is None:
            raise ValueError("timestamp_needs_timezone")
        return v

    @model_validator(mode="after")
    def _v_requirements(self):
        if not 1 <= len(self.requirements) <= 30:
            raise ValueError("requirements_count")
        desc = normalise_ws(self.description)
        for r in self.requirements:
            if normalise_ws(r.source_quote) not in desc:
                raise ValueError("source_quote_not_in_description")
        for n in self.eligibility_notes:
            if normalise_ws(n.source_quote) not in desc:
                raise ValueError("eligibility_quote_not_in_description")
        return self


class ImportFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    jobs: list[JobIn]


class ImportIssue(BaseModel):
    index: int | None            # position of the job in the file, None for file-level problems
    source_job_id: str | None
    field: str                   # dotted path, for example "requirements.2.importance"
    code: str                    # pydantic error type or one of our fixed codes


def _issues_from(err: ValidationError, raw_jobs: list | None) -> list[ImportIssue]:
    out = []
    for e in err.errors(include_input=False, include_url=False):
        loc = list(e["loc"])
        idx = loc[1] if len(loc) > 1 and loc[0] == "jobs" and isinstance(loc[1], int) else None
        sjid = None
        if idx is not None and raw_jobs is not None and idx < len(raw_jobs) and isinstance(raw_jobs[idx], dict):
            v = raw_jobs[idx].get("source_job_id")
            sjid = v if isinstance(v, str) and len(v) <= 200 else None
        out.append(ImportIssue(index=idx, source_job_id=sjid, field=".".join(str(x) for x in loc[2:] or loc), code=e["type"]))
    return out


def validate_import(raw: bytes | str | dict, allowed_sources: tuple[str, ...] = DEFAULT_ALLOWED_SOURCES
                    ) -> tuple[list[JobIn], list[ImportIssue]]:
    """Validate a whole batch. Returns (jobs, issues); jobs is empty whenever there is any issue."""
    try:
        doc = raw if isinstance(raw, dict) else json.loads(raw)
    except (ValueError, TypeError):
        return [], [ImportIssue(index=None, source_job_id=None, field="file", code="invalid_json")]
    raw_jobs = doc.get("jobs") if isinstance(doc, dict) and isinstance(doc.get("jobs"), list) else None
    if raw_jobs is not None and len(raw_jobs) > MAX_BATCH_JOBS:
        return [], [ImportIssue(index=None, source_job_id=None, field="jobs", code="batch_too_large")]
    try:
        parsed = ImportFile.model_validate(doc)
    except ValidationError as err:
        return [], _issues_from(err, raw_jobs)
    issues: list[ImportIssue] = []
    seen: dict[tuple[str, str], int] = {}
    for i, j in enumerate(parsed.jobs):
        if j.source not in allowed_sources:
            issues.append(ImportIssue(index=i, source_job_id=j.source_job_id, field="source", code="source_not_allowed"))
        key = (j.source, j.source_job_id)
        if key in seen:
            issues.append(ImportIssue(index=i, source_job_id=j.source_job_id, field="source_job_id", code="duplicate_in_batch"))
        seen[key] = i
    if not parsed.jobs:
        issues.append(ImportIssue(index=None, source_job_id=None, field="jobs", code="empty_batch"))
    return ([] if issues else list(parsed.jobs)), issues
