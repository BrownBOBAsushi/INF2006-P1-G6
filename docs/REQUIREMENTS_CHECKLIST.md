# INF2006 project brief requirements checklist

**Working date:** 2026-10-03
**Scope:** Project brief Sections 1–10 and Appendix A. Section 11 is non-mandatory suggested planning guidance and is intentionally omitted from this tracker.

**Source:** local `INF2006_Team_Project_Brief_2026.pdf` (Sections 1–10 and Appendix A), in `~/SIT/Y2/T1/INF2006-Cloud Computing/Project/`.

**Submission:** `Group_Gxxx_INF2006_Project.zip`, due Sunday 11 October 2026 at 11:59 PM (end of Week 6). The brief does not state a timezone; confirm the LMS timezone before upload. Keep `Gxxx` until the official group ID is confirmed.

## How to read this file

- A checked box means repository evidence has been recorded; it does **not** mean a fresh command was run for this checklist.
- `[Implemented locally]` means code or local behaviour is present; `[Evidence recorded]` means a dated or explicit repository record exists.
- `[Proposed]` is a target design/team action, not a completion claim; `[Open]` is unresolved or still needs evidence.
- Existing `[x]` marks in Sections 1–4 are a 2026-09-23 recorded snapshot, not a fresh rerun or final acceptance. For new work, leave `[ ]` until the current evidence has been reviewed; only then change it to `[x]`.

Current boundary (2026-10-03): the operator reports that the separate private target has been deployed: the base retry reached `UPDATE_COMPLETE`, and ingress and app reached `CREATE_COMPLETE`. Partial worker, certificate, catalogue, queue, monitoring, and controlled target-continuity results in the [2026-10-03 cloud acceptance record](../evidence/cloud-acceptance-2026-10-03.md) are operator-reported. That record also contains direct CUA browser observations of matching, save/retry, refresh, and extraction behavior; cookie/CSRF details remain operator-reported. The documentation update did not query AWS or repeat the operator's CLI checks. The combined evidence does not close the brief's functional, security, resilience, or operations acceptance requirements. The older temporary synchronous foundation and its user-reported teardown remain recorded in the [2026-09-27 run record](../evidence/cloud-foundation-run-2026-09-27.md) and [preparation evidence](../evidence/cloud-foundation-preparation-2026-09-27.md). The manifest still says `tests_executed: false` for overall application acceptance. Coursework decision owners and the S5.1 architecture gate remain open. The 2026-09-23 journey is useful local evidence but does not replace full cloud acceptance evidence. Submission data must contain no real user/resume data beyond the expressly required team names and student IDs in team metadata.

## Section 1 — problem and solution fit

- [x] `[Evidence recorded]` Focused problem: students need to browse internships and find relevant opportunities using approved resume content and requirement-level similarity. See [README](../README.md) and [manifest](../project_manifest.yaml).
- [x] `[Evidence recorded]` Supporting features are sign-in, catalogue search/filtering, resume review/save/delete, and requirement-level recommendations, listed in the [MVP PRD](handoff/MVP_PRD.md).
- [x] `[Implemented locally]` The journey records search, filtering, resume persistence, and matching behaviour: [2026-09-23 verification](verification/2026-09-23-user-journey.md).
- [ ] `[Open]` Turn the problem-to-feature relationship into the final brief narrative while keeping local/cloud claims separate.
Example application domains are illustrative only and are not a compulsory requirement; add them only if useful to the final narrative.

## Section 2 — outcomes, choices, and responsible delivery

