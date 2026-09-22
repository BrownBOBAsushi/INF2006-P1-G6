"""Catalogue import: validation (pure) and the importer against a real PostgreSQL + pgvector."""
import copy
import json

import pytest
from sqlalchemy import func, select, text

from conftest import EVAL_DIR, ROOT

from app.catalogue.importer import dedupe_requirements, import_catalogue, job_content_hash, requirement_texts
from app.catalogue.models import AppState, Job, JobRequirement, RequirementEmbedding
from app.catalogue.schema import MAX_BATCH_JOBS, validate_import


def subset(raw, ids):
    return {"schema_version": 1, "jobs": [copy.deepcopy(j) for j in raw["jobs"] if j["source_job_id"] in ids]}


def issues_of(raw, **kw):
    jobs, issues = validate_import(raw, **kw)
    return jobs, [(i.index, i.field, i.code) for i in issues]


def counts(db):
    out = {t: db.execute(text(f"SELECT count(*) FROM {t}")).scalar()
           for t in ("jobs", "job_requirements", "requirement_embeddings")}
    out["rev"] = db.execute(select(AppState.catalogue_revision)).scalar()
    return out


# ---------------------------------------------------------------- validation (no database)

def test_synthetic_jobs_file_matches_the_evaluation_jobs_and_validates(jobs_raw):
    assert (ROOT / "data" / "synthetic_jobs.json").read_bytes() == (EVAL_DIR / "jobs.json").read_bytes()
    jobs, issues = validate_import(jobs_raw)
    assert issues == [] and len(jobs) == 30


def test_requirement_structure_is_parsed_into_alternatives_and_evidence_skills(jobs_raw):
    jobs, _ = validate_import(jobs_raw)
    j01 = next(j for j in jobs if j.source_job_id == "J01")
    r0 = j01.requirements[0]
    assert r0.importance == "REQUIRED" and len(r0.alternatives) == 2 and r0.evidence_skills == ["Python", "Java", "Go"]
    assert requirement_texts(r0) == r0.alternatives                                  # OR: each alternative is embedded
    assert requirement_texts(j01.requirements[1]) == [j01.requirements[1].requirement_text]   # none: text embedded once
    j02 = next(j for j in jobs if j.source_job_id == "J02")
    assert [r.importance for r in j02.requirements] == ["REQUIRED", "REQUIRED", "REQUIRED", "PREFERRED"]   # AND = separate rows


def test_missing_required_field_and_bad_values_are_reported_with_field_paths(jobs_raw):
    raw = subset(jobs_raw, {"J01", "J02", "J03", "J04", "J05"})
    del raw["jobs"][0]["title"]
    raw["jobs"][1]["job_type"] = "FREELANCE"
    raw["jobs"][2]["apply_url"] = "http://example.com/x"
    raw["jobs"][3]["apply_url"] = "https://user:pw@example.com/x"
    raw["jobs"][4]["requirements"][0]["importance"] = "MUST"
    jobs, found = issues_of(raw)
    assert jobs == []
    fields = {(i, f) for i, f, _ in found}
    assert (0, "title") in fields and (1, "job_type") in fields and (2, "apply_url") in fields
    assert (3, "apply_url") in fields and (4, "requirements.0.importance") in fields
    assert "missing" in {c for _, f, c in found if f == "title"}


