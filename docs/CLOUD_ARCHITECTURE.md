# Cloud architecture discussion log

**Status:** Proposed architecture, recorded 2026-09-26; not deployed or cloud-verified. The service choices and flow below record the team's current planning decisions. Unresolved settings are called out explicitly and must be settled and tested before implementation claims are made.

## Current local baseline and evidence

The latest recorded warm local HTTP benchmark is [run `20260925T212438-27799-d2985816e73a`](../evidence/baseline-2026-09-25-journey-v2/runs/20260925T212438-27799-d2985816e73a/analysis.json). The [earlier v2 methodology report](../evidence/baseline-2026-09-25-journey-v2.md) describes a different run (`20260925T205235-16677-516be94e57f2`), so its numeric results differ. The latest run exercised a single API worker and one process-wide processing slot using synthetic accounts and a small 30-job catalogue:

| Scenario | Result | What it measures |
|---|---|---|
| Sequential, 45 journeys | 45/45 completed; p50 177.7 ms, p95 476 ms | Warm prepare, save, reload, and matches HTTP steps, excluding browser rendering and human review time |
| Burst of 5, 15 journeys | 15/15 eventually completed; p50 6.222 s, p95 12.2567 s; 30 busy responses | Client retries and waits as requests contend with the single processing slot |
| Burst of 10, 30 journeys | 30/30 eventually completed; p50 13.8155 s, p95 27.3844 s; 135 busy responses | Same contention with a larger burst and the benchmark runner's bounded retry policy |
| Browse during bursts | 7,215 requests validated; p95 about 20 ms | `GET /api/jobs` under these local test conditions |
| Memory sample | 678.4 MiB idle; 688.7 MiB simultaneous sampled peak | Sum of API, database, and web container memory at the same sample times |

This is evidence about a warm local setup, not cloud capacity. The benchmark bypassed Google OAuth with synthetic sessions, did not include browser rendering or human review time, and used only 30 jobs. Successful retries demonstrate the runner's retry policy for these runs; they do not prove that the frontend retries correctly or that a cloud service will eventually complete every submission. The largest tested burst was 10 clients. **The selected planning workload is 50 concurrent submissions; it has not been tested.** No cloud latency, availability, or completion target has been selected.

## Proposed AWS architecture

The team has selected a separated application, worker, and database shape for planning. This is a proposed target, not a deployed system. AWS Learner Lab currently permits `us-east-1` and `us-west-2`; `us-east-1` is the planning region for this design, not a statement about an existing deployment.

- **Public web/API:** one EC2 instance in a public subnet runs Nginx and the React frontend, and proxies API requests to FastAPI on the same host. A DuckDNS hostname is the chosen hostname approach. The actual hostname, TLS certificate, and OAuth callback configuration are not set up.
- **Private processing:** one private worker EC2 instance runs two bounded processes: PDF extraction/cleanup and MiniLM CPU embedding. Pin the application and model images in ECR. The worker polls its own SQS queue and reads required input from S3. It does not serve public traffic.
- **Queues:** use separate SQS queues for extraction and embedding, each with its own dead-letter queue and bounded retries. Queue counts, retry limits, visibility timeouts, redrive/DLQ policy, and idempotency keys/retention need exact values before implementation. Repeated delivery must not duplicate a user's accepted operation.
- **Files:** private S3 stores the latest successfully processed PDF for each user. Keep the previous PDF until its replacement has processed successfully. Downloads use short-lived URLs issued only after authenticated ownership checks. Provide explicit file and account deletion. The cleanup interval for failed or abandoned uploads remains to be selected.
- **Database:** private RDS PostgreSQL, Single-AZ, with pgvector planned. The subnet group spans a second Availability Zone for placement coverage; this does not create a standby or high availability. The 2026-09-26 [Learner Lab capability evidence](LEARNER_LAB_CAPABILITIES.md) records PostgreSQL 16 minor versions and burstable classes offered in the console, plus a candidate `db.t3.micro`/20 GiB gp2 configuration. No database was created; exact pgvector compatibility remains unverified.
- **Network and observability:** one NAT gateway is provisional for private worker outbound access; use an S3 gateway endpoint. API instances publish SQS jobs through AWS APIs and do not route through NAT. Workers poll SQS and fetch input from S3; S3 traffic uses the gateway endpoint. CloudWatch logs and metrics are selected, while exact alarms and thresholds remain open.
- **Permissions:** Learner Lab supplies a pre-created `LabRole`. The team cannot claim custom per-component least-privilege IAM roles under that constraint. Specific role permissions and security-group rules still need to be recorded and checked. Enhanced Monitoring is unsupported in this lab; standard available monitoring can be used.

