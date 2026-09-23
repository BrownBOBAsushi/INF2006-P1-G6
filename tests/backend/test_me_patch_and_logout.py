from unittest.mock import patch
from sqlalchemy import text


def _login(client):
    resp = client.get("/api/auth/bootstrap")
    nonce = resp.json()["csrf_token"]
    with patch("app.auth.router.verify_google_credential") as mock_verify:
        mock_verify.return_value = "fake-sub-patch-test"
        login_resp = client.post(
            "/api/auth/google",
            json={"credential": "irrelevant"},
            headers={"X-CSRF-Token": nonce, "Origin": "http://localhost:8080"},
            cookies=resp.cookies,
        )
    return login_resp.cookies, login_resp.json()["csrf_token"]


def _cleanup(db_engine, sub):
    with db_engine.connect() as conn:
        conn.execute(text("DELETE FROM users WHERE google_sub = :sub"), {"sub": sub})
        conn.commit()


def test_patch_me_updates_display_name(client, db_engine):
    cookies, csrf = _login(client)
    resp = client.patch(
        "/api/me",
        json={"display_name": "  Jia Xin  "},
        headers={"Origin": "http://localhost:8080", "X-CSRF-Token": csrf},
        cookies=cookies,
    )
    assert resp.status_code == 200
    assert resp.json()["user"]["display_name"] == "Jia Xin"  # trimmed
    _cleanup(db_engine, "fake-sub-patch-test")


def test_patch_me_rejects_empty_name(client, db_engine):
    cookies, csrf = _login(client)
    resp = client.patch(
        "/api/me",
        json={"display_name": "   "},
        headers={"Origin": "http://localhost:8080", "X-CSRF-Token": csrf},
        cookies=cookies,
    )
    assert resp.status_code == 422
    _cleanup(db_engine, "fake-sub-patch-test")


def test_patch_me_rejects_control_characters(client, db_engine):
    cookies, csrf = _login(client)
    resp = client.patch(
        "/api/me",
        json={"display_name": "Bad\x00Name"},
        headers={"Origin": "http://localhost:8080", "X-CSRF-Token": csrf},
        cookies=cookies,
    )
    assert resp.status_code == 422
    _cleanup(db_engine, "fake-sub-patch-test")


def test_patch_me_requires_csrf_and_uses_the_contract_error_envelope(client, db_engine):
    cookies, _csrf = _login(client)
    resp = client.patch(
        "/api/me",
        json={"display_name": "No token"},
        headers={"Origin": "http://localhost:8080"},
        cookies=cookies,
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "CSRF_INVALID"
    assert "detail" not in resp.json()
    _cleanup(db_engine, "fake-sub-patch-test")


def test_logout_clears_session(client, db_engine):
    cookies, csrf = _login(client)
    resp = client.post(
        "/api/auth/logout",
        headers={"Origin": "http://localhost:8080", "X-CSRF-Token": csrf},
        cookies=cookies,
    )
    assert resp.status_code == 204
    assert any(value.startswith("session=") and "Max-Age=0" in value for value in resp.headers.get_list("set-cookie"))

    # session should now be rejected
    me_resp = client.get("/api/me", cookies=cookies)
    assert me_resp.status_code == 401
    _cleanup(db_engine, "fake-sub-patch-test")


def test_logout_requires_csrf_for_active_session(client, db_engine):
    cookies, _csrf = _login(client)
    resp = client.post(
        "/api/auth/logout",
        headers={"Origin": "http://localhost:8080"},
        cookies=cookies,
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "CSRF_INVALID"
    _cleanup(db_engine, "fake-sub-patch-test")


def test_logout_returns_204_even_with_no_session(client):
    resp = client.post("/api/auth/logout", headers={"Origin": "http://localhost:8080"})
    assert resp.status_code == 204