@pytest.mark.parametrize("mutate", [
    lambda j: j.__setitem__("requirements", []),
    lambda j: j["requirements"][0].__setitem__("source_quote", "this quote is not in the description"),
    lambda j: j["requirements"][0].__setitem__("alternatives", ["a", "a"]),
    lambda j: j["requirements"][0].__setitem__("alternatives", [f"alt {i}" for i in range(11)]),
    lambda j: j["requirements"][0].__setitem__("evidence_skills", [f"s{i}" for i in range(21)]),
    lambda j: j.__setitem__("country_code", "sg"),
    lambda j: j.__setitem__("posted_at", "2026-01-01T00:00:00"),          # naive timestamp
    lambda j: j.__setitem__("description", "x" * 50_001),
    lambda j: j.__setitem__("unexpected", 1),                              # extra fields rejected
    lambda j: j["requirements"].extend([copy.deepcopy(j["requirements"][0]) for _ in range(30)]),   # > 30 requirements
], ids=["no_requirements", "quote_not_in_description", "duplicate_alternatives", "too_many_alternatives",
        "too_many_evidence_skills", "lowercase_country", "naive_timestamp", "description_too_long", "extra_field",
        "too_many_requirements"])
def test_invalid_records_are_rejected(jobs_raw, mutate):
    raw = subset(jobs_raw, {"J01"})
    mutate(raw["jobs"][0])
    jobs, found = issues_of(raw)
    assert jobs == [] and found and all(i == 0 for i, _, _ in found)


def test_duplicate_identity_disallowed_source_batch_limit_and_bad_json(jobs_raw):
    raw = subset(jobs_raw, {"J01", "J02"})
    raw["jobs"].append(copy.deepcopy(raw["jobs"][0]))
    assert ("source_job_id", "duplicate_in_batch") in [(f, c) for _, f, c in issues_of(raw)[1]]
    other = subset(jobs_raw, {"J01"})
    other["jobs"][0]["source"] = "JSEARCH"
    assert issues_of(other)[1] == [(0, "source", "source_not_allowed")]
    assert issues_of(other, allowed_sources=("SYNTHETIC", "JSEARCH"))[1] == []           # explicit provenance opt-in
    big = {"schema_version": 1, "jobs": [{}] * (MAX_BATCH_JOBS + 1)}
    assert issues_of(big)[1] == [(None, "jobs", "batch_too_large")]
    assert issues_of(b"{not json")[1] == [(None, "file", "invalid_json")]
    assert issues_of({"schema_version": 2, "jobs": []})[1]
    assert issues_of({"schema_version": 1, "jobs": []})[1] == [(None, "jobs", "empty_batch")]


def test_issues_never_contain_job_text(jobs_raw):
    raw = subset(jobs_raw, {"J01", "J02"})
    raw["jobs"][0]["requirements"][0]["source_quote"] = "SECRET-QUOTE not present"
    raw["jobs"][1]["title"] = ""
    _, issues = validate_import(raw)
    blob = json.dumps([i.model_dump() for i in issues])
    assert "SECRET-QUOTE" not in blob and raw["jobs"][0]["description"][:40] not in blob and issues


def test_requirement_deduplication_and_content_hash(jobs_raw):
    jobs, _ = validate_import(subset(jobs_raw, {"J01"}))
    j = jobs[0]
    dup = j.model_copy(update={"requirements": [*j.requirements, j.requirements[1].model_copy(
        update={"requirement_text": "  can WRITE sql queries against a relational database ", "importance": "PREFERRED"})]})
    deduped, removed = dedupe_requirements(dup)
    assert removed == 1 and len(deduped.requirements) == 3
    assert job_content_hash(j) == job_content_hash(jobs[0]) and len(job_content_hash(j)) == 64
    assert job_content_hash(j) != job_content_hash(j.model_copy(update={"title": j.title + "!"}))


# ---------------------------------------------------------------- importer against real PostgreSQL + pgvector

