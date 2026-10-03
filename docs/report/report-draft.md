# Internship Matcher: A Secure, Scalable, Data-Driven Internship Recommendation Service on AWS

INF2006 Cloud Computing & Big Data — Team Project 1 — Group P1-G5 — Jiaxin · Chuying · Xue E · Nasya · Zhihao

## 1. Problem, users and success criteria

**Problem.** Students searching for internships face long, inconsistent listings. Keyword search only finds exact
words, so a student who writes "built REST services in Flask" is not matched to a listing asking for "backend API
development in Python". Students therefore either read every listing or miss relevant ones. A useful tool must also
handle résumés carefully, because they contain names, phone numbers, addresses and identity numbers.

**Users.** The primary users are university students looking for internships in Singapore. The secondary user is the
team acting as operator, who imports the job catalogue and runs the service.

**Workflow supported.** A student signs in with Google, browses and searches the internship catalogue, and may
upload a résumé PDF. The service extracts the text, removes personal data, and shows an editable draft. Only after the
student approves the draft is it embedded and used for matching. The student then sees internships ranked by how well
their approved experience covers each job's required skills, with the supporting résumé passage shown for every
requirement, and can apply on the original site.

**Success criteria** (from the MVP requirements, `docs/handoff/MVP_PRD.md`):

| Area | Criterion | Evidence |
|---|---|---|
| Workflow | Sign-in, upload, review, save, match, search and refresh work on the deployed service | `evidence/test-functional.md` F1 |
| Validation | Oversized, missing, scanned, encrypted or over-length PDFs are rejected clearly without altering saved data | F2, pipeline tests |
| Privacy | Names, emails, phones, addresses, NRIC/FIN IDs and URLs are removed before review; only approved text is embedded | `evidence/threat-control-map.md` T7 |
| Matching quality | Requirement-level ranking performs at least as well as a keyword baseline on held-out data | `evidence/test-data-ai.md` |
| Resilience | Loss of a web/API instance is detected and recovered without losing saved data | `evidence/test-resilience.md` |
| Security | Unauthenticated, cross-site and direct-network access is refused | `evidence/test-security.md` |
| Cost | Runs within a 50 USD Learner Lab allowance per member | Section 7 |

## 2. Solution overview and architecture

Figure 1 (`evidence/architecture.png`) shows the deployed architecture. Labels are the CloudFormation logical IDs
in `src/infra/cloudformation/`, and the deployed state was captured read-only on 3 October 2026
(`evidence/cloud-capture-2026-10-03/`).

[Figure 1: evidence/architecture.png — Deployed AWS architecture]

**Components.**

- **Entry point.** An API Gateway HTTP API (`HttpApi`) is the only Internet-facing component. Its single `$default`
  route forwards every request through a VPC Link to an internal Application Load Balancer, so the browser loads
  the React single-page app and calls `/api` on one HTTPS origin.
- **Web/API tier.** Two `t3.small` EC2 instances in an Auto Scaling group (`AppAutoScalingGroup`) in private subnets
  in two Availability Zones. Each runs two containers: Nginx (serves the SPA, terminates TLS on port 8443, enforces a
  6 MiB body limit, writes a sanitised access log) and FastAPI (Google sign-in, sessions, CSRF checks, validation,
  matching, and an outbox publisher).
- **Worker.** One `t3.medium` instance runs the extraction service (pdfplumber + Microsoft Presidio redaction) and the
  embedding service (sentence-transformers `all-MiniLM-L6-v2`). It has no inbound network rules and pulls work
  from SQS.
- **Data.** Amazon RDS for PostgreSQL 16 with the pgvector extension stores users, sessions, résumé profiles and
  chunks, jobs, requirement embeddings, processing tasks and the transactional outbox. A private S3 bucket holds
  uploaded PDFs for at most one day.
- **Messaging.** Two SQS queues (extraction, embedding), each with a dead-letter queue.
- **Supporting services.** Secrets Manager (database credentials, session signing key), ECR (container images pulled
  by digest), CloudWatch (logs, alarms, Logs Insights), Systems Manager Session Manager (administration without SSH)
  and two NAT gateways for outbound access from private subnets.

**Main data flow.** (1) The browser sends an upload to the API, which stores the PDF in S3 through a gateway VPC
endpoint and, in one database transaction, records a processing task and an outbox row, then returns HTTP 202.
(2) The outbox publisher sends the task to the extraction queue. (3) The worker reads the PDF, extracts and redacts
text, writes the draft to the database and deletes the PDF. (4) The browser polls the task and shows the draft. (5) On
save, the API stores the approved content and queues an embedding task; the worker writes requirement-matching
vectors. (6) `GET /api/matches` ranks jobs in PostgreSQL using those vectors.