- [x] `[Evidence recorded]` Intended outcomes and local architecture/trade-offs are in [historical local architecture](handoff/ARCHITECTURE.md); proposed cloud service choices are in [cloud architecture](CLOUD_ARCHITECTURE.md).
- [x] `[Evidence recorded]` Current local stack: React/TypeScript, FastAPI/Python, PostgreSQL/pgvector, Docker Compose, PDF privacy cleanup, and MiniLM. See [README](../README.md).
- [ ] `[Operator-reported deployment; partial acceptance 2026-10-03]` Current target: public API Gateway HTTP API and VPC Link to an internal HTTPS ALB, private API Auto Scaling Group, separate private worker, private Single-AZ RDS PostgreSQL/pgvector, temporary-processing-input-only S3, separate SQS extraction/embedding queues and DLQs, ECR, Secrets Manager, Systems Manager and CloudWatch. Permanent PDF retention/download is out of scope. See the [authoritative target](diagrams/cloud-target-final-2026-10-02.md) and [dated acceptance record](../evidence/cloud-acceptance-2026-10-03.md). Extraction and embedding worker services and queues are reported present; the record does not document a complete API-to-outbox-to-SQS-to-worker job lifecycle. End-to-end async integration and full acceptance remain open.
- [ ] `[Open; partial deployed-state evidence recorded 2026-10-03]` Complete and evidence the cloud service, monitoring, scaling or recovery behaviour, and reliability controls. The current record includes a controlled single-target withdrawal, not automatic failure recovery.
- [x] `[Evidence recorded]` Target design includes persistent storage, private database networking, bounded logs, least-privilege intent, and encrypted off-VM backups: [infra notes](../src/infra/README.md).
- [ ] `[Open]` Confirm cloud storage/database implementation and schema evidence using synthetic/sample data only; no production credentials or personal data belong in the submission.
- [x] `[Implemented locally; Evidence recorded]` Meaningful ML is evaluated on synthetic fixtures with metrics, baselines, provenance, examples, and limitations in [data/AI evidence](../evidence/test-data-ai.md).
- [x] `[Evidence recorded]` Evaluation labels are provisional: a team member supplied 90 labels (P06–P08; recorded as blind, not independently verified), one pair was corrected post-result in a separate audit copy, and the remaining 210 are AI-drafted. This superseded the earlier 12-pair adjudication and 48-pair unverified set (see `data/evaluation/LABEL_REVIEW_LOG.md`). Human labels are useful strengthening, not an explicit brief mandate.
- [x] `[Evidence recorded]` Least-privilege, ownership, CSRF, privacy, and restricted-network intentions are in the [threat map](../evidence/threat-control-map.md) and architecture notes.
- [ ] `[Open]` Complete named-threat validation; the user-reported cloud checks are partial and do not cover the full threat map.
- [x] `[Evidence recorded]` Reproduction commands are documented in the [analytics README](../analytics/README.md) and [local integration runbook](LOCAL_INTEGRATION.md); pinned model/dependency details, AI-use disclosure, and data provenance guidance are in the [manifest](../project_manifest.yaml), [AI declaration](../AI_USE_DECLARATION.md), and [data README](../data/README.md).
- [ ] `[Open]` Replace planned team assignments with actual contributions, artefacts, commits, tests, and reflections.

## Section 3 — secure cloud service and integrity

- [ ] `[Open; deployment reported 2026-10-03]` Complete acceptance of the deployed secure cloud service, user-facing web/API, and data-driven capability. The operator-reported deployment and partial browser checks are in the [dated cloud record](../evidence/cloud-acceptance-2026-10-03.md); local app/ML evidence alone does not prove full cloud acceptance.
- [x] `[Evidence recorded]` AWS is the recommended provider in the brief; Azure or GCP are acceptable alternatives when the chosen provider and required evidence are supplied.
- [x] `[Implemented locally]` User-facing web/API and semantic matching exist locally; the separate private cloud deployment is now operator-reported, with full acceptance still pending.
- [x] `[Evidence recorded]` AI assistance is declared and the repository directs the team to record source revisions, licences, notices, retained modifications, and data permission. See [AI declaration](../AI_USE_DECLARATION.md) and [frontend notices](../src/frontend/THIRD_PARTY_NOTICES.md).
- [ ] `[Open]` Complete the licence/source audit, substantive team-modification explanation, and final integrity-policy record.

## Section 4 — seven compulsory implementation areas

### 4.1 Application workflow and input validation

