# Cloud resilience test record

Status: PARTIAL PASS — one user-executed API stop/recovery test completed on 2026-09-27. Results were transcribed from user-supplied CloudWatch CLI screenshots and terminal/browser confirmations.

- Objective: Verify application-readiness monitoring detects an API outage and that manual API recovery preserves saved application data.
- Environment/artifact: AWS us-east-1, stack `inf2006-foundation`, source snapshot SHA-256 `f18034f19af1d8781d5b05667e2da64041df0c9706c906e186a96522a20bd968`, commit `4a9b781e3ae9afcc36b7d104449c131d81e115ac`.
- Procedure and result (user-executed):
  1. Stopped only the API container through Docker Compose on the EC2 Session Manager shell.
  2. User supplied a CloudWatch alarm screenshot showing `ApiReadinessAlarm=ALARM` while `ApiHostStatusAlarm=OK`.
  3. Started the API container with Compose `up -d --wait api`; the user reported the public readiness endpoint returned `ready`.
  4. The user confirmed the saved synthetic profile and recommendations were still present after refreshing.
  5. User supplied a later CloudWatch alarm screenshot showing both `ApiReadinessAlarm=OK` and `ApiHostStatusAlarm=OK`.
- Result: The configured alarm distinguished application readiness failure from EC2 host status; manual API restart restored readiness and persisted RDS-backed user data remained available.
- Limitations: This test did not stop/start or replace EC2, restore an RDS snapshot, test a database failure, simulate sustained overload, or measure recovery time formally. It is a manual process recovery check, not proof of automated recovery or disaster recovery. No notification delivery was verified.
- Evidence source: `evidence/cloud-foundation-run-2026-09-27.md`; screenshots/CLI exports must be redacted and saved separately before final submission.
