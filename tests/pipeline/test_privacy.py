"""Privacy cleanup: Presidio + app rules. All PII in these tests is synthetic (example.com, 9000 00NN, S000000NZ, 000000)."""
import json
import logging
import sys

import pytest

from conftest import PDF_DIR, ROOT

sys.path.insert(0, str(ROOT / "tests" / "fixtures"))
import generate_pdf_fixtures as gen  # noqa: E402

from app.processing.pipeline import prepare_resume, recheck_privacy  # noqa: E402
from app.processing.privacy import Redactor  # noqa: E402

MANIFEST = json.loads((ROOT / "tests" / "fixtures" / "pdf_manifest.json").read_text(encoding="utf-8"))
VALID = [e for e in MANIFEST["files"] if e["kind"] == "valid_text_resume"]


@pytest.mark.parametrize("entry", VALID, ids=lambda e: e["file"])
def test_no_fictional_pii_survives_prepare_and_project_titles_do(entry):
    result = prepare_resume((PDF_DIR / entry["file"]).read_bytes())
    blob = json.dumps(result.draft, ensure_ascii=False) + "\n" + result.unassigned_text
    for pii in entry["pii_must_not_survive_cleanup"]:
        assert pii not in blob, "a fictional PII string survived cleanup"
    for title in entry["content_must_survive"]:
        assert title in blob, "privacy cleanup destroyed a project/experience title"


def test_each_pii_type_is_replaced_in_plain_text(redactor):
    ident = gen.fake_identity(3)
    text = "\n".join([f"Email: {ident['email']}", f"Mobile: {ident['phone']}", "Phone: +65 9000 0042",
                      f"Address: {ident['address']}", f"NRIC: {ident['national_id']}", f"Web: {ident['profile_url']}",
                      "Contact at synthetic.other@example.com for a reference"])
    out = redactor.redact_text(text)
    for secret in (ident["email"], "9000 0003", "9000 0042", "Synthetic Road", "S0000003Z", "example.com/in/", "synthetic.other@example.com"):
        assert secret not in out
    res = redactor.redact_lines(text.splitlines())
    assert {"EMAIL_ADDRESS", "PHONE_NUMBER", "SG_ADDRESS", "SG_NRIC_FIN", "URL"} <= set(res.counts)


def test_person_name_in_a_sentence_and_in_the_header_is_removed(redactor):
    out = redactor.redact_text("My name is Melissa Goh Shu Ting and I study computing.")
    assert "Melissa" not in out and "Shu Ting" not in out
    header = redactor.redact_lines(["Rohan Krishnan", "Skills", "Python, SQL"], header_rule=True)       # NER may miss it; the header rule must not
    assert "Rohan" not in " ".join(header.lines) and header.counts.get("PERSON", 0) >= 1


TECH_LINES = [
    "Built REST APIs with Python, SQL, Docker, AWS and PostgreSQL",
    "Technologies: React, Node.js, ASP.NET, Vue.js, Next.js, scikit-learn, TensorFlow, Kubernetes, CI/CD, TCP/IP",
    "Skills: Java, C++, C#, Go, R, Git, Linux, Spring Boot, FastAPI, Flask, Tableau, Power BI, Excel",
    "Deployed the service to AWS using Docker and GitHub Actions",
]


@pytest.mark.parametrize("line", TECH_LINES)
def test_technical_keywords_are_not_destroyed(redactor, line):
    assert redactor.redact_text(line) == line


def test_generic_location_words_are_not_blindly_removed(redactor):
    line = "Worked with a Singapore logistics team on delivery routes"
    assert redactor.redact_text(line) == line


def test_technical_skills_survive_the_full_pdf_pipeline(profiles):
    for pid in ("P01", "P06", "P07"):
        result = prepare_resume((PDF_DIR / f"resume_{pid}.pdf").read_bytes())
        assert result.draft["skills"] == profiles[pid]["content"]["skills"]


def test_redaction_is_deterministic_across_runs_and_instances(redactor):
    lines = ["Priya Ramanathan Nair", f"Email: {gen.fake_identity(1)['email']}", "Skills", "Python, SQL, Docker"]
    a = redactor.redact_lines(lines)
    b = redactor.redact_lines(lines)
    c = Redactor().redact_lines(lines)                     # a freshly built analyzer
    assert (a.lines, a.kept, a.counts) == (b.lines, b.kept, b.counts) == (c.lines, c.kept, c.counts)
    p1 = prepare_resume((PDF_DIR / "resume_P05.pdf").read_bytes())
    p2 = prepare_resume((PDF_DIR / "resume_P05.pdf").read_bytes())
    assert p1 == p2


def test_logs_contain_counts_only_never_the_original_text(redactor, caplog):
    caplog.set_level(logging.DEBUG)
    ident = gen.fake_identity(2)
    redactor.redact_lines([ident["name"], f"Email: {ident['email']}", f"Phone: {ident['phone']}", "Skills", "Python"])
    prepare_resume((PDF_DIR / "resume_P02.pdf").read_bytes())
    for secret in (ident["name"], ident["email"], ident["phone"], ident["address"], ident["national_id"], "Retail sales dashboard"):
        assert secret not in caplog.text
    assert "privacy_redacted" in caplog.text               # it does log the (content-free) counts


def test_recheck_privacy_detects_a_change_and_returns_the_cleaned_draft(redactor, profiles):
    clean = profiles["P01"]["content"]
    changed, cleaned = recheck_privacy(clean, redactor)
    assert changed is False and cleaned == clean
    dirty = json.loads(json.dumps(clean))
    dirty["projects"][0]["description"] += " Reach me at synthetic.student01@example.com."
    changed, cleaned = recheck_privacy(dirty, redactor)
    assert changed is True and "example.com" not in json.dumps(cleaned)
