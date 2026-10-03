# Private cloud rollout and partial acceptance record — 2026-10-03

**Evidence provenance:** this record summarizes AWS CLI and browser results
executed by the project operator and pasted into the working session. The
documentation update did not query AWS, use credentials, or repeat those
operations. Treat the results as operator-reported evidence until the team
reviews and retains the original redacted command output. Account IDs, instance
IDs, public URLs, public IPs, and full certificate ARNs are intentionally
omitted. No resume contents or user secrets are recorded.

## Deployment and ingress

- The operator reports that the retried private-base stack reached
  `UPDATE_COMPLETE`; its worker is running both extraction and embedding
  services and was reported healthy. The ingress and app stacks reached
  `CREATE_COMPLETE`.
- The HTTP API integration was reported as `HTTP_PROXY` over `VPC_LINK`, using
  the internal ALB HTTPS listener ARN, TLS server-name verification for the
  configured certificate hostname, a 30,000 ms integration timeout, and the
  `$request.path` overwrite mapping. The public execute-api origin is withheld
  from this coursework evidence.
- The operator reports that public `/health/ready` returned HTTP 200. The
  imported certificate was issued by Let's Encrypt and is reported to expire
  at `2027-01-01 09:23:35 +08:00`. The same ACM certificate resource was reused
  for reimport; the full ARN is withheld.
- The worker-only security-group update adding outbound UDP/TCP port 53 was
  reported applied. Existing HTTPS and database egress were retained; no
  inbound rule was added.

## Certificate and renewal observations

- A staging DNS-01 issuance passed. A production certificate was issued and
  imported, and a later same-ARN reimport passed.
- Certbot 2.6 was installed by the operator. A separate Certbot renewal dry
  run passed. A custom renewal timer is reported active; the generic timer is
  disabled. The last manual service invocation reported success with exit
  status 0.
- The updated DuckDNS hook was installed on the current worker as an
  operational overlay. Its SHA-256 is
  `48bf32189016a95f8d9ea2edfa42b9ca3dea55d83fae8299c0fc48b07329be69`.
  The certificate secret ARN is saved in the worker's protected configuration;
  its value is not reproduced here. All three published image digests remain
  unchanged and predate this worker overlay; no image rebuild included it.
- These separate checks do **not** demonstrate one complete due-renewal cycle
  through hook execution, DNS propagation, certificate replacement, and
  deployment after the prior certificate expires. The published image and its
  recorded source snapshot still predate the worker hook overlay; rebuilding
  and reproducibility remain open.

## Application and data observations

- Browser checks reported Google GIS sign-in, refresh persistence, upload and
  save, matching, deep-detail refresh, logout, and denial after logout working
  through the public origin. A second Google account could not see the first
  account's profile in the browser journey; the original account's profile
  remained present. This is useful UI evidence, not a substitute for direct
  authenticated cross-account API and CSRF tests.
- A 5 MiB PDF was rejected while the previously saved resume remained intact.
  This does not establish the formal server-side 6 MiB multipart boundary or
  exact near-limit binary behavior.
- The operator reports an imported catalogue of 247 records: 78 from JSearch
  and 169 from LinkedIn. It had 1,588 embeddings at model revision 1, with no
  synthetic embeddings. Post-import counts were checked. A later dry run
  reported the same 247 records and zero embedding changes. The original local
  catalogue of 277 records, including 30 synthetic records, was not copied to
  the cloud.

## Worker, queues, storage, and continuity observations

- At the reported capture, both DLQs showed zero visible and zero in-flight
  messages. The temporary S3 bucket had zero objects at that point in time;
  this does not establish its lifecycle or retained-data behavior.
- Five visible CloudWatch alarms reported `OK`, but the queue alarm was
  missing; a missing alarm was treated as non-breaching. SQS metrics listed all
  four queues. Extraction visible-message samples were zero from 11:15 to 12:10
  Singapore time. This does not establish that every queue metric was recent,
  that an alarm can trigger, or that notification delivery works.
- An earlier app target became unhealthy after local readiness had been
  reported at 02:40:35 UTC and the load balancer reported failure at 02:42:46
  UTC. The cause remains unresolved. A replacement target became healthy and
  no further churn was reported. The two current app targets were reported
  healthy and in service, with no suspended Auto Scaling processes.
- A controlled continuity check suspended `HealthCheckReplaceUnhealthy`,
  deregistered one healthy target, waited for draining, and then confirmed
  public health HTTP 200 at 04:25:34 UTC. The browser session, resume, and
  matches remained available. The target was registered again, returned to
  healthy, and the suspended-process list was cleared. This demonstrates a
  manually controlled single-target withdrawal with service continuity; it
  does not prove automatic crash recovery or negative TLS verification.

## Acceptance still open

These observations support a partial deployed-state record. They do not close
the brief's cloud acceptance requirements. Remaining checks include:

- Direct API tests for CSRF, cookie handling including multiple `Set-Cookie`
  headers, server-side ownership across accounts, and exact multipart limits up
  to the formal 6 MiB boundary.
- Cold and warm privacy-check/save latency, the 30-second integration limit,
  and timeout/retry behavior without duplicate saves.
- Automatic target failure and recovery, wrong-name or invalid-certificate
  rejection, and a complete production renewal/deploy cycle.
- Queue alarm threshold behavior, notification delivery, current metrics for
  every queue, worker retry/DLQ behavior, temporary-object lifecycle, and
  database snapshot restore.
- A current cost and retained-resource review based on the deployed two-app
  plus worker footprint and any resources retained from failed attempts. No
  current bill or complete retained-resource inventory was independently
  verified for this record. Cleanup of retained workers, snapshots, and EIPs
  remains a separate approval decision.
- Reproducible redacted command/configuration exports and review of this
  operator-reported evidence by the project team.

The deployment does not complete the coursework submission. Keep the related
checklist items open until the required test records, report, manifest, and
submission package have been reviewed.
