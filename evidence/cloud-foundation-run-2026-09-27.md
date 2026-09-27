# Cloud foundation test run — 2026-09-27

Status: PARTIAL PASS (user-reported). A temporary live foundation was deployed and the listed user journeys/checks were reported successful. This record was initially written while the stack was live. The user later reported teardown of the foundation stack, its retained database snapshot, and its CloudWatch log group; ECR repositories and Secrets Manager records were retained. Current AWS state was not independently checked by Codex. This record was prepared from the user's terminal transcripts, screenshots, and direct confirmations in the Codex conversation. The operator-user executed AWS and browser actions. Codex did not independently access or operate the user's AWS account.

## Tested artifact

- Region: `us-east-1`.
- CloudFormation stacks: `inf2006-images` and the current successful `inf2006-foundation` stack. The current foundation reached `UPDATE_COMPLETE` after a CloudFormation retry; its bootstrap reached the success marker saying database and digest-pinned images were prepared, with application containers kept stopped pending DNS/HTTPS activation.
- Repository source commit recorded by the build: `4a9b781e3ae9afcc36b7d104449c131d81e115ac`.
- Deterministic source snapshot SHA-256: `f18034f19af1d8781d5b05667e2da64041df0c9706c906e186a96522a20bd968`.
- ECR artifact digests reported by the user's completed build-and-publish command:
  - API: `sha256:15ea0500af071ea0561cc6b4c43f9cc83444e840bc4873a2f6934dcaede0c59e`
  - Web: `sha256:fb073e4f44295996c4ce591ee3fe142ca8b952a50a138c956d99a556cc2e5e0c`
  - Bootstrap: `sha256:35dc147ac99d63db3fa8c54f3724fcaaaf65a78a511728450cebe7c844d81b2d`
- Data fixtures: 30-job synthetic catalogue and a generated fictional synthetic resume. No real resume contents, passwords, session tokens, DuckDNS token, or AWS credentials are included here.

## Deployment and recovery history

The first foundation create failed when EC2 bootstrap could not retrieve the master secret: the command used an incorrect master-secret ARN suffix (the actual suffix begins with `j`, while the submitted parameter began with `i`). The remaining four secret references matched. The first failed stack used `DO_NOTHING`, so CloudFormation could not update it in place. The user deleted that failed stack, waited for deletion, and separately deleted its retained 20-GiB final snapshot and zero-byte API log group. The image stack and secrets were retained and reused.

The corrected foundation create used `--disable-rollback`. Its EC2 bootstrap then completed database role setup and all four migrations but stopped before service activation because the signing-key secret failed the app's allowed-character/length validation. The user replaced the key with a generated value; a local validator reported only `VALID` and did not print the value. CloudFormation retry reached `UPDATE_COMPLETE`, and the EC2 bootstrap success marker was observed. The user then dry-ran and imported the bundled synthetic job fixture and activated DNS/HTTPS. This sequence is recorded to explain the two failed attempts; it does not imply any secret value was exposed in this repository.

## Observed results

All items below are user-executed/user-reported, based on terminal output/screenshots or explicit confirmation:

- Build/upload: all three digest-pinned ECR images were pushed. The user reported the build command completed successfully and supplied the final three image digests and snapshot identity above.
- Database/bootstrap: pgvector extension and restricted app roles were prepared; all four Alembic migrations completed. The user confirmed the bootstrap success marker. This demonstrates the tested RDS path allowed the configured logging parameter changes in this run.
- Catalogue: dry-run succeeded. A subsequent import output reported zero new/updated rows, 30 unchanged jobs, no embeddings recomputed, and catalogue revision 1. This is evidence the 30 jobs were already present and repeat import was idempotent; do not rewrite this as a measured initial `created=30` result. An earlier foreground import attempt returned `Hangup`; the later repeat output establishes the resulting catalogue state.
- DNS/TLS/readiness: DuckDNS confirmed its A-record update, the user reported public DNS matched the EC2 address, HTTPS activation printed its success message, and a public readiness request returned `ready`.
- Functional journey: user confirmed Google sign-in, job browse, synthetic resume upload/prepare/review/save, recommendations, and saved-state persistence after refresh. After the API restart, the original user's synthetic profile and recommendations remained present.
- Monitoring/recovery: both alarms were observed `OK`; after stopping only the API container, the user supplied a screenshot with API-readiness `ALARM` and EC2 host-status `OK`; after API restart and readiness recovery, a later screenshot showed both alarms `OK`.
- Authentication and basic separation: signed-out `/resume` redirected to login; a no-cookie `GET /api/resume` returned HTTP 401. A second Google account saw an empty resume state while the original account's synthetic saved profile remained after switching back. This is basic UI-level separation evidence, not a comprehensive authenticated cross-user API/IDOR test.

See [`test-functional.md`](test-functional.md), [`test-security.md`](test-security.md), [`test-resilience.md`](test-resilience.md), and [`monitoring.md`](monitoring.md) for scoped interpretations and limitations.

## Evidence and remaining work

This repository record is a sanitized transcription, not a raw evidence bundle. Before formal submission, export and retain the user's build log, CloudFormation success/resource summary, bootstrap success lines, importer output, sanitized readiness/auth checks, and redacted CloudWatch screenshots/history. Do not copy screenshots containing personal account names/student context or any secret/session material without redaction.

The final teammate data, UX changes, LLM evaluation/report, and integrated final project version remain pending. EC2 stop/start with dynamic DNS refresh, RDS snapshot restore, IMDS denial verification, peak/load/memory capacity, notification delivery, and stronger cross-account API ownership tests were not run. This foundation run therefore does not establish overall project or final submission completion.

## Follow-up status — 2026-09-27

After the run above, the user reported deleting the successful foundation stack, its retained database snapshot, and its CloudWatch log group. The ECR repositories and Secrets Manager records remain. This is user-reported current status, not an independent AWS observation. The temporary stack's tests do not establish that cloud resources remain deployed or that overall application acceptance is complete.
