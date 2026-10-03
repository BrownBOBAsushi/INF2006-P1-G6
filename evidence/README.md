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
| [local-tests-2026-10-03.md](local-tests-2026-10-03.md) | [Local run] Backend, frontend, infrastructure, analytics and pipeline suites, with raw logs in `local-tests-2026-10-03/` |
| [cloud-foundation-run-2026-09-27.md](cloud-foundation-run-2026-09-27.md) | [Operator-reported] Earlier single-instance foundation deployment (since torn down), including the first alarm/recovery test |
| `data-ai-eval-*.md/json`, `test-processing-*.md`, `load-*.md/json` | Component-level evaluation and local load measurements |
| `baseline-2026-09-25-*` | Local end-to-end baselines before cloud deployment |
| [architecture-local-baseline.svg](architecture-local-baseline.svg) | Earlier local Docker Compose design (historical) |

`baseline-2026-09-25-fullapp/sessions.json` contains local test-session tokens and must not be packaged.
