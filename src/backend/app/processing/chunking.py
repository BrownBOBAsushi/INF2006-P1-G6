"""Resume chunking under the 240-token limit. Never truncates: it splits, or raises.

Rules (MVP_PRD.md, ARCHITECTURE.md): each project or experience entry is a meaningful chunk headed by its
section and title (retaining context); long entries are split by bullet/newline, then sentence, then, only when a
single sentence is itself too long, at tokenizer-token boundaries. Every chunk is at most `max_tokens`
tokenizer tokens including the heading and special tokens ([CLS]/[SEP]).

Education and skills are not embedded (contract). The same algorithm is used by analytics/evaluate.py; a test
asserts the two produce identical chunks.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from app.processing.config import MAX_CHUNKS_PER_PROFILE, MAX_INPUT_TOKENS
from app.processing.errors import ProcessingError, TokenLimitError

_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_MIN_WINDOW = 8  # a heading may not consume so much budget that fewer than this many body tokens fit


class TokenCounter:
    """Counts tokenizer tokens including special tokens. Truncation is disabled: it measures, it never cuts."""

    def __init__(self, hf_tokenizer: Any):
        self.tok = hf_tokenizer
        self.tok.model_max_length = 1_000_000  # silences the length warning only

    def count(self, text: str) -> int:
        return len(self.tok(text, add_special_tokens=True, truncation=False)["input_ids"])


def split_units(text: str) -> list[str]:
    """Bullets/lines first, then sentences."""
    units: list[str] = []
    for line in text.splitlines():
        line = _BULLET.sub("", line).strip()
        if line:
            units.extend(s.strip() for s in _SENTENCE.split(line) if s.strip())
    return units


def _render(heading: str, units: list[str]) -> str:
    return heading + "\n" + " ".join(units)


def _hard_split(counter: TokenCounter, heading: str, unit: str, max_tokens: int) -> list[str]:
    """Split one over-long sentence at token boundaries so that heading + piece fits max_tokens."""
    window = max_tokens - counter.count(_render(heading, [""]))
    if window < _MIN_WINDOW:
        raise TokenLimitError("heading leaves no room for body text within the token limit")
    offs = counter.tok(unit, add_special_tokens=False, return_offsets_mapping=True, truncation=False)["offset_mapping"]
    n, start, pieces = len(offs), 0, []
    while start < n:
        w = window
        while True:
            end = min(start + w, n)
            c0 = offs[start][0]
            c1 = len(unit) if end == n else offs[end][0]
            piece = unit[c0:c1].strip()
            if counter.count(_render(heading, [piece])) <= max_tokens:
                break
            w -= 1  # re-tokenising a substring can add a token at a cut; shrink until it fits
            if w < 1:
                raise TokenLimitError("cannot fit a single token")
        pieces.append(piece)
        start = end
    return pieces


def chunk_entry(counter: TokenCounter, heading: str, body: str, technologies: Iterable[str] = (),
                max_tokens: int = MAX_INPUT_TOKENS) -> list[str]:
    """One entry -> chunk texts, each `heading + newline + units` and <= max_tokens tokens."""
    units = split_units(body)
    tech = [t for t in technologies if t and t.strip()]
    if tech:
        units.append("Technologies: " + ", ".join(tech) + ".")
    if not units:
        return []
    groups: list[list[str]] = []
    cur: list[str] = []
    for unit in units:
        pieces = [unit] if counter.count(_render(heading, [unit])) <= max_tokens \
            else _hard_split(counter, heading, unit, max_tokens)
        for piece in pieces:
            if cur and counter.count(_render(heading, cur + [piece])) > max_tokens:
                groups.append(cur)
                cur = []
            cur.append(piece)
    if cur:
        groups.append(cur)
    texts = [_render(heading, g) for g in groups]
    for t in texts:  # belt and braces: the invariant the whole pipeline relies on
        if counter.count(t) > max_tokens:
            raise TokenLimitError("chunk exceeds the token limit")
    return texts


def chunk_resume_content(counter: TokenCounter, content: dict, max_tokens: int = MAX_INPUT_TOKENS) -> list[dict]:
    """ResumeContent -> chunk dicts {section, entry_index, chunk_index, text} for projects then experience.

    More than MAX_CHUNKS_PER_PROFILE chunks is an error (INVALID_CONTENT): the user must shorten the content;
    nothing is dropped silently.
    """
    out: list[dict] = []
    for section, key, label in (("PROJECT", "projects", "Project"), ("EXPERIENCE", "experience", "Experience")):
        for entry_index, entry in enumerate(content.get(key, [])):
            heading = f"{label}: {entry.get('title', '')}".rstrip()
            texts = chunk_entry(counter, heading, entry.get("description", ""), entry.get("technologies", ()), max_tokens)
            out.extend({"section": section, "entry_index": entry_index, "chunk_index": ci, "text": t}
                       for ci, t in enumerate(texts))
    if len(out) > MAX_CHUNKS_PER_PROFILE:
        raise ProcessingError("INVALID_CONTENT", "chunk_cap")
    return out
