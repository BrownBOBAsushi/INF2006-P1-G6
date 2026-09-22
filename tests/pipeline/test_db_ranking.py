"""pgvector ranking in real PostgreSQL: parity with the reference matcher and with analytics/evaluate.py, contract
semantics with hand-made vectors, and the migration itself. Requires the `pgserver` package (real PG 16 + pgvector)."""
import os
import uuid

import numpy as np
import pytest
from sqlalchemy import create_engine, text

from conftest import BACKEND, reenable_loggers

from app.catalogue.importer import import_catalogue
from app.catalogue.loader import load_job_vectors
from app.catalogue.models import Job, JobRequirement, RequirementEmbedding
from app.db.models import ResumeChunk, ResumeProfile, User
from app.matching.scoring import rank_jobs
from app.matching.sql import RANK_SQL, closest_passages_sql, rank_jobs_sql
from app.processing.pipeline import embed_resume

DIM = 384
VER = "test-embedding@1"


def E(i):
    v = np.zeros(DIM, dtype=np.float32)
    v[i] = 1.0
    return v


def mix(i, j, w):
    return (w * E(i) + np.sqrt(1 - w * w) * E(j)).astype(np.float32)


def put_user(db, chunk_vecs, *, revision=1, version=VER, sub=None):
    uid = uuid.uuid4()
    db.add(User(user_id=uid, google_sub=sub or f"sub-{uid}", resume_revision=revision))
    db.flush()
    db.add(ResumeProfile(user_id=uid, revision=revision, content={"skills": [], "projects": [], "experience": [], "education": []},
                         content_hash="0" * 64, embedding_version=version))
    db.flush()
    for i, v in enumerate(chunk_vecs):
        db.add(ResumeChunk(chunk_id=uuid.uuid4(), user_id=uid, profile_revision=revision, section="PROJECT", entry_index=i,
                           chunk_index=0, text=f"chunk {i}", embedding=v, embedding_version=version))
    db.flush()
    return uid


def put_job(db, n, reqs, *, active=True, job_type="INTERNSHIP", version=VER):
    """reqs: list of (text, importance, [alternative vectors], alternatives_json)."""
    jid = uuid.UUID(int=n)
    db.add(Job(job_id=jid, source="SYNTHETIC", source_job_id=f"S{n}", title=f"Job {n}", company_name="Co", country_code="SG",
               location="Singapore", description="d", apply_url="https://example.com/a", source_url="https://example.com/b",
               job_type=job_type, employment_time="FULL_TIME", work_arrangement="HYBRID", eligibility_notes=[],
               is_active=active, content_hash="0" * 64))
    db.flush()
    for ordinal, (txt, importance, vecs, alternatives) in enumerate(reqs):
        rid = uuid.uuid4()
        db.add(JobRequirement(requirement_id=rid, job_id=jid, ordinal=ordinal, requirement_text=txt, importance=importance,
                              alternatives=alternatives, source_quote="d", evidence_skills=[]))
        db.flush()
        for k, v in enumerate(vecs):
            db.add(RequirementEmbedding(embedding_id=uuid.uuid4(), requirement_id=rid, alternative_index=k,
                                        text=(alternatives[k] if alternatives else txt), embedding=v, embedding_version=version))
    db.flush()
    return jid


def rank(db, uid, **kw):
    kw.setdefault("limit", 50)
    page = rank_jobs_sql(db, user_id=uid, profile_revision=kw.pop("profile_revision", 1), embedding_version=kw.pop("embedding_version", VER), **kw)
    return [(uuid.UUID(r.job_id).int, r.score) for r in page.rows], page


# ------------------------------------------------------------------ parity on the real catalogue with the real model

