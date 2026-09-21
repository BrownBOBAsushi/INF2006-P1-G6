"""Checks that the synthetic PDF fixtures have the properties the extraction/privacy tests rely on.

Run from the repo root with the analytics environment plus tests/fixtures/requirements-pdf.txt:
    pytest tests/fixtures
These tests verify the FIXTURES (with pdfplumber), not any backend pipeline, which does not exist yet.
"""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pdfplumber
import pytest

FIX = Path(__file__).resolve().parent
PDF_DIR = FIX / "pdf"
MANIFEST = json.loads((FIX / "pdf_manifest.json").read_text(encoding="utf-8"))
ENTRIES = {e["file"]: e for e in MANIFEST["files"]}
VALID = [e for e in MANIFEST["files"] if e["kind"] == "valid_text_resume"]


def _text(path: Path) -> str:
    with pdfplumber.open(path) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def _flat(s: str) -> str:
    return re.sub(r"\s+", " ", s)


def test_manifest_lists_ten_valid_resumes_and_five_edge_cases():
    assert len(VALID) == 10
    assert len(MANIFEST["files"]) == 15


def test_manifest_checksums_match_files_and_files_are_small():
    for e in MANIFEST["files"]:
        data = (PDF_DIR / e["file"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == e["sha256"], e["file"]
        assert len(data) < 100_000, e["file"]


@pytest.mark.parametrize("entry", VALID, ids=lambda e: e["file"])
def test_valid_resume_has_text_layer_pii_and_content(entry):
    text = _flat(_text(PDF_DIR / entry["file"]))
    for pii in entry["pii_must_not_survive_cleanup"]:
        assert pii in text, f"fixture is missing the fictional PII string {pii!r} the privacy test needs"
    for title in entry["content_must_survive"]:
        assert title in text
    for heading in ("Skills", "Projects", "Experience", "Education"):
        assert heading in text


def test_pii_is_fictional_by_construction():
    for e in VALID:
        pii = e["pii_must_not_survive_cleanup"]
        name, email, phone, address, nid, url = pii
        assert email.endswith("@example.com")
        assert phone.replace("+65 ", "").startswith("9000 ")
        assert address.endswith("Singapore 000000")
        assert re.fullmatch(r"S00000\d\dZ", nid)
        assert url.startswith("https://example.com/")


def test_unfamiliar_headings_variant_lacks_standard_headings():
    text = _text(PDF_DIR / "edge_unfamiliar_headings.pdf")
    assert "Things I Have Built" in text and "Where I Have Worked" in text
    assert "Projects" not in text and "Experience" not in text


def test_scanned_fixture_has_no_text_layer_but_has_an_image():
    with pdfplumber.open(PDF_DIR / "edge_scanned_image_only.pdf") as pdf:
        assert (pdf.pages[0].extract_text() or "").strip() == ""
        assert len(pdf.pages[0].images) == 1


def test_encrypted_fixture_needs_a_password():
    path = PDF_DIR / "edge_encrypted.pdf"
    with pytest.raises(Exception) as exc:
        with pdfplumber.open(path) as pdf:
            pdf.pages[0].extract_text()
    assert "PDFPasswordIncorrect" in repr(exc.value)      # pdfplumber wraps pdfminer's password error
    with pdfplumber.open(path, password="synthetic-test-only") as pdf:
        assert "Skills" in (pdf.pages[0].extract_text() or "")


def test_page_limit_fixture_has_eleven_pages():
    with pdfplumber.open(PDF_DIR / "edge_11_pages.pdf") as pdf:
        assert len(pdf.pages) == 11


def test_not_a_pdf_fixture_is_rejected_by_the_parser_and_lacks_pdf_magic():
    path = PDF_DIR / "edge_not_a_pdf.pdf"
    assert not path.read_bytes().startswith(b"%PDF")
    with pytest.raises(Exception):
        pdfplumber.open(path)


def test_generation_is_deterministic(tmp_path):
    subprocess.run([sys.executable, str(FIX / "generate_pdf_fixtures.py"), "--out", str(tmp_path / "pdf")],
                   check=True, capture_output=True)
    for e in MANIFEST["files"]:
        if e["kind"] == "encrypted":
            continue  # encryption is not byte-deterministic
        assert hashlib.sha256((tmp_path / "pdf" / e["file"]).read_bytes()).hexdigest() == e["sha256"], e["file"]