- [x] `[Implemented locally]` Flow covers sign-in, browse/search/filter, resume prepare/review/save/delete, matching, and external apply links.
- [x] `[Evidence recorded]` Journey records malformed, scanned, encrypted, and oversized PDF rejection, stale-revision conflict handling, and safe external links: [journey evidence](verification/2026-09-23-user-journey.md).
- [ ] `[Open]` Complete the dated final workflow/input-validation record; the existing cloud happy-path checks are partial and do not cover all workflows or input validation.

### 4.2 Cloud compute and IaaS/PaaS/SaaS boundary

- [ ] `[Open]` Explain the deployed target boundary: AWS EC2/VM is IaaS; the team manages the guest/container runtime, Nginx, and FastAPI; RDS PostgreSQL is DBaaS; Google identity is an external SaaS dependency. The temporary synchronous foundation used private Single-AZ RDS PostgreSQL and is recorded separately. The split target deployment is operator-reported; full acceptance remains open.
- [ ] `[Open; deployment reported 2026-10-03]` Reconcile the deployed cloud compute configuration with the report and capture reviewed redacted boundary evidence; the new cloud record is operator-reported and partial.

### 4.3 Persistent cloud storage or database

- [x] `[Implemented locally]` PostgreSQL/pgvector persistence and schema/API contract are documented; restart persistence was browser-observed locally.
- [ ] `[Open; restore evidence recorded 2026-10-03]` Persistent **cloud** database: a point-in-time restore produced an instance with the same 12 tables, pgvector extension and row counts as the source ([R5](../evidence/test-resilience.md)). The [dated record](../evidence/cloud-acceptance-2026-10-03.md) reports deployed resources and a point-in-time empty temporary bucket; S3 lifecycle behavior is unproven. The contents of the deployed database were not inspected; only counts are in the evidence, and no row data is packaged.
- [ ] `[Open]` Ask the professor how self-hosted PostgreSQL is interpreted; do not infer that managed RDS is mandatory. The rotating-member $50 learner-lab question is also pending.

### 4.4 Interpretable analytics or ML

- [x] `[Implemented locally]` Requirement-level MiniLM matching returns requirement evidence/closest passages and is evaluated against baselines. A hosted LLM is not required by this brief.
- [x] `[Evidence recorded]` Metrics, examples, model revisions, fixture provenance, and limitations are in [test-data-ai](../evidence/test-data-ai.md).
- [ ] `[Open]` Re-run or ratify evaluation with accepted label provenance and explain what the metrics do and do not establish.

### 4.5 Scaling or resilience mechanism and test evidence

- [x] `[Implemented locally]` Design includes one bounded processing slot, child deadlines, controlled busy responses, restart handling, and safe retries; local restart persistence is recorded in the journey.
- [x] `[Evidence recorded 2026-10-03]` Mechanism and dated operational tests: automatic replacement observed twice (R1/R2), a controlled, timed instance termination with a 290-probe public monitor (R4: 2 failed probes, replacement healthy after ~9 min, no operator action), and a point-in-time database restore matching the source's schema and row counts (R5). A grace-period defect found during this work (R0) was fixed (420 s → 900 s on the live ASG and in `private-app.yaml`; the deployed stack template has not been re-applied). See [resilience record](../evidence/test-resilience.md). Not covered: whole-AZ failure, database failover, application cut-over to a restored database, load.
- [ ] `[Proposed]` Backup/restore is a chosen safeguard, not an individual brief mandate if another implemented mechanism satisfies the requirement; it remains planned in the current architecture.

### 4.6 Authentication, authorisation, least privilege, and threats

- [x] `[Implemented locally]` Authentication, CSRF handling, and session-scoped ownership implementation exist; two-user isolation test evidence is still pending.
- [ ] `[Open; partial evidence recorded 2026-10-03]` Complete cloud auth/authz, least-privilege, secrets-handling, restricted network/data-access, and named-threat validation with sanitised evidence. Local live ownership/CSRF checks (29/29) and public-endpoint TLS checks (6/6) pass; deployed-site ownership/CSRF checks passed (26/26) and the session cookie is HttpOnly, Secure, SameSite=Lax, `__Host-` prefixed. The runtime database role was observed to lack SELECT on the migration table (least privilege).
- [ ] `[Proposed]` Team hardening actions to assess: restricted database runtime role, non-root containers, and OS-level sandbox for the PDF child. These strengthen the design; they are not extra literal brief mandates.

