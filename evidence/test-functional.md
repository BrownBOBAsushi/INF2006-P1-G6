# Cloud functional test record

Status: PARTIAL PASS — user-reported live run on 2026-09-27. Evidence in this record was transcribed from user-provided terminal output, screenshots, and confirmations in the Codex conversation; the repository author did not independently operate the AWS account or browser in this test.

- Objective: Verify the deployed synchronous foundation and main user journey.
- Environment: AWS us-east-1, stack `inf2006-foundation`, public URL `https://internshipmatcher.duckdns.org`.
- Artifact identity: source commit `4a9b781e3ae9afcc36b7d104449c131d81e115ac`; source snapshot SHA-256 `f18034f19af1d8781d5b05667e2da64041df0c9706c906e186a96522a20bd968`. API image `sha256:15ea0500af071ea0561cc6b4c43f9cc83444e840bc4873a2f6934dcaede0c59e`; web image `sha256:fb073e4f44295996c4ce591ee3fe142ca8b952a50a138c956d99a556cc2e5e0c`; bootstrap image `sha256:35dc147ac99d63db3fa8c54f3724fcaaaf65a78a511728450cebe7c844d81b2d`.
- Setup and fixture: Learner Lab EC2 plus PostgreSQL/pgvector RDS; 30-job synthetic catalogue; synthetic fictional resume PDF generated for this test. No real resume content is recorded here.
- Steps and actual results (user-executed/user-reported):
  - Bootstrap reached its success marker after correction of the signing-key format; database setup enabled pgvector, created restricted application roles, and completed all four Alembic migrations.
  - Catalogue dry-run returned `DRY RUN ok`. A later import reported `created=0 updated=0 unchanged=30 embeddings_computed=0 embeddings_reused=0 requirements_deduplicated=0 catalogue_revision=1`; this establishes that all 30 fixture jobs were already present and the repeat import was idempotent. The initial first import was interrupted at the terminal, so its result is not separately asserted.
  - User reported public readiness returned `ready` over HTTPS.
  - User reported Google sign-in succeeded, jobs were browseable, a synthetic resume could be uploaded/prepared/reviewed/saved, recommendations rendered, and profile/recommendations remained after refresh.
  - After API restart, user confirmed public readiness and saved profile/recommendations remained accessible.
- Result: The reported cloud happy path and persistence checks passed for the tested artifacts and synthetic data.
- Limitations: These are conversational user reports, not exported browser/network captures or independently reproduced runs. The final teammate dataset, frontend changes, and final integrated project version have not been tested. This does not establish ML quality, peak capacity, or all acceptance criteria.
- Evidence source: `evidence/cloud-foundation-run-2026-09-27.md`; raw console/browser exports remain to be saved and reviewed before final submission.
