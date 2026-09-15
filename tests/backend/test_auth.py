import json
from unittest.mock import patch

from app.db.models import User


def _get_bootstrap(client):
    resp = client.get("/api/auth/bootstrap")
    assert resp.status_code == 200
    nonce = resp.json()["csrf_token"]
    return nonce, resp.cookies


def test_bootstrap_issues_nonce_and_cookie(client):
    resp = client.get("/api/auth/bootstrap")
    assert resp.status_code == 200
    assert "csrf_token" in resp.json()
    assert "pre_login" in resp.cookies


@patch("app.auth.router.verify_google_credential")
def test_google_exchange_creates_new_user(mock_verify, client, db_engine):
    mock_verify.return_value = "fake-sub-12345"
    nonce, cookies = _get_bootstrap(client)

    resp = client.post(
        "/api/auth/google",
        json={"credential": "fake-credential"},
        headers={"X-CSRF-Token": nonce, "Origin": "http://localhost:8080"},
        cookies=cookies,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "user_id" in body["user"]
    assert "csrf_token" in body
    assert "session" in resp.cookies

    # Cleanup: remove the test user so reruns don't accumulate rows
    from sqlalchemy import text
    with db_engine.connect() as conn:
        conn.execute(text("DELETE FROM users WHERE google_sub = 'fake-sub-12345'"))
        conn.commit()


@patch("app.auth.router.verify_google_credential")
def test_google_exchange_finds_existing_user(mock_verify, client, db_engine):
    mock_verify.return_value = "fake-sub-existing"

    # Seed an existing user directly
    from sqlalchemy import text
    with db_engine.connect() as conn:
        conn.execute(text(
            "INSERT INTO users (user_id, google_sub) VALUES (gen_random_uuid(), 'fake-sub-existing')"
        ))
        conn.commit()

    nonce, cookies = _get_bootstrap(client)
    resp = client.post(
        "/api/auth/google",
        json={"credential": "fake-credential"},
        headers={"X-CSRF-Token": nonce, "Origin": "http://localhost:8080"},
        cookies=cookies,
    )
    assert resp.status_code == 200

    with db_engine.connect() as conn:
        count = conn.execute(text(
            "SELECT count(*) FROM users WHERE google_sub = 'fake-sub-existing'"
        )).scalar()
    assert count == 1  # confirms find, not duplicate create

    with db_engine.connect() as conn:
        conn.execute(text("DELETE FROM users WHERE google_sub = 'fake-sub-existing'"))
        conn.commit()


def test_google_exchange_rejects_wrong_csrf(client):
    _nonce, cookies = _get_bootstrap(client)
    resp = client.post(
        "/api/auth/google",
        json={"credential": "irrelevant"},
        headers={"X-CSRF-Token": "wrong-token", "Origin": "http://localhost:8080"},
        cookies=cookies,
    )
    assert resp.status_code == 403


def test_google_exchange_rejects_bad_origin(client):
    nonce, cookies = _get_bootstrap(client)
    resp = client.post(
        "/api/auth/google",
        json={"credential": "irrelevant"},
        headers={"X-CSRF-Token": nonce, "Origin": "http://evil.example.com"},
        cookies=cookies,
    )
    assert resp.status_code == 403