def test_valid_import_stores_jobs_requirements_and_vectors(db, jobs_raw, fake_embedder):
    s = import_catalogue(db, jobs_raw, fake_embedder)
    assert s.ok and (s.created, s.updated, s.unchanged) == (30, 0, 0) and s.requirements_deduplicated == 0
    n_req = sum(len(j["requirements"]) for j in jobs_raw["jobs"])
    n_vec = sum(len(r["alternatives"]) or 1 for j in jobs_raw["jobs"] for r in j["requirements"])
    assert counts(db) == {"jobs": 30, "job_requirements": n_req, "requirement_embeddings": n_vec, "rev": 1}
    unique_texts = {t for j in validate_import(jobs_raw)[0] for r in j.requirements for t in requirement_texts(r)}
    assert s.catalogue_revision == 1 and s.embeddings_computed == len(unique_texts)
    assert db.execute(text("SELECT DISTINCT vector_dims(embedding) FROM requirement_embeddings")).scalars().all() == [384]
    assert db.execute(text("SELECT DISTINCT embedding_version FROM requirement_embeddings")).scalars().all() == [fake_embedder.version]
    row = db.execute(select(JobRequirement).join(Job).where(Job.source_job_id == "J01", JobRequirement.ordinal == 0)).scalar_one()
    assert row.importance == "REQUIRED" and row.alternatives == jobs_raw["jobs"][0]["requirements"][0]["alternatives"]
    assert row.evidence_skills == ["Python", "Java", "Go"]
    job = db.execute(select(Job).where(Job.source_job_id == "J01")).scalar_one()
    assert job.last_verified_at is None and job.is_active and len(job.content_hash) == 64      # never auto-filled


def test_repeating_the_same_import_changes_nothing(db, jobs_raw, fake_embedder):
    import_catalogue(db, jobs_raw, fake_embedder)
    ids = dict(db.execute(select(Job.source_job_id, Job.job_id)).all())
    before = counts(db)
    s = import_catalogue(db, jobs_raw, fake_embedder)
    assert s.ok and (s.created, s.updated, s.unchanged, s.embeddings_computed) == (0, 0, 30, 0)
    assert counts(db) == before and dict(db.execute(select(Job.source_job_id, Job.job_id)).all()) == ids   # no dupes, same rows
    assert s.catalogue_revision == 1                                                                        # revision not bumped


def test_display_only_change_updates_the_job_but_regenerates_no_vectors(db, jobs_raw, fake_embedder):
    import_catalogue(db, jobs_raw, fake_embedder)
    old_vec = list(db.execute(select(RequirementEmbedding.embedding).order_by(RequirementEmbedding.text).limit(1)).scalar())
    raw = copy.deepcopy(jobs_raw)
    raw["jobs"][0]["title"] = "Backend Software Engineer Intern (Updated)"
    raw["jobs"][0]["posted_at"] = "2026-09-01T00:00:00+08:00"
    s = import_catalogue(db, raw, fake_embedder)
    assert (s.created, s.updated, s.unchanged) == (0, 1, 29)
    assert s.embeddings_computed == 0 and s.embeddings_reused > 0 and s.catalogue_revision == 2
    db.expire_all()
    j = db.execute(select(Job).where(Job.source_job_id == "J01")).scalar_one()
    assert j.title.endswith("(Updated)") and j.posted_at is not None
    n_vec = sum(len(r["alternatives"]) or 1 for jj in jobs_raw["jobs"] for r in jj["requirements"])
    assert counts(db)["jobs"] == 30 and counts(db)["requirement_embeddings"] == n_vec
    new_vec = list(db.execute(select(RequirementEmbedding.embedding).order_by(RequirementEmbedding.text).limit(1)).scalar())
    assert new_vec == old_vec


def test_changed_requirement_embeds_only_the_new_text(db, jobs_raw, fake_embedder):
    import_catalogue(db, jobs_raw, fake_embedder)
    raw = copy.deepcopy(jobs_raw)
    raw["jobs"][0]["requirements"][1]["requirement_text"] = "Can write and optimise SQL queries against a relational database"
    s = import_catalogue(db, raw, fake_embedder)
    assert (s.updated, s.embeddings_computed) == (1, 1)
    db.expire_all()
    texts = db.execute(select(RequirementEmbedding.text).join(JobRequirement).join(Job)
                       .where(Job.source_job_id == "J01")).scalars().all()
    assert "Can write and optimise SQL queries against a relational database" in texts
    assert "Can write SQL queries against a relational database" not in texts


