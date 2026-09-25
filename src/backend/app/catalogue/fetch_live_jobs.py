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
from collections import Counter
from html.parser import HTMLParser
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

# Requirements are taken only from the listing's own requirements /
# qualifications / "what you bring" section (never by keyword from anywhere in
# the text), then labelled REQUIRED unless the line itself says preferred /
# nice-to-have / advantage / plus. See extract_requirements().
_PREFERRED_RX = re.compile(
    r"\b(prefer(red|ably)?|nice[- ]to[- ]have|advantage(ous)?|bonus|good to have|a plus|is a plus|an asset|"
    r"beneficial|desirable|valuable|ideally|vorteil|w[uü]nschenswert|idealerweise)\b", re.I)
_START_RX = re.compile(
    r"^(?:key |minimum |basic |required )?(?:requirements?|qualifications?(?: (?:&|and) experience)?|required(?: qualifications| skills)?"
    r"|skills(?: (?:&|and) (?:experience|qualifications))?"
    r"|what you(?:'|’)?(?:ll)? (?:bring|need|have)(?: to the team)?|what we(?:'|’)?re looking for|who you are|about you"
    r"|what makes you a (?:great |good )?fit|the ideal candidate|ideal candidate|you have|must[- ]haves?"
    r"|your profile.*|anforderungen|dein profil|deine qualifikationen?|das bringst du mit|it(?:'|’)?s a match.*|deine basis)"
    r"\s*[:\-–]?\s*$", re.I)
# Sub-headings inside a section that mark everything after them as PREFERRED.
_PREF_HEAD_RX = re.compile(
    r"^(?:preferred(?: qualifications| skills)?|nice[- ]to[- ]haves?|bonus(?: points)?|good to have)\s*[:\-–]?\s*$", re.I)
_STOP_RX = re.compile(
    r"^(?:responsibilit\w+|key responsibilit\w+|accountabilit\w+|what you(?:'|’)?ll (?:do|build)(?: in this role.*)?"
    r"|what is your day to day mission|your day to day.*|(?:[\w& ]{0,25}\b)?benefits?|our benefits|perks(?: (?:&|and) benefits)?"
    r"|(?:conditions|compensation|package|salary)\s*(?:&|and)\s*benefits|pay range|what we offer.*"
    r"|what you can expect|what makes this .*|why .*|about .*|our (?:commitment|culture|mission)|equal opportunity.*"
    r"|security advisory.*|how .* works|data privacy notice|the role|role summary|deine aufgaben|das erwartet dich"
    r"|was wir dir bieten|deine vorteile|unsere benefits|gleiche chancen.*|chancengleichheit.*"
    r"|(?:potential )?research directions?|project scope|academic supervision|.*\bsupervision\b.*)\s*[:\-–]?\s*$", re.I)
# Phrases that end a requirements section wherever they appear in a line (closing pitches, perks, legal
# boilerplate, footers, CTAs) -- searched across the whole line, not just a short heading-like prefix, because
# these often show up mid-sentence or at the end of an otherwise ordinary-looking line.
_STOP_LINE_RX = re.compile(
    r"why (?:join|you|work)\b|\bbenefits?\b|\bperks\b|what we offer\b|more about\b|working at\b|about (?:us|the company)\b"
    r"|equal opportunit\w+|find (?:more )?.{0,60}on arbeitnow|have questions about\b|any questions about\b|are you in\b"
    r"|by submitting your application|subject to applicable|depending on your location|we are committed to"
    r"|the above list of|all posted ranges|pay range|salary range|\bcompensation\b|if this role excites you"
    r"|is an equal opportunity employer"
    r"|you want to be part of our|are you a team ?player looking for|follow us on (?:instagram|linkedin|twitter|facebook|x)\b"
    r"|(?:look|glimpse) behind the scenes|requirements are not listed in order"
    r"|apply now|let'?s talk|get in touch|reach out to|\bworkation\b|vacation days?\b|home office days?\b"
    r"|company pension|childcare allowance|wellpass|corporate benefits|kununu\s*score", re.I)