### 4.7 Logs, monitoring, and operations

- [ ] `[Proposed]` Target design calls for request IDs, sanitised logs, health signals, bounded retention, and no raw resume content, cookies, or keys in output.
- [ ] `[Open; partial operator observations recorded 2026-10-03]` Complete operational evidence, including reviewed sanitized output and interpretation. The [cloud acceptance record](../evidence/cloud-acceptance-2026-10-03.md) records queue/DLQ observations and alarm gaps; alarm triggering, notification delivery, complete recent queue metrics, and raw exports remain unverified.

## Section 5 — required design and evaluation

### 5.1 Architecture and rationale

- [ ] **S5.1-A01** Create one final architecture diagram naming users, application components, cloud services, trust boundaries, data stores, observability, and data flows. Labels must match source/configuration and evidence filenames.
- [ ] **S5.1-A02** Explain both service-model and deployment-model choices, with at least two considered alternatives and why they were not selected.
- [ ] **S5.1-A03** State assumptions, constraints, expected workload, and cost-control measures using synthetic or anonymised data only. Do not invent a mandatory 100-user capacity or autoscaling requirement.
- [ ] **S5.1-A04** Align the final diagram, README, report, manifest, deployed configuration, and redacted evidence. The brief uses `evidence/architecture.png` as an example; PNG/SVG or another suitable format is a packaging choice. Choose the actual packaged path and align every reference while retaining an editable source if desired.
- [ ] **S5.1-A05** Capture dated, redacted cloud configuration and deployment evidence. The [2026-10-03 record](../evidence/cloud-acceptance-2026-10-03.md) summarizes operator-reported deployment results with identifiers and public URLs omitted; reviewed reproducible CLI/configuration exports remain to be retained.

### 5.2 Test plan and results

For each test below record: objective; setup, versions, fixtures and environment; command or repeatable steps; expected result; actual result; date; artefact path; failed-test diagnosis; and a sensible improvement plan. A failed test can still be reported honestly; it must not be rewritten as a pass.

- [ ] **S5.2-F** Functional workflow test: cover the meaningful web/API workflow and input validation. `evidence/test-functional.md` and the [2026-10-03 cloud record](../evidence/cloud-acceptance-2026-10-03.md) contain partial user/operator-reported checks; formal multipart boundary, server-side validation, and complete workflow coverage remain open.
- [ ] **S5.2-S** Security control test: select a named threat and test its relevant authentication/authorisation, ownership, CSRF, secrets, network, or data controls; map other controls separately where they are not in this test. `evidence/test-security.md` now includes a live local check with two synthetic users (29/29: ownership, CSRF/Origin, session; `evidence/test-security-live-local-2026-10-03.md`) and a negative TLS test of the public endpoint (6/6; `evidence/test-security-tls-2026-10-03.md`). The same ownership/session/CSRF checks also passed on the deployed site with two real accounts (26/26, `evidence/test-security-live-cloud-real-task.md`, including A's GET and DELETE on B's real task id). Session cookie attributes were captured from DevTools (`__Host-session`: HttpOnly, Secure, SameSite=Lax, Path `/`, host-only).
- [ ] **S5.2-D** Data/AI validation test: report the identified dataset, method, interpretable output, metrics, examples and limits. `evidence/test-data-ai.md` records a 2026-09-20 run with provisional labels; the [2026-10-03 cloud record](../evidence/cloud-acceptance-2026-10-03.md) adds operator-reported catalogue counts and an unchanged dry run, not a replacement evaluation.
- [x] **S5.2-R** Scalability, resilience or recovery test: `evidence/test-resilience.md` records R0–R5 including a timed, agent-assisted instance-termination test (raw logs in `evidence/recovery-test-2026-10-03/`) and a verified point-in-time restore (`tests/infra/verify_restore.sh`). Load testing and disaster recovery beyond an instance and a database copy remain out of scope and are stated as limits.
- [ ] **S5.2-Q** Confirm the test environment and cloud evidence expectation with the professor. The brief requires cloud deployment; it does not require 100-user testing or autoscaling, and it does not prescribe one test environment.

### 5.3 Data and AI/ML expectations

- [ ] **S5.3-A01** Show that the data/AI feature supports the stated workflow or operational decision and is more than a generic chatbot added to an unrelated app.
- [ ] **S5.3-A02** Document dataset/provenance fields, preprocessing, output interpretation, quality/evaluation approach, limitations, and responsible-use considerations.
- [ ] **S5.3-A03** Integrate the capability with the service or decision workflow. Cloud inference is optional: reproducible local inference or a Colab notebook is acceptable; a hosted LLM is not required.
- [ ] **S5.3-A04** Preserve the current truth: local MiniLM matching is implemented and evaluated, while the 2026-09-20 labels/metrics are provisional (12 adjudicated after draft review, 48 unverified-origin, remainder AI-drafted).

## Section 6 — required submission package

- [ ] **S6-A01** Package one ZIP named exactly `Group_Gxxx_INF2006_Project.zip`; confirm the official group ID before replacing `Gxxx`.
- [ ] **S6-A02** `README.md`: title, one-paragraph problem statement, team members, quick-start commands, architecture image link, technology list, and known limitations.
- [ ] **S6-A03** `project_manifest.yaml`: required Section 8 schema, factual values, and stable paths relative to the ZIP root.
- [ ] **S6-A04** `report.pdf`: 8–12 pages excluding references and appendices; use the exact Section 7 headings and explain rather than duplicate the manifest.
- [ ] **S6-A05** `src/`: runnable application, infrastructure/configuration, and dependency files; include `.env.example` with placeholders only.
- [ ] **S6-A06** `data/`: synthetic/sample data and `DATA_DICTIONARY.md`; exclude personal, sensitive, proprietary, and unlicensed data. Required team names/student IDs remain only in team metadata.
- [ ] **S6-A07** `analytics/`: notebook(s) or script(s), requirements, and a short README explaining reproduction.
- [ ] **S6-A08** `evidence/`: named, dated artefacts cited by the manifest, including test output, redacted screenshots/configuration when needed, monitoring output, and diagrams.
- [ ] **S6-A09** `tests/`: automated tests, API collection, or repeatable test scripts where feasible.
- [ ] **S6-A10** `TEAM_CONTRIBUTIONS.md`: one row per member with role, artefacts/commits, test/evidence ownership, and reflection.
- [ ] **S6-A11** `AI_USE_DECLARATION.md`: tools, usage locations, sources/baselines, verification, licences, and attribution.
- [ ] **S6-A12** `video_link.txt` is optional and never the primary assessment evidence.
- [ ] **S6-A13** Do not package passwords, access keys, tokens, private URLs, raw cloud credentials, real resumes, or personal data; required team names/student IDs are the metadata exception.

## Section 7 — exact report headings

- [ ] **S7-A01** Use these headings exactly in `report.pdf`; keep the numbered order and do not silently rename them:
  1. `Problem, users and success criteria`
  2. `Solution overview and architecture`
  3. `Cloud service/deployment choices and trade-offs`
  4. `Implementation, data design and security controls`
  5. `Analytics or AI/ML feature: data, method, evaluation and limitations`
  6. `Testing, scalability/resilience and monitoring results`
  7. `Cost, sustainability and operational considerations`
  8. `Team contribution, ethical considerations and reflection`

## Section 8 — `project_manifest.yaml` required schema

