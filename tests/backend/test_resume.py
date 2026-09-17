import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from sqlalchemy import text

from app.db.models import ResumeProfile, SaveOperation


def _login(client):
    resp = client.get("/api/auth/bootstrap")
    nonce = resp.json()["csrf_token"]
    with patch("app.auth.router.verify_google_credential") as mock_verify:
        mock_verify.return_value = "fake-sub-resume-test"
        login_resp = client.post(
            "/api/auth/google",
            json={"credential": "irrelevant"},
            headers={"X-CSRF-Token": nonce, "Origin": "http://localhost:8080"},
            cookies=resp.cookies,
        )
    return login_resp.cookies, login_resp.json()["user"]["user_id"], login_resp.json()["csrf_token"]


def _cleanup(db_engine, sub):
    with db_engine.connect() as conn:
        conn.execute(text("DELETE FROM users WHERE google_sub = :sub"), {"sub": sub})
        conn.commit()


def test_get_resume_404_when_none_exists(client, db_engine):
    cookies, _uid, _csrf = _login(client)
    resp = client.get("/api/resume", cookies=cookies)
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"]["code"] == "RESUME_NOT_FOUND"
    _cleanup(db_engine, "fake-sub-resume-test")


def test_get_resume_returns_saved_profile(client, db_engine):
    cookies, user_id, _csrf = _login(client)
    with db_engine.connect() as conn:
        conn.execute(text(
            "INSERT INTO resume_profiles (user_id, revision, content, content_hash, embedding_version) "
            "VALUES (:uid, 1, '{\"skills\": []}'::jsonb, 'hash123', 'v1')"
        ), {"uid": user_id})
        conn.commit()

    resp = client.get("/api/resume", cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert body["revision"] == 1
    assert body["embedding_version"] == "v1"
    _cleanup(db_engine, "fake-sub-resume-test")


def test_delete_resume_rejects_revision_conflict(client, db_engine):
    cookies, _uid, csrf = _login(client)
    resp = client.request(
        "DELETE", "/api/resume",
        json={"expected_revision": 999},
        headers={"X-CSRF-Token": csrf, "Origin": "http://localhost:8080"},
        cookies=cookies,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"]["code"] == "REVISION_CONFLICT"
    _cleanup(db_engine, "fake-sub-resume-test")


def test_delete_resume_succeeds_and_increments_revision(client, db_engine):
    cookies, user_id, csrf = _login(client)
    with db_engine.connect() as conn:
        conn.execute(text(
            "INSERT INTO resume_profiles (user_id, revision, content, content_hash, embedding_version) "
            "VALUES (:uid, 1, '{}'::jsonb, 'h', 'v1')"
        ), {"uid": user_id})
        conn.commit()

    resp = client.request(
        "DELETE", "/api/resume",
        json={"expected_revision": 0},
        headers={"X-CSRF-Token": csrf, "Origin": "http://localhost:8080"},
        cookies=cookies,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_resume"] is False
    assert body["resume_revision"] == 1

    with db_engine.connect() as conn:
        remaining = conn.execute(text(
            "SELECT count(*) FROM resume_profiles WHERE user_id = :uid"
        ), {"uid": user_id}).scalar()
    assert remaining == 0
    _cleanup(db_engine, "fake-sub-resume-test")


def test_delete_resume_rejects_bad_csrf(client, db_engine):
    cookies, _uid, _csrf = _login(client)
    resp = client.request(
        "DELETE", "/api/resume",
        json={"expected_revision": 0},
        headers={"X-CSRF-Token": "wrong", "Origin": "http://localhost:8080"},
        cookies=cookies,
    )
    assert resp.status_code == 403
    _cleanup(db_engine, "fake-sub-resume-test")


def test_operation_status_not_found(client, db_engine):
    cookies, _uid, _csrf = _login(client)
    fake_op_id = str(uuid.uuid4())
    resp = client.get(f"/api/resume/operations/{fake_op_id}", cookies=cookies)
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"]["code"] == "OPERATION_EXPIRED"
    _cleanup(db_engine, "fake-sub-resume-test")


def test_operation_status_returns_existing_operation(client, db_engine):
    cookies, user_id, _csrf = _login(client)
    op_id = str(uuid.uuid4())
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    with db_engine.connect() as conn:
        conn.execute(text(
            "INSERT INTO save_operations "
            "(user_id, operation_id, payload_hash, state, expected_revision, expires_at) "
            "VALUES (:uid, :oid, 'hash', 'SUCCEEDED', 0, :exp)"
        ), {"uid": user_id, "oid": op_id, "exp": future})
        conn.commit()

    resp = client.get(f"/api/resume/operations/{op_id}", cookies=cookies)
    assert resp.status_code == 200
    assert resp.json()["state"] == "SUCCEEDED"
    _cleanup(db_engine, "fake-sub-resume-test")