from unittest.mock import patch
from sqlalchemy import text


def _login(client):
    resp = client.get("/api/auth/bootstrap")
    nonce = resp.json()["csrf_token"]
    with patch("app.auth.router.verify_google_credential") as mock_verify:
        mock_verify.return_value = "fake-sub-me-test"
        login_resp = client.post(
            "/api/auth/google",
            json={"credential": "irrelevant"},
            headers={"X-CSRF-Token": nonce, "Origin": "http://localhost:8080"},
            cookies=resp.cookies,
        )
    return login_resp.cookies


def test_me_requires_auth(client):
    resp = client.get("/api/me")
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "AUTH_REQUIRED"


def test_me_returns_correct_shape_for_new_user(client, db_engine):
    cookies = _login(client)
    resp = client.get("/api/me", cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_resume"] is False
    assert body["has_matchable_resume"] is False
    assert body["resume_revision"] == 0
    assert "csrf_token" in body

    with db_engine.connect() as conn:
        conn.execute(text("DELETE FROM users WHERE google_sub = 'fake-sub-me-test'"))
        conn.commit()