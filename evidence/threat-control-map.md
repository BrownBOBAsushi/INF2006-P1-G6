# Threat-control map

Status: PLANNED, controls not implemented/verified.

| Threat | Planned control | Verification |
|---|---|---|
| Cross-account access | Session-derived owner; scoped queries | Two-user isolation tests |
| Forged login | Google signature, issuer, audience and expiry validation | Invalid-token tests |
| CSRF | Session-bound CSRF plus allowed Origin | Missing/wrong token and Origin tests |
| Malicious/oversized PDF | File/page/body/time bounds; restricted child | Synthetic bad-file tests |
| Sensitive data disclosure | Cleanup/review; no raw logs/persistent PDF | PII/log fixtures |
| Resource exhaustion | One admitted expensive task; controlled busy | Concurrent submissions and recovery |
| Lost/duplicate update | Revision lock and durable idempotency | Lost-response and stale-tab tests |
| Database loss | Restricted off-VM backups and tested restore | Restore into disposable separate DB |
