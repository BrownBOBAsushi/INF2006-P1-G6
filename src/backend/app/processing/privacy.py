"""Privacy cleanup with Microsoft Presidio (local, offline) plus app-specific rules.

Detected and replaced with fixed placeholders ([PERSON], [EMAIL], [PHONE], [ADDRESS], [ID], [URL]):
person names (spaCy NER plus a resume-header rule), email addresses, phone numbers (Singapore formats and
Presidio's phone recognizer), Singapore-style addresses (Blk/street/unit/postal code) and NRIC/FIN-style IDs,
and URLs. Generic location words are deliberately NOT removed ("Singapore" alone stays) and technical terms
(Python, Node.js, ASP.NET, ...) are protected by an allow-list.

Deterministic: same input gives the same output. No logging of content: only entity-type counts. This is
best-effort minimisation, not a guarantee of perfect anonymisation; the student reviews the result.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Sequence

from app.processing.vocab import contains_tech_term, heading_key, is_generic_phrase

log = logging.getLogger(__name__)

SPACY_MODEL = "en_core_web_sm"

PLACEHOLDERS = {
    "PERSON": "[PERSON]", "EMAIL_ADDRESS": "[EMAIL]", "PHONE_NUMBER": "[PHONE]", "SG_ADDRESS": "[ADDRESS]",
    "SG_NRIC_FIN": "[ID]", "URL": "[URL]",
}
_PROTECTED_ENTITIES = {"PERSON", "URL"}          # results overlapping a technical term are dropped for these
_PLACEHOLDER_ONLY_LINE = re.compile(r"^\s*(?:(?:[A-Za-z ]{0,20}|\[[A-Z]+\]):\s*)?(?:\[[A-Z]+\][\s,|/-]*)+$")
_NAME_LINE = re.compile(r"^[A-Z][A-Za-z'’-]+(?:\s+[A-Z][A-Za-z'’-]+){1,3}$")


@dataclass(frozen=True)
class RedactionResult:
    lines: list[str]                      # cleaned lines (lines that became placeholder-only are removed)
    kept: list[int]                       # index in the input of each returned line (to carry formatting hints)
    counts: dict[str, int] = field(default_factory=dict)   # entity type -> number of replacements (no content)


class Redactor:
    def __init__(self) -> None:
        from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerRegistry
        from presidio_analyzer.nlp_engine import NlpEngineProvider
        from presidio_analyzer.predefined_recognizers import (
            EmailRecognizer, PhoneRecognizer, SpacyRecognizer, UrlRecognizer,
        )

        nlp = NlpEngineProvider(nlp_configuration={
            "nlp_engine_name": "spacy", "models": [{"lang_code": "en", "model_name": SPACY_MODEL}],
        }).create_engine()
        registry = RecognizerRegistry(supported_languages=["en"])
        for rec in (EmailRecognizer(), UrlRecognizer(), PhoneRecognizer(supported_regions=("SG",)),
                    SpacyRecognizer(supported_entities=["PERSON"])):
            registry.add_recognizer(rec)
        cs = re.MULTILINE  # case-sensitive custom patterns
        registry.add_recognizer(PatternRecognizer(
            supported_entity="SG_NRIC_FIN", global_regex_flags=cs,
            patterns=[Pattern("sg_nric_fin", r"\b[STFGM]\d{7}[A-Z]\b", 0.9)]))
        registry.add_recognizer(PatternRecognizer(
            supported_entity="PHONE_NUMBER", name="SgPhoneRecognizer", global_regex_flags=cs,
            patterns=[Pattern("sg_phone", r"(?<![\d])(?:\+65[\s-]?)?[3689]\d{3}[\s-]?\d{4}(?![\d])", 0.75)]))
        registry.add_recognizer(PatternRecognizer(
            supported_entity="SG_ADDRESS", global_regex_flags=cs,
            patterns=[
                Pattern("sg_blk", r"\b(?:Blk|Block)\s+\d+[A-Za-z]?\b[^\n]*", 0.85),
                Pattern("sg_street", r"\b\d{1,4}[A-Za-z]?\s+(?:[A-Z][A-Za-z]+\s+){1,3}"
                                     r"(?:Road|Rd|Street|St|Avenue|Ave|Drive|Dr|Lane|Crescent|Close|Way|Walk|Place|"
                                     r"Terrace|Boulevard)\b[^\n]*", 0.8),
                Pattern("sg_postal", r"\bSingapore\s+\d{6}\b", 0.8),
                Pattern("sg_unit", r"#\d{1,3}-\d{1,4}\b", 0.7),
            ]))
        self._analyzer = AnalyzerEngine(nlp_engine=nlp, registry=registry, supported_languages=["en"])
        self._entities = list(PLACEHOLDERS)

    def _spans(self, line: str) -> list[tuple[int, int, str]]:
        found = self._analyzer.analyze(text=line, language="en", entities=self._entities)
        spans = []
        for r in found:
            span = line[r.start:r.end]
            if r.entity_type in _PROTECTED_ENTITIES and (contains_tech_term(span) or is_generic_phrase(span)):
                continue                      # "Node.js" mistaken for a domain, "Android"/"Volunteer" for a name, ...
            spans.append((r.start, r.end, r.entity_type, r.score))
        # Resolve overlaps deterministically: longest span first, then higher score, then earlier start.
        spans.sort(key=lambda s: (-(s[1] - s[0]), -s[3], s[0]))
        chosen: list[tuple[int, int, str]] = []
        for s, e, t, _ in spans:
            if all(e <= cs or s >= ce for cs, ce, _ in chosen):
                chosen.append((s, e, t))
        return sorted(chosen)

    def redact_lines(self, lines: Sequence[str], header_rule: bool = False) -> RedactionResult:
        """`header_rule=True` is for a WHOLE document only: its first line, if it is just a name, is redacted."""
        counts: dict[str, int] = {}
        cleaned: list[str] = []
        for line in lines:
            out = line
            for s, e, t in reversed(self._spans(line)):
                out = out[:s] + PLACEHOLDERS[t] + out[e:]
                counts[t] = counts.get(t, 0) + 1
            cleaned.append(out)
        if header_rule:
            cleaned = self._redact_header_names(list(lines), cleaned, counts)
        kept = [i for i, ln in enumerate(cleaned) if ln.strip() and not _PLACEHOLDER_ONLY_LINE.match(ln)]
        log.info("privacy_redacted lines_in=%d lines_out=%d counts=%s", len(lines), len(kept), dict(sorted(counts.items())))
        return RedactionResult(lines=[cleaned[i] for i in kept], kept=kept, counts=dict(sorted(counts.items())))

    @staticmethod
    def _redact_header_names(original: list[str], cleaned: list[str], counts: dict[str, int]) -> list[str]:
        """App rule for a whole document: a resume's first non-empty line that is just a capitalised 2-4 word name
        is a person name, even if NER missed it. Applies to that one line only, never to the body."""
        for i, raw in enumerate(original):
            if not raw.strip():
                continue
            if heading_key(raw) is None and _NAME_LINE.match(raw.strip()) and cleaned[i] == raw                     and not contains_tech_term(raw) and not is_generic_phrase(raw):
                cleaned[i] = PLACEHOLDERS["PERSON"]
                counts["PERSON"] = counts.get("PERSON", 0) + 1
            break
        return cleaned

    def redact_text(self, text: str) -> str:
        return "\n".join(self.redact_lines(text.splitlines()).lines)


@lru_cache(maxsize=1)
def get_redactor() -> Redactor:
    """Build the analyzer once (loading the spaCy model is the slow part)."""
    return Redactor()