def test_sql_ranking_equals_the_in_memory_reference_and_the_evaluation_harness_for_all_profiles(db, jobs_raw, profiles, model):
    import evaluate as ev
    import_catalogue(db, jobs_raw, model)
    sid = {str(j): s for j, s in db.execute(text("SELECT job_id, source_job_id FROM jobs")).all()}
    catalogue = load_job_vectors(db, model.version)
    assert len(catalogue) == 30

    fx = ev.load_fixtures(ev.Path(__file__).resolve().parents[2] / "data" / "evaluation",
                          ev.Path(__file__).resolve().parents[2] / "data" / "evaluation" / "labels.csv")
    harness = ev.score_model(ev.Embedder(model.name, model.revision), fx, sorted(profiles), "")["scores"]["requirement_level"]

    for pid, p in profiles.items():
        emb = embed_resume(p["content"], model)
        uid = put_user(db, list(emb.vectors), version=model.version, sub=f"sub-{pid}")
        db.commit()
        page, _, _ = rank_jobs(emb.vectors, catalogue, top_k=30)
        sql_rows, sql_page = rank(db, uid, embedding_version=model.version, limit=30)
        # SQL == in-memory reference: same order, same scores (pgvector stores float32)
        assert [sid[str(uuid.UUID(int=j))] for j, _ in sql_rows] == [sid[m.job_id] for m in page], pid
        assert np.allclose([s for _, s in sql_rows], [m.score for m in page], atol=1e-5), pid
        assert sql_page.total == 30 and sql_page.omitted_incomplete_or_unscorable == 0
        # ... and both equal the evaluation harness's requirement-level scores (so evaluation measured the production formula)
        h = harness[pid]
        assert np.allclose([h[sid[m.job_id]] for m in page], [m.score for m in page], atol=1e-5), pid
        assert [sid[m.job_id] for m in page[:5]] == sorted(h, key=lambda j: (-round(h[j], 9), j))[:5], pid


def test_top_five_page_has_five_items_and_matches_the_head_of_the_full_ranking(db, jobs_raw, profiles, model):
    import_catalogue(db, jobs_raw, model)
    emb = embed_resume(profiles["P01"]["content"], model)
    uid = put_user(db, list(emb.vectors), version=model.version)
    top5, page = rank(db, uid, embedding_version=model.version, limit=5)
    full, _ = rank(db, uid, embedding_version=model.version, limit=30)
    assert len(top5) == 5 and top5 == full[:5] and page.total == 30
    assert [s for _, s in top5] == sorted((s for _, s in top5), reverse=True)
    again, _ = rank(db, uid, embedding_version=model.version, limit=5)
    assert again == top5                                                       # deterministic


# ------------------------------------------------------------------ contract semantics with hand-made vectors

def scenario_user(db):
    return put_user(db, [mix(0, 7, 0.95), mix(1, 7, 0.6), mix(2, 7, 0.5)])


def test_aggregation_and_or_and_preferred_semantics_in_sql(db):
    uid = scenario_user(db)
    put_job(db, 1, [("Python or Java", "REQUIRED", [E(5), E(1)], ["Python", "Java"])])                  # OR -> max(0, .6) = .6
    put_job(db, 2, [("r1", "REQUIRED", [E(1)], []), ("r2", "REQUIRED", [E(2)], [])])                     # AND -> (.6+.5)/2 = .55
    put_job(db, 3, [("strong", "REQUIRED", [E(0)], []), ("unmet", "REQUIRED", [E(5)], [])])             # (.95+0)/2 = .475
    put_job(db, 4, [("a", "REQUIRED", [E(5)], []), ("b", "REQUIRED", [E(1)], [])])                       # AND -> .3
    put_job(db, 5, [("core", "REQUIRED", [E(0)], []), ("nice", "PREFERRED", [E(6)], [])])               # preferred ignored -> .95
    rows, page = rank(db, uid)
    got = {j: s for j, s in rows}
    assert [j for j, _ in rows] == [5, 1, 2, 3, 4]
    assert got[1] == pytest.approx(0.6, abs=1e-5) and got[2] == pytest.approx(0.55, abs=1e-5)
    assert got[3] == pytest.approx(0.475, abs=1e-5) and got[4] == pytest.approx(0.3, abs=1e-5) and got[5] == pytest.approx(0.95, abs=1e-5)
    assert [j for j, _ in rank(db, uid, limit=1)[0]] == [5]                                              # LIMIT applies after aggregation
    order = [j for j, _ in rows]
    assert order.index(2) < order.index(3)          # job 3 has the single strongest vector (.95) but ranks below job 2 (aggregate)


