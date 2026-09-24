#!/usr/bin/env python3
"""
fetch_live_jobs.py
===================

Replaces the hard-coded / synthetic catalogue file with jobs fetched live from
real job-board APIs, then transforms them into a batch that matches your
importer's contract (see docs/JIAXIN_JOB_DATA_GUIDE.md and
src/backend/app/catalogue/schema.py).

WHY THIS EXISTS
----------------
Your current data/synthetic_jobs.json is hand-written. This script instead
calls a live API at run time, normalises each listing into the exact shape
`JobIn` in schema.py expects, and writes:

  1. <output>.json              -- the importer-ready batch (schema_version 1)
  2. <output>.provenance.json   -- the sidecar your guide asks for (source,
                                    collection method/date, licence status,
                                    etc. left as TODO for Zhihao to fill in)

IMPORTANT -- READ BEFORE RUNNING FOR REAL
-------------------------------------------
Per docs/JIAXIN_JOB_DATA_GUIDE.md section 1: a real source is NOT
importable by default. `import_jobs.py` only accepts `SOURCE = "SYNTHETIC"`
unless you pass `--allow-source <NAME>`, and that flag should only be used
*after* Zhihao has reviewed provenance (who owns the data, what licence/
permission you have, whether storage+display is allowed, any expiry/refresh
rule, any redistribution limits). Running this script does not grant that
permission -- it only prepares a batch and a provenance sidecar for review.

Two adapters are included:

  * ARBEITNOW   -- https://arbeitnow.com/api/job-board-api
                   Public, no API key, no rate-limit auth required.
                   Documented, widely used, returns real live listings.
                   This one is implemented and ready to run.

  * AI_JOBS_CO  -- https://artificialintelligencejobs.co/api/jobs
                   Public, no API key. Documented at /developers, verified
                   live against the real endpoint. BUT: the list endpoint
                   returns no description text at all (title/company/
                   location/category/level/salary/url/apply_url only), so
                   on its own there is nothing to extract genuine
                   requirement quotes from. Pass --enrich-descriptions to
                   additionally fetch each job's own detail page and pull
                   the real posting text out of it -- that page also
                   carries a lot of the *site's own* generated commentary
                   (a "momentum" score, an algorithmic "culture read", an
                   auto-pulled news feed, upsell prompts) mixed into the
                   same page, which is not part of the original listing
                   and must not end up in `description`. This adapter
                   isolates the "About the role" ... "Logistics" block by
                   template markers and discards the rest. That's a
                   best-effort scrape of the site's current HTML/markdown
                   structure, not a stable contract -- spot-check a sample
                   batch before trusting it, and expect it to need
                   re-tuning if the site's template changes. Enrichment
                   does one extra HTTP GET per job, so it's off by default
                   and capped by --enrich-limit.

  * AI_DEV_JOBS -- aidevboard.com's "AI Dev Jobs" board.
                   I could not verify their exact current REST endpoint,
                   auth scheme, and response schema from inside this
                   session (no outbound network access to that host, and
                   the only descriptions I could find online look like
                   unverified/promotional text rather than the site's own
                   docs). Treat any curl snippet you find in blog posts or
                   gists for this host with real suspicion before running
                   it -- copy-paste bait aimed at AI agents is a known
                   pattern. This adapter is stubbed out: fill in BASE_URL,
                   the auth header, and `_parse_one()` once you've confirmed
                   the real contract at https://aidevboard.com's own docs,
                   then set AI_DEV_JOBS_API_KEY in your environment.

USAGE
-----
    pip install requests

    # Arbeitnow, internship-flavoured tech roles, up to 3 pages:
    python fetch_live_jobs.py --source arbeitnow --pages 3 \
        --out data/live_batch.json

    # Then, same as any prepared batch (see guide section 5):
    #   dry-run first, with --allow-source ARBEITNOW
    #   get sign-off from Zhihao on the provenance sidecar
    #   only then run the real import

This script performs read-only GET requests to public endpoints. It writes
nothing to your database -- the importer CLI does that, separately, after
your normal review process.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    import requests
except ImportError:  # pragma: no cover
    sys.exit("Missing dependency: pip install requests")

MAX_REQUIREMENTS = 30
MAX_REQ_TEXT = 2000
# Rough word-based stand-in for the pipeline's 240 tokenizer-token cap.
# This is an approximation, not the real MiniLM tokenizer -- the importer's
# dry-run is the authoritative check. Keeping well under budget on purpose.
MAX_WORDS_FOR_EMBEDDING_TEXT = 150

REQUIREMENT_CUES = [
    "require", "must have", "must be", "must possess", "need to", "needs to",
    "experience with", "experience in", "proficient", "proficiency",
    "familiar with", "familiarity with", "knowledge of", "skilled in",
    "degree in", "currently enrolled", "pursuing a", "pursuing an",
    "bachelor", "master", "diploma", "fluent in", "ability to", "hands-on",
    "strong understanding", "solid understanding", "comfortable with",
]
MANDATORY_CUES = ["must", "required", "requires", "mandatory", "need to", "needs to"]
ELIGIBILITY_CUES = [
    "currently enrolled", "pursuing a degree", "pursuing an", "work permit",
    "authorised to work", "authorized to work", "visa", "eligible to work",
    "final year", "penultimate year", "graduating in", "must be a student",
]


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

def normalise_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def strip_html(raw: str) -> str:
    """Turn API-supplied HTML description into plain text, matching the
    'Plain text source description' expectation in the guide's field table."""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.I | re.S)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.I)
    text = re.sub(r"</li\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<li[^>]*>", "- ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_sentences(text: str) -> list[str]:
    # Also split on newlines/bullets first so list items become their own
    # candidate sentences, then split remaining prose on sentence punctuation.
    chunks: list[str] = []
    for line in text.split("\n"):
        line = line.strip(" -*•\t")
        if not line:
            continue
        chunks.extend(re.split(r"(?<=[.!?])\s+", line))
    return [c.strip() for c in chunks if c.strip()]


def clip_words(s: str, max_words: int = MAX_WORDS_FOR_EMBEDDING_TEXT) -> str:
    words = s.split()
    if len(words) <= max_words:
        return s
    return " ".join(words[:max_words]).rstrip(",;:") + "..."


def clip_chars(s: str, limit: int) -> str:
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


@dataclass
class Requirement:
    requirement_text: str
    importance: str  # REQUIRED | PREFERRED
    source_quote: str
    alternatives: list[str] = field(default_factory=list)
    evidence_skills: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "requirement_text": self.requirement_text,
            "importance": self.importance,
            "source_quote": self.source_quote,
        }
        if self.alternatives:
            d["alternatives"] = self.alternatives
        if self.evidence_skills:
            d["evidence_skills"] = self.evidence_skills
        return d


