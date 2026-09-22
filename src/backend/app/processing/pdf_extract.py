"""PDF text extraction with pdfplumber (text PDFs only; no OCR).

Every failure mode maps to a contract error code and a fixed message. Parser exceptions are swallowed and
never propagated, because their text can include document content. Nothing is written to disk or logged
beyond counts.
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass

import pdfplumber
from pdfminer.pdfdocument import PDFPasswordIncorrect

from app.processing.config import MAX_PDF_BYTES, MAX_PDF_PAGES, MIN_TEXT_CHARS
from app.processing.errors import ProcessingError

log = logging.getLogger(__name__)

PAGE_BREAK_GAP = 1000.0  # gap_before for the first line on a page (treated as "large")


@dataclass(frozen=True)
class ExtractedLine:
    text: str
    bold: bool = False
    size: float = 0.0
    gap_before: float = PAGE_BREAK_GAP  # vertical distance in points from the previous line's bottom


@dataclass(frozen=True)
class ExtractedDocument:
    lines: tuple[ExtractedLine, ...]
    page_count: int

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)


def _is_password_error(exc: BaseException) -> bool:
    # pdfplumber wraps pdfminer errors: PdfminerException(PDFPasswordIncorrect())
    return isinstance(exc, PDFPasswordIncorrect) or any(isinstance(a, PDFPasswordIncorrect) for a in exc.args)


def _line_from_dict(raw: dict, prev_bottom: float | None) -> ExtractedLine | None:
    text = " ".join(str(raw.get("text", "")).split())
    if not text:
        return None
    chars = raw.get("chars") or []
    bold = bool(chars) and sum("bold" in str(c.get("fontname", "")).casefold() for c in chars) * 2 > len(chars)
    size = round(max((float(c.get("size", 0.0)) for c in chars), default=0.0), 1)
    gap = PAGE_BREAK_GAP if prev_bottom is None else max(0.0, float(raw["top"]) - prev_bottom)
    return ExtractedLine(text=text, bold=bold, size=size, gap_before=round(gap, 1))


def extract_pdf(data: bytes) -> ExtractedDocument:
    """Extract text lines (with font hints) from PDF bytes, or raise ProcessingError.

    Order of checks (deterministic): size, PDF signature, encryption/readability, page limit, text presence.
    """
    if len(data) > MAX_PDF_BYTES:
        raise ProcessingError("FILE_TOO_LARGE", "byte_limit")
    if not data.startswith(b"%PDF-"):
        raise ProcessingError("PDF_REQUIRED", "missing_signature")

    lines: list[ExtractedLine] = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            page_count = len(pdf.pages)
            if page_count == 0:
                raise ProcessingError("PDF_UNREADABLE", "no_pages")
            if page_count > MAX_PDF_PAGES:
                raise ProcessingError("PDF_UNREADABLE", "page_limit")
            for page in pdf.pages:
                prev_bottom = None
                for raw in page.extract_text_lines(strip=True, return_chars=True):
                    line = _line_from_dict(raw, prev_bottom)
                    if line is not None:
                        lines.append(line)
                        prev_bottom = float(raw["bottom"])
    except ProcessingError:
        raise
    except Exception as exc:  # noqa: BLE001 - deliberately broad: pdf parsers raise many types
        if _is_password_error(exc):
            raise ProcessingError("PDF_ENCRYPTED", "password_required") from None
        # Log only the exception class name: its message can contain document content.
        log.warning("pdf_extract_failed exception_class=%s", type(exc).__name__)
        raise ProcessingError("PDF_UNREADABLE", "parse_error") from None

    if sum(len("".join(l.text.split())) for l in lines) < MIN_TEXT_CHARS:
        raise ProcessingError("TEXT_REQUIRED", "no_text_layer")
    log.info("pdf_extracted pages=%d lines=%d", page_count, len(lines))
    return ExtractedDocument(lines=tuple(lines), page_count=page_count)