def test_equal_scores_tie_break_by_job_id_and_pagination_continues_the_ranking(db):
    uid = put_user(db, [E(0)])
    for n in (12, 10, 11):
        put_job(db, n, [("same", "REQUIRED", [E(0)], [])])
    for n in range(20, 25):
        put_job(db, n, [("lower", "REQUIRED", [mix(0, 7, 0.9 - (n - 20) * 0.1)], [])])
    full, page = rank(db, uid, limit=50)
    assert [j for j, _ in full] == [10, 11, 12, 20, 21, 22, 23, 24] and page.total == 8
    p1, _ = rank(db, uid, limit=5, offset=0)
    p2, p2page = rank(db, uid, limit=5, offset=5)
    assert [j for j, _ in p1 + p2] == [j for j, _ in full] and p2page.total == 8
    past, past_page = rank(db, uid, limit=5, offset=100)
    assert past == [] and past_page.total == 8 and past_page.omitted_incomplete_or_unscorable == 0   # totals still correct


def test_fewer_than_five_jobs_returns_what_exists(db):
    uid = put_user(db, [E(0)])
    put_job(db, 1, [("a", "REQUIRED", [E(0)], [])])
    put_job(db, 2, [("a", "REQUIRED", [mix(0, 7, 0.5)], [])])
    rows, page = rank(db, uid, limit=5)
    assert [j for j, _ in rows] == [1, 2] and page.total == 2


def test_incomplete_wrong_version_inactive_preferred_only_and_filtered_jobs_are_excluded(db):
    uid = put_user(db, [E(0)])
    put_job(db, 1, [("ok", "REQUIRED", [E(0)], [])])
    put_job(db, 2, [("two alts but one vector", "REQUIRED", [E(0)], ["a", "b"])])          # incomplete: 1 of 2 alternatives
    put_job(db, 3, [("old model", "REQUIRED", [E(0)], [])], version="other-model@0")       # embedding version mismatch
    put_job(db, 4, [("closed", "REQUIRED", [E(0)], [])], active=False)
    put_job(db, 5, [("only nice", "PREFERRED", [E(0)], [])])
    put_job(db, 6, [("other type", "REQUIRED", [E(0)], [])], job_type="OTHER")
    rows, page = rank(db, uid)
    assert [j for j, _ in rows] == [1, 6] and page.total == 2
    assert page.omitted_incomplete_or_unscorable == 2                                     # jobs 2 and 3 (5 has no required; 4 inactive)
    assert [j for j, _ in rank(db, uid, job_types=["INTERNSHIP"])[0]] == [1]
    assert [j for j, _ in rank(db, uid, job_types=["OTHER", "INTERNSHIP"], work_arrangements=["REMOTE"])[0]] == []


def test_only_the_authenticated_users_current_chunks_are_used(db):
    mine = put_user(db, [E(0)], sub="me")
    theirs = put_user(db, [E(1)], sub="them")
    put_job(db, 1, [("topic 0", "REQUIRED", [E(0)], [])])
    put_job(db, 2, [("topic 1", "REQUIRED", [E(1)], [])])
    assert [j for j, _ in rank(db, mine)[0]][0] == 1
    assert [j for j, _ in rank(db, theirs)[0]][0] == 2
    assert rank(db, mine, profile_revision=2)[0] == []                                    # stale revision: no chunks match
    assert rank(db, uuid.uuid4())[0] == []                                                # unknown user: nothing, no error
    assert rank(db, mine, embedding_version="other@1")[0] == []


