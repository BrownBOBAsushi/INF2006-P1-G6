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
from app.db.models import OutboxEvent, ProcessingTask, ResumeChunk, ResumeProfile, SaveOperation, Session as SessionModel, User
from app.db.session import configure_transaction_timeouts, get_db
from app.catalogue.models import AppState, Job, JobRequirement, RequirementEmbedding
from app.main import app
from app.processing.config import EMBEDDING_VERSION
from app.processing.local_worker import LocalWorker
from app.processing.local_storage import LocalTempStorage


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
    monkeypatch.setattr("app.api.resume._privacy_recheck", lambda content: (False, content))
    content = {"skills": ["Python"], "projects": [], "experience": [], "education": []}
    headers = _unsafe_headers(session)
    key = str(uuid.uuid4())
    first = client.put("/api/resume", json={"expected_revision": 0, "content": content},
                       headers={**headers, "Idempotency-Key": key})
    assert first.status_code == 200 and first.json()["changed"] is True
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


def test_save_commits_approved_content_before_embedding_is_ready(authenticated_client, monkeypatch):
    client, db, user, session, _marker = authenticated_client
    content = {
        "skills": ["Python"],
        "projects": [{"title": "API", "description": "Built API", "technologies": ["Python"]}],
        "experience": [],
        "education": [],
    }
    monkeypatch.setattr("app.api.resume._privacy_recheck", lambda content: (False, content))

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
    assert persisted == []
    task = db.query(ProcessingTask).filter_by(owner_id=user.user_id, kind="EMBEDDING").one()
    outbox = db.query(OutboxEvent).filter_by(task_id=task.task_id).one()
    assert task.state == "PENDING" and outbox.state == "PENDING"
    operation = db.get(SaveOperation, {"user_id": user.user_id, "operation_id": uuid.UUID(operation_id)})
    assert operation.state == "SUCCEEDED"


def test_save_succeeds_without_waiting_for_embedding_worker(authenticated_client, monkeypatch):
    client, db, user, session, marker = authenticated_client
    old = {"skills": ["SQL"], "projects": [], "experience": [], "education": []}
    db.add(ResumeProfile(user_id=user.user_id, revision=0, content=old, content_hash="old" * 16,
                         embedding_version=EMBEDDING_VERSION))
    db.commit()
    monkeypatch.setattr("app.api.resume._privacy_recheck", lambda content: (False, content))
    new = {"skills": ["Python"], "projects": [], "experience": [], "education": []}
    key = str(uuid.uuid4())
    response = client.put("/api/resume", json={"expected_revision": 0, "content": new},
                          headers={**_unsafe_headers(session), "Idempotency-Key": key})
    assert response.status_code == 200
    profile = db.get(ResumeProfile, user.user_id)
    op = db.get(SaveOperation, {"user_id": user.user_id, "operation_id": uuid.UUID(key)})
    assert profile.content == new and profile.revision == 1 and op.state == "SUCCEEDED"
    assert db.query(ProcessingTask).filter_by(owner_id=user.user_id, kind="EMBEDDING").count() == 1


def test_save_commit_failure_leaves_no_partial_profile_or_operation(authenticated_client, monkeypatch, caplog):
    client, db, _user, session, _marker = authenticated_client
    monkeypatch.setattr("app.api.resume._privacy_recheck", lambda content: (False, content))

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
    assert "resume_save_failed exception_class=RuntimeError" in caplog.text
    assert "synthetic operation insert failure" not in caplog.text


def test_prepare_requires_csrf_and_capped_upload_has_no_store(authenticated_client, monkeypatch):
    client, _db, _user, session, _marker = authenticated_client
    monkeypatch.setattr("app.api.resume._privacy_recheck", lambda content: (False, content))
    missing = client.post("/api/resume/prepare", files={"file": ("resume.pdf", b"pdf")},
                          headers={"Origin": "http://localhost:8080"})
    assert missing.status_code == 403 and missing.json()["error"]["code"] == "CSRF_INVALID"
    oversized = client.post("/api/resume/prepare", content=b"x", headers={
        **_unsafe_headers(session), "Content-Type": "multipart/form-data; boundary=x",
        "Content-Length": str(6 * 1024 * 1024 + 1),
    })
    assert oversized.status_code == 413 and oversized.headers["cache-control"] == "no-store"


