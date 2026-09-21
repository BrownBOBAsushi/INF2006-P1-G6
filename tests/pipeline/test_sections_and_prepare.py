"""Section parsing and the prepare stage (PDF -> extraction -> privacy -> structured draft)."""
import copy
import io
import json

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from conftest import PDF_DIR

from app.processing.content import content_hash, validate_resume_content
from app.processing.errors import ProcessingError
from app.processing.pipeline import prepare_resume
from app.processing.sections import parse_sections_from_text


@pytest.mark.parametrize("pid", [f"P{i:02d}" for i in range(1, 11)])
def test_prepare_reproduces_the_source_profile_exactly(pid, profiles):
    """PDF built from profiles.json -> prepare -> the same ResumeContent (PII removed, nothing lost or invented)."""
    result = prepare_resume((PDF_DIR / f"resume_{pid}.pdf").read_bytes())
    assert result.draft == profiles[pid]["content"]
    assert result.unassigned_text == "" and result.warnings == []
    validate_resume_content(result.draft)


def test_unfamiliar_headings_keep_every_paragraph_in_unassigned_text_with_a_warning(profiles):
    result = prepare_resume((PDF_DIR / "edge_unfamiliar_headings.pdf").read_bytes())
    assert result.draft["projects"] == [] and result.draft["experience"] == []
    assert [w["code"] for w in result.warnings] == ["SECTION_REVIEW_NEEDED"]
    src = profiles["P01"]["content"]
    flat = " ".join(result.unassigned_text.split())                       # PDF line wrapping is not content
    for entry in src["projects"] + src["experience"]:
        assert entry["title"] in flat                                     # nothing silently dropped
        assert entry["description"] in flat
    assert "synthetic.student01@example.com" not in result.unassigned_text   # and PII is still removed


def test_plain_text_bullets_labels_and_unsupported_sections():
    text = """Skills
Languages: Python, SQL; Docker
- Git

Projects
Order API
- Built REST endpoints in Python.
- Added pytest tests.
Technologies: Python, pytest

Weather app
Wrote a small web app that shows the forecast. Deployed it on a VM.

Certifications
AWS Cloud Practitioner

Education
BSc Computing - Year 3
"""
    r = parse_sections_from_text(text)
    assert r.draft["skills"] == ["Python", "SQL", "Docker", "Git"]
    assert r.draft["projects"][0] == {"title": "Order API", "description": "Built REST endpoints in Python.\nAdded pytest tests.",
                                      "technologies": ["Python", "pytest"]}
    assert r.draft["projects"][1]["title"] == "Weather app"
    assert r.draft["education"] == [{"qualification": "BSc Computing", "details": "Year 3"}]
    assert "AWS Cloud Practitioner" in r.unassigned_text and r.warnings[0]["code"] == "SECTION_REVIEW_NEEDED"


def test_entries_over_contract_limits_go_to_unassigned_not_dropped():
    many = "\n\n".join(f"Project {i}\nDid thing number {i}." for i in range(22))
    r = parse_sections_from_text("Projects\n" + many)
    assert len(r.draft["projects"]) == 20
    assert "Project 21" in r.unassigned_text and "Did thing number 21." in r.unassigned_text


def test_empty_text_gives_an_empty_draft_and_no_crash():
    r = parse_sections_from_text("")
    assert r.draft == {"skills": [], "projects": [], "experience": [], "education": []} and r.unassigned_text == ""


def _pdf(lines):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    y = 780
    for ln in lines:
        c.drawString(60, y, ln)
        y -= 16
    c.save()
    return buf.getvalue()


def test_a_pdf_that_is_only_personal_details_is_rejected_as_no_text(redactor):
    pdf = _pdf(["Priya Ramanathan Nair", "Email: synthetic.student01@example.com", "Phone: +65 9000 0001",
                "Address: Blk 101 Synthetic Road #02-001, Singapore 000000", "NRIC: S0000001Z"])
    with pytest.raises(ProcessingError) as exc:
        prepare_resume(pdf, redactor)
    assert exc.value.code == "TEXT_REQUIRED"


@pytest.mark.parametrize("name,code", [("edge_scanned_image_only.pdf", "TEXT_REQUIRED"), ("edge_encrypted.pdf", "PDF_ENCRYPTED"),
                                       ("edge_11_pages.pdf", "PDF_UNREADABLE"), ("edge_not_a_pdf.pdf", "PDF_REQUIRED")])
def test_malformed_inputs_fail_deterministically_at_the_pipeline_level(name, code):
    with pytest.raises(ProcessingError) as exc:
        prepare_resume((PDF_DIR / name).read_bytes())
    assert exc.value.code == code


def test_content_validation_enforces_the_contract():
    ok = {"skills": ["Python"], "projects": [{"title": "t", "description": "d", "technologies": []}], "experience": [], "education": []}
    assert validate_resume_content(ok) is ok
    bad = [
        {**ok, "extra": 1},                                                        # extra field
        {**ok, "skills": ["Python", "python"]},                                    # duplicate skill
        {**ok, "skills": ["x" * 101]},
        {**ok, "projects": [{"title": "t", "description": "d" * 5001, "technologies": []}]},
        {**ok, "projects": [{"title": "t", "description": "d", "technologies": [], "x": 1}]},
        {"skills": [], "projects": [], "experience": [], "education": []},          # entirely blank
    ]
    for content in bad:
        with pytest.raises(ProcessingError) as exc:
            validate_resume_content(content)
        assert exc.value.code == "INVALID_CONTENT"


def test_content_hash_is_stable_and_sensitive():
    a = {"skills": ["Python"], "projects": [], "experience": [], "education": []}
    b = copy.deepcopy(a)
    assert content_hash(a) == content_hash(b) == content_hash(json.loads(json.dumps(a)))
    b["skills"].append("SQL")
    assert content_hash(a) != content_hash(b)
