# Evidence index

Provenance labels used across these records: **[Captured]** read-only command output saved as text at the time
shown; **[Observed]** directly observed in a browser by an AI agent operating the app; **[Operator-reported]**
results reported by the team member operating AWS and transcribed into the record; **[Local run]** automated test
output from a local machine. Account IDs, resource IDs, IPs, hostnames, cookies and secret values are redacted.

## Brief-required records (project_manifest.yaml `evidence:`)

| Brief requirement | File |
|---|---|
| Functional workflow test | [test-functional.md](test-functional.md) |
| Security control test (named threats) | [test-security.md](test-security.md) |
| Data/AI validation test | [test-data-ai.md](test-data-ai.md) |
| Scalability/resilience/recovery test | [test-resilience.md](test-resilience.md) |
| Logging/monitoring and operational query/alert | [monitoring.md](monitoring.md) |
| Threat-control mapping | [threat-control-map.md](threat-control-map.md) |
| Architecture diagram | [architecture.png](architecture.png) (source [architecture.svg](architecture.svg)) |

## Supporting evidence

| File | What it is |
|---|---|
| [cloud-capture-2026-10-03/](cloud-capture-2026-10-03/) | [Captured] Deployed configuration: stacks, ingress, compute, security groups, data stores, secrets metadata, alarms, Logs Insights queries, public probes, resource inventory and cost estimate |
| [cloud-acceptance-2026-10-03.md](cloud-acceptance-2026-10-03.md) | [Observed]/[Operator-reported] Deployment and acceptance observations for the current private architecture |
| [test-security-live-local-2026-10-03.md](test-security-live-local-2026-10-03.md) | [Local run] Live HTTP ownership, session and CSRF checks with two synthetic users (29/29); script `tests/security/live_security_check.py` |
| [test-security-live-cloud-real-task.md](test-security-live-cloud-real-task.md) | [Cloud] Ownership, session and CSRF checks on the deployed site with two real accounts (26/26; script `tests/security/live_site_check.py`, operator-run) |
| [test-security-tls-2026-10-03.md](test-security-tls-2026-10-03.md) | [Cloud, read-only] Negative TLS tests of the public endpoint, plus the 502 observation |
| [recovery-test-2026-10-03/](recovery-test-2026-10-03/) | [Cloud] Raw monitor logs of the controlled instance-termination test (instance IDs redacted); write-up is R4 in `test-resilience.md` |
| [local-tests-2026-10-03.md](local-tests-2026-10-03.md) | [Local run] Backend, frontend, infrastructure, analytics and pipeline suites, with raw logs in `local-tests-2026-10-03/` |
| [cloud-foundation-run-2026-09-27.md](cloud-foundation-run-2026-09-27.md) | [Operator-reported] Earlier single-instance foundation deployment (since torn down), including the first alarm/recovery test |
| `data-ai-eval-*.md/json`, `test-processing-*.md`, `load-*.md/json` | Component-level evaluation and local load measurements |
| `baseline-2026-09-25-*` | Local end-to-end baselines before cloud deployment |
| [architecture-local-baseline.svg](architecture-local-baseline.svg) | Earlier local Docker Compose design (historical) |

`baseline-2026-09-25-fullapp/sessions.json` contains local test-session tokens and must not be packaged.
