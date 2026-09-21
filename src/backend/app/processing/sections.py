"""Deterministic heading/bullet parsing of cleaned resume lines into the contract's ResumeContent draft.

No LLM and no invention: text is only split and regrouped. Anything that cannot be placed (unfamiliar headings,
unsupported sections such as Certifications, text before the first heading, entries over the contract limits)
goes to `unassigned_text` with a SECTION_REVIEW_NEEDED warning, so nothing is silently dropped. The student
assigns or omits it on the review screen; it is never embedded directly.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from typing import Sequence

from app.processing.pdf_extract import PAGE_BREAK_GAP, ExtractedLine
from app.processing.vocab import heading_key

ENTRY_GAP_POINTS = 5.0      # vertical gap larger than this (unformatted input) starts a new entry
HEADING_SIZE_RATIO = 1.15   # bold text this much larger than body text is treated as a heading
_BULLET = re.compile(r"^\s*(?:[-*•▪]|\d+[.)])\s+")
_TECH_LINE = re.compile(r"^\s*technolog(?:y|ies)\s*:\s*(.+)$", re.IGNORECASE)
_EDU_SEP = re.compile(r"\s+[-–—|]\s+")
_SKILL_SPLIT = re.compile(r"[,;|•\n]")


@dataclass
class PrepareResult:
    draft: dict
    unassigned_text: str
    warnings: list[dict] = field(default_factory=list)


def _norm_gap(gap: float) -> float:
    return 0.0 if gap >= PAGE_BREAK_GAP else gap   # page starts are not evidence of a new entry


def _split_skills(lines: Sequence[ExtractedLine]) -> list[str]:
    out: list[str] = []
    for ln in lines:
        text = _BULLET.sub("", ln.text)
        head, sep, tail = text.partition(":")
        if sep and len(head) <= 30 and tail.strip():
            text = tail
        out += [p.strip() for p in _SKILL_SPLIT.split(text) if p.strip()]
    seen, unique = set(), []
    for s in out:
        if s.casefold() not in seen:
            seen.add(s.casefold())
            unique.append(s)
    return unique


def _entries(lines: Sequence[ExtractedLine]) -> list[dict]:
    """Group lines into {title, description, technologies} entries."""
    formatted = any(l.bold for l in lines)
    groups: list[list[ExtractedLine]] = []
    prev_was_tech = False
    for ln in lines:
        gap = _norm_gap(ln.gap_before)
        starts = not groups or prev_was_tech or (ln.bold and formatted) or (not formatted and gap > ENTRY_GAP_POINTS)
        if starts:
            groups.append([])
        groups[-1].append(ln)
        prev_was_tech = bool(_TECH_LINE.match(ln.text))
    entries = []
    for g in groups:
        title, body = "", list(g)
        first = body[0]
        if first.bold and formatted:
            title, body = first.text, body[1:]
        elif len(first.text) <= 80 and not first.text.rstrip().endswith((".", "!", "?")) and len(body) > 1 \
                and not _TECH_LINE.match(first.text):
            title, body = first.text, body[1:]
        tech: list[str] = []
        desc = ""
        for ln in body:
            m = _TECH_LINE.match(ln.text)
            if m:
                tech += [t.strip() for t in m.group(1).rstrip(".").split(",") if t.strip()]
            elif _BULLET.match(ln.text):
                desc += ("\n" if desc else "") + _BULLET.sub("", ln.text)
            else:
                desc += (" " if desc else "") + ln.text
        if title or desc or tech:
            entries.append({"title": title, "description": desc, "technologies": tech})
    return entries


def _education(lines: Sequence[ExtractedLine]) -> list[dict]:
    """One entry per 'qualification - details' line; a following wrapped line (no separator, no gap, not bold)
    continues the previous entry's details instead of becoming a new entry."""
    out: list[dict] = []
    for ln in lines:
        text = _BULLET.sub("", ln.text)
        parts = _EDU_SEP.split(text, maxsplit=1)
        continuation = (out and len(parts) == 1 and not ln.bold and _norm_gap(ln.gap_before) <= ENTRY_GAP_POINTS
                        and out[-1]["details"])
        if continuation:
            out[-1]["details"] += " " + text.strip()
        else:
            out.append({"qualification": parts[0].strip(), "details": parts[1].strip() if len(parts) > 1 else ""})
    return out


def _fits_entry(e: dict) -> bool:
    return (len(e["title"]) <= 200 and len(e["description"]) <= 5000 and len(e["technologies"]) <= 30
            and all(len(t) <= 100 for t in e["technologies"]))


def _entry_text(e: dict) -> str:
    tech = f"\nTechnologies: {', '.join(e['technologies'])}" if e["technologies"] else ""
    return "\n".join(x for x in (e["title"], e["description"]) if x) + tech


def parse_sections(lines: Sequence[ExtractedLine]) -> PrepareResult:
    sizes = [l.size for l in lines if l.size > 0]
    body_size = statistics.median(sizes) if sizes else 0.0
    buckets: dict[str, list[ExtractedLine]] = {"skills": [], "projects": [], "experience": [], "education": [], "other": []}
    current = "other"
    for ln in lines:
        key = heading_key(ln.text)
        if key is not None:
            current = "other" if key == "unsupported" else key
            if key == "unsupported":
                buckets["other"].append(ln)             # keep the heading text with its content
            continue
        looks_like_heading = body_size > 0 and ln.bold and ln.size >= body_size * HEADING_SIZE_RATIO
        if looks_like_heading:
            current = "other"                           # unfamiliar heading: this and following text is unassigned
        buckets[current].append(ln)

    unassigned: list[str] = [l.text for l in buckets["other"]]
    skills = _split_skills(buckets["skills"])
    keep_skills = []
    for s in skills:
        (keep_skills if len(s) <= 100 and len(keep_skills) < 100 else unassigned).append(s)
    content = {"skills": keep_skills, "projects": [], "experience": [], "education": []}
    for key, cap in (("projects", 20), ("experience", 20)):
        for e in _entries(buckets[key]):
            if len(content[key]) < cap and _fits_entry(e):
                content[key].append(e)
            else:
                unassigned.append(_entry_text(e))
    for e in _education(buckets["education"]):
        if len(content["education"]) < 10 and len(e["qualification"]) <= 200 and len(e["details"]) <= 5000:
            content["education"].append(e)
        else:
            unassigned.append(f"{e['qualification']} {e['details']}".strip())
    text = "\n".join(unassigned).strip()
    warnings = [{"code": "SECTION_REVIEW_NEEDED",
                 "message": "Some text could not be placed in a section. Please review it and add it where it belongs."}] \
        if text else []
    return PrepareResult(draft=content, unassigned_text=text, warnings=warnings)


def parse_sections_from_text(text: str) -> PrepareResult:
    """Plain-text variant (no font hints): blank lines separate entries."""
    lines: list[ExtractedLine] = []
    blank = False
    for raw in text.splitlines():
        if not raw.strip():
            blank = True
            continue
        lines.append(ExtractedLine(text=" ".join(raw.split()), gap_before=12.0 if blank else 0.0))
        blank = False
    return parse_sections(lines)
