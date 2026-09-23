"""Deterministic skill gaps and evidence-based explanations."""
import json
import uuid

import pytest

from test_scoring import E, chunks, job, req

from app.matching.explain import DISCLAIMER, explain_job
from app.matching.skill_gap import analyse_skill_gap, normalise_skill


def rq(rid, text, skills, importance="REQUIRED"):
    return req(rid, text, E[0], skills=skills, importance=importance)


def test_prd_example_python_sql_git_rest_matched_aws_docker_missing():
    reqs = [rq("1", "Python", ["Python"]), rq("2", "SQL", ["SQL"]), rq("3", "Git", ["Git"]), rq("4", "REST API", ["REST API"]),
            rq("5", "AWS", ["AWS"]), rq("6", "Docker", ["Docker"])]
    report = analyse_skill_gap(reqs, ["Python", "SQL", "Git", "REST API"])
    assert [e.requirement_text for e in report.matched] == ["Python", "SQL", "Git", "REST API"]
    assert [e.requirement_text for e in report.missing] == ["AWS", "Docker"]
    assert report.unassessed == ()
    assert report.missing_skill_groups() == [("AWS",), ("Docker",)]


def test_or_group_is_matched_by_any_alternative_and_reported_once_when_missing():
    r = rq("1", "Backend language", ["Python", "Java", "Go"])
    hit = analyse_skill_gap([r], ["java"])
    assert hit.matched[0].explicit_skill_evidence == ("java",) and hit.missing == ()     # student's own spelling is kept
    miss = analyse_skill_gap([r], ["Rust"])
    assert len(miss.missing) == 1 and miss.missing[0].named_skills_not_evidenced == ("Python", "Java", "Go")   # one group, not three gaps


def test_aliases_case_and_whitespace_but_never_substring_matching():
    assert normalise_skill("  Postgres ") == normalise_skill("PostgreSQL") == "postgresql"
    assert analyse_skill_gap([rq("1", "DB", ["PostgreSQL"])], ["postgres"]).matched
    assert analyse_skill_gap([rq("1", "REST", ["REST"])], ["RESTful  API"]).matched
    assert not analyse_skill_gap([rq("1", "Go", ["Go"])], ["Google Cloud", "Django"]).matched      # "go" is not inside "Google"
    assert not analyse_skill_gap([rq("1", "Java", ["Java"])], ["JavaScript"]).matched               # nor "java" inside "JavaScript"


def test_requirements_without_named_skills_are_unassessed_never_missing():
    report = analyse_skill_gap([rq("1", "Communicates clearly", [])], ["Python"])
    assert report.unassessed and not report.missing and not report.matched


def test_preferred_requirements_are_reported_with_their_importance():
    report = analyse_skill_gap([rq("1", "Kubernetes", ["Kubernetes"], importance="PREFERRED")], [])
    assert report.missing[0].importance == "PREFERRED"


def test_uuid_requirement_ids_survive_skill_gap_analysis():
    requirement_id = uuid.uuid4()
    report = analyse_skill_gap([rq(requirement_id, "Python", ["Python"])], ["Python"])
    assert report.matched[0].requirement_id == requirement_id


def _meta(n):
    return [{"text": f"Project: Demo {i}\nBuilt a Flask API and wrote SQL queries for booking. Technologies: Python, SQL.",
             "section": "PROJECT", "entry_index": i} for i in range(n)]


def test_explanation_is_traceable_to_requirements_passages_and_skills():
    j = job("J", rq("r1", "Build web APIs", ["Python"]), rq("r2", "Cloud deployment", ["AWS", "Azure"]))
    ex = explain_job(j, chunks(E[0], E[3]), _meta(2), ["Python", "Git"])
    text = "\n".join(ex.statements)
    assert "Build web APIs" in text and "Cloud deployment" in text                    # each statement names its requirement
    assert "Built a Flask API and wrote SQL queries" in text                          # quotes the passage, not the heading
    assert "your confirmed skills include Python (self-reported)" in text
    assert "none of AWS, Azure appears in your confirmed skills" in text
    assert "closest passage, not proof" in text
    assert [r["requirement_id"] for r in ex.requirements] == ["r1", "r2"]
    assert ex.requirements[0]["closest_passage"]["section"] == "PROJECT"
    assert ex.requirements[0]["explicit_skill_evidence"] == ["Python"]
    assert ex.requirements[1]["named_skills_not_evidenced"] == ["AWS", "Azure"]


def test_public_explanation_has_no_scores_but_the_internal_trace_does():
    j = job("J", rq("r1", "Build web APIs", ["Python"]))
    ex = explain_job(j, chunks(E[0]), _meta(1), ["Python"])
    blob = json.dumps(ex.to_public())
    assert "similarity" not in blob and "score" not in blob.lower().replace("scores", "")
    assert ex.trace[0]["similarity"] == pytest.approx(1.0, abs=1e-3) and ex.trace[0]["requirement_id"] == "r1"


@pytest.mark.parametrize("banned", ["qualified", "guarantee", "will succeed", "likely to", "hired", "best candidate", "suitable"])
def test_explanations_make_no_hiring_or_suitability_claims(banned):
    j = job("J", rq("r1", "Build web APIs", ["Python"]), rq("r2", "Cloud", ["AWS"]))
    ex = explain_job(j, chunks(E[0], E[3]), _meta(2), ["Python"])
    assert banned not in " ".join(ex.statements).replace(DISCLAIMER, "").lower()
    assert "not a hiring decision" in ex.to_public()["disclaimer"]