def test_closest_passages_query_returns_the_best_chunk_per_requirement(db):
    uid = put_user(db, [mix(0, 7, 0.3), mix(0, 6, 0.9), mix(1, 7, 0.8)])
    put_job(db, 1, [("r0", "REQUIRED", [E(0)], []), ("r1", "PREFERRED", [E(1)], [])])
    rows = {r.requirement_id: r for r in closest_passages_sql(db, user_id=uid, profile_revision=1, embedding_version=VER, job_ids=[str(uuid.UUID(int=1))])}
    by_text = {db.execute(text("SELECT requirement_text FROM job_requirements WHERE requirement_id = :i"), {"i": k}).scalar(): v for k, v in rows.items()}
    assert by_text["r0"].entry_index == 1 and by_text["r0"].sim == pytest.approx(0.9, abs=1e-5)
    assert by_text["r1"].entry_index == 2 and by_text["r1"].text == "chunk 2"


def test_limit_only_appears_after_the_aggregation_in_the_sql():
    sql = str(RANK_SQL)
    assert sql.count("LIMIT") == 1 and sql.index("LIMIT") > sql.index("HAVING BOOL_AND") > sql.index("GROUP BY req.job_id")
    assert "<=>" in sql and "1 - (re.embedding <=> c.embedding)" in sql                  # pgvector cosine distance -> similarity


# ------------------------------------------------------------------ schema, indexes and migration

def test_vector_columns_indexes_and_no_approximate_index(db):
    rows = lambda q: db.execute(text(q)).scalars().all()                                  # noqa: E731
    assert rows("SELECT atttypmod FROM pg_attribute WHERE attrelid='requirement_embeddings'::regclass AND attname='embedding'") == [384]
    assert rows("SELECT atttypmod FROM pg_attribute WHERE attrelid='resume_chunks'::regclass AND attname='embedding'") == [384]
    idx = set(rows("SELECT indexname FROM pg_indexes WHERE schemaname='public'"))
    assert {"ix_requirement_embeddings_requirement_id", "ix_jobs_active_posted", "ix_resume_chunks_user_id",
            "uq_job_requirements_ordinal", "uq_requirement_embeddings_alt", "uq_jobs_source_identity"} <= idx
    defs = " ".join(rows("SELECT indexdef FROM pg_indexes WHERE schemaname='public'")).lower()
    assert "hnsw" not in defs and "ivfflat" not in defs                                  # exact search: no ANN index (ARCHITECTURE.md)
    assert db.execute(text("SELECT catalogue_revision FROM app_state WHERE id = 1")).scalar() == 0
    with pytest.raises(Exception):
        db.execute(text("INSERT INTO app_state (id) VALUES (2)"))                         # singleton constraint
    db.rollback()


def test_migration_upgrades_downgrades_and_upgrades_again_without_touching_existing_tables(pg_url):
    from alembic import command
    from alembic.config import Config
    admin = create_engine(pg_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text("DROP DATABASE IF EXISTS mig_test"))
        c.execute(text("CREATE DATABASE mig_test"))
    mig_url = pg_url.rsplit("/", 1)[0] + "/mig_test"
    old = os.environ["DATABASE_URL"]
    os.environ["DATABASE_URL"] = mig_url
    try:
        cfg = Config(str(BACKEND / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND / "migrations"))
        eng = create_engine(mig_url)
        tables = lambda: {r[0] for r in eng.connect().execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'"))}   # noqa: E731
        command.upgrade(cfg, "e378f7a1a884")                                              # Jiaxin's head before this change
        before = tables()
        assert not {"jobs", "job_requirements", "requirement_embeddings", "app_state"} & before
        command.upgrade(cfg, "head")
        after = tables()
        assert {"jobs", "job_requirements", "requirement_embeddings", "app_state"} <= after and before <= after
        assert eng.connect().execute(text("SELECT catalogue_revision FROM app_state")).scalar() == 0
        command.downgrade(cfg, "e378f7a1a884")
        assert tables() == before                                                        # downgrade removes only the new tables
        command.upgrade(cfg, "head")
        assert tables() == after
        eng.dispose()
    finally:
        os.environ["DATABASE_URL"] = old
        reenable_loggers()
        with admin.connect() as c:
            c.execute(text("DROP DATABASE IF EXISTS mig_test WITH (FORCE)"))
        admin.dispose()
