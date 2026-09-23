"""DB-gated route tests for the local integration contract.

These tests run only when DISPOSABLE_DATABASE_URL is explicitly supplied by
the disposable pgvector test service. They create uniquely named rows and
delete only those rows during teardown; they never truncate a configured app
database.
"""

from __future__ import annotations

import os
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("pgvector")
DISPOSABLE_DATABASE_URL = os.environ.get("DISPOSABLE_DATABASE_URL")
if not DISPOSABLE_DATABASE_URL:
    pytest.skip("DISPOSABLE_DATABASE_URL is required for route integration tests", allow_module_level=True)
if os.environ.get("DATABASE_URL") not in (None, DISPOSABLE_DATABASE_URL):
    pytest.skip("DATABASE_URL must equal the explicit disposable database URL", allow_module_level=True)

os.environ["DATABASE_URL"] = DISPOSABLE_DATABASE_URL
os.environ.setdefault("APP_ORIGIN", "http://localhost:8080")
os.environ.setdefault("GOOGLE_CLIENT_ID", "disposable-test-client")
os.environ.setdefault("APP_SIGNING_KEY", "disposable-test-signing-key")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.auth import security
from app.api.resume import _payload_hash
from app.db.models import ResumeChunk, ResumeProfile, SaveOperation, Session as SessionModel, User
from app.db.session import configure_transaction_timeouts, get_db
from app.catalogue.models import AppState, Job, JobRequirement, RequirementEmbedding
from app.main import app
from app.processing.config import EMBEDDING_VERSION