**Trust boundaries.** The Internet is untrusted. Only `HttpApi` accepts inbound traffic; the ALB is internal and
accepts only the VPC Link security group; app instances accept port 8443 only from the ALB; the worker and the
database accept nothing from the Internet, and the database accepts port 5432 only from the app and worker
security groups. The database subnets have no route to the Internet.

## 3. Cloud service/deployment choices and trade-offs

**Service model.** We chose IaaS compute with managed PaaS services around it. The team manages the EC2 guest
operating system, Docker runtime, Nginx and FastAPI; AWS manages the database engine (RDS, a DBaaS), queues (SQS),
object storage (S3), the API front door (API Gateway), load balancing (ALB) and secrets. Google Identity Services is an
external SaaS identity provider. The IaaS/PaaS boundary therefore sits at the VM: everything inside the instances is
ours to patch and configure, and everything outside is a managed service with an SLA.

**Deployment model.** Public cloud, single AWS region (us-east-1, required by the Learner Lab), two Availability Zones
for the web/API tier, deployed as three CloudFormation stacks (`inf2006-private-base-retry1`,
`inf2006-private-ingress`, `inf2006-private-app`). Local Docker Compose reproduces the same application without AWS,
so markers can run it offline.

**Why EC2 rather than a more managed compute service.** The extraction and embedding steps load spaCy, Presidio and
a PyTorch model of several hundred megabytes and run a sandboxed child process with a 60-second deadline. That fits a
long-running VM with predictable memory. It does not fit short-lived functions, and the Learner Lab forbids the custom
IAM roles that many managed container setups expect.

**Alternatives considered.**

| Alternative | Benefit | Why not selected |
|---|---|---|
| A. One VM running web, API and PostgreSQL | Cheapest; simplest network | Database on the public host; no isolation, backup or recovery separation; one failure takes everything down. Our first foundation (27 Sept) already moved the database to RDS. |
| B. One public EC2 host plus private RDS (our 27 Sept foundation) | Simple; deployed and tested | Single web/API host with a public IP; PDF processing ran on the API host with one processing slot, so a second upload got a busy response and a host failure meant an outage. Replaced by the current design. |
| C. AWS Lambda functions + DynamoDB | Pay per request; no servers | Model loading and PDF processing exceed comfortable function limits; vector search would need another service; rewriting the data layer for DynamoDB removes pgvector ranking. |
| D. Container service (ECS/Fargate) with RDS | Less host management | Feasible, but the Learner Lab IAM constraints and time budget favoured the EC2 model the team already ran; would be the next step. |
| E. Cognito instead of Google sign-in | AWS-native identity | Students already have Google accounts; the server verifies Google ID tokens directly. Deferred. |
| F. PostgreSQL table as the job queue instead of SQS | No extra service | SQS gives managed dead-letter queues and backlog/age metrics for alarms; the PostgreSQL-backed queue is kept for local runs. |

**Main trade-offs accepted.** Two NAT gateways cost about a third of the hourly bill but keep each AZ's outbound path
independent; a single NAT gateway or interface endpoints would be cheaper. RDS is Single-AZ: a Multi-AZ standby would
roughly double database cost, which the budget does not justify for a demonstration. API Gateway in front of an
internal ALB adds a hop and a 30-second integration timeout, but removes every public IP and gives us an HTTPS origin
without managing a public certificate on the browser side.

**Assumptions and expected workload.** Demonstration scale: tens of students, a catalogue of a few hundred listings
(247 deployed), and occasional bursts of uploads (planning figure: 50 uploads queued). Browsing and matching are
cheap database queries; uploads are expensive and are therefore made asynchronous so a burst becomes a queue
backlog rather than failed requests. All data used in testing is synthetic or public job listings; no real student
résumés were used.

## 4. Implementation, data design and security controls

**Application.** The backend is FastAPI with SQLAlchemy and Alembic migrations (`src/backend/`); the frontend is React
19 and TypeScript built with Vite (`src/frontend/`). Uploads return 202 and the browser polls a task resource. Saves
carry the current revision and an idempotency key, so retries after a network failure apply once and a stale tab cannot
overwrite newer work (HTTP 409). The task and its outbox message are written in the same transaction as the business
change, so a crash cannot lose a queued task or send one for data that was never saved; workers hold fenced leases so a
slow worker cannot overwrite a newer result.

