# Negative TLS test of the public API endpoint (T-transport)

**Date (UTC):** 2026-10-03 ~15:30. **Target:** public API Gateway HTTP API `https://<api-id>.execute-api.us-east-1.amazonaws.com` (id redacted).
**Tools:** OpenSSL 3.6.4 `s_client`; curl 8.7.1 (LibreSSL 3.3.6) on the operator's macOS workstation. Read-only; no credentials, no state change.
**Scope:** browser-to-API-Gateway link only. The Gateway-to-ALB link, and the ALB-to-target link (encryption without certificate validation), are not tested here.

| # | Test | Command (host redacted) | Expected | Actual | Result |
|---|---|---|---|---|---|
| 1 | Plain HTTP is not served | `curl http://<host>/api/me` | no HTTP listener | `curl: (7) Failed to connect ... port 80` | PASS |
| 2 | TLS 1.2 accepted, certificate verifies for hostname | `openssl s_client -connect <host>:443 -servername <host> -tls1_2 -verify_hostname <host>` | handshake OK, verify 0 | TLSv1.2 ECDHE-RSA-AES128-GCM-SHA256, `Verify return code: 0 (ok)` | PASS |
| 3 | TLS 1.3 accepted | `... -tls1_3` | handshake OK | TLSv1.3 TLS_AES_128_GCM_SHA256, verify 0 | PASS |
| 4 | TLS 1.1 refused by the server | `curl --tlsv1.1 --tls-max 1.1 https://<host>/` | handshake refused | `tlsv1 alert protocol version` (server alert) | PASS |
| 5 | TLS 1.0 refused by the server | `curl --tlsv1.0 --tls-max 1.0 https://<host>/` | handshake refused | `tlsv1 alert protocol version` (server alert) | PASS |
| 6 | Hostname mismatch is detected | `openssl s_client ... -verify_hostname wrong.example.com` | verification fails | `Verify return code: 62 (hostname mismatch)` | PASS |

Notes: OpenSSL 3.6.4 on the workstation was built without TLS 1.0/1.1 (`no protocols available`), so its 1.0/1.1 attempts
are not evidence; the curl runs (#4, #5) used a different TLS library and both received a server protocol-version alert. API Gateway terminates TLS with
an AWS-managed policy; the team does not configure cipher suites.

## Finding: the public endpoint returned 502 during this test

At ~15:33 UTC `GET /health/ready`, `/api/me` and `/` all returned **HTTP 502** with `server: awselb/2.0` (the internal ALB's
error page). The TLS layer worked, so the Gateway is up but the ALB has no healthy target, consistent with stopped,
unhealthy or deregistered app instances. This test did not diagnose the cause (no AWS credentials were available); see the
follow-up record. Response security headers (HSTS, CSP) remain unset, as already listed in the limitations.
