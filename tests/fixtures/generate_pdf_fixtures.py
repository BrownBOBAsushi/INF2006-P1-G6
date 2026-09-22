#!/usr/bin/env python
"""Generate synthetic resume PDFs for testing PDF extraction and privacy cleanup.

    python tests/fixtures/generate_pdf_fixtures.py            # writes tests/fixtures/pdf/ and pdf_manifest.json

Every person, email, phone number, address and ID below is FICTIONAL and machine-generated:
emails use the reserved example.com domain, phones are +65 9000 00NN, ID-like strings are S00000NNZ,
addresses use postal code 000000, profile links use example.com. Any resemblance of a name to a real
person is coincidental. Resume content (skills, projects, experience, education) comes from
data/evaluation/profiles.json so the PDFs stay consistent with the evaluation dataset.

Output is deterministic (reportlab invariant mode) except the encrypted file. The password of the
encrypted fixture is a public test value, not a secret.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.pdfencrypt import StandardEncryption
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[2]
ENCRYPTED_FIXTURE_PASSWORD = "synthetic-test-only"

NAMES = [  # fictional; coincidental resemblance to real persons is possible
    "Priya Ramanathan Nair", "Daniel Ong Wei Jie", "Aisha Binte Rahman", "Kevin Lim Zhi Hao",
    "Sarah Tan Mei Ling", "Rohan Krishnan", "Nur Amirah Ismail", "Jason Chua Kai Xiang",
    "Melissa Goh Shu Ting", "Ethan Lee Jun Hao",
]


def fake_identity(i: int) -> dict:
    """Deterministic, obviously fictional identity for profile number i (1-based)."""
    phone_national = f"9000 {i:04d}"
    return {
        "name": NAMES[i - 1],
        "email": f"synthetic.student{i:02d}@example.com",
        "phone": f"+65 {phone_national}" if i % 2 else phone_national,   # both SG formats
        "address": f"Blk {100 + i} Synthetic Road #0{i % 9 + 1}-{i:03d}, Singapore 000000",
        "national_id": f"S{i:07d}Z",
        "profile_url": f"https://example.com/in/synthetic-student-{i:02d}",
    }


def _styles():
    ss = getSampleStyleSheet()
    return {
        "name": ParagraphStyle("name", parent=ss["Title"], fontSize=20, alignment=TA_LEFT, spaceAfter=4),
        "contact": ParagraphStyle("contact", parent=ss["Normal"], fontSize=10, leading=13),
        "h": ParagraphStyle("h", parent=ss["Heading2"], fontSize=13, spaceBefore=10, spaceAfter=3),
        "item": ParagraphStyle("item", parent=ss["Normal"], fontSize=10.5, leading=14, fontName="Helvetica-Bold"),
        "body": ParagraphStyle("body", parent=ss["Normal"], fontSize=10.5, leading=14),
    }


def _resume_story(content: dict, ident: dict, headings: dict) -> list:
    st = _styles()
    e = escape
    s = [Paragraph(e(ident["name"]), st["name"])]
    for label, key in (("Email", "email"), ("Phone", "phone"), ("Address", "address"),
                       ("NRIC", "national_id"), ("Profile", "profile_url")):
        s.append(Paragraph(f"{label}: {e(ident[key])}", st["contact"]))
    s.append(Paragraph(e(headings["skills"]), st["h"]))
    s.append(Paragraph(e(", ".join(content["skills"])), st["body"]))
    for key in ("projects", "experience"):
        if content[key]:
            s.append(Paragraph(e(headings[key]), st["h"]))
        for entry in content[key]:
            s.append(Paragraph(e(entry["title"]), st["item"]))
            s.append(Paragraph(e(entry["description"]), st["body"]))
            if entry.get("technologies"):
                s.append(Paragraph("Technologies: " + e(", ".join(entry["technologies"])), st["body"]))
            s.append(Spacer(1, 3 * mm))
    s.append(Paragraph(e(headings["education"]), st["h"]))
    for ed in content["education"]:
        s.append(Paragraph(f"{e(ed['qualification'])} - {e(ed.get('details', ''))}", st["body"]))
    return s


STANDARD_HEADINGS = {"skills": "Skills", "projects": "Projects", "experience": "Experience", "education": "Education"}
UNFAMILIAR_HEADINGS = {"skills": "Toolbox", "projects": "Things I Have Built", "experience": "Where I Have Worked",
                       "education": "Studies"}


def build_resume_pdf(content: dict, ident: dict, headings: dict, encrypt=None) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm,
                            bottomMargin=18 * mm, title="Synthetic resume", author="Synthetic fixture generator",
                            invariant=1, encrypt=encrypt)
    doc.build(_resume_story(content, ident, headings))
    return buf.getvalue()


def build_scanned_like_pdf(content: dict, ident: dict) -> bytes:
    """A page that is only a picture of text: no text layer, as a scan would be."""
    lines = [ident["name"], f"Email: {ident['email']}", f"Phone: {ident['phone']}", "", "Skills: " + ", ".join(content["skills"][:6])]
    img = Image.new("RGB", (900, 400), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=24)
    for n, line in enumerate(lines):
        d.text((30, 30 + n * 40), line, fill="black", font=font)
    png = io.BytesIO()
    img.save(png, format="PNG", optimize=True)
    png.seek(0)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    c.drawImage(ImageReader(png), 20 * mm, 150 * mm, width=170 * mm, height=75.5 * mm)
    c.save()
    return buf.getvalue()


def build_many_pages_pdf(pages: int) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    for n in range(1, pages + 1):
        c.drawString(30 * mm, 250 * mm, f"Synthetic filler page {n} of {pages}. Skills: Python, SQL.")
        c.showPage()
    c.save()
    return buf.getvalue()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--profiles", type=Path, default=ROOT / "data" / "evaluation" / "profiles.json")
    ap.add_argument("--out", type=Path, default=ROOT / "tests" / "fixtures" / "pdf")
    args = ap.parse_args()
    profiles = json.loads(args.profiles.read_text(encoding="utf-8"))["profiles"]
    args.out.mkdir(parents=True, exist_ok=True)
    entries = []

    def emit(name: str, data: bytes, **meta):
        (args.out / name).write_bytes(data)
        entries.append({"file": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), **meta})

    for idx, p in enumerate(profiles, start=1):
        ident = fake_identity(idx)
        emit(f"resume_{p['profile_id']}.pdf", build_resume_pdf(p["content"], ident, STANDARD_HEADINGS),
             kind="valid_text_resume", profile_id=p["profile_id"],
             pii_must_not_survive_cleanup=[ident[k] for k in ("name", "email", "phone", "address", "national_id", "profile_url")],
             expected_prepare_outcome="200 draft with skills/projects/experience/education; no PII in draft",
             content_must_survive=[e["title"] for e in p["content"]["projects"] + p["content"]["experience"]])

    p1 = profiles[0]
    ident1 = fake_identity(1)
    emit("edge_unfamiliar_headings.pdf", build_resume_pdf(p1["content"], ident1, UNFAMILIAR_HEADINGS),
         kind="unfamiliar_section_headings", profile_id=p1["profile_id"],
         pii_must_not_survive_cleanup=[ident1[k] for k in ("name", "email", "phone", "address", "national_id", "profile_url")],
         expected_prepare_outcome="200 with warning SECTION_REVIEW_NEEDED and non-empty unassigned_text; no text silently dropped")
    emit("edge_scanned_image_only.pdf", build_scanned_like_pdf(p1["content"], ident1),
         kind="no_text_layer", expected_prepare_outcome="422 TEXT_REQUIRED (no OCR in MVP)")
    emit("edge_encrypted.pdf", build_resume_pdf(p1["content"], ident1, STANDARD_HEADINGS,
                                                encrypt=StandardEncryption(ENCRYPTED_FIXTURE_PASSWORD, canPrint=1)),
         kind="encrypted", expected_prepare_outcome="422 PDF_ENCRYPTED",
         note=f"user password is the public test value {ENCRYPTED_FIXTURE_PASSWORD!r}; output is not byte-deterministic")
    emit("edge_11_pages.pdf", build_many_pages_pdf(11), kind="too_many_pages",
         expected_prepare_outcome="rejected: contract allows at most 10 pages (error code for page limit is not specified in the contract)")
    emit("edge_not_a_pdf.pdf", b"This is plain text with a .pdf name, not a PDF.\n", kind="not_a_pdf",
         expected_prepare_outcome="415 PDF_REQUIRED")

    manifest = {
        "note": "Expected outcomes are the design intent from docs/handoff (DATA_API_CONTRACT.md), not measured behaviour of an implemented pipeline. "
                "All identities are fictional. No PDF exceeds a few tens of KB; an oversize (>5,242,880 byte) file is not committed and must be generated in the test that needs it.",
        "files": entries,
    }
    (args.out.parent / "pdf_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {len(entries)} PDFs to {args.out}")


if __name__ == "__main__":
    main()
