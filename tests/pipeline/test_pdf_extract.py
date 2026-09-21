"""PDF extraction: the real extractor on the real synthetic fixtures plus generated edge cases."""
import io
import logging
import sys

import pytest
from reportlab.pdfgen import canvas

from conftest import PDF_DIR, ROOT

sys.path.insert(0, str(ROOT / "tests" / "fixtures"))
import generate_pdf_fixtures as gen  # noqa: E402

from app.processing.config import MAX_PDF_BYTES, MAX_PDF_PAGES  # noqa: E402
from app.processing.errors import ProcessingError  # noqa: E402
from app.processing.pdf_extract import extract_pdf  # noqa: E402


def _code(data: bytes) -> ProcessingError:
    with pytest.raises(ProcessingError) as exc:
        extract_pdf(data)
    return exc.value


def test_valid_resume_extracts_lines_with_headings_and_font_hints():
    doc = extract_pdf((PDF_DIR / "resume_P01.pdf").read_bytes())
    assert doc.page_count == 1
    texts = [l.text for l in doc.lines]
    assert {"Skills", "Projects", "Experience", "Education"} <= set(texts)
    skills_heading = next(l for l in doc.lines if l.text == "Skills")
    body = next(l for l in doc.lines if l.text.startswith("Python, Java"))
    assert skills_heading.bold and skills_heading.size > body.size      # formatting hints survive extraction
    assert "Campus event booking service" in texts


def test_multi_page_pdf_is_extracted_and_page_limit_is_inclusive():
    three = extract_pdf(gen.build_many_pages_pdf(3))
    assert three.page_count == 3 and "Skills: Python, SQL." in three.text
    assert extract_pdf(gen.build_many_pages_pdf(MAX_PDF_PAGES)).page_count == MAX_PDF_PAGES


def test_eleven_pages_is_rejected_by_the_page_limit():
    err = _code((PDF_DIR / "edge_11_pages.pdf").read_bytes())
    assert (err.code, err.reason) == ("PDF_UNREADABLE", "page_limit") and err.status_code == 422


def test_encrypted_pdf_is_reported_as_encrypted_not_crashed():
    err = _code((PDF_DIR / "edge_encrypted.pdf").read_bytes())
    assert err.code == "PDF_ENCRYPTED" and err.status_code == 422


def test_non_pdf_bytes_and_empty_input_are_pdf_required():
    assert _code((PDF_DIR / "edge_not_a_pdf.pdf").read_bytes()).code == "PDF_REQUIRED"
    err = _code(b"")
    assert err.code == "PDF_REQUIRED" and err.status_code == 415


def test_scanned_image_only_pdf_is_text_required_not_silently_empty():
    err = _code((PDF_DIR / "edge_scanned_image_only.pdf").read_bytes())
    assert err.code == "TEXT_REQUIRED" and err.reason == "no_text_layer"


def test_nearly_empty_text_pdf_is_text_required():
    buf = io.BytesIO()
    c = canvas.Canvas(buf, invariant=1)
    c.drawString(72, 700, "Hi")
    c.save()
    assert _code(buf.getvalue()).code == "TEXT_REQUIRED"


def test_truncated_and_corrupt_pdfs_are_unreadable_not_exceptions():
    valid = (PDF_DIR / "resume_P01.pdf").read_bytes()
    assert _code(valid[:300]).code == "PDF_UNREADABLE"
    assert _code(b"%PDF-1.4\n" + b"\x00garbage" * 50).code == "PDF_UNREADABLE"


def test_size_limit_is_checked_first_and_is_exact():
    over = b"%PDF-" + b"0" * (MAX_PDF_BYTES - 4)            # exactly MAX_PDF_BYTES + 1 bytes
    assert len(over) == MAX_PDF_BYTES + 1
    assert _code(over).code == "FILE_TOO_LARGE" and _code(over).status_code == 413
    at_limit = b"%PDF-" + b"0" * (MAX_PDF_BYTES - 5)          # exactly MAX_PDF_BYTES: passes the size gate
    assert len(at_limit) == MAX_PDF_BYTES
    assert _code(at_limit).code == "PDF_UNREADABLE"


def test_errors_and_logs_never_contain_resume_content(caplog):
    caplog.set_level(logging.DEBUG)
    secrets = [gen.fake_identity(1)["email"], gen.fake_identity(1)["national_id"], "Nightly data loader"]
    for name in ("edge_encrypted.pdf", "edge_scanned_image_only.pdf", "edge_11_pages.pdf", "edge_not_a_pdf.pdf"):
        err = _code((PDF_DIR / name).read_bytes())
        blob = f"{err} {err.message} {err.reason} {err.code}"
        assert not any(s in blob for s in secrets)
    extract_pdf((PDF_DIR / "resume_P01.pdf").read_bytes())    # success path logs counts only
    assert "pdf_extracted pages=1" in caplog.text            # logging is live (the negative check below is not vacuous)
    assert not any(s in caplog.text for s in secrets)


def test_third_party_debug_logging_that_would_leak_resume_text_is_capped(caplog):
    """pdfminer logs raw document tokens at DEBUG. Root DEBUG must not make resume text appear in logs."""
    assert logging.getLogger("pdfminer").level == logging.WARNING
    assert logging.getLogger("presidio-analyzer").level == logging.WARNING
    caplog.set_level(logging.DEBUG)
    extract_pdf((PDF_DIR / "resume_P03.pdf").read_bytes())
    assert "Handwritten digit recogniser" not in caplog.text and "pdfminer" not in caplog.text


@pytest.mark.parametrize("name", [f"resume_P{i:02d}.pdf" for i in range(1, 11)])
def test_every_valid_fixture_extracts(name):
    doc = extract_pdf((PDF_DIR / name).read_bytes())
    assert doc.page_count >= 1 and len(doc.lines) > 10