# Encouragement/reassurance lines that sit *inside* a requirements section, mixed in with
# real requirements (unlike _STOP_LINE_RX above, these do NOT end the section -- a genuine
# requirement often follows immediately after one, e.g. "...if this sounds like you, apply!
# / Currently enrolled in a Bachelor's program..." -- so this only skips the one line).
_FILLER_LINE_RX = re.compile(
    r"tick every box|sounds like (?:you|the)|if this sounds like|no perfect match needed|"
    r"we don'?t expect you to (?:tick|check)", re.I)
_SKILLS = ["Python", "SQL", "Java", "JavaScript", "TypeScript", "React", "Node.js", "C++", "C#", "Go", "Docker",
           "Kubernetes", "AWS", "Azure", "GCP", "Linux", "Git", "Excel", "Power BI", "Tableau", "Pandas",
           "TensorFlow", "PyTorch", "PostgreSQL", "MySQL", "MongoDB", "REST", "HTML", "CSS"]
_SKILL_RX = {k: re.compile(r"(?<![A-Za-z0-9+#])" + re.escape(k) + r"(?![A-Za-z0-9+#])", re.I) for k in _SKILLS}
_DE_RX = re.compile(r"\b(und|der|die|das|mit|f[uü]r|wir|du|deine?|sie|ist|bei|auf|oder)\b", re.I)
_FR_RX = re.compile(r"\b(le|la|les|des|une|vous|nous|pour|avec|est|et|du|que|dans|votre|sur)\b", re.I)
_EN_RX = re.compile(r"\b(and|the|with|for|we|you|your|is|are|of|to)\b", re.I)
# Publishers / ATS names that are not the employer.
_PUBLISHER_SUFFIX_RX = re.compile(
    r"\s*[-–|]\s*(personio|greenhouse|smartrecruiters|join\.com|join|teamtailor|recruitee|comeet|lever|workable)\s*$", re.I)
# Intermediaries whose listings hide the real employer ("listed on behalf of a partner company").
INTERMEDIARIES = {"jobgether", "huzzle"}
ELIGIBILITY_CUES = [
    "currently enrolled", "currently pursuing", "pursuing a degree", "pursuing an", "recently completed",
    "work permit", "authorised to work", "authorized to work", "visa", "eligible to work",
    "final year", "penultimate year", "graduating in", "must be a student",
]

# Skip reasons are counted here and written to the provenance sidecar.
SKIPS: Counter = Counter()


def skip(reason: str) -> None:
    SKIPS[reason] += 1
    return None


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

def normalise_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