**Data design.** Eleven PostgreSQL tables are defined by migrations: `users`, `sessions`, `resume_profiles`,
`resume_chunks`, `save_operations`, `jobs`, `job_requirements`, `requirement_embeddings`, `app_state`,
`processing_tasks` and `processing_outbox`. Each job requirement is stored separately with its source quote and any
"OR" alternatives, and each requirement and alternative has a 384-dimension vector. Résumé chunks are stored with their
vectors and a model version. The catalogue import (`app.catalogue.import_jobs`) validates the entire batch, is
idempotent (a repeat import of the 247 jobs reported zero changes and zero recomputed embeddings) and reuses vectors for
unchanged text. Field definitions are in `data/DATA_DICTIONARY.md`.

**Input validation.** Limits are enforced in layers: Nginx rejects bodies over 6 MiB; the API limits multipart bodies to
6 MiB and JSON to 256 KiB; PDFs must be at most 5 MiB and 10 pages and must contain extractable text, so encrypted,
scanned and non-PDF files are rejected with specific error codes.

**Security controls** (full mapping in `evidence/threat-control-map.md`, 13 threats):

- *Authentication:* Google ID tokens are verified server-side (signature, issuer, audience, expiry) with a one-time
  nonce; the server then issues its own database-backed session in an `HttpOnly`, `Secure`, `SameSite=Lax` cookie.
  Only a SHA-256 hash of the session token is stored, and sessions expire after 30 minutes idle or 8 hours absolute.
- *Authorisation:* the user is always taken from the session; no route accepts a user ID, so one student cannot name
  another student's data.
- *CSRF:* every state-changing request must come from the allowed Origin and carry the session-bound CSRF token.
- *Network restriction:* as described under trust boundaries; no instance has a public IP; IMDSv2 is required.
- *Secrets:* stored in Secrets Manager, read at boot into root-only (0600) environment files, never in images,
  templates, logs or the repository.
- *Data protection:* RDS, S3 and SQS are encrypted at rest; every network hop uses TLS; S3 blocks public access, enforces
  TLS and expires objects after one day.
- *Least privilege:* the Learner Lab does not allow custom IAM roles, so all instances use the lab's `LabRole`. We
  compensated with network isolation and with two restricted PostgreSQL roles (migrator and runtime) that cannot create
  databases or roles or bypass row security. This is a genuine limitation, not a solved problem.

## 5. Analytics or AI/ML feature: data, method, evaluation and limitations

**Purpose.** The data-driven feature is the recommender: it decides which internships a student sees first and explains
why, which is the core decision in the workflow.

**Data.** Two datasets are used. (1) A synthetic evaluation set (`data/evaluation/`): 30 internship listings with
hand-written requirements, 10 synthetic résumé profiles split into 5 development and 5 held-out, and 300 relevance
labels on a 0/1/2 scale defined in `LABELLING_CRITERIA.md`. 90 labels (three held-out profiles) were supplied by a team
member; the other 210 were drafted by an AI assistant from the written criteria before any model output existed.
(2) The deployed catalogue of 247 real Singapore internship listings collected on 1 October 2026 (78 via the JSearch
API, 169 from LinkedIn via an Apify scraper), reviewed record by record with reasons for every exclusion. Because
redistribution rights are not established, this catalogue is not in the submission; all reproducible results use the
synthetic set.

**Preprocessing.** Résumés: text and layout extracted with pdfplumber, sections detected from headings and fonts, PII
replaced with placeholders, then split into chunks within the model's token limit (the largest chunk was 108 of 240
allowed tokens; nothing was truncated). Jobs: each required skill becomes its own requirement row, quoted from the
original description.

**Method.** Each requirement (and each "OR" alternative) and each résumé chunk is embedded with
`all-MiniLM-L6-v2` at a pinned revision. A requirement's score is its best cosine similarity to any résumé chunk;
a job's score is the mean over its required requirements, so a job scores highly only if most of its requirements are
covered. Preferred skills and eligibility notes are shown but do not change ranking. The output is interpretable: for
every requirement the student sees the closest résumé passage, and scores are presented as similarities, not as
chances of being hired.

**Evaluation.** Precision@5 (strict counts only label 2; lenient counts labels 1–2) and NDCG@5 on the held-out
profiles, compared with three baselines.

| Method (held-out, MiniLM) | P@5 strict | P@5 lenient | NDCG@5 |
|---|---|---|---|
| Requirement-level (deployed method) | 0.640 | 0.760 | 0.922 |
| Keyword / BM25 baseline | 0.640 | 0.720 | 0.910 |
| Pooled résumé embedding | 0.560 | 0.640 | 0.771 |
| Whole-résumé single vector (truncated) | 0.560 | 0.680 | 0.808 |

