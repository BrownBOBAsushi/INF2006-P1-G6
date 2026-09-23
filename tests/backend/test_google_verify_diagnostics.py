"""Safe diagnostics for real Google credential verification failures."""

import logging
import os

import pytest

pytest.importorskip("google.oauth2.id_token")

os.environ.setdefault("APP_ORIGIN", "http://localhost:8080")
os.environ.setdefault("GOOGLE_CLIENT_ID", "diagnostic-test-client")
os.environ.setdefault("APP_SIGNING_KEY", "diagnostic-test-signing-key")

from app.auth import google_verify


@pytest.mark.parametrize("message, expected", [
    ("Wrong audience: token audience does not match", "audience_mismatch"),
    ("Issued-at time is in the future", "issued_in_future"),
    ("Token used too early, 4s before current time", "issued_in_future"),
    ("Token expired", "expired"),
    ("Invalid JWT signature", "signature_invalid"),
    ("Wrong issuer", "issuer_invalid"),
    ("Wrong number of segments in token", "malformed"),
    ("third-party verifier failed", "verification_failed"),
])
def test_value_error_classification_is_allowlisted(message, expected):
    error = ValueError(message)
    assert google_verify._classify_verification_error(error) == expected


def test_verifier_logs_only_safe_code_and_rejects_value_error(monkeypatch, caplog):
    sentinel = "credential-secret-email@example.test"
    forwarded = {}
    monkeypatch.setattr(google_verify.settings, "google_client_id", "diagnostic-test-client")

    def reject(_credential, _request, *, audience, clock_skew_in_seconds):
        forwarded["audience"] = audience
        forwarded["clock_skew_in_seconds"] = clock_skew_in_seconds
        raise ValueError(f"Wrong audience {sentinel}; expected {audience}")

    monkeypatch.setattr(google_verify.id_token, "verify_oauth2_token", reject)
    caplog.set_level(logging.WARNING, logger="app.auth.google_verify")

    with pytest.raises(google_verify.InvalidGoogleCredential) as exc:
        google_verify.verify_google_credential(sentinel)

    assert exc.value.reason == "audience_mismatch"
    assert "google_credential_rejected reason=audience_mismatch" in caplog.text
    assert sentinel not in caplog.text
    assert "diagnostic-test-client" not in caplog.text
    assert forwarded == {"audience": "diagnostic-test-client", "clock_skew_in_seconds": 10}


@pytest.mark.parametrize("claims, expected", [
    ({"iss": "https://evil.example", "sub": "verified-sub"}, "issuer_invalid"),
    ({"iss": "https://accounts.google.com"}, "missing_subject"),
])
def test_explicit_claim_checks_remain_fail_closed_and_safe(monkeypatch, caplog, claims, expected):
    monkeypatch.setattr(google_verify.id_token, "verify_oauth2_token", lambda *_args, **_kwargs: claims)
    caplog.set_level(logging.WARNING, logger="app.auth.google_verify")

    with pytest.raises(google_verify.InvalidGoogleCredential) as exc:
        google_verify.verify_google_credential("credential-token")

    assert exc.value.reason == expected
    assert f"google_credential_rejected reason={expected}" in caplog.text
    assert "credential-token" not in caplog.text


def test_verified_flow_still_returns_only_sub(monkeypatch, caplog):
    monkeypatch.setattr(
        google_verify.id_token,
        "verify_oauth2_token",
        lambda *_args, **_kwargs: {"iss": "https://accounts.google.com", "sub": "verified-sub"},
    )
    caplog.set_level(logging.WARNING, logger="app.auth.google_verify")

    assert google_verify.verify_google_credential("credential-token") == "verified-sub"
    assert "google_credential_rejected" not in caplog.text


def test_google_jwt_time_window_allows_ten_seconds_but_rejects_larger_drift(monkeypatch):
    jwt = pytest.importorskip("google.auth.jwt")
    verify_iat_and_exp = getattr(jwt, "_verify_iat_and_exp", None)
    if verify_iat_and_exp is None:
        pytest.skip("google-auth does not expose its JWT time validator")
    import calendar
    import datetime

    helpers = getattr(jwt, "_helpers", None)
    if helpers is None or not hasattr(helpers, "utcnow"):
        pytest.skip("google-auth does not expose its UTC clock helper")
    fixed_utc = datetime.datetime(2023, 11, 14, 22, 13, 20)
    now = calendar.timegm(fixed_utc.timetuple())
    # google-auth's JWT validator uses a naive UTC datetime internally.
    monkeypatch.setattr(helpers, "utcnow", lambda: fixed_utc)
    valid = {"iat": now + 10, "exp": now + 300}
    too_future = {"iat": now + 11, "exp": now + 300}
    valid_expiry = {"iat": now - 300, "exp": now - 10}
    expired = {"iat": now - 300, "exp": now - 11}
    verify_iat_and_exp(valid, clock_skew_in_seconds=10)
    verify_iat_and_exp(valid_expiry, clock_skew_in_seconds=10)
    with pytest.raises(ValueError):
        verify_iat_and_exp(too_future, clock_skew_in_seconds=10)
    with pytest.raises(ValueError):
        verify_iat_and_exp(expired, clock_skew_in_seconds=10)