@pytest.fixture
def db_session():
    engine = create_engine(DISPOSABLE_DATABASE_URL)
    configure_transaction_timeouts(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    marker = f"codex-disposable-{uuid.uuid4()}"
    try:
        yield db, marker
    finally:
        db.rollback()
        db.query(Job).filter(Job.source == "CODEX_DISPOSABLE", Job.source_job_id.like(f"{marker}:%")).delete(synchronize_session=False)
        db.query(User).filter(User.google_sub.like(f"{marker}%")).delete(synchronize_session=False)
        db.commit()
        db.close()
        engine.dispose()


@pytest.fixture
def authenticated_client(db_session):
    db, marker = db_session
    user = User(user_id=uuid.uuid4(), google_sub=marker, resume_revision=0)
    raw_token = secrets.token_urlsafe(32)
    session = SessionModel(
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        user_id=user.user_id,
        csrf_token=f"csrf-{uuid.uuid4()}",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    # Keep the fixture's parent/child insert order explicit.  These models do
    # not declare an ORM relationship, so a single add_all() can attempt the
    # session row before its users row on PostgreSQL.
    db.add(user)
    db.flush()
    db.add(session)
    db.commit()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    client.cookies.set(security.session_cookie_name(), raw_token)
    yield client, db, user, session, marker
    app.dependency_overrides.pop(get_db, None)
    client.close()


class _FakeLease:
    def __init__(self, *, bad_vectors=False, transaction_probe=None, cleaned=None,
                 chunks=None, vectors=None):
        self.released = False
        self.bad_vectors = bad_vectors
        self.transaction_probe = transaction_probe
        self.cleaned = cleaned
        self.chunks = chunks if chunks is not None else []
        self.vectors = vectors if vectors is not None else []
        self.transaction_active_during_run = None

    def run(self, operation, payload):
        if self.transaction_probe is not None:
            self.transaction_active_during_run = self.transaction_probe()
        if operation == "prepare":
            return {"draft": {"skills": [], "projects": [], "experience": [], "education": []},
                    "unassigned_text": "", "warnings": []}
        if self.bad_vectors:
            return {"review_required": False, "version": EMBEDDING_VERSION,
                    "chunks": [{"section": "PROJECT", "entry_index": 0, "chunk_index": 0, "text": "x"}],
                    "vectors": []}
        if payload.get("skip_embedding"):
            if self.cleaned is not None:
                return {"review_required": True, "cleaned": self.cleaned}
            return {"review_required": False, "no_op": True, "version": EMBEDDING_VERSION,
                    "chunks": [], "vectors": []}
        return {"review_required": False, "version": EMBEDDING_VERSION,
                "chunks": self.chunks, "vectors": self.vectors}

    def release(self):
        self.released = True


class _FakeService:
    def __init__(self, *, bad_vectors=False, transaction_probe=None, cleaned=None,
                 chunks=None, vectors=None):
        self.bad_vectors = bad_vectors
        self.transaction_probe = transaction_probe
        self.cleaned = cleaned
        self.chunks = chunks
        self.vectors = vectors
        self.leases = []

    def try_acquire(self):
        lease = _FakeLease(
            bad_vectors=self.bad_vectors,
            transaction_probe=self.transaction_probe,
            cleaned=self.cleaned,
            chunks=self.chunks,
            vectors=self.vectors,
        )
        self.leases.append(lease)
        return lease


def _unsafe_headers(session):
    return {"Origin": "http://localhost:8080", "X-CSRF-Token": session.csrf_token}


def _job(marker, suffix, *, active=True, title="Python internship"):
    return Job(
        job_id=uuid.uuid4(), source="CODEX_DISPOSABLE", source_job_id=f"{marker}:{suffix}",
        title=title, company_name="Disposable Co", country_code="SG", location="Singapore",
        description=f"{title} opportunity building APIs", apply_url="https://example.test/apply",
        source_url="https://example.test/source", job_type="INTERNSHIP", employment_time="FULL_TIME",
        work_arrangement="HYBRID", eligibility_notes=[], is_active=active, content_hash="x" * 64,
        posted_at=datetime.now(timezone.utc), last_imported_at=datetime.now(timezone.utc),
    )


def test_jobs_search_paging_and_revision_guard(authenticated_client):
    client, db, _user, _session, marker = authenticated_client
    db.add_all([_job(marker, "one"), _job(marker, "two", title="SQL internship"), _job(marker, "closed", active=False)])
    state = db.get(AppState, 1)
    state.catalogue_revision += 1
    db.commit()
    revision = state.catalogue_revision

    page = client.get("/api/jobs", params={"q": "Python", "limit": 1})
    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store"
    assert page.json()["total"] == 1
    assert page.json()["catalogue_revision"] == revision

    state.catalogue_revision += 1
    db.commit()
    changed = client.get("/api/jobs", params={"catalogue_revision": revision})
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "RESULTS_CHANGED"


def test_save_replay_noop_revision_and_operation_ownership(authenticated_client, monkeypatch):
    client, db, user, session, marker = authenticated_client
    service = _FakeService(transaction_probe=db.in_transaction)
    monkeypatch.setattr("app.main.processing_service", service)
    content = {"skills": ["Python"], "projects": [], "experience": [], "education": []}
    headers = _unsafe_headers(session)
    key = str(uuid.uuid4())
    first = client.put("/api/resume", json={"expected_revision": 0, "content": content},
                       headers={**headers, "Idempotency-Key": key})
    assert first.status_code == 200 and first.json()["changed"] is True
    assert service.leases[0].transaction_active_during_run is False
    replay = client.put("/api/resume", json={"expected_revision": 0, "content": content},
                        headers={**headers, "Idempotency-Key": key})
    assert replay.status_code == 200
    no_op = client.put("/api/resume", json={"expected_revision": 1, "content": content},
                       headers={**headers, "Idempotency-Key": str(uuid.uuid4())})
    assert no_op.status_code == 200 and no_op.json()["changed"] is False
    stale = client.put("/api/resume", json={"expected_revision": 0, "content": content},
                       headers={**headers, "Idempotency-Key": str(uuid.uuid4())})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "REVISION_CONFLICT"

    other = User(user_id=uuid.uuid4(), google_sub=f"{marker}:other", resume_revision=0)
    other_raw = secrets.token_urlsafe(32)
    other_session = SessionModel(token_hash=hashlib.sha256(other_raw.encode()).hexdigest(), user_id=other.user_id,
                                 csrf_token=f"csrf-{uuid.uuid4()}",
                                 expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    db.add(other)
    db.flush()
    db.add(other_session)
    db.commit()
    other_client = TestClient(app)
    other_client.cookies.set(security.session_cookie_name(), other_raw)
    status = other_client.get(f"/api/resume/operations/{key}")
    other_client.close()
    assert status.status_code == 404


def test_save_flushes_profile_before_persisting_pipeline_chunks(authenticated_client, monkeypatch):
    client, db, user, session, _marker = authenticated_client
    content = {
        "skills": ["Python"],
        "projects": [{"title": "API", "description": "Built API", "technologies": ["Python"]}],
        "experience": [],
        "education": [],
    }
    chunks = [{
        "section": "PROJECT",
        "entry_index": 0,
        "chunk_index": 0,
        "text": "Built API",
    }]
    vectors = [[1.0] + [0.0] * 383]
    service = _FakeService(chunks=chunks, vectors=vectors)
    monkeypatch.setattr("app.main.processing_service", service)

    operation_id = str(uuid.uuid4())
    response = client.put(
        "/api/resume",
        json={"expected_revision": 0, "content": content},
        headers={**_unsafe_headers(session), "Idempotency-Key": operation_id},
    )

    assert response.status_code == 200
    assert response.json() == {
        "operation_id": operation_id,
        "result_revision": 1,
        "changed": True,
    }
    profile = db.get(ResumeProfile, user.user_id)
    assert profile is not None and profile.revision == 1
    persisted = db.query(ResumeChunk).filter(ResumeChunk.user_id == user.user_id).all()
    assert len(persisted) == 1
    assert persisted[0].profile_revision == 1
    assert persisted[0].text == "Built API"
    assert service.leases[0].released is True


def test_save_atomic_failure_preserves_previous_profile(authenticated_client, monkeypatch):
    client, db, user, session, marker = authenticated_client
    old = {"skills": ["SQL"], "projects": [], "experience": [], "education": []}
    db.add(ResumeProfile(user_id=user.user_id, revision=0, content=old, content_hash="old" * 16,
                         embedding_version=EMBEDDING_VERSION))
    db.commit()
    service = _FakeService(bad_vectors=True)
    monkeypatch.setattr("app.main.processing_service", service)
    new = {"skills": ["Python"], "projects": [], "experience": [], "education": []}
    key = str(uuid.uuid4())
    response = client.put("/api/resume", json={"expected_revision": 0, "content": new},
                          headers={**_unsafe_headers(session), "Idempotency-Key": key})
    assert response.status_code == 500
    profile = db.get(ResumeProfile, user.user_id)
    op = db.get(SaveOperation, {"user_id": user.user_id, "operation_id": uuid.UUID(key)})
    assert profile.content == old and op.state == "FAILED"
    assert service.leases[0].released is True


def test_save_releases_lease_when_operation_insert_commit_fails(authenticated_client, monkeypatch, caplog):
    client, db, _user, session, _marker = authenticated_client
    service = _FakeService()
    monkeypatch.setattr("app.main.processing_service", service)

    class FailingCommitSession:
        def __init__(self, delegate):
            self.delegate = delegate
            self.commit_calls = 0

        def commit(self):
            self.commit_calls += 1
            if self.commit_calls == 1:
                raise RuntimeError("synthetic operation insert failure")
            return self.delegate.commit()

        def __getattr__(self, name):
            return getattr(self.delegate, name)

    failing = FailingCommitSession(db)

    def override_db():
        yield failing

    app.dependency_overrides[get_db] = override_db
    content = {"skills": ["Python"], "projects": [], "experience": [], "education": []}
    response = client.put("/api/resume", json={"expected_revision": 0, "content": content},
                          headers={**_unsafe_headers(session), "Idempotency-Key": str(uuid.uuid4())})
    def restore_db():
        yield db

    app.dependency_overrides[get_db] = restore_db
    assert response.status_code == 500
    assert service.leases[0].released is True
    assert "resume_save_failed stage=operation_insert exception_class=RuntimeError" in caplog.text
    assert "synthetic operation insert failure" not in caplog.text


def test_prepare_requires_csrf_and_capped_upload_has_no_store(authenticated_client, monkeypatch):
    client, _db, _user, session, _marker = authenticated_client
    service = _FakeService()
    monkeypatch.setattr("app.main.processing_service", service)
    missing = client.post("/api/resume/prepare", files={"file": ("resume.pdf", b"pdf")},
                          headers={"Origin": "http://localhost:8080"})
    assert missing.status_code == 403 and missing.json()["error"]["code"] == "CSRF_INVALID"
    oversized = client.post("/api/resume/prepare", content=b"x", headers={
        **_unsafe_headers(session), "Content-Type": "multipart/form-data; boundary=x",
        "Content-Length": str(6 * 1024 * 1024 + 1),
    })
    assert oversized.status_code == 413 and oversized.headers["cache-control"] == "no-store"
    assert service.leases == []


def test_prepare_processing_runs_without_request_transaction(authenticated_client, monkeypatch):
    client, db, _user, session, _marker = authenticated_client
    service = _FakeService(transaction_probe=db.in_transaction)
    monkeypatch.setattr("app.main.processing_service", service)
    boundary = "codex-boundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="resume.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
        "%PDF-1.4\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    response = client.post("/api/resume/prepare", content=body, headers={
        **_unsafe_headers(session), "Content-Type": f"multipart/form-data; boundary={boundary}",
    })
    assert response.status_code == 200
    assert service.leases[0].transaction_active_during_run is False


def test_review_required_replay_rederives_draft_and_maps_service_unavailable(
    authenticated_client, monkeypatch,
):
    client, db, user, session, _marker = authenticated_client
    content = {"skills": ["Jane Example"], "projects": [], "experience": [], "education": []}
    cleaned = {"skills": [], "projects": [], "experience": [], "education": []}
    review_key = uuid.uuid4()
    now = datetime.now(timezone.utc)
    db.add(SaveOperation(
        user_id=user.user_id, operation_id=review_key,
        payload_hash=_payload_hash(0, content), state="FAILED", expected_revision=0,
        failure_code="REVIEW_REQUIRED", expires_at=now + timedelta(hours=1),
    ))
    unavailable_key = uuid.uuid4()
    db.add(SaveOperation(
        user_id=user.user_id, operation_id=unavailable_key,
        payload_hash=_payload_hash(0, content), state="FAILED", expected_revision=0,
        failure_code="SERVICE_UNAVAILABLE", expires_at=now + timedelta(hours=1),
    ))
    db.commit()
    service = _FakeService(cleaned=cleaned, transaction_probe=db.in_transaction)
    monkeypatch.setattr("app.main.processing_service", service)
    headers = _unsafe_headers(session)
    mismatch = client.put("/api/resume", json={"expected_revision": 0,
                                               "content": {"skills": ["Other"], "projects": [],
                                                           "experience": [], "education": []}},
                          headers={**headers, "Idempotency-Key": str(review_key)})
    assert mismatch.status_code == 409
    assert mismatch.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    replay = client.put("/api/resume", json={"expected_revision": 0, "content": content},
                        headers={**headers, "Idempotency-Key": str(review_key)})
    assert replay.status_code == 422
    assert replay.json()["error"]["code"] == "REVIEW_REQUIRED"
    assert replay.json()["error"]["details"]["cleaned_draft"] == cleaned
    assert service.leases[0].transaction_active_during_run is False

    malformed_key = uuid.uuid4()
    db.add(SaveOperation(
        user_id=user.user_id, operation_id=malformed_key,
        payload_hash=_payload_hash(0, content), state="FAILED", expected_revision=0,
        failure_code="REVIEW_REQUIRED", expires_at=now + timedelta(hours=1),
    ))
    db.commit()
    service.cleaned = None
    malformed = client.put("/api/resume", json={"expected_revision": 0, "content": content},
                           headers={**headers, "Idempotency-Key": str(malformed_key)})
    assert malformed.status_code == 500
    assert malformed.json()["error"]["code"] == "INTERNAL_ERROR"

    unavailable = client.put("/api/resume", json={"expected_revision": 0, "content": content},
                             headers={**headers, "Idempotency-Key": str(unavailable_key)})
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_matches_returns_evidence_without_score_and_requires_current_profile(authenticated_client):
    client, db, user, _session, marker = authenticated_client
    response = client.get("/api/matches")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "RESUME_REQUIRED"

    content = {"skills": ["Python"], "projects": [{"title": "API", "description": "Built API", "technologies": ["Python"]}],
               "experience": [], "education": []}
    db.add(ResumeProfile(user_id=user.user_id, revision=0, content=content, content_hash="p" * 64,
                         embedding_version=EMBEDDING_VERSION))
    db.flush()
    db.add(ResumeChunk(user_id=user.user_id, profile_revision=0, section="PROJECT", entry_index=0,
                       chunk_index=0, text="Built API", embedding=[1.0] + [0.0] * 383,
                       embedding_version=EMBEDDING_VERSION))
    job = _job(marker, "match")
    req = JobRequirement(requirement_id=uuid.uuid4(), job_id=job.job_id, ordinal=0,
                         requirement_text="Python", importance="REQUIRED", alternatives=[],
                         source_quote="Python", evidence_skills=["Python"])
    db.add(job)
    db.flush()
    db.add(req)
    db.flush()
    db.add(RequirementEmbedding(embedding_id=uuid.uuid4(), requirement_id=req.requirement_id,
                                alternative_index=0, text="Python", embedding=[1.0] + [0.0] * 383,
                                embedding_version=EMBEDDING_VERSION))
    db.commit()
    user.resume_revision = 0
    page = client.get("/api/matches")
    assert page.status_code == 200
    payload = page.json()
    assert "score" not in str(payload)
    assert payload["items"][0]["requirements"][0]["requirement_text"] == "Python"


def test_locked_revision_refreshes_after_concurrent_commit(db_session):
    db, marker = db_session
    user = User(user_id=uuid.uuid4(), google_sub=marker, resume_revision=0)
    db.add(user)
    db.commit()
    engine = db.get_bind()
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    first, second = Session(), Session()
    try:
        first_user = first.get(User, user.user_id)
        second_user = second.get(User, user.user_id)
        stale_revision = second_user.resume_revision
        first_user.resume_revision = 1
        first.commit()
        second.rollback()
        locked = second.execute(
            select(User).where(User.user_id == user.user_id).with_for_update().execution_options(populate_existing=True)
        ).scalar_one()
        assert stale_revision == 0
        assert locked.resume_revision == 1
    finally:
        first.close()
        second.close()


def test_application_transactions_have_bounded_statement_and_lock_waits(db_session):
    db, _marker = db_session
    assert db.execute(text("SHOW statement_timeout")).scalar() == "5s"
    assert db.execute(text("SHOW lock_timeout")).scalar() == "5s"