The best achievable strict P@5 on this set is 0.680. The requirement-level method matches BM25 on strict precision and
is slightly better on lenient precision and NDCG; both clearly beat embedding the whole résumé as one vector. Mean scores
rise with label (held-out: 0.212 for irrelevant, 0.291 partial, 0.420 relevant), so the scores carry signal. A second
model (`bge-small-en-v1.5`) gave similar results and was not adopted. The evaluation was reproduced on 3 October on a
different operating system and CPU with identical numbers.

**Limitations and responsible use.** The evaluation is small (5 held-out profiles, no confidence intervals), synthetic
text is cleaner than real résumés, most labels are AI-drafted, and quality on the real catalogue was not measured
because it has no labels. The advantage over BM25 is therefore not statistically established; the main benefit we can
claim is explainable, requirement-by-requirement matching with comparable precision. PII detection makes mistakes in
both directions; in testing "Cloud Computing" was wrongly removed as a person's name, which is why the student reviews
the draft before anything is stored or embedded. The model is English-only and could disadvantage students who
describe skills in unusual wording; ranking explains rather than decides, and the student always sees every listing.

## 6. Testing, scalability/resilience and monitoring results

Four required tests were run, each recorded with objective, steps, expected and actual results, date and artefacts.

| Test | Result | Record |
|---|---|---|
| Functional workflow | PASS: full journey on AWS — sign-in, upload, review, save (first save 12.58 s on a cold privacy check; later saves 0.5–0.65 s), 247 ranked matches, search, refresh, offline retry with exactly one revision increment. Validation: 413 for oversized requests and PDFs, 415 for missing file, saved data unchanged. | `evidence/test-functional.md` |
| Security | PASS: without a session, `/api/me`, `/api/resume`, `/api/matches` and uploads returned 401; cross-site and missing-Origin state changes returned 403 `CSRF_INVALID`; captured configuration shows no public IPs, an internal ALB and database access only from app/worker security groups. 133 backend tests (including CSRF, Google-token and ownership tests) passed. | `evidence/test-security.md` |
| Data/AI | PASS: metrics above, reproduced exactly on a second machine. | `evidence/test-data-ai.md` |
| Resilience | PASS: two real failures recovered automatically (below); a controlled withdrawal of one load-balancer target kept the service and session available. | `evidence/test-resilience.md` |

**Resilience mechanisms and observed results.** The web/API tier runs two instances behind the load balancer, with
ELB health checks on `/health/ready` (which queries the database) and Auto Scaling keeping two in service. Uploads are
queued in SQS, so a burst or a worker outage delays work instead of losing it; messages failing five times move to a
dead-letter queue. On 3 October the Auto Scaling activity history recorded two unplanned events:

- *02:42 UTC:* one instance failed the health check shortly after deployment; Auto Scaling terminated it and launched a
  replacement within seconds, with no operator action.
- *05:23–05:31 UTC:* a Learner Lab session restart stopped both instances. Auto Scaling detected this through EC2
  health checks; launches failed while the lab was unavailable, then two replacements started at 05:28:43. The
  in-service alarm entered ALARM at 05:25:59 and cleared at 05:30:59, about seven minutes from the first stop. The
  service had a full outage during this window — two instances protect against one instance or one zone failing, not
  against both being stopped.

**Monitoring.** All container logs go to CloudWatch Logs with 30-day retention; Nginx logs omit query strings, cookies
and headers. A Logs Insights query over 24 hours (`evidence/monitoring.md`) found 2,269 requests: 90% were load-balancer
health checks and the rest matched the acceptance session. Every 4xx response was explained by a deliberate test or an
expected state, and there were no 5xx responses. Five alarms watch in-service instance count, queue message age and
dead-letter queues.

**Failed tests and improvements.** Four local pipeline tests fail because they still create the processing service
without the worker type added during the asynchronous redesign; the production code passes it correctly. A stale local
test image initially broke the backend suite until rebuilt. Not tested: database restore, cloud load testing, alarm
notifications (no SNS action is configured) and the queue alarms firing. Planned improvements: fix the stale tests, add
SNS notifications, run a restore drill, put the worker in its own Auto Scaling group scaled on queue age, and add
security headers.

## 7. Cost, sustainability and operational considerations

**Cost.** Cost Explorer reports zero in the Learner Lab, so we estimated cost from the captured inventory and
on-demand list prices (`evidence/cloud-capture-2026-10-03/10-resource-inventory-and-cost.txt`):