def extract_requirements(description: str, tags: Iterable[str] = ()) -> list[Requirement]:
    """Pull genuine, verifiable requirement sentences out of the real
    description text. Never invents a requirement: every source_quote is a
    literal substring of `description` (checked again by the importer)."""
    sentences = split_sentences(description)
    tag_list = [t for t in tags if t]
    picked: list[Requirement] = []
    seen_quotes: set[str] = set()

    for sent in sentences:
        if len(picked) >= 8:
            break
        low = sent.lower()
        if not any(cue in low for cue in REQUIREMENT_CUES):
            continue
        quote = clip_chars(sent, MAX_REQ_TEXT)
        norm_quote = normalise_ws(quote)
        if norm_quote in seen_quotes or len(norm_quote) < 8:
            continue
        seen_quotes.add(norm_quote)

        importance = "REQUIRED" if any(c in low for c in MANDATORY_CUES) else "PREFERRED"
        req_text = clip_chars(clip_words(sent), MAX_REQ_TEXT)
        evidence = [t for t in tag_list if t.lower() in low][:20]

        picked.append(Requirement(
            requirement_text=req_text,
            importance=importance,
            source_quote=quote,
            evidence_skills=evidence,
        ))

    if not picked:
        # Schema requires >=1 requirement row. Fall back to a generic,
        # honestly-labelled PREFERRED row rather than fabricating a
        # REQUIRED one just to make the job appear in Matches (the guide
        # explicitly forbids that). Jobs with no REQUIRED row simply won't
        # rank in Matches -- that's correct behaviour, not a bug.
        first = sentences[0] if sentences else description
        quote = clip_chars(first, MAX_REQ_TEXT)
        picked.append(Requirement(
            requirement_text="See the full listing for specific requirements "
                              "(no explicit requirement language detected).",
            importance="PREFERRED",
            source_quote=quote,
        ))
    return picked[:MAX_REQUIREMENTS]