class _TextParser(HTMLParser):
    _BLOCK = {"p", "div", "br", "li", "ul", "ol", "tr", "table", "section", "figure",
              "h1", "h2", "h3", "h4", "h5", "h6"}
    _SKIP = {"script", "style", "iframe", "figure"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._BLOCK:
            self.parts.append("\n")
        if tag in self._SKIP:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in self._BLOCK:
            self.parts.append("\n")
        if tag in self._SKIP and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def strip_html(raw: str) -> str:
    """API HTML -> plain text, one logical line (paragraph, heading, list
    item) per line. Entities are decoded BEFORE parsing when the API sent
    escaped HTML (&lt;li&gt;...), so no literal tags leak into the text."""
    if re.search(r"&lt;/?[a-z]", raw, re.I):
        raw = html.unescape(raw)
    if re.search(r"<\s*/?\s*[a-z][^>]*>", raw, re.I):
        parser = _TextParser()
        parser.feed(raw)
        raw = "".join(parser.parts)
    raw = unicodedata.normalize("NFKC", raw)
    return "\n".join(l for l in (normalise_ws(x) for x in raw.split("\n")) if l)


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


def _strip_bullet(line: str) -> str:
    return re.sub(r"^\s*(?:[-*•·▪◦]|\d+[.)])\s+", "", line).strip()


def _split_inline_heading(line: str) -> list[str]:
    """'Requirements: - Python' -> ['Requirements:', 'Python'] (some sources merge a heading with its first item)."""
    m = re.match(r"^(?P<h>[^:]{3,60}:)\s+(?P<rest>\S.*)$", line)
    if m and (_START_RX.match(m["h"]) or _STOP_RX.match(m["h"]) or _STOP_LINE_RX.match(m["h"]) or _PREF_HEAD_RX.match(m["h"])):
        return [m["h"], _strip_bullet(m["rest"])]
    return [line]


def _skills_in(text: str) -> list[str]:
    return [k for k, rx in _SKILL_RX.items() if rx.search(text)][:20]


def looks_non_english(text: str) -> bool:
    """Crude stop-word vote (German/French vs English); the embedding model is English."""
    return len(_DE_RX.findall(text)) + len(_FR_RX.findall(text)) > len(_EN_RX.findall(text))


def extract_requirements(description: str, tags: Iterable[str] = ()) -> list[Requirement]:
    """Requirement rows = the lines inside the listing's own requirements /
    qualifications / "what you bring" section, verbatim. Nothing is invented,
    clipped or paraphrased: requirement_text == source_quote == a line of
    `description`. Returns [] when the listing has no such section (the caller
    then skips the job instead of adding a placeholder row)."""
    lines: list[str] = []
    for raw_line in description.split("\n"):
        lines.extend(_split_inline_heading(_strip_bullet(raw_line)))
    picked: list[Requirement] = []
    seen: set[str] = set()
    on = pref = False
    desc_norm = normalise_ws(description)
    for ln in lines:
        head = re.sub(r"^[^\w]+", "", ln)          # ignore leading emoji / arrows in headings
        short = len(head) <= 70
        if short and _START_RX.match(head):
            on, pref = True, False
            continue
        if short and on and _PREF_HEAD_RX.match(head):
            pref = True
            continue
        if (short and (_STOP_RX.match(head) or head.endswith(":"))) or _STOP_LINE_RX.search(ln):
            on = pref = False
            continue
        text = normalise_ws(ln)
        if (not on or not (12 <= len(text) <= 400) or text.casefold() in seen
                or text not in desc_norm or _FILLER_LINE_RX.search(text)):
            continue
        seen.add(text.casefold())
        picked.append(Requirement(
            requirement_text=text,
            importance="PREFERRED" if (pref or _PREFERRED_RX.search(text)) else "REQUIRED",
            source_quote=text,
            evidence_skills=_skills_in(text),
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
    "singapore": "SG", "germany": "DE", "deutschland": "DE", "berlin": "DE", "munich": "DE", "münchen": "DE",
    "united kingdom": "GB", "uk": "GB", "london": "GB", "united states": "US", "usa": "US",
}


def guess_country_code(location: str) -> str:
    low = (location or "").lower()
    found = {code for needle, code in _COUNTRY_HINTS.items()
             if re.search(r"(?<![a-zà-ÿ])" + re.escape(needle) + r"(?![a-zà-ÿ])", low)}
    return found.pop() if len(found) == 1 else "ZZ"


# --------------------------------------------------------------------------
# Adapter: Arbeitnow (implemented, no API key required)
# --------------------------------------------------------------------------

ARBEITNOW_BASE = "https://arbeitnow.com/api/job-board-api"


def _iso_or_none(v) -> str | None:
    """Best-effort ISO-8601 with a UTC offset; None if unparseable. Some providers (Remotive) send a
    naive local-looking timestamp with no offset, which the schema rejects as-is."""
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).isoformat()


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
        # whole-word match, allowing plural/"-ship": "intern" hits "Intern" and
        # "Internship" but NOT "International"
        rx = re.compile(r"(?<![A-Za-z])" + re.escape(keyword) + r"(?:s|ship|ships)?(?![A-Za-z])", re.I)
        listings = [
            j for j in listings
            if rx.search(" ".join([j.get("title") or "", " ".join(j.get("tags") or []),
                                    " ".join(j.get("job_types") or [])]))
        ]
    return listings


def transform_arbeitnow(raw: dict, fetch_time: datetime, allow_non_english: bool = False) -> dict | None:
    title = normalise_ws(raw.get("title") or "")
    company = normalise_ws(raw.get("company_name") or "")
    slug = raw.get("slug") or raw.get("url") or ""
    if not title or not company or not slug:
        return skip("missing_title_company_or_id")
    if company.lower() in INTERMEDIARIES:
        return skip("intermediary_not_employer")
    company = _PUBLISHER_SUFFIX_RX.sub("", company).strip() or company

    description = strip_html(raw.get("description") or "")
    if not description:
        return skip("empty_description")          # no title-as-description fallback
    if not allow_non_english and looks_non_english(description):
        return skip("non_english")

    job_types = [normalise_ws(t) for t in (raw.get("job_types") or [])]
    job_types_low = [t.lower() for t in job_types]
    # Only the provider's explicit job_types field decides; the title never does.
    job_type = "INTERNSHIP" if any(t.startswith(("intern", "praktik")) for t in job_types_low) else (
        "OTHER" if job_types_low else "UNKNOWN")

    if any(t.startswith("part") or " part" in t for t in job_types_low):
        employment_time = "PART_TIME"
    elif any("full" in t for t in job_types_low):
        employment_time = "FULL_TIME"
    else:
        employment_time = "UNKNOWN"

    work_arrangement = "REMOTE" if raw.get("remote") else "UNKNOWN"

    location = normalise_ws(raw.get("location") or ("Remote" if raw.get("remote") else "")) or "Unknown"
    country_code = guess_country_code(location)

    apply_url = source_url = raw.get("url") or ""   # the API supplies one URL: the Arbeitnow listing page
    if not apply_url.startswith("https://"):
        return skip("no_https_url")

    posted_at = None
    created_at = raw.get("created_at")
    if isinstance(created_at, (int, float)):
        posted_at = datetime.fromtimestamp(created_at, tz=timezone.utc).isoformat()

    requirements = extract_requirements(description, raw.get("tags") or [])
    if not requirements:
        return skip("no_requirements_section")   # never pad with a placeholder row
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

    # Only the provider's structured `level` field counts; the title never does.
    job_type = "INTERNSHIP" if level.lower().startswith("intern") else "UNKNOWN"
    work_arrangement = "REMOTE" if remote else "UNKNOWN"

    posted_at = None
    posted_raw = raw.get("posted")
    if posted_raw:
        try:
            posted_at = datetime.strptime(posted_raw, "%Y-%m-%d").replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            posted_at = None

    requirements = extract_requirements(description)
    if not requirements:
        return skip("no_requirements_section")
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


# --------------------------------------------------------------------------
# Adapter: AI Dev Jobs (aidevboard.com) -- verified against its published
# OpenAPI spec at https://aidevboard.com/openapi.yaml. No key needed; the
# earlier AI_DEV_JOBS_API_KEY stub above was based on an unverified guess
# and is replaced by this. AI/ML roles worldwide, small volume for Singapore.
# --------------------------------------------------------------------------
AI_DEV_JOBS_BASE = "https://aidevboard.com/api/v1/jobs"


def fetch_ai_dev_jobs(pages: int, keyword: str | None, session: requests.Session,
                       location: str | None = None) -> list[dict]:
    listings: list[dict] = []
    for page_num in range(1, pages + 1):
        params: dict[str, Any] = {"limit": 50, "page": page_num}
        if keyword:
            params["q"] = keyword
        if location:
            params["location"] = location
        resp = session.get(AI_DEV_JOBS_BASE, params=params, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        listings.extend(payload.get("jobs") or [])
        if not payload.get("has_next"):
            break
        time.sleep(0.5)
    return listings


def transform_ai_dev_jobs(raw: dict, fetch_time: datetime) -> dict | None:
    title = normalise_ws(raw.get("title") or "")
    company = normalise_ws(raw.get("company_name") or "")
    job_id = raw.get("id") or raw.get("slug") or ""
    if not title or not company or not job_id:
        return skip("missing_title_company_or_id")

    apply_url = raw.get("apply_url") or ""
    if not apply_url.startswith("https://"):
        return skip("no_https_url")
    # The spec has no public listing-page URL; the job's own API record is
    # the traceable source instead.
    source_url = f"https://aidevboard.com/api/v1/jobs/{job_id}"

    description = strip_html(raw.get("description") or "")
    if not description:
        return skip("empty_description")

    req_field = raw.get("requirements") or ""
    req_lines = [_strip_bullet(l) for l in strip_html(req_field).split("\n") if len(_strip_bullet(l)) >= 8]
    desc_norm = normalise_ws(description)
    matched = [l for l in req_lines if normalise_ws(l) in desc_norm]
    if req_lines and len(matched) * 2 < len(req_lines):
        # The requirements field isn't part of the stored description text:
        # append it verbatim under its own heading so it stays quotable.
        description = description + "\n\nRequirements\n" + "\n".join(req_lines)
        desc_norm = normalise_ws(description)
    requirements = extract_requirements(description)
    if not requirements:
        return skip("no_requirements_section")

    jt = (raw.get("job_type") or "").lower()
    wp = (raw.get("workplace") or "").lower()
    return {
        "source": "AIDEVBOARD",
        "source_job_id": clip_chars(str(job_id), 200),
        "title": clip_chars(title, 300),
        "company_name": clip_chars(company, 200),
        "country_code": guess_country_code(raw.get("location") or ""),
        "location": clip_chars(normalise_ws(raw.get("location") or ""), 300) or "Unknown",
        "description": clip_chars(description, 50_000),
        "apply_url": apply_url,
        "source_url": source_url,
        # Only the provider's own job_type field decides; never the title.
        "job_type": "INTERNSHIP" if "intern" in jt else ("OTHER" if jt else "UNKNOWN"),
        "employment_time": "FULL_TIME" if jt == "full-time" else ("PART_TIME" if jt == "part-time" else "UNKNOWN"),
        "work_arrangement": {"remote": "REMOTE", "hybrid": "HYBRID", "onsite": "ON_SITE"}.get(wp, "UNKNOWN"),
        "eligibility_notes": extract_eligibility_notes(description),
        "posted_at": _iso_or_none(raw.get("created_at")),
        "is_active": True,
        "requirements": [r.to_dict() for r in requirements],
    }


# --------------------------------------------------------------------------
# Adapter: RemoteOK (remoteok.com/api). No key. ITS OWN TERMS (returned
# inside the API response) require a followed backlink to the job's
# remoteok.com URL plus "Remote OK" named as the source wherever a listing
# is shown, or they may suspend access; their logo needs written permission,
# the name does not. One call returns a fixed snapshot of the newest ~100
# postings -- no real pagination, so --pages beyond 1 just re-reads it.
# Every listing is global remote tech, never Singapore-specific.
# --------------------------------------------------------------------------
REMOTEOK_BASE = "https://remoteok.com/api"


def fetch_remoteok(pages: int, keyword: str | None, session: requests.Session) -> list[dict]:
    if pages > 1:
        print("remoteok returns one fixed snapshot; ignoring --pages beyond 1.", file=sys.stderr)
    resp = session.get(REMOTEOK_BASE, timeout=20)
    resp.raise_for_status()
    payload = resp.json()
    listings = [j for j in payload if isinstance(j, dict) and "legal" not in j]   # [0] is a legal/metadata row
    print(f"remoteok: API returned {len(listings)} listings before keyword filter.", file=sys.stderr)
    if keyword:
        rx = re.compile(r"(?<![A-Za-z])" + re.escape(keyword) + r"(?:s|ship|ships)?(?![A-Za-z])", re.I)
        listings = [j for j in listings
                    if rx.search(" ".join([j.get("position") or j.get("title") or "",
                                            " ".join(str(t) for t in j.get("tags") or [])]))]
        print(f"remoteok: {len(listings)} left after --keyword {keyword!r}.", file=sys.stderr)
    return listings


def transform_remoteok(raw: dict, fetch_time: datetime, allow_non_english: bool = False) -> dict | None:
    title = normalise_ws(raw.get("position") or raw.get("title") or "")
    company = normalise_ws(raw.get("company") or "")
    job_id = str(raw.get("id") or raw.get("slug") or "")
    if not title or not company or not job_id:
        return skip("missing_title_company_or_id")

    apply_url = raw.get("apply_url") or raw.get("url") or ""
    source_url = raw.get("url") or apply_url
    if not str(apply_url).startswith("https://") or not str(source_url).startswith("https://"):
        return skip("no_https_url")

    description = strip_html(raw.get("description") or "")
    if not description:
        return skip("empty_description")
    if not allow_non_english and looks_non_english(description):
        return skip("non_english")

    requirements = extract_requirements(description, raw.get("tags") or [])
    if not requirements:
        return skip("no_requirements_section")

    posted_at = None
    epoch = raw.get("epoch")
    if isinstance(epoch, (int, float)):
        posted_at = datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()

    return {
        "source": "REMOTEOK",
        "source_job_id": clip_chars(job_id, 200),
        "title": clip_chars(title, 300),
        "company_name": clip_chars(company, 200),
        "country_code": "ZZ",
        "location": clip_chars(normalise_ws(raw.get("location") or "Worldwide"), 300),
        "description": clip_chars(description, 50_000),
        "apply_url": apply_url,
        "source_url": source_url,
        "job_type": "UNKNOWN",         # RemoteOK has no job_type field; never inferred from the title
        "employment_time": "UNKNOWN",
        "work_arrangement": "REMOTE",  # every RemoteOK listing is remote by definition
        "eligibility_notes": extract_eligibility_notes(description),
        "posted_at": posted_at,
        "is_active": True,
        "requirements": [r.to_dict() for r in requirements],
    }


# --------------------------------------------------------------------------
# Adapter: Remotive (remotive.com/api/remote-jobs). No key. ITS OWN TERMS
# explicitly forbid submitting Remotive jobs to third-party job-listing
# sites/aggregators (they name Jooble, Neuvoo, Google Jobs, LinkedIn Jobs)
# unless you link back and credit Remotive, and ask for at most ~4 fetches
# a day. Storing and re-displaying these in this catalogue looks like
# exactly the reuse their terms restrict -- flag this to Zhihao explicitly,
# separately from the usual provenance review, before importing REMOTIVE.
# Every listing is global remote tech, never Singapore-specific.
# --------------------------------------------------------------------------
REMOTIVE_BASE = "https://remotive.com/api/remote-jobs"


def fetch_remotive(pages: int, keyword: str | None, session: requests.Session) -> list[dict]:
    if pages > 1:
        print("remotive returns one snapshot per call; ignoring --pages beyond 1.", file=sys.stderr)
    params = {"limit": 500}
    if keyword:
        params["search"] = keyword     # Remotive's server-side filters are unreliable; --keyword still re-filters below
    resp = session.get(REMOTIVE_BASE, params=params, timeout=20)
    resp.raise_for_status()
    listings = resp.json().get("jobs") or []
    print(f"remotive: API returned {len(listings)} listings before keyword filter.", file=sys.stderr)
    if keyword:
        rx = re.compile(r"(?<![A-Za-z])" + re.escape(keyword) + r"(?:s|ship|ships)?(?![A-Za-z])", re.I)
        listings = [j for j in listings
                    if rx.search(" ".join([j.get("title") or "", j.get("category") or "",
                                            " ".join(str(t) for t in j.get("tags") or [])]))]
        print(f"remotive: {len(listings)} left after --keyword {keyword!r}.", file=sys.stderr)
    return listings


def transform_remotive(raw: dict, fetch_time: datetime, allow_non_english: bool = False) -> dict | None:
    title = normalise_ws(raw.get("title") or "")
    company = normalise_ws(raw.get("company_name") or "")
    job_id = str(raw.get("id") or "")
    if not title or not company or not job_id:
        return skip("missing_title_company_or_id")

    apply_url = raw.get("url") or ""       # Remotive gives one URL per job
    if not str(apply_url).startswith("https://"):
        return skip("no_https_url")

    description = strip_html(raw.get("description") or "")
    if not description:
        return skip("empty_description")
    if not allow_non_english and looks_non_english(description):
        return skip("non_english")

    requirements = extract_requirements(description, raw.get("tags") or [])
    if not requirements:
        return skip("no_requirements_section")

    jt = normalise_ws(raw.get("job_type") or "").lower().replace("-", "_")
    return {
        "source": "REMOTIVE",
        "source_job_id": clip_chars(job_id, 200),
        "title": clip_chars(title, 300),
        "company_name": clip_chars(company, 200),
        "country_code": guess_country_code(raw.get("candidate_required_location") or ""),
        "location": clip_chars(normalise_ws(raw.get("candidate_required_location") or "Worldwide"), 300),
        "description": clip_chars(description, 50_000),
        "apply_url": apply_url,
        "source_url": apply_url,
        "job_type": "UNKNOWN",          # Remotive has no internship flag; never inferred from the title
        "employment_time": {"full_time": "FULL_TIME", "part_time": "PART_TIME"}.get(jt, "UNKNOWN"),
        "work_arrangement": "REMOTE",   # every Remotive listing is remote by definition
        "eligibility_notes": extract_eligibility_notes(description),
        "posted_at": _iso_or_none(raw.get("publication_date")),
        "is_active": True,
        "requirements": [r.to_dict() for r in requirements],
    }


ADAPTERS = {
    "arbeitnow": (fetch_arbeitnow, transform_arbeitnow),
    "ai_jobs_co": (fetch_ai_jobs_co, transform_ai_jobs_co),
    "aidevboard": (fetch_ai_dev_jobs, transform_ai_dev_jobs),
    "remoteok": (fetch_remoteok, transform_remoteok),
    "remotive": (fetch_remotive, transform_remotive),
}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_batch(source: str, pages: int, keyword: str | None, *,
                 enrich: bool = False, enrich_limit: int = 25,
                 allow_non_english: bool = False, location: str | None = None) -> tuple[list[dict], int]:
    fetch_fn, transform_fn = ADAPTERS[source]
    session = requests.Session()
    session.headers["User-Agent"] = "INF2006-P1-G6 catalogue-fetcher/1.0 (student project)"
    raw_listings = fetch_fn(pages, keyword, session, location) if source == "aidevboard" else fetch_fn(pages, keyword, session)
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
        elif source in ("arbeitnow", "remoteok", "remotive"):
            job = transform_fn(raw, fetch_time, allow_non_english)
        else:
            job = transform_fn(raw, fetch_time)
        if job is None:
            skipped += 1
            continue
        if job["source_job_id"] in seen_ids:
            skipped += 1
            SKIPS["duplicate_id"] += 1
            continue
        seen_ids.add(job["source_job_id"])
        jobs.append(job)
    return jobs, skipped


PROVIDER_NOTES = {
    "arbeitnow": "Arbeitnow (https://www.arbeitnow.com/api/job-board-api), free public API, no key. Jobs mostly come "
                 "from employers' ATS feeds. The API returns one URL per job (the Arbeitnow page), used for both "
                 "source_url and apply_url. Coverage is Germany plus remote, so few or no Singapore roles.",
    "ai_jobs_co": "artificialintelligencejobs.co public jobs API; description text is scraped from detail pages "
                  "(best effort, verify a sample).",
    "aidevboard": "AI Dev Jobs API (https://aidevboard.com/openapi.yaml), free public API, no key. AI/ML roles "
                   "worldwide; source_url points to the job's own API record because the spec exposes no public "
                   "listing page.",
    "remoteok": "RemoteOK public API (https://remoteok.com/api), no key. ITS OWN TERMS require a followed backlink "
                "to the job's remoteok.com URL and 'Remote OK' named as the source wherever shown, or they may "
                "suspend access; their logo needs written permission, the name does not. One call returns a fixed "
                "snapshot of the newest ~100 postings, global remote tech, never Singapore-specific.",
    "remotive": "Remotive public API (https://remotive.com/api/remote-jobs), no key. ITS OWN TERMS forbid "
                "submitting Remotive jobs to third-party job-listing sites/aggregators unless you link back and "
                "credit Remotive, and ask for at most ~4 fetches a day. Flag this to Zhihao explicitly, separately "
                "from the usual review, before importing REMOTIVE. Global remote tech, never Singapore-specific.",
}


def write_provenance(provenance_path: Path, batch_path: Path, source: str, pages: int,
                      keyword: str | None, job_count: int, fetch_time: datetime) -> None:
    sidecar = {
        "batch_file": batch_path.name,
        "source_name": source.upper(),
        "provider": PROVIDER_NOTES.get(source, source),
        "collection_method": f"live API fetch via fetch_live_jobs.py (--source {source})",
        "collection_params": {"pages": pages, "keyword": keyword},
        "collected_at": fetch_time.isoformat(),
        "job_count": job_count,
        "transformations": [
            "HTML converted to plain text (entities decoded before tags are parsed)",
            "requirements = lines verbatim from the listing's own requirements/qualifications/'what you bring' "
            "section; requirement_text == source_quote; lines with preferred/nice-to-have/advantage/plus wording "
            "= PREFERRED, all others REQUIRED; jobs with no such section are skipped, no placeholder rows",
            "job_type INTERNSHIP only when the provider's job_types field says internship/Praktikum; never from the title",
            "non-English listings skipped; intermediary employers (" + ", ".join(sorted(INTERMEDIARIES)) + ") skipped; "
            "ATS suffixes such as ' - Personio' removed from company_name",
            "country_code from whole-word location match, otherwise ZZ",
        ],
        "skipped_counts": dict(SKIPS),
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
    ap.add_argument("--pages", type=int, default=1,
                     help="pages to fetch (Arbeitnow/AI Dev Jobs: ~100/50 jobs per page; "
                          "remoteok/remotive return one fixed snapshot regardless)")
    ap.add_argument("--location", default=None, help="aidevboard only: location filter, e.g. Singapore")
    ap.add_argument("--keyword", default=None, help="filter title/tags/job_types by this keyword")
    ap.add_argument("--out", type=Path, required=True, help="output path, e.g. data/live_batch.json")
    ap.add_argument("--enrich-descriptions", action="store_true",
                     help="ai_jobs_co only: fetch each job's own page for real posting text "
                          "(one extra HTTP request per job; see adapter docstring)")
    ap.add_argument("--enrich-limit", type=int, default=25,
                     help="ai_jobs_co only: cap on how many jobs get the extra page fetch")
    ap.add_argument("--allow-non-english", action="store_true",
                     help="keep listings that look German/French etc. (the embedding model is English)")
    args = ap.parse_args(argv)

    if args.enrich_descriptions and args.source != "ai_jobs_co":
        print("--enrich-descriptions only applies to --source ai_jobs_co; ignoring.", file=sys.stderr)

    if args.location and args.source != "aidevboard":
        print("--location only applies to --source aidevboard; ignoring.", file=sys.stderr)
    jobs, skipped = build_batch(args.source, args.pages, args.keyword,
                                 enrich=args.enrich_descriptions, enrich_limit=args.enrich_limit,
                                 allow_non_english=args.allow_non_english,
                                 location=args.location if args.source == "aidevboard" else None)
    if not jobs:
        print(f"No usable jobs produced (skipped {skipped}: {dict(SKIPS)}). Nothing written.", file=sys.stderr)
        return 1

    batch = {"schema_version": 1, "jobs": jobs}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(batch, indent=2, ensure_ascii=False), encoding="utf-8")

    provenance_path = args.out.with_suffix(".provenance.json")
    write_provenance(provenance_path, args.out, args.source, args.pages, args.keyword,
                      len(jobs), datetime.now(timezone.utc))

    print(f"Wrote {len(jobs)} jobs to {args.out} (skipped {skipped} unusable listings: {dict(SKIPS)})")
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