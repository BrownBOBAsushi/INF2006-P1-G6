# AI use declaration

Status: living declaration, not final submission.

## Architecture review and documentation revision — 2026-09-26

Claude (Anthropic) produced `INF2006_architecture_review.md`, an independent
review of the project brief, repository evidence, and cloud plan. Codex used it
as untrusted review input, checked the code findings, and revised
`docs/CLOUD_ARCHITECTURE.md`, `docs/diagrams/cloud-architecture.md`,
`docs/superpowers/plans/2026-09-26-cloud-deployment.md`, README/manifest and
historical-status notes, and this declaration. Finding dispositions are in
`docs/ARCHITECTURE_REVIEW_RESPONSE.md`. The review and this revision changed
documentation only; neither implemented application code nor created cloud
resources. These changes await independent review and cloud verification.
Synthetic data only is used for coursework cloud evidence.

| Tool | Use so far | Verification / limitation |
|---|---|---|
| OpenAI Codex | Assisted architecture discussion, source research, PRD/API/schema handoff, backend API integration and hardening review, synthetic PDF fixture restoration/regression-test assistance and repository scaffold; on 2026-09-22 implemented the approved frontend/runtime integration in `src/frontend/**`, Dockerfiles, Compose/proxy configuration and local runbook, then added explicit logout CSRF recovery and disposable test wiring | Frontend typecheck, 198 frontend tests and production build passed with the test/build harness using `envDir:false`; four HTTP loopback tests were excluded because listenEPERM blocked their local listener. Compose config parsing passed. Focused backend checks recorded 30 passed and 3 skipped; 40 PDF fixture/extraction checks passed under an alternate cached runtime, not the pinned production environment. Docker/model download, full disposable PostgreSQL/ML runtime, real Google login, browser end-to-end and load acceptance remain pending. |
| Claude (Anthropic, Claude Code) | 2026-09-20: wrote `analytics/evaluate.py`, its unit tests, the 30 synthetic jobs, 10 synthetic profiles and the **draft** relevance labels/criteria under `data/evaluation/`, ran the evaluation, generated the synthetic resume PDFs (`tests/fixtures/`), and on 2026-09-21 implemented `src/backend/app/{processing,matching,catalogue}` (PDF extraction, privacy, chunking, embeddings, catalogue import, requirement-level matching, skill gaps, explanations), one migration, `tests/pipeline`, and `tests/load/run.py`; on 2026-09-21 also the isolated processing child and slot (`app/processing/slot.py`, `worker.py`), an HTTP reference harness and the API-level load script (`tests/load/harness_app.py`, `api_load.py`) and the integration guide for Jiaxin, on request of Chuying | Labels remain AI-drafted for 210/300 pairs. A 90-pair team-member submission is recorded separately; its described blind process is not independently verified. On 2026-10-01, Codex made a user-authorized, AI-assisted post-result correction to a separate audit copy for one rubric inconsistency; details and limitations are in `data/evaluation/LABEL_REVIEW_LOG.md` and `evidence/test-data-ai.md`. These labels are not complete human ground truth. Code checks and original evaluation are documented in their respective evidence files. |

Implementation agents and other tools must be added as used. Do not claim Claude/ChatGPT extracted a dataset until the team actually does it. Record prompt/task scope, changed files, human checks and actual tests.

## Synchronous cloud-foundation preparation — 2026-09-27

OpenAI Codex prepared the synchronous AWS foundation templates, image/bootstrap
scripts, cloud-only proxy configuration, contract checks, and deployment/evidence
runbooks under `src/infra/`, `tests/infra/`, and
`evidence/cloud-foundation-preparation-2026-09-27.md`. This work adds no
application routes or schema; it also includes the minimal Alembic URL
interpolation helper and Dockerfile base-image/provenance support. A later user-operated temporary deployment and scoped checks, followed by user-reported teardown, are recorded in `evidence/cloud-foundation-run-2026-09-27.md`. Docker-based image
builds and runtime checks could not run because access to the local Docker
socket was denied. CloudShell read-only checks and CloudFormation template
validation are listed with their exact limits in the evidence record. The cold
memory requirement, DNS, HTTPS, Google login, backup/restore, and real
end-to-end cloud journey remain unverified.

## Label provenance (updated 2026-10-01)

- The 300 relevance labels in `data/evaluation/labels.csv` were drafted by Claude before any model output existed. They are AI-drafted.
- Chuying decided 12 disputed pairs personally, **after seeing the AI labels** (adjudication, not blind labelling), and changed 6 of them
  (P04-J16, P04-J21, P06-J26, P07-J01, P07-J26, P08-J01). This record (`labels_human_adjudication12.csv`) was removed on 2026-10-01 and superseded
  by a separate 90-pair team-member submission, whose recorded blind process has not been independently verified (see `data/evaluation/LABEL_REVIEW_LOG.md`).
- A further 48 labels were supplied by a team member as `labels_48.csv`. **Their origin was never verified**; they agreed with the
  AI draft on 45 of 48 pairs. That file and the evaluation run built from it were also removed on 2026-10-01 for the same reason.
- `data/evaluation_reviewed_subset/labels_human.csv` preserves the original 90-row submission byte-for-byte. After that file had been evaluated, a rubric mismatch was identified for P06-J29: its rationale inferred technical-writing ability from coding experience despite the explicit J29 keyword-trap rule. At the user's direction, Codex created `labels_audited.csv`, an AI-assisted audit copy changing only that pair from 2 to 0 with a corrected rationale (2026-10-01). This is a post-result correction, not a new human label, independent review, or human ratification. The original and audited metrics are reported separately.
- The remaining 210 pairs are AI-drafted and unreviewed. Manifest `label_review.status` is `PARTIAL` (90/300 coverage), not `PENDING` or `COMPLETED`; neither the original submission nor its audit copy establishes complete human ground truth. The recorded blind process is not independently verified, and disagreement patterns do not prove blind independence.
- Other label files supplied during review were checked and not used. All metrics that depend on labels are provisional (`evidence/test-data-ai.md`).

## Baselines and licences

The reuse checklist in docs/handoff/IMPLEMENTATION_GUIDE.md identifies FastAPI Template, react-dropzone, pdfplumber, Presidio, Sentence Transformers, MiniLM, pgvector and optional code references. These are selected/reference candidates; no upstream code is imported by this scaffold.

Before copying/installing: record exact repository/model revision, file paths used, licence, retained notices and team modifications. Update this declaration with tested dependencies. Provider API use is different from an open-source code licence; record data permission separately.

## Frontend foundation assistance — 2026-09-12

OpenAI Codex assisted Xue E's requested local frontend milestone: React/TypeScript
routing, shared same-origin CSRF client, login and optional onboarding, synthetic
catalogue browsing/search/paging, active/closed details, tests and dependency locking.
Nasya's existing origin/dev resume feature was inspected and mounted without edits.

Scope/files and actual validation are recorded in
[src/frontend/MILESTONE_VALIDATION.md](src/frontend/MILESTONE_VALIDATION.md).
Final checks: typecheck passed, 138 tests passed, production and mock-mode production
builds passed, localhost HTTP smoke checks passed. Real Google/backend end-to-end
verification and human review remain pending. No cloud resources were created.

Only direct dependencies were used; no upstream template internals were copied.
Nasya's declared dependencies were preserved, react-router 7.18.3 was added, and
npm generated an integrity lockfile. Exact versions/licences and retained runtime
notices are in [src/frontend/THIRD_PARTY_NOTICES.md](src/frontend/THIRD_PARTY_NOTICES.md).
Synthetic fixtures contain no provider records, secrets or real resume contents.

## Frontend session recovery assistance — 2026-09-16

OpenAI Codex assisted Xue E's next frontend milestone after inspecting TEAM_PROMPTS,
the current handoff, Nasya's origin/dev feature and Jiaxin's backend branch.
Recovered the conflicted local frontend checkout while preserving its staged work
and restoring teammate files unchanged. Implemented session/CSRF recovery, stale
response and account isolation, and synthetic loopback HTTP integration tests.

Actual validation: typecheck passed; 163 tests passed (including Nasya's unchanged
100); normal and mock-mode production builds passed with fixture exclusion.
Added only pinned @types/node 24.13.4 and its required type dependency; existing
lockfile versions/integrities were preserved. No real Google/backend end-to-end
result, teammate approval, cloud deployment or human review is claimed.

See [session recovery validation](src/frontend/SESSION_RECOVERY_VALIDATION.md)
for commands, failures resolved, changed files and remaining integration dependencies.
No upstream implementation was copied and no real resume/credential data was used.

## Requirements audit, evidence capture and documentation — 2026-10-03

Claude Code (Anthropic, Claude Opus 5.5), operated by Zhihao, audited the repository against the original brief
(`INF2006_Team_Project_Brief_2026.pdf`) and then:

- ran read-only AWS CLI commands (describe/get/list only; no resource changes, no secret values retrieved) and
  unauthenticated HTTP probes, saving redacted output in `evidence/cloud-capture-2026-10-03/` via
  `src/infra/scripts/capture-cloud-evidence.py` and `capture-logs-insights.py`;
- ran the local test suites and the evaluation reproduction (`evidence/local-tests-2026-10-03.md`), rebuilding the
  stale local backend test image;
- drew the deployed architecture diagram (`evidence/architecture.svg/.png`) from the CloudFormation templates;
- rewrote `README.md`, `project_manifest.yaml`, `data/README.md`, `evidence/README.md`, the four test records,
  `evidence/monitoring.md` and `evidence/threat-control-map.md`, and pre-filled git-derived facts in
  `TEAM_CONTRIBUTIONS.md`; replaced a real AWS account ID in `tests/infra/test_deploy_foundation.py` with a placeholder.

Verification: every claim in these documents was checked against source files, captured command output or the
recorded observations they cite; the infrastructure test file still passes (14 tests). Browser observations
labelled [Observed] were made earlier on 2026-10-03 by OpenAI Codex operating the browser; results labelled
[Operator-reported] come from the team member's own AWS/browser actions. The team had reviewed these
documents, confirmed the contribution rows and writen their own reflections.
