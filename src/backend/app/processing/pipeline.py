"""Processing pipeline glue: PDF -> extraction -> privacy -> sections (prepare), and content -> chunks -> vectors (save).

Stage functions are separate so the API layer can call them where the contract says (prepare before review; privacy
re-check and embedding at confirm/save). Nothing here touches the database, the network or the session.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass

import numpy as np

from app.processing.chunking import chunk_resume_content
from app.processing.config import MIN_TEXT_CHARS
from app.processing.content import validate_resume_content
from app.processing.errors import ProcessingError
from app.processing.pdf_extract import extract_pdf
from app.processing.privacy import Redactor, get_redactor
from app.processing.sections import PrepareResult, parse_sections


def prepare_resume(pdf_bytes: bytes, redactor: Redactor | None = None) -> PrepareResult:
    """/api/resume/prepare core: {draft, unassigned_text, warnings} from a PDF, or a ProcessingError."""
    doc = extract_pdf(pdf_bytes)
    red = (redactor or get_redactor()).redact_lines([l.text for l in doc.lines], header_rule=True)
    if sum(len("".join(t.split())) for t in red.lines) < MIN_TEXT_CHARS:
        raise ProcessingError("TEXT_REQUIRED", "nothing_left_after_privacy")
    cleaned = [dataclasses.replace(doc.lines[i], text=t) for i, t in zip(red.kept, red.lines)]
    return parse_sections(cleaned)


def recheck_privacy(content: dict, redactor: Redactor | None = None) -> tuple[bool, dict]:
    """Final-save re-run of cleanup. Returns (changed, cleaned_content). The API answers 422 REVIEW_REQUIRED with the
    cleaned draft when `changed` is true, instead of silently saving text the student has not seen."""
    r = redactor or get_redactor()

    def clean(s: str) -> str:
        return "\n".join(r.redact_lines(s.split("\n")).lines) if s else s

    cleaned = {
        "skills": [c for c in (clean(s) for s in content["skills"]) if c],
        "projects": [{**e, "title": clean(e["title"]), "description": clean(e["description"]),
                      "technologies": [t for t in (clean(x) for x in e["technologies"]) if t]} for e in content["projects"]],
        "experience": [{**e, "title": clean(e["title"]), "description": clean(e["description"]),
                        "technologies": [t for t in (clean(x) for x in e["technologies"]) if t]} for e in content["experience"]],
        "education": [{"qualification": clean(e["qualification"]), "details": clean(e["details"])} for e in content["education"]],
    }
    return cleaned != content, cleaned


@dataclass(frozen=True)
class ResumeEmbedding:
    version: str
    chunks: list[dict]            # {section, entry_index, chunk_index, text}
    vectors: np.ndarray           # (len(chunks), dim) float32, unit-normalised

    @property
    def matrix(self) -> np.ndarray:
        return self.vectors


def embed_resume(content: dict, model) -> ResumeEmbedding:
    """Validate approved content, chunk it under the 240-token limit and embed the chunks.

    Skills-only/education-only content yields zero chunks (it may be saved but cannot be matched).
    """
    validate_resume_content(content)
    chunks = chunk_resume_content(model.counter, content)
    vectors = model.embed([c["text"] for c in chunks]) if chunks else np.zeros((0, model.dim), dtype=np.float32)
    return ResumeEmbedding(model.version, chunks, vectors)