def extract_eligibility_notes(description: str) -> list[dict]:
    notes = []
    seen = set()
    for sent in split_sentences(description):
        low = sent.lower()
        if not any(cue in low for cue in ELIGIBILITY_CUES):
            continue
        quote = clip_chars(sent, MAX_REQ_TEXT)
        norm = normalise_ws(quote)
        if norm in seen:
            continue
        seen.add(norm)
        notes.append({
            "text": clip_chars(clip_words(sent), MAX_REQ_TEXT),
            "source_quote": quote,
        })
        if len(notes) >= 5:
            break
    return notes


# Minimal, conservative location -> ISO alpha-2 mapping. Left deliberately
# short: the guide says "ZZ means unknown; do not guess." Extend only with
# names you're confident are unambiguous.
_COUNTRY_HINTS = {
    "singapore": "SG", "germany": "DE", "berlin": "DE", "munich": "DE",
    "united kingdom": "GB", "uk": "GB", "london": "GB",
    "united states": "US", "usa": "US", "remote": None,
}


def guess_country_code(location: str) -> str:
    low = (location or "").lower()
    for needle, code in _COUNTRY_HINTS.items():
        if needle in low and code:
            return code
    return "ZZ"


# --------------------------------------------------------------------------
# Adapter: Arbeitnow (implemented, no API key required)
# --------------------------------------------------------------------------

ARBEITNOW_BASE = "https://arbeitnow.com/api/job-board-api"