def test_invalid_batch_writes_nothing_and_leaves_the_previous_catalogue_intact(db, jobs_raw, fake_embedder):
    import_catalogue(db, subset(jobs_raw, {"J01", "J02"}), fake_embedder)
    before = counts(db)
    bad = subset(jobs_raw, {"J01", "J03"})
    bad["jobs"][0]["title"] = "Changed but batch is invalid"
    del bad["jobs"][1]["company_name"]
    s = import_catalogue(db, bad, fake_embedder)
    assert not s.ok and s.issues and counts(db) == before
    assert db.execute(select(Job.title).where(Job.source_job_id == "J01")).scalar() != "Changed but batch is invalid"


def test_dry_run_reports_the_plan_and_writes_nothing(db, jobs_raw, fake_embedder):
    import_catalogue(db, subset(jobs_raw, {"J01"}), fake_embedder)
    before = counts(db)
    s = import_catalogue(db, subset(jobs_raw, {"J01", "J02", "J03"}), fake_embedder, dry_run=True)
    assert s.ok and s.dry_run and (s.created, s.unchanged) == (2, 1) and s.embeddings_computed > 0
    assert counts(db) == before
    assert import_catalogue(None, subset(jobs_raw, {"J01"}), None, dry_run=True).created == 1     # counts-only, no DB or model
    with pytest.raises(ValueError):
        import_catalogue(None, jobs_raw, None)


def test_embedding_failure_and_a_failed_write_leave_the_catalogue_intact(db, jobs_raw, fake_embedder):
    import numpy as np
    import_catalogue(db, subset(jobs_raw, {"J01"}), fake_embedder)
    before = counts(db)

    class Exploding(type(fake_embedder)):
        def embed(self, texts):
            raise RuntimeError("model crashed")

    with pytest.raises(RuntimeError):
        import_catalogue(db, subset(jobs_raw, {"J01", "J02"}), Exploding())
    assert counts(db) == before

    class WrongDim(type(fake_embedder)):
        def embed(self, texts):
            return np.ones((len(texts), 3), dtype=np.float32)

    with pytest.raises(Exception):
        import_catalogue(db, subset(jobs_raw, {"J01", "J02"}), WrongDim())     # fails inside the transaction: rolled back
    assert counts(db) == before


def test_absence_from_a_file_never_deactivates_and_is_active_false_closes(db, jobs_raw, fake_embedder):
    import_catalogue(db, subset(jobs_raw, {"J01", "J02"}), fake_embedder)
    import_catalogue(db, subset(jobs_raw, {"J03", "J04"}), fake_embedder)
    assert db.execute(select(func.count()).select_from(Job).where(Job.is_active)).scalar() == 4
    closing = subset(jobs_raw, {"J01"})
    closing["jobs"][0]["is_active"] = False
    import_catalogue(db, closing, fake_embedder)
    db.expire_all()
    assert db.execute(select(Job.is_active).where(Job.source_job_id == "J01")).scalar() is False
    assert db.execute(select(func.count()).select_from(Job).where(Job.is_active)).scalar() == 3


def test_real_model_vectors_are_stored_with_the_expected_dimension_and_version(db, jobs_raw, model):
    import numpy as np
    s = import_catalogue(db, subset(jobs_raw, {"J01", "J13"}), model)
    assert s.ok and s.embeddings_computed > 0
    assert db.execute(text("SELECT DISTINCT vector_dims(embedding) FROM requirement_embeddings")).scalars().all() == [384]
    assert db.execute(text("SELECT DISTINCT embedding_version FROM requirement_embeddings")).scalars().all() == [model.version]
    row = db.execute(select(RequirementEmbedding)).scalars().first()
    assert np.allclose(np.asarray(row.embedding), model.embed([row.text])[0], atol=1e-5)