def test_prepare_persists_upload_task_and_outbox(authenticated_client, monkeypatch, tmp_path):
    client, db, _user, session, _marker = authenticated_client
    monkeypatch.setenv("PROCESSING_TEMP_DIR", str(tmp_path))
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
    assert response.status_code == 202
    body_json = response.json()
    task = db.get(ProcessingTask, uuid.UUID(body_json["task_id"]))
    event = db.query(OutboxEvent).filter_by(task_id=task.task_id).one()
    assert task.state == "PENDING" and event.state == "PENDING"
    assert task.payload_ref is not None and (tmp_path / f"{uuid.UUID(task.payload_ref).hex}.pdf").exists()


def test_discard_or_profileless_delete_cleans_temporary_work(authenticated_client, monkeypatch, tmp_path):
    client, db, user, session, _marker = authenticated_client
    monkeypatch.setenv("PROCESSING_TEMP_DIR", str(tmp_path))
    boundary = "discard-boundary"
    body = (f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="resume.pdf"\r\n'
            "Content-Type: application/pdf\r\n\r\n%PDF-1.4\r\n"
            f"--{boundary}--\r\n").encode()
    accepted = client.post("/api/resume/prepare", content=body, headers={
        **_unsafe_headers(session), "Content-Type": f"multipart/form-data; boundary={boundary}",
    })
    task_id = uuid.UUID(accepted.json()["task_id"])
    task = db.get(ProcessingTask, task_id)
    assert task.payload_ref is not None
    path = LocalTempStorage(tmp_path).path_for(task.payload_ref)
    assert path.exists()
    missing_csrf = client.delete(f"/api/resume/tasks/{task_id}", headers={"Origin": "http://localhost:8080"})
    assert missing_csrf.status_code == 403
    discarded = client.delete(f"/api/resume/tasks/{task_id}", headers=_unsafe_headers(session))
    assert discarded.status_code == 200 and discarded.json()["state"] == "CANCELLED"
    assert not path.exists()
    db.expire_all()
    task = db.get(ProcessingTask, task_id)
    assert task.state == "CANCELLED" and task.result_data is None and task.payload_ref is None

    # Deleting while no permanent profile exists still advances the revision and
    # fences any other pending extraction work for that account.
    second = client.post("/api/resume/prepare", content=body, headers={
        **_unsafe_headers(session), "Content-Type": f"multipart/form-data; boundary={boundary}",
    })
    second_id = uuid.UUID(second.json()["task_id"])
    second_task = db.get(ProcessingTask, second_id)
    assert second_task.payload_ref is not None
    second_path = LocalTempStorage(tmp_path).path_for(second_task.payload_ref)
    assert second_path.exists()
    deleted = client.request("DELETE", "/api/resume", json={"expected_revision": 0},
                             headers=_unsafe_headers(session))
    assert deleted.status_code == 200 and deleted.json() == {"resume_revision": 1, "has_resume": False}
    db.expire_all()
    task = db.get(ProcessingTask, second_id)
    assert task.state == "CANCELLED" and task.payload_ref is None
    assert not second_path.exists()


def test_local_async_journey_extract_save_embed_delete_and_session_reuse(
    authenticated_client, monkeypatch, tmp_path,
):
    client, db, user, session, _marker = authenticated_client
    monkeypatch.setattr("app.api.resume._privacy_recheck", lambda content: (False, content))
    monkeypatch.setenv("PROCESSING_TEMP_DIR", str(tmp_path))
    Session = sessionmaker(bind=db.get_bind(), autoflush=False, autocommit=False)

    # Production get_db() creates one SQLAlchemy Session per request. Keep the
    # fixture's separate `db` session for setup/assertions, but preserve that
    # request boundary while workers commit changes concurrently.
    def override_request_db():
        request_db = Session()
        try:
            yield request_db
        finally:
            request_db.close()

    monkeypatch.setitem(app.dependency_overrides, get_db, override_request_db)
    boundary = "local-async-boundary"
    upload = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="resume.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
        "%PDF-1.4\r\nsynthetic resume\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    accepted = client.post("/api/resume/prepare", content=upload, headers={
        **_unsafe_headers(session), "Content-Type": f"multipart/form-data; boundary={boundary}",
    })
    assert accepted.status_code == 202
    task_id = uuid.UUID(accepted.json()["task_id"])
    task = db.get(ProcessingTask, task_id)
    assert task.payload_ref is not None
    pdf_path = LocalTempStorage(tmp_path).path_for(task.payload_ref)
    assert pdf_path.exists()

    extract_result = {
        "draft": {"skills": ["Python"], "projects": [{
            "title": "API", "description": "Built an API", "technologies": ["Python"],
        }], "experience": [], "education": []},
        "unassigned_text": "", "warnings": [],
    }
    extraction = LocalWorker("EXTRACTION", handlers={"prepare": lambda _payload: extract_result},
                             storage=LocalTempStorage(tmp_path),
                             session_factory=Session)
    assert extraction.dispatch_outbox() == 1
    assert extraction.run_one() is True
    assert not pdf_path.exists()
    draft = client.get(f"/api/resume/tasks/{task_id}")
    assert draft.status_code == 200 and draft.json()["result"] == extract_result

    # The same persistent cookie works from another app client and independent DB session.
    second_client = TestClient(app)
    second_client.cookies.set(security.session_cookie_name(), client.cookies.get(security.session_cookie_name()))
    try:
        assert second_client.get(f"/api/resume/tasks/{task_id}").status_code == 200
    finally:
        second_client.close()

    other = User(user_id=uuid.uuid4(), google_sub=f"{_marker}:other", resume_revision=0)
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
    try:
        assert other_client.get(f"/api/resume/tasks/{task_id}").status_code == 404
    finally:
        other_client.close()

    save = client.put("/api/resume", json={
        "expected_revision": 0, "content": extract_result["draft"], "extraction_task_id": str(task_id),
    }, headers={**_unsafe_headers(session), "Idempotency-Key": str(uuid.uuid4())})
    assert save.status_code == 200 and save.json()["result_revision"] == 1
    assert db.get(ResumeProfile, user.user_id).content == extract_result["draft"]
    embedding_task = db.query(ProcessingTask).filter_by(owner_id=user.user_id, kind="EMBEDDING").one()
    assert embedding_task.state == "PENDING"
    assert client.get("/api/resume").json()["embedding_state"] == "PENDING"

    embed_result = {"chunks": [{"section": "PROJECT", "entry_index": 0, "chunk_index": 0,
                                 "text": "Built an API"}],
                    "vectors": [[1.0] + [0.0] * 383], "version": EMBEDDING_VERSION}
    embedding = LocalWorker("EMBEDDING", handlers={"embed": lambda _payload: embed_result},
                            session_factory=Session)
    assert embedding.dispatch_outbox() == 1
    assert embedding.run_one() is True
    assert client.get("/api/resume").json()["embedding_state"] == "READY"

    deleted = client.request("DELETE", "/api/resume", json={"expected_revision": 1},
                             headers=_unsafe_headers(session))
    assert deleted.status_code == 200 and deleted.json() == {"resume_revision": 2, "has_resume": False}
    task_status = client.get(f"/api/resume/tasks/{task_id}")
    assert task_status.status_code == 200
    assert task_status.json() == {
        "task_id": str(task_id), "kind": "EXTRACTION", "state": "CANCELLED",
        "revision": 0, "failure_code": "CANCELLED_BY_OWNER", "result": None,
        "expires_at": None,
    }
    active_tasks = client.get("/api/resume/tasks/active")
    assert active_tasks.status_code == 200 and active_tasks.json() is None
    db.expire_all()
    assert db.get(ResumeProfile, user.user_id) is None
    retained_task = db.get(ProcessingTask, task_id)
    assert retained_task.state == "CANCELLED"
    assert retained_task.result_data is None and retained_task.expires_at is None
    assert retained_task.payload_ref is None
    assert db.query(ResumeChunk).filter_by(user_id=user.user_id).count() == 0


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
    monkeypatch.setattr("app.api.resume._privacy_recheck", lambda _content: (True, cleaned))
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

    malformed_key = uuid.uuid4()
    db.add(SaveOperation(
        user_id=user.user_id, operation_id=malformed_key,
        payload_hash=_payload_hash(0, content), state="FAILED", expected_revision=0,
        failure_code="REVIEW_REQUIRED", expires_at=now + timedelta(hours=1),
    ))
    db.commit()
    monkeypatch.setattr("app.api.resume._privacy_recheck", lambda _content: (True, None))
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