def fetch_arbeitnow(pages: int, keyword: str | None, session: requests.Session) -> list[dict]:
    listings: list[dict] = []
    url = ARBEITNOW_BASE
    for page_num in range(1, pages + 1):
        params = {"page": page_num}
        resp = session.get(url, params=params, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        page_items = payload.get("data", [])
        if not page_items:
            break
        listings.extend(page_items)
        # be polite; this is a shared free public API
        time.sleep(0.5)
    if keyword:
        kw = keyword.lower()
        listings = [
            j for j in listings
            if kw in (j.get("title") or "").lower()
            or kw in " ".join(j.get("tags") or []).lower()
            or kw in " ".join(j.get("job_types") or []).lower()
        ]
    return listings


def transform_arbeitnow(raw: dict, fetch_time: datetime) -> dict | None:
    title = normalise_ws(raw.get("title") or "")
    company = normalise_ws(raw.get("company_name") or "")
    slug = raw.get("slug") or raw.get("url") or ""
    if not title or not company or not slug:
        return None

    description_html = raw.get("description") or ""
    description = strip_html(description_html)
    if not description:
        description = title  # last-resort non-blank description

    job_types = [normalise_ws(t) for t in (raw.get("job_types") or [])]
    job_types_low = [t.lower() for t in job_types]
    job_type = "INTERNSHIP" if any("intern" in t for t in job_types_low) else "UNKNOWN"
    if job_type == "UNKNOWN" and "intern" in title.lower():
        job_type = "INTERNSHIP"

    if any("full" in t for t in job_types_low):
        employment_time = "FULL_TIME"
    elif any("part" in t for t in job_types_low):
        employment_time = "PART_TIME"
    else:
        employment_time = "UNKNOWN"

    work_arrangement = "REMOTE" if raw.get("remote") else "UNKNOWN"

    location = normalise_ws(raw.get("location") or ("Remote" if raw.get("remote") else "")) or "Unknown"
    country_code = guess_country_code(location)

    apply_url = source_url = raw.get("url") or ""
    if not apply_url.startswith("https://"):
        return None  # importer requires HTTPS; skip anything odd rather than guess

    posted_at = None
    created_at = raw.get("created_at")
    if isinstance(created_at, (int, float)):
        posted_at = datetime.fromtimestamp(created_at, tz=timezone.utc).isoformat()

    requirements = extract_requirements(description, raw.get("tags") or [])
    eligibility = extract_eligibility_notes(description)

    return {
        "source": "ARBEITNOW",
        "source_job_id": clip_chars(slug, 200),
        "title": clip_chars(title, 300),
        "company_name": clip_chars(company, 200),
        "country_code": country_code,
        "location": clip_chars(location, 300),
        "description": clip_chars(description, 50_000),
        "apply_url": apply_url,
        "source_url": source_url,
        "job_type": job_type,
        "employment_time": employment_time,
        "work_arrangement": work_arrangement,
        "eligibility_notes": eligibility,
        "posted_at": posted_at,
        "is_active": True,
        "requirements": [r.to_dict() for r in requirements],
    }


# --------------------------------------------------------------------------
# Adapter: artificialintelligencejobs.co (implemented, no API key required)
# --------------------------------------------------------------------------

AI_JOBS_CO_BASE = "https://artificialintelligencejobs.co/api/jobs"
AI_JOBS_CO_PAGE_SIZE = 100  # API max is 200; kept modest to be a polite client

# Markers taken from the site's own detail-page template (see docstring
# above). Text is only kept between a start marker and whichever end marker
# occurs first after it. This is deliberately conservative: if none of the
# start markers are found, enrichment is skipped for that job rather than
# guessing at where the real posting text begins.
_AI_JOBS_CO_START_MARKERS = ["about the role", "about this role", "the role"]
_AI_JOBS_CO_END_MARKERS = [
    "logistics", "more like this", "is this your role", "our read on this one",
    "your match", "momentum", "company signals", "culture read",
    "how to actually get hired here", "in the news", "the weekly drop",
    "ai jobs plus", "prefer instant alerts",
]


def isolate_ai_jobs_co_posting_text(page_text: str) -> str:
    low = page_text.lower()
    start = -1
    for marker in _AI_JOBS_CO_START_MARKERS:
        idx = low.find(marker)
        if idx != -1:
            # Use the *last* occurrence of "about the role" before an end
            # marker -- the page repeats it once as a section link and once
            # as the real heading; the real body follows the second one.
            second = low.find(marker, idx + len(marker))
            start = second if second != -1 else idx
            break
    if start == -1:
        return ""
    end = len(page_text)
    for marker in _AI_JOBS_CO_END_MARKERS:
        idx = low.find(marker, start)
        if idx != -1:
            end = min(end, idx)
    body = page_text[start:end]
    body = re.sub(r"^\s*about the role\s*", "", body, flags=re.I)
    body = body.replace("**", "")  # markdown bold markers from the fetched page
    # Keep line breaks (bullets, paragraphs) so split_sentences() can treat
    # each list item as its own candidate; only collapse in-line whitespace.
    lines = [re.sub(r"[ \t]+", " ", ln).strip(" -\t") for ln in body.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def fetch_full_description(url: str, session: requests.Session) -> str:
    try:
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
    except requests.RequestException:
        return ""
    text = strip_html(resp.text)
    return isolate_ai_jobs_co_posting_text(text)


def fetch_ai_jobs_co(pages: int, keyword: str | None, session: requests.Session) -> list[dict]:
    listings: list[dict] = []
    offset = 0
    for _ in range(pages):
        params: dict[str, Any] = {"limit": AI_JOBS_CO_PAGE_SIZE, "offset": offset}
        if keyword:
            params["q"] = keyword
        resp = session.get(AI_JOBS_CO_BASE, params=params, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        batch = payload.get("jobs", [])
        if not batch:
            break
        listings.extend(batch)
        offset += len(batch)
        if len(batch) < AI_JOBS_CO_PAGE_SIZE:
            break
        time.sleep(0.5)
    return listings


def transform_ai_jobs_co(raw: dict, fetch_time: datetime, *, enrich: bool = False,
                          session: requests.Session | None = None) -> dict | None:
    title = normalise_ws(raw.get("title") or "")
    company = normalise_ws(raw.get("company") or "")
    apply_url = raw.get("apply_url") or ""
    source_url = raw.get("url") or ""
    if not title or not company or not apply_url.startswith("https://") or not source_url.startswith("https://"):
        return None

    location = normalise_ws(raw.get("location") or "") or "Unknown"
    remote = bool(raw.get("remote"))
    category = normalise_ws(raw.get("category") or "")
    level = normalise_ws(raw.get("level") or "")
    salary = raw.get("salary")

    # Real, structured facts from the API -- not invented. This is the
    # description even without enrichment; enrichment appends genuine
    # posting text fetched from the job's own page (see isolate_* above).
    desc_parts = [f"{title} at {company}."]
    loc_bit = f"Location: {location}."
    if remote:
        loc_bit += " Listed as remote."
    desc_parts.append(loc_bit)
    if category:
        desc_parts.append(f"Category: {category}.")
    if level:
        desc_parts.append(f"Level: {level}.")
    if salary:
        desc_parts.append(f"Listed salary: {salary}.")

    if enrich and session is not None:
        extra = fetch_full_description(source_url, session)
        if extra:
            desc_parts.append(extra)
        time.sleep(0.5)  # one extra page fetch per job -- be polite

    # Join with blank lines rather than normalise_ws() here: normalise_ws
    # would collapse the enrichment text's line breaks, which extract_
    # requirements()/split_sentences() rely on to separate bullet points.
    # Newlines are fine inside a stored description field.
    description = "\n\n".join(p.strip() for p in desc_parts if p and p.strip())
    country_code = guess_country_code(location)

    title_low = title.lower()
    job_type = "INTERNSHIP" if "intern" in title_low or "intern" in level.lower() else "UNKNOWN"
    work_arrangement = "REMOTE" if remote else "UNKNOWN"

    posted_at = None
    posted_raw = raw.get("posted")
    if posted_raw:
        try:
            posted_at = datetime.strptime(posted_raw, "%Y-%m-%d").replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            posted_at = None

    requirements = extract_requirements(description)
    eligibility = extract_eligibility_notes(description)

    return {
        "source": "AI_JOBS_CO",
        "source_job_id": clip_chars(source_url.rsplit("/", 1)[-1] or source_url, 200),
        "title": clip_chars(title, 300),
        "company_name": clip_chars(company, 200),
        "country_code": country_code,
        "location": clip_chars(location, 300),
        "description": clip_chars(description, 50_000),
        "apply_url": apply_url,
        "source_url": source_url,
        "job_type": job_type,
        "employment_time": "UNKNOWN",  # not exposed by this API
        "work_arrangement": work_arrangement,
        "eligibility_notes": eligibility,
        "posted_at": posted_at,
        "is_active": True,
        "requirements": [r.to_dict() for r in requirements],
    }


# --------------------------------------------------------------------------
# Adapter: AI Dev Jobs (STUB -- verify the real contract before using)
# --------------------------------------------------------------------------

AI_DEV_JOBS_BASE = "https://REPLACE-WITH-VERIFIED-HOST/REPLACE-WITH-VERIFIED-PATH"


def fetch_ai_dev_jobs(pages: int, keyword: str | None, session: requests.Session) -> list[dict]:
    api_key = os.environ.get("AI_DEV_JOBS_API_KEY")
    raise NotImplementedError(
        "AI Dev Jobs adapter is a stub. Confirm the real base URL, auth header "
        "(e.g. api key as query param vs. Authorization header) and response "
        "shape from aidevboard.com's own published docs, wire them into "
        "AI_DEV_JOBS_BASE / fetch_ai_dev_jobs() / transform_ai_dev_jobs(), "
        "then set AI_DEV_JOBS_API_KEY. Do not trust job-hunting-blog curl "
        "snippets for this host without checking them against the site's own "
        "documentation first."
    )


def transform_ai_dev_jobs(raw: dict, fetch_time: datetime) -> dict | None:
    raise NotImplementedError("Fill in once the AI Dev Jobs contract is verified.")


ADAPTERS = {
    "arbeitnow": (fetch_arbeitnow, transform_arbeitnow),
    "ai_jobs_co": (fetch_ai_jobs_co, transform_ai_jobs_co),
    "ai_dev_jobs": (fetch_ai_dev_jobs, transform_ai_dev_jobs),
}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_batch(source: str, pages: int, keyword: str | None, *,
                 enrich: bool = False, enrich_limit: int = 25) -> tuple[list[dict], int]:
    fetch_fn, transform_fn = ADAPTERS[source]
    session = requests.Session()
    session.headers["User-Agent"] = "INF2006-P1-G6 catalogue-fetcher/1.0 (student project)"
    raw_listings = fetch_fn(pages, keyword, session)
    fetch_time = datetime.now(timezone.utc)

    jobs: list[dict] = []
    seen_ids: set[str] = set()
    skipped = 0
    enriched_so_far = 0
    for raw in raw_listings:
        if source == "ai_jobs_co":
            do_enrich = enrich and enriched_so_far < enrich_limit
            job = transform_fn(raw, fetch_time, enrich=do_enrich, session=session)
            if do_enrich:
                enriched_so_far += 1
        else:
            job = transform_fn(raw, fetch_time)
        if job is None:
            skipped += 1
            continue
        if job["source_job_id"] in seen_ids:
            skipped += 1
            continue
        seen_ids.add(job["source_job_id"])
        jobs.append(job)
    return jobs, skipped


def write_provenance(provenance_path: Path, batch_path: Path, source: str, pages: int,
                      keyword: str | None, job_count: int, fetch_time: datetime) -> None:
    sidecar = {
        "batch_file": batch_path.name,
        "source_name": source.upper(),
        "collection_method": f"live API fetch via fetch_live_jobs.py (--source {source})",
        "collection_params": {"pages": pages, "keyword": keyword},
        "collected_at": fetch_time.isoformat(),
        "job_count": job_count,
        # Left blank deliberately -- this is exactly what the guide asks
        # Zhihao to review and fill in before --allow-source is used for real.
        "licence_or_permission": "TODO: record the provider's terms of use / "
                                  "API licence and whether this project has "
                                  "written permission to store and display "
                                  "these listings.",
        "storage_and_display_allowed": "TODO",
        "expiry_or_refresh_rule": "TODO: e.g. re-fetch and re-run import "
                                   "every N days; set is_active=false for "
                                   "listings that disappear from the source.",
        "redistribution_limits": "TODO",
        "reviewed_by": None,
        "review_date": None,
    }
    provenance_path.write_text(json.dumps(sidecar, indent=2, ensure_ascii=False), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=sorted(ADAPTERS), required=True)
    ap.add_argument("--pages", type=int, default=1, help="pages to fetch (Arbeitnow: ~100 jobs/page)")
    ap.add_argument("--keyword", default=None, help="filter title/tags/job_types by this keyword")
    ap.add_argument("--out", type=Path, required=True, help="output path, e.g. data/live_batch.json")
    ap.add_argument("--enrich-descriptions", action="store_true",
                     help="ai_jobs_co only: fetch each job's own page for real posting text "
                          "(one extra HTTP request per job; see adapter docstring)")
    ap.add_argument("--enrich-limit", type=int, default=25,
                     help="ai_jobs_co only: cap on how many jobs get the extra page fetch")
    args = ap.parse_args(argv)

    if args.enrich_descriptions and args.source != "ai_jobs_co":
        print("--enrich-descriptions only applies to --source ai_jobs_co; ignoring.", file=sys.stderr)

    jobs, skipped = build_batch(args.source, args.pages, args.keyword,
                                 enrich=args.enrich_descriptions, enrich_limit=args.enrich_limit)
    if not jobs:
        print(f"No usable jobs produced (skipped {skipped}). Nothing written.", file=sys.stderr)
        return 1

    batch = {"schema_version": 1, "jobs": jobs}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(batch, indent=2, ensure_ascii=False), encoding="utf-8")

    provenance_path = args.out.with_suffix(".provenance.json")
    write_provenance(provenance_path, args.out, args.source, args.pages, args.keyword,
                      len(jobs), datetime.now(timezone.utc))

    print(f"Wrote {len(jobs)} jobs to {args.out} (skipped {skipped} unusable listings)")
    print(f"Wrote provenance sidecar to {provenance_path}")
    print()
    print("Next steps (per docs/JIAXIN_JOB_DATA_GUIDE.md):")
    print(f"  1. Fill in the TODO fields in {provenance_path.name} and send to Zhihao for review.")
    print(f"  2. Dry-run:  python -m app.catalogue.import_jobs --file {args.out} "
          f"--dry-run --allow-source {args.source.upper()}")
    print("  3. Only after Zhihao approves provenance/permission, run the real import "
          "with the same --allow-source flag.")
    return 0


if __name__ == "__main__":
    sys.exit(main())