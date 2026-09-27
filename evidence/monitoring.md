# Cloud monitoring record

Status: PARTIAL PASS — user supplied dated screenshots and status observations from the live test on 2026-09-27. Exact event times are not asserted beyond the displayed screenshot clock; no raw CloudWatch export has yet been archived.

- Environment: AWS us-east-1; CloudFormation stack `inf2006-foundation`; source snapshot SHA-256 `f18034f19af1d8781d5b05667e2da64041df0c9706c906e186a96522a20bd968`.
- Baseline: Before the outage test, the user supplied a `describe-alarms` screenshot showing both the EC2 host-status alarm and API-readiness alarm in `OK`.
- Failure observation: User stopped the API container. A later screenshot showed the readiness alarm in `ALARM` and the host-status alarm in `OK`, consistent with an application outage on a reachable host.
- Recovery observation: User restarted the API container. Public `/health/ready` returned `ready`; saved profile and recommendations remained available. A later screenshot showed both alarms back in `OK`.
- Result: Both failure detection and alarm recovery were observed for the manual API interruption.
- Limitations: The screenshots show alarm states/reason text but do not establish notification delivery, alarm evaluation delay, or continuous monitoring coverage. Raw alarm history and metric exports should be saved for formal submission; redact account identifiers and personal screen context.
- Related record: `evidence/test-resilience.md`.
