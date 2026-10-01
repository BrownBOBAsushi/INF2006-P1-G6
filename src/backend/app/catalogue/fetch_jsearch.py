#!/usr/bin/env python3
"""Fetch a bounded JSearch candidate batch for the local catalogue review.

The API key is read only from ``OPENWEBNINJA_API_KEY`` in the process
environment. This module never loads dotenv files or prints provider response
bodies. Outputs remain pending provenance review until the source terms and
storage/display conditions are reviewed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import fetch_live_jobs as rules

API_URL = "https://api.openwebninja.com/jsearch/search-v2"
SOURCE = "JSEARCH"
DEFAULT_QUERY = "software internship in Singapore"
MAX_PAGES = 5
RECENT_DAYS = 7
REQUEST_TIMEOUT = 20


def api_key_from_environment() -> str:
    key = os.environ.get("OPENWEBNINJA_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENWEBNINJA_API_KEY is missing from the process environment")
    return key


def validate_page_count(pages: int) -> int:
    if isinstance(pages, bool) or not isinstance(pages, int) or not 1 <= pages <= MAX_PAGES:
        raise ValueError(f"pages must be between 1 and {MAX_PAGES}")
    return pages


def _provider_request(query: str, key: str, cursor: str | None = None) -> dict[str, Any]:
    params = {
        "query": query,
        "country": "sg",
        "language": "en",
        "date_posted": "week",
        "employment_types": "INTERN",
        "num_pages": "1",
    }
    if cursor:
        params["cursor"] = cursor
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"x-api-key": key, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("JSearch request failed; provider details were omitted") from None
    except Exception:
        # Keep unexpected transport/provider exceptions sanitized as well.
        raise RuntimeError("JSearch request failed; provider details were omitted") from None

    if not isinstance(payload, dict) or payload.get("status") != "OK":
        raise RuntimeError("JSearch returned an invalid response; provider details were omitted")
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise RuntimeError("JSearch returned an invalid response; provider details were omitted")
    jobs = data["jobs"]
    if any(not isinstance(job, dict) for job in jobs):
        raise RuntimeError("JSearch returned an invalid response; provider details were omitted")
    next_cursor = data.get("cursor")
    if next_cursor is not None and not isinstance(next_cursor, str):
        raise RuntimeError("JSearch returned an invalid response; provider details were omitted")
    return {"jobs": jobs, "cursor": next_cursor}


def fetch_listings(query: str = DEFAULT_QUERY, pages: int = 1) -> tuple[list[dict], int]:
    """Fetch at most five cursor pages; each provider request costs one page."""
    validate_page_count(pages)
    query = rules.normalise_ws(query)
    if not query or len(query) > 200:
        raise ValueError("query must contain 1 to 200 characters")
    key = api_key_from_environment()
    cursor = None
    output = []
    pages_fetched = 0
    for _ in range(pages):
        page = _provider_request(query, key, cursor)
        pages_fetched += 1
        output.extend(page["jobs"])
        cursor = page["cursor"]
        if not cursor:
            break
    return output, pages_fetched


def _country_is_singapore(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return rules.normalise_ws(value).casefold() in {"singapore", "sg"}


def _location_corroborates_singapore(raw: dict) -> bool:
    location = rules.normalise_ws(_provider_text(raw, "job_location"))
    if location:
        parts = [part.strip().casefold() for part in location.split(",")]
        return location.casefold() in {"singapore", "sg"} or parts[-1] in {"singapore", "sg"}
    return any(
        rules.normalise_ws(_provider_text(raw, field)).casefold() in {"singapore", "sg"}
        for field in ("job_city", "job_state")
    )


def _posted_at(raw: dict) -> datetime | None:
    value = raw.get("job_posted_at_datetime_utc")
    parsed = None
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    timestamp = raw.get("job_posted_at_timestamp")
    if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    return None


def _https_url(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if len(value) > 2048:
        return None
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    return value


def _provider_text(raw: dict, field: str) -> str:
    value = raw.get(field)
    return value.strip() if isinstance(value, str) else ""


def source_identity(provider_job_id: str) -> str:
    """Keep provider IDs verbatim when possible; hash long IDs to fit schema v1."""
    if len(provider_job_id) <= 200:
        return provider_job_id
    return "sha256:" + hashlib.sha256(provider_job_id.encode("utf-8")).hexdigest()


def _employment_labels(raw: dict) -> set[str]:
    values = [raw.get("job_employment_type")]
    extra = raw.get("job_employment_types")
    if isinstance(extra, list):
        values.extend(extra)
    labels = set()
    for value in values:
        if isinstance(value, str):
            # Provider values appear as FULLTIME and as prose such as
            # Full–time. Removing separators handles ASCII and Unicode dashes.
            labels.add("".join(char for char in value.casefold() if char.isalnum()))
    return labels


def transform_listing(raw: dict, now: datetime | None = None) -> dict | None:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must include a timezone")
    now = now.astimezone(timezone.utc)

    if not _country_is_singapore(raw.get("job_country")):
        return rules.skip("non_singapore")
    if not _location_corroborates_singapore(raw):
        return rules.skip("location_not_singapore")
    posted = _posted_at(raw)
    if posted is None:
        return rules.skip("missing_or_invalid_posting_date")
    if posted > now:
        return rules.skip("future_posting_date")
    if posted < now - timedelta(days=RECENT_DAYS):
        return rules.skip("outside_recent_window")

    job_id = raw.get("job_id")
    title = rules.normalise_ws(_provider_text(raw, "job_title"))
    company = rules.normalise_ws(_provider_text(raw, "employer_name"))
    if not isinstance(job_id, str) or not job_id.strip() or not title or not company:
        return rules.skip("missing_title_company_or_id")
    if company.casefold() in rules.INTERMEDIARIES:
        return rules.skip("intermediary_not_employer")

    description = rules.strip_html(_provider_text(raw, "job_description"))
    if not description:
        return rules.skip("empty_description")
    if rules.looks_non_english(description):
        return rules.skip("non_english")

    employment_labels = _employment_labels(raw)
    explicit_intern = "intern" in employment_labels
    job_type = "INTERNSHIP" if explicit_intern else rules.classify_description_job_type(description)
    if job_type != "INTERNSHIP":
        return rules.skip("not_internship")
    has_full_time = "fulltime" in employment_labels
    has_part_time = "parttime" in employment_labels
    employment_time = (
        "FULL_TIME" if has_full_time and not has_part_time else
        "PART_TIME" if has_part_time and not has_full_time else
        "UNKNOWN"
    )

    requirements, ambiguous = rules.extract_job_requirements(description)
    if ambiguous:
        return rules.skip("manual_review_ambiguous_requirements")
    if not requirements:
        return rules.skip("no_requirements_section")

    apply_url = _https_url(raw.get("job_apply_link"))
    if not apply_url:
        return rules.skip("no_https_apply_url")
    source_url = _https_url(raw.get("job_google_link")) or apply_url

    city = rules.normalise_ws(_provider_text(raw, "job_city"))
    state = rules.normalise_ws(_provider_text(raw, "job_state"))
    location = rules.normalise_ws(_provider_text(raw, "job_location"))
    if not location:
        parts = []
        for part in (city, state, "Singapore"):
            if part and part.casefold() not in {existing.casefold() for existing in parts}:
                parts.append(part)
        location = ", ".join(parts)
    if not location:
        location = "Singapore"  # supported by the explicit provider country field

    remote = raw.get("job_is_remote") is True
    return {
        "source": SOURCE,
        "source_job_id": source_identity(job_id.strip()),
        "title": rules.clip_chars(title, 300),
        "company_name": rules.clip_chars(company, 200),
        "country_code": "SG",
        "location": rules.clip_chars(location, 300),
        "description": rules.clip_chars(description, 50_000),
        "apply_url": apply_url,
        "source_url": source_url,
        "job_type": job_type,
        "employment_time": employment_time,
        "work_arrangement": "REMOTE" if remote else "UNKNOWN",
        "eligibility_notes": rules.extract_eligibility_notes(description),
        "posted_at": posted.isoformat(),
        "is_active": True,
        "requirements": [requirement.to_dict() for requirement in requirements],
    }


def transform_listings(listings: list[dict], now: datetime | None = None) -> tuple[list[dict], int]:
    jobs: list[dict] = []
    seen_ids: set[str] = set()
    skipped = 0
    for raw in listings:
        job = transform_listing(raw, now)
        if job is None:
            skipped += 1
            continue
        if job["source_job_id"] in seen_ids:
            rules.SKIPS["duplicate_id"] += 1
            skipped += 1
            continue
        seen_ids.add(job["source_job_id"])
        jobs.append(job)
    return jobs, skipped


def build_provenance(*, output_file: str, query: str, pages: int, collected_at: datetime,
                     pages_fetched: int, job_count: int, skipped_counts: dict,
                     provider_job_ids: dict[str, str] | None = None) -> dict:
    return {
        "batch_file": output_file,
        "source_name": SOURCE,
        "provider": "OpenWebNinja JSearch API v2 (https://api.openwebninja.com/jsearch/search-v2)",
        "collection_method": "JSearch search-v2 API using x-api-key authentication from process environment",
        "collection_params": {
            "query": query,
            "country": "sg",
            "language": "en",
            "date_posted": "week",
            "employment_types": "INTERN",
            "num_pages": 1,
            "cursor_pages_requested": pages,
            "cursor_pages_fetched": pages_fetched,
            "recent_cutoff_days": RECENT_DAYS,
        },
        "collected_at": collected_at.astimezone(timezone.utc).isoformat(),
        "job_count": job_count,
        "provider_job_ids": provider_job_ids or {},
        "review_status": "PENDING_HUMAN_PROVENANCE_REVIEW",
        "authorization_note": "Collection requested by CLI; provider permission is not implied.",
        "api_documentation": "https://www.openwebninja.com/api/jsearch",
        "endpoint_manifest": "https://raw.githubusercontent.com/OpenWeb-Ninja/openwebninja-mcp/main/src/generated/manifest.ts",
        "terms_reference": "https://www.openwebninja.com/terms",
        "transformations": [
            "Only rows with a Singapore job_country and corroborating job_location are retained; when job_location is absent, job_city or job_state must explicitly say Singapore or SG.",
            "Job type is INTERNSHIP only for the explicit provider INTERN category or an affirmative description classification; titles alone do not establish it.",
            "Employment time is mapped only from explicit FULLTIME/PARTTIME provider labels, including labels with Unicode dashes; conflicts remain UNKNOWN.",
            "Only postings with an explicit UTC date within seven days of collection time are retained; missing, future, and older dates are skipped.",
            "Requirements and eligibility quotes are extracted only from the listing description; job_highlights are not rewritten or appended.",
            "Original job link is job_google_link when HTTPS; otherwise the actual HTTPS application link is used.",
            "Employment time is UNKNOWN unless the provider returns a supported explicit value; no schedule is inferred.",
        ],
        "skipped_counts": skipped_counts,
        "licence_or_permission": (
            "Provider terms reference recorded for review; retention/display conditions and any expiry rule "
            "remain pending human review."
        ),
        "storage_and_display_allowed": "PENDING_HUMAN_REVIEW",
        "expiry_or_refresh_rule": "PENDING_HUMAN_REVIEW",
        "redistribution_limits": "PENDING_HUMAN_REVIEW",
        "reviewed_by": None,
        "review_date": None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default=DEFAULT_QUERY, help="JSearch query (1 to 200 characters)")
    parser.add_argument("--pages", type=int, default=1, help=f"cursor pages to fetch (maximum {MAX_PAGES})")
    parser.add_argument("--out", type=Path, required=True, help="JSON output path, kept outside Git")
    args = parser.parse_args(argv)
    try:
        validate_page_count(args.pages)
        query = rules.normalise_ws(args.query)
        if not query or len(query) > 200:
            raise ValueError("query must contain 1 to 200 characters")
        fetch_time = datetime.now(timezone.utc)
        raw_listings, pages_fetched = fetch_listings(query, args.pages)
        jobs, skipped = transform_listings(raw_listings, fetch_time)
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not jobs:
        print(f"No usable jobs produced (skipped {skipped}: {dict(rules.SKIPS)}). Nothing written.", file=sys.stderr)
        return 1
    batch = {"schema_version": 1, "jobs": jobs}
    from .schema import validate_import
    _validated, issues = validate_import(batch, allowed_sources=(SOURCE,))
    if issues:
        codes = ", ".join(f"{issue.field}:{issue.code}" for issue in issues[:20])
        print(f"Candidate batch failed schema_version 1 validation; nothing written ({codes}).", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(batch, indent=2, ensure_ascii=False), "utf-8")
    sidecar = build_provenance(output_file=args.out.name, query=query, pages=args.pages,
                               collected_at=fetch_time, pages_fetched=pages_fetched,
                               job_count=len(jobs), skipped_counts=dict(rules.SKIPS),
                               provider_job_ids={
                                   job["source_job_id"]: raw["job_id"]
                                   for raw in raw_listings
                                   if isinstance(raw.get("job_id"), str)
                                   for job in jobs
                                   if job["source_job_id"] == source_identity(raw["job_id"].strip())
                               })
    args.out.with_suffix(".provenance.json").write_text(
        json.dumps(sidecar, indent=2, ensure_ascii=False), "utf-8")
    print(f"Wrote {len(jobs)} jobs to {args.out}; {skipped} unusable listings skipped.")
    print(f"Wrote pending provenance sidecar to {args.out.with_suffix('.provenance.json')}.")
    print("Output remains pending provider permission review; no database import was performed.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
