"""Dependency-light regressions for backend contract helpers.

These checks intentionally exercise validation and catalogue deduplication without
requiring a database or the processing model.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "backend"))


def test_blank_resume_entries_are_rejected_before_embedding():
    from app.processing.content import validate_resume_content
    from app.processing.errors import ProcessingError

    content = {
        "skills": ["Python"],
        "projects": [{"title": " ", "description": "", "technologies": []}],
        "experience": [],
        "education": [],
    }

    with pytest.raises(ProcessingError) as exc:
        validate_resume_content(content)

    assert exc.value.code == "INVALID_CONTENT"


def test_review_replay_allows_a_fully_redacted_draft_but_rejects_bad_shape():
    from app.processing.content import validate_review_draft
    from app.processing.errors import ProcessingError

    empty = {"skills": [], "projects": [], "experience": [], "education": []}
    assert validate_review_draft(empty) == empty

    malformed = {"skills": [], "projects": [], "experience": [{"title": 1}], "education": []}
    with pytest.raises(ProcessingError) as exc:
        validate_review_draft(malformed)
    assert exc.value.code == "INVALID_CONTENT"


def test_duplicate_requirement_keeps_required_provenance():
    pytest.importorskip("pgvector")
    from app.catalogue.importer import dedupe_requirements
    from app.catalogue.schema import JobIn, RequirementIn

    first = RequirementIn(
        requirement_text="Python experience",
        importance="PREFERRED",
        source_quote="Python experience is useful",
        evidence_skills=["Python"],
    )
    required = first.model_copy(update={
        "importance": "REQUIRED",
        "source_quote": "Python experience is required",
        "evidence_skills": ["Django"],
    })
    job = JobIn(
        source="SYNTHETIC", source_job_id="1", title="Intern", company_name="Example",
        country_code="SG", location="Singapore", description="Python experience is useful. Python experience is required",
        apply_url="https://example.com/apply", source_url="https://example.com/source",
        job_type="INTERNSHIP", employment_time="FULL_TIME", work_arrangement="HYBRID",
        requirements=[first, required],
    )

    deduped, removed = dedupe_requirements(job)

    assert removed == 1
    assert len(deduped.requirements) == 1
    assert deduped.requirements[0].importance == "REQUIRED"
    assert deduped.requirements[0].source_quote == "Python experience is required"
    assert deduped.requirements[0].evidence_skills == ["Django"]


def test_country_code_rejects_non_iso_alpha_two_values():
    from app.catalogue.schema import JobIn
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        JobIn(
            source="SYNTHETIC", source_job_id="1", title="Intern", company_name="Example",
            country_code="AA", location="Unknown", description="Python experience",
            apply_url="https://example.com/apply", source_url="https://example.com/source",
            job_type="INTERNSHIP", employment_time="FULL_TIME", work_arrangement="HYBRID",
            requirements=[{
                "requirement_text": "Python experience", "importance": "REQUIRED",
                "source_quote": "Python experience",
            }],
        )