- [ ] **S8-A01** Preserve every required key below; extra fields are allowed, but required names may not be renamed or removed. Required field inventory: `project.group_id`, `project.title`, `project.problem_statement`, `project.cloud_provider`, `project.repository_commit`; `team.members[].name`, `team.members[].student_id`, `team.members[].role`; `architecture.diagram`, `architecture.service_model`, `architecture.deployment_model`, `architecture.components`; `evidence.functional_test`, `evidence.security_test`, `evidence.data_ai_test`, `evidence.scale_resilience_test`, `evidence.monitoring`; `data_ai.dataset`, `data_ai.method`, `data_ai.evaluation`, `data_ai.reproducible_command`; `security.threat_control_map`, `security.secrets_handling`; `run.prerequisites`, `run.commands`; `declarations.ai_use`, `declarations.contributions`.
- [ ] **S8-A02** Keep every path relative to the ZIP root; ensure identity, run commands, components, evidence paths, and status fields are complete and factual.
- [ ] **S8-A03** Align `architecture.diagram` with the actual packaged export; `evidence/architecture.png` is the brief's example, not a mandatory extension. Retain an editable source if desired. Existing empty values and `cloud_deployed: false` must not survive final packaging when the corresponding facts are available.

## Section 9 — evidence and redaction rules

- [ ] **S9-A01** Give every artefact a clear filename, cite it from the manifest and report, and put commands, inputs, and result summaries in text files. Use screenshots only when text/config exports are unavailable.
- [ ] **S9-A02** Redact account IDs, public IPs, URLs containing tokens, credentials, secret values, and sensitive configuration. Required team member names and student IDs remain in the required team metadata; the redaction rule applies to user/resume personal data and secrets.
- [ ] **S9-A03** Exclude credentials, production data, personal/user/resume data, proprietary datasets, unlicensed code/assets, private URLs, passwords, access keys, and tokens; required team names/student IDs remain in required team metadata.
- [ ] **S9-A04** Make instructions runnable on a clean machine where feasible; state unavoidable cloud prerequisites and expected cost. Do not require a marker to log in, join a team account, infer hidden configuration, or make paid purchases.
- [ ] **S9-A05** State limitations and failed tests honestly, link each claim to an artefact, and retain external code/AI-use attribution. A polished screenshot, video narration, or live cloud URL alone is not proof.

## Section 10 — assessment traceability

The rubric totals 100 marks. These are assessment criteria, not promised grades; this tracker only checks whether evidence is traceable and reviewable.

- [ ] **S10-A01** Problem framing and architecture — 15 marks: clear user need, coherent architecture, explicit service/deployment choices, trade-offs, README/report Sections 1–3, diagram, and manifest.
- [ ] **S10-A02** Cloud implementation and functionality — 20 marks: working workflow, appropriate source/configuration, compute/network/data configuration, functional test, and reproducible run/deploy instructions.
- [ ] **S10-A03** Cloud data and analytics/AI — 20 marks: relevant capability, provenance, reproducible method, credible evaluation/output, and limitations.
- [ ] **S10-A04** Security and responsible cloud practice — 15 marks: threats mapped to controls, least privilege, secret/access/network/data protection, security test, and responsible data/AI practice.
- [ ] **S10-A05** Scalability, resilience and operations — 15 marks: implemented mechanism, meaningful operational test, monitoring evidence, sound interpretation, and cost awareness.
- [ ] **S10-A06** Engineering quality — 10 marks: organised code, dependencies, deterministic artefacts, valid ZIP/manifest, reproducibility, and traceable evidence paths.
- [ ] **S10-A07** Team contribution and professional communication — 5 marks: specific balanced contributions, attribution, reflection, AI declaration, and clear communication.
- [ ] **S10-A08** Capture dated, redacted configuration and evidence before decommissioning cloud resources; the brief permits decommissioning when required configuration and evidence remain accessible.

## Appendix A — final submission preflight

