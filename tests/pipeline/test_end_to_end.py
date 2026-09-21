"""The whole local pipeline with real components: synthetic PDF -> extraction -> privacy -> structured draft -> (student
confirms) -> privacy re-check -> 240-token chunking -> MiniLM embeddings -> catalogue import (PostgreSQL + pgvector) ->
requirement-level matching -> top 5 -> skill gaps -> evidence-based explanations."""
import json

import pytest
from sqlalchemy import text

from conftest import PDF_DIR

from app.catalogue.importer import import_catalogue
from app.catalogue.loader import load_job_vectors
from app.matching.recommend import recommend
from app.processing.errors import ProcessingError
from app.processing.pipeline import embed_resume, prepare_resume, recheck_privacy


@pytest.fixture()
def catalogue(db, jobs_raw, model):
    import_catalogue(db, jobs_raw, model)
    sid = {str(j): s for j, s in db.execute(text("SELECT job_id, source_job_id FROM jobs")).all()}
    return load_job_vectors(db, model.version), sid


def run(pdf_name, model, catalogue_jobs):
    prepared = prepare_resume((PDF_DIR / pdf_name).read_bytes())
    assert prepared.warnings == []
    changed, cleaned = recheck_privacy(prepared.draft)
    assert changed is False                                       # a confirmed, already-clean draft passes the re-check
    emb = embed_resume(cleaned, model)
    meta = [{"text": c["text"], "section": c["section"], "entry_index": c["entry_index"]} for c in emb.chunks]
    return prepared, emb, recommend(emb.vectors, meta, catalogue_jobs, cleaned["skills"], top_k=5)


def test_pdf_to_top_five_with_skill_gaps_and_explanations(model, catalogue):
    jobs, sid = catalogue
    prepared, emb, page = run("resume_P01.pdf", model, jobs)
    assert emb.version == model.version and emb.vectors.shape[1] == 384
    assert len(page.items) == 5 and page.total == 30 and page.diagnostics.omitted_incomplete == 0
    scores = [i.match.score for i in page.items]
    assert scores == sorted(scores, reverse=True) and [i.rank for i in page.items] == [1, 2, 3, 4, 5]
    top_ids = [sid[i.job_id] for i in page.items]
    assert len(set(top_ids) & {"J01", "J02", "J07"}) >= 2         # sanity: the backend/data-loader roles rank at the top for this profile

    j01 = next(i for i in page.items if sid[i.job_id] == "J01")
    gap = j01.explanation.skill_gap
    matched = {e.requirement_text: e.explicit_skill_evidence for e in gap.matched}
    assert matched == {"Has built a web API or backend service": ("Python", "Java"),      # OR group: both listed skills are confirmed
                       "Can write SQL queries against a relational database": ("SQL", "PostgreSQL")}
    missing = {e.requirement_text: e.named_skills_not_evidenced for e in gap.missing}
    assert missing == {"Writes automated tests for their own code": ("pytest", "unit testing")}   # confirmed skills do not list pytest

    public = json.dumps(j01.explanation.to_public())
    assert "similarity" not in public and "hired" not in public.lower() and "not a hiring decision" in public
    passages = [r["closest_passage"]["text"] for r in j01.explanation.requirements]
    assert all(p in {c["text"] for c in emb.chunks} for p in passages)   # every quoted passage really is a chunk of the resume


def test_a_skills_only_profile_can_be_embedded_but_cannot_be_matched(model, catalogue):
    jobs, _ = catalogue
    content = {"skills": ["Python", "SQL"], "projects": [], "experience": [], "education": []}
    emb = embed_resume(content, model)
    assert emb.chunks == [] and emb.vectors.shape == (0, 384)
    with pytest.raises(ProcessingError) as exc:
        recommend(emb.vectors, [], jobs, content["skills"])
    assert exc.value.code == "INSUFFICIENT_RESUME_INFORMATION"


def test_a_non_technical_profile_still_gets_five_results_and_relevant_ones_lead(model, catalogue):
    jobs, sid = catalogue
    _, _, page = run("resume_P09.pdf", model, jobs)
    assert len(page.items) == 5
    assert len({sid[i.job_id] for i in page.items[:3]} & {"J15", "J17", "J25", "J26"}) >= 2      # business roles lead for a business profile


def test_the_same_pdf_gives_the_same_recommendations_every_time(model, catalogue):
    jobs, sid = catalogue
    a = [(i.job_id, round(i.match.score, 6)) for i in run("resume_P05.pdf", model, jobs)[2].items]
    b = [(i.job_id, round(i.match.score, 6)) for i in run("resume_P05.pdf", model, jobs)[2].items]
    assert a == b