| Item | USD/hour |
|---|---|
| 2 × t3.small web/API | 0.042 |
| 1 × t3.medium worker | 0.042 |
| 2 × NAT gateway | 0.090 |
| RDS db.t3.micro Single-AZ | 0.018 |
| Internal ALB | 0.023 |
| Public IPv4 addresses (5) | 0.025 |
| Storage, secrets, registry, queues, logs | ~0.017 |
| **Total while running** | **~0.26 (≈ 6.2/day)** |

At this rate a 50 USD allowance lasts about eight days of continuous running. Cost controls used: smallest instance
classes that fit the models, Single-AZ RDS with 20 GiB storage, a one-day S3 lifecycle, 30-day log retention, an S3
gateway endpoint (free) instead of NAT for S3 traffic, and CloudFormation so the stack can be deleted and recreated.
The largest saving available is replacing two NAT gateways with one (about 0.045/hour) at the cost of zone
independence. Ending a lab session stops EC2 but not NAT gateways, the load balancer or Elastic IPs, so stacks must be
deleted, not just paused. A post-deployment inventory found leftovers from failed attempts — three unused Elastic IPs,
one RDS snapshot and one rolled-back stack — that should be removed.

**Sustainability.** Embeddings are computed once per job requirement and reused across imports and students
(re-importing 247 jobs recomputed zero embeddings); the model is small and CPU-only, so no GPU is needed; the worker
processes one task at a time instead of keeping idle capacity; and temporary files expire automatically.

**Operations.** Deployment is scripted (`docs/PRIVATE_CLOUD_ROLLOUT.md`) with images pinned by digest. Administration
uses Session Manager without SSH keys. The TLS certificate for the internal listener comes from Let's Encrypt via DNS
validation and renews on a timer; a complete renewal cycle has not yet been observed. One reproducibility gap remains:
a renewal-hook fix was applied directly to the running worker and is committed to the repository, but the published
images predate it.

## 8. Team contribution, ethical considerations and reflection

**Contributions.** Jiaxin built authentication, sessions, the data model and migrations; Chuying built PDF extraction,
privacy redaction, embeddings, matching and the evaluation, and supplied 90 relevance labels; Xue E built the catalogue,
search and job-details frontend; Nasya built the résumé upload, review and recommendation screens and their tests;
Zhihao led system design, integration, cloud deployment and evidence. Commit-level detail is in
`TEAM_CONTRIBUTIONS.md`.

**Use of AI tools.** OpenAI Codex and Anthropic Claude assisted with code, infrastructure templates, the evaluation
harness, synthetic fixtures and documentation, as declared in `AI_USE_DECLARATION.md`. AI output was accepted only after
tests, source review or captured command output confirmed it; AI-drafted evaluation labels are reported as such rather
than as human ground truth.

**Ethical considerations.** Résumés are sensitive, so the design minimises what is kept: the PDF is deleted after
extraction, personal identifiers are removed before the student sees the draft, and only content the student approves
is stored and embedded. Recommendations show their evidence and make no claim about hiring likelihood. Job listings
were collected from public sources for a coursework demonstration and are not redistributed; scraping terms of service
are a real concern, and a production service would use a licensed feed.

**Reflection.** *[TEAM INPUT: each member adds 2–4 sentences on what they learned and what they would do differently.]*
As a team, the most valuable change was moving from one public server with synchronous, one-at-a-time processing to
a private, queue-based design, so that uploads queue instead of being refused and no server is directly exposed. The hardest part was
not building features but producing evidence a marker can verify without our AWS account. With more time we would
replace the NAT gateways with VPC endpoints, add a database restore drill and gather real labelled data to test whether
semantic matching beats keyword search on real résumés.

## References

- AWS Documentation: Amazon API Gateway HTTP API private integrations; Elastic Load Balancing; Amazon EC2 Auto Scaling
  health checks; Amazon RDS for PostgreSQL extensions (pgvector); Amazon SQS dead-letter queues.
- Reimers, N. & Gurevych, I. (2019). Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks. EMNLP.
- `sentence-transformers/all-MiniLM-L6-v2` model card (Apache-2.0). Microsoft Presidio (MIT). pdfplumber (MIT). pgvector (PostgreSQL licence).
- Järvelin, K. & Kekäläinen, J. (2002). Cumulated gain-based evaluation of IR techniques. ACM TOIS 20(4).

## Appendix: evidence index

All paths are relative to the submission root and listed in `project_manifest.yaml`; `evidence/README.md` indexes every
artefact.