- [ ] **SAPP-A01** ZIP filename follows `Group_Gxxx_INF2006_Project.zip`; official group identity is confirmed and no invented IDs are used.
- [ ] **SAPP-A02** README, manifest, report, `src/`, `data/`, `analytics/`, `evidence/`, `tests/`, declarations, and optional link are present as appropriate.
- [ ] **SAPP-A03** Every `project_manifest.yaml` path exists and opens from the ZIP root; report/evidence paths use the same filenames.
- [ ] **SAPP-A04** Every required test record has objective, setup, command/steps, expected result, actual result, date, artefact path, and honest diagnosis/improvement where needed.
- [ ] **SAPP-A05** No credential, token, private URL, personal/user/resume data, real resume, proprietary/unlicensed dataset, or secret remains in the submission; required team names/student IDs remain in required team metadata. Excluding `.env`, `.git`, and `node_modules` is packaging hygiene and keeps the ZIP reviewable.
- [ ] **SAPP-A06** Architecture labels match component names in source/configuration and evidence; the editable SVG and packaged PNG choice is deliberate and consistent.
- [ ] **SAPP-A07** AI/baseline code, data sources, licences, and attribution are declared; team verification is recorded and provisional labels are not presented as ground truth.
- [ ] **SAPP-A08** Extract the ZIP on a clean machine and have a teammate who did not create an artefact follow the README to locate paths and run safe/offline checks where feasible.
- [ ] **SAPP-A09** Keep proposals clearly separate from literal brief mandates: backup/restore is a chosen safeguard, autoscaling is not compulsory, self-hosted PostgreSQL/RDS interpretation is open, and intended workload thresholds are not invented.
- [ ] **SAPP-A10** Before the deadline, the submitting user confirms that the correct ZIP was uploaded and records the submission receipt. This is a final user action, not an agent claim.

## Practical work order and live register

1. Resolve provider, deployment boundary, cloud database interpretation, workload assumptions, cost controls, and the professor questions.
2. Bring the architecture diagram, manifest paths, README quick start, report headings, and actual component names into alignment.
3. Deploy the chosen cloud service and capture redacted configuration, persistent data/schema, auth/security, monitoring, and recovery evidence.
4. Run the four required tests, fill every record field, diagnose failures, and record improvements without claiming fresh results from the earlier snapshot.
5. Complete provenance/licence/contribution/AI records, assemble the report and ZIP, extract/reproduce it cleanly, then perform the user-controlled upload confirmation.

| Action ID | Owner | Result to capture | Evidence path | Status |
|---|---|---|---|---|
| S5.1-A01 | TBD | Final labelled architecture diagram and editable source | Actual packaged diagram path plus source | [ ] |
| S5.2-F | TBD | Functional test record with all required fields | `evidence/test-functional.md` | [ ] |
| S5.2-S | TBD | Security/threat test and redacted output | `evidence/test-security.md` | [ ] |
| S5.2-D | TBD | Data/AI method, evaluation and limitations | `evidence/test-data-ai.md` | [ ] |
| S5.2-R | TBD | Scaling/resilience/recovery procedure and result | `evidence/test-resilience.md` | [ ] |
| S4.7 | TBD | Operational query/alert/health output and interpretation | `evidence/monitoring.md` | [ ] |
| S6/S8 | TBD | Complete package and valid manifest paths | `project_manifest.yaml` and ZIP | [ ] |
| S7 | TBD | Report with eight exact headings | `report.pdf` | [ ] |
| SAPP-A08 | TBD | Clean extraction and teammate reproduction note | `evidence/` or report | [ ] |
| SAPP-A10 | User | Upload receipt for the correct final ZIP | LMS receipt or submission record | [ ] |

## Clarifications to ask the professor

- [ ] Are rotating team members' five `$50` learner-lab credits permitted for the project, and how should shared usage be documented?
- [ ] Is a self-hosted PostgreSQL database on a cloud VM acceptable as the persistent cloud database, or is a managed RDS-style service expected? Do not assume RDS is mandatory.
- [ ] Is a cloud recovery test required after deployment, and what exact environment/evidence is expected? The brief requires cloud deployment and a scalability, resilience, or recovery test.
- [ ] Is any intended workload guidance expected beyond a justified qualitative assumption? Do not invent a threshold.