The [editable Mermaid source](diagrams/cloud-architecture.md) contains the logical workflow and network topology. The existing [`cloud-architecture-draft.png`](diagrams/cloud-architecture-draft.png) is an inaccurate draft and is superseded by that source; it is retained for history and is not the canonical architecture diagram.

## User and processing flow

1. The authenticated browser submits a PDF to the API. The API validates ownership and input, stores the upload in private S3, records durable task state, publishes an extraction message to SQS, then returns `202 Accepted` with a task identifier. The exact publication/database consistency mechanism is still to be chosen; the API must not claim durable acceptance before both task state and work publication are safely recoverable.
2. The browser polls the authenticated API for task status. It can continue browsing while extraction runs. Polling returns `202` while the accepted task remains pending; task lookup is scoped to the authenticated owner.
3. The extraction process consumes the extraction queue, reads the PDF from S3, and writes a reviewable draft and terminal extraction status to PostgreSQL. Extraction failure is visible in task status and follows the bounded retry/DLQ policy.
4. The user reviews and edits the draft in the browser. Human review is an explicit boundary. No embedding job is published until the user explicitly saves the reviewed profile.
5. On save, the API records the accepted save/revision idempotently and publishes an embedding job. The embedding process creates CPU MiniLM vectors and persists the approved profile and vectors to PostgreSQL/pgvector. A retry must not overwrite a newer revision or duplicate the logical save. Matches use the successfully persisted profile.
6. Only after a replacement PDF has processed successfully does it become the user's latest PDF; the former PDF can then be removed. Explicit user/account deletion removes the associated stored file. The retention period for failed and abandoned submissions remains open.

The logical task flow, database publication consistency, queue parameters, cleanup interval, and concurrency sizing need implementation and resilience tests. A ten-minute recording is an assumption about recording duration, not total provisioning or billing time. Clarification from the professor about required environment uptime is pending.

## Unresolved sizing and operational settings

The design has not selected instance sizes, worker concurrency, request/processing latency targets, retention periods, queue retry counts, SQS visibility timeouts, DLQ redrive settings, API polling interval, or CloudWatch alarms. TLS termination details, OAuth callback values, IAM permissions within `LabRole`, security-group specifics, backup/recovery objectives, and infrastructure-as-code tooling also remain unresolved. Do not infer these values from the 50-submission planning workload or from the local benchmark.

The project checklist remains the place to track cloud implementation and acceptance evidence. Cloud deployment, cloud storage, security validation, and resilience results remain open until supported by dated evidence. The project manifest must continue to distinguish proposed architecture from deployed resources.

## Course and evidence boundaries

The user reports that the professor emphasized that infrastructure quantity does not itself earn marks; the team should justify the choices. Treat that as reported guidance, not a verified written rule. The repository's `project_manifest.yaml` is a required submission artifact and must keep claims and paths aligned with evidence. An AI-use declaration is required. The user reports that an AI notebook is allowed and that a cloud-hosted model is not mandated; the [requirements checklist](REQUIREMENTS_CHECKLIST.md) also records local/reproducible inference as acceptable and does not require a hosted LLM.

Do not claim the design guarantees an official grade. Do not state that 50 concurrent submissions passed. The manifest, checklist, report, diagram, and deployment evidence must distinguish local measurements, selected planning decisions, and future cloud tests.

## Related project documents

- [Requirements checklist](REQUIREMENTS_CHECKLIST.md) — literal brief requirements and current evidence status.
- [Existing local architecture rationale](handoff/ARCHITECTURE.md) — current local design and trade-offs; it is not this proposed AWS deployment.
- [Existing data and API contract](handoff/DATA_API_CONTRACT.md) — current local request, save, idempotency, and busy-response behavior.
- [Earlier v2 benchmark report](../evidence/baseline-2026-09-25-journey-v2.md) — methodology and limitations; its results are from the earlier run. The latest numeric source is the `analysis.json` linked above.
