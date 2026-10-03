# Private cloud rollout and partial acceptance record — 2026-10-03

**Evidence provenance:** this record combines direct CUA browser observations
from 2026-10-03 with AWS CLI and browser results reported by the project
operator in the working session. Items are labeled by provenance below. This
documentation update did not query AWS, use credentials, or repeat those
operations. Treat operator-reported results as such until the team reviews and
retains the original redacted command output. Account IDs, instance IDs,
public URLs, public IPs, and full certificate ARNs are intentionally omitted.
No resume contents or user secrets are recorded.

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
- After a lab restart, the operator reports that the current new app targets
  were healthy, the worker was healthy, and the public endpoint returned HTTP
  200. Resource identifiers are omitted. This is operator-reported current
  state, not an independently queried infrastructure check in this update.
- The worker-only security-group update adding outbound UDP/TCP port 53 was
  reported applied. Existing HTTPS and database egress were retained; no
  inbound rule was added.

## Certificate and renewal observations

- A staging DNS-01 issuance passed. A production certificate was issued and
  imported, and a later same-ARN reimport passed.
- **Operator-reported isolated TLS hostname-mismatch probe:** the operator ran
  `/tmp/inf2006-isolated-tls-probe.sh --execute`. Preflight matched the live
  API and VPC link. A temporary API (`mjpn0kfi48`) initially returned HTTP 404
  while propagating, then HTTP 200. With
  `serverNameToVerify=tls-negative.invalid`, it initially returned HTTP 200
  during propagation, then returned three consecutive HTTP 500 responses
  while each live-API control request returned HTTP 200. After restoring the
  configured hostname, the temporary API returned HTTP 500 once, then HTTP
  200. The probe made 12 HTTPS requests total. Cleanup succeeded; a subsequent
  operator `get-api` returned `NotFoundException` for the temporary API. The
  helper review and operator log report that the live API was unchanged. This
  closes the isolated hostname-mismatch behavioral check only; an untrusted
  certificate-chain rejection test was not performed.
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

- **Direct CUA browser observations, 2026-10-03 (Singapore time):** on the main
  account, matching returned 247 results; pagination to page 2, refresh
  persistence, session assets, and an API request returning HTTP 200 were
  observed. An empty search followed by clearing the search restored results.
  Matching while offline showed a visible failure and Retry control; after
  network restoration, matching recovered and returned 247 results.
- In the same browser session, saving identical content twice returned HTTP
  200 in 0.609 s and 0.549 s, respectively, with the saved revision remaining
  at 2. In a separate synthetic-resume session, the first save returned HTTP
  200 in 12.58 s at revision 1 and matching returned 247 results. A later save
  with a changed synthetic project description returned HTTP 200 in 649 ms at
  revision 2.
- For that separate session, a test account displayed as “Cloud Acceptance
  Test” uploaded the user-approved synthetic PDF
  `synthetic-internship-resume.pdf` through native Chrome. The extracted
  review showed email redaction and an unplaced-text warning. “Cloud Computing”
  was incorrectly classified as a person. This confirms the observed flow and
  those specific extraction results; it does not establish perfect extraction
  quality.
- **Observed failed-save retry, 2026-10-03 (Singapore time):** with Chrome
  DevTools set to Offline, saving changed content from revision 2 failed twice
  with `net::ERR_INTERNET_DISCONNECTED`. The UI showed “Trying again” at 3 then
  6 seconds and “Your draft is here.” After restoring No Throttling, the UI
  reported “Earlier save confirmed” and “Your earlier save completed”; the
  current saved resume was revision 3. This records one observed connection
  failure followed by automatic retry and one revision increment. It does not
  establish behavior after a response is lost following server commit, an
  actual gateway timeout, or whether duplicate embedding jobs can occur.
- **Operator-reported auth details:** cookie attributes were reported as
  `HttpOnly`, `Secure`, `SameSite=Lax`, and `Path=/`, with two separate
  `Set-Cookie` headers. Missing or invalid CSRF was reported to return HTTP
  403, and the session remained logged in after refresh. These details were
  not independently inspected in DevTools or verified by direct authenticated
  API tests for this record. The earlier cross-account browser journey also
  does not replace direct authenticated ownership tests.
- A 5 MiB PDF was rejected while the previously saved resume remained intact.
  Follow-up direct native-Chrome probes on the test account observed an
  externally visible HTTP request-size boundary of 6 MiB. A synthetic-padding
  `POST /api/resume/prepare` form with no file and total request size 6,291,456
  bytes returned HTTP 415 `PDF_REQUIRED`, showing that the application parser
  was reached at that size. At 6,291,457 bytes the response was HTTP 413 with a
  non-JSON body; the rejecting layer was not identified. In a separate
  multipart request, a synthetic oversized PDF of 5,242,881 bytes (total
  request size 5,243,039 bytes) returned HTTP 413 `FILE_TOO_LARGE`. Source
  validation precedes enqueue in the implementation, but no independent queue
  or database task-count check was performed, so task absence is not directly
  verified. The saved profile remained at revision 3 in the UI after reload.
- These probes verify the observed request-size boundary and oversized-PDF
  response. A valid PDF padded to exactly 6 MiB was not successfully tested:
  native file reselection failed and the dialog was cancelled. The positive
  exact-boundary acceptance, including resulting save/task behavior, therefore
  remains open.
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
- Five CloudWatch alarms reported `OK`. The four queue alarms were `OK`
  because no metric datapoints had been received in their evaluation window and
  missing data is configured as non-breaching; no alarm was missing (confirmed
  by `evidence/cloud-capture-2026-10-03/07-alarms.txt`). SQS metrics listed all
  four queues. Extraction visible-message samples were zero from 11:15 to 12:10
  Singapore time. This does not establish that every queue metric was recent,
  that an alarm can trigger, or that notification delivery works.
- An earlier app target became unhealthy after local readiness had been
  reported at 02:40:35 UTC and the load balancer reported failure at 02:42:46
  UTC. The cause remains unresolved. A replacement target became healthy and
  no further churn was reported. The two current app targets were reported
  healthy and in service, with no suspended Auto Scaling processes.
- A controlled continuity check suspended the `HealthCheck` and
  `ReplaceUnhealthy` Auto Scaling processes,
  deregistered one healthy target, waited for draining, and then confirmed
  public health HTTP 200 at 04:25:34 UTC. The browser session, resume, and
  matches remained available. The target was registered again, returned to
  healthy, and the suspended-process list was cleared. This demonstrates a
  manually controlled single-target withdrawal with service continuity; it
  does not prove automatic crash recovery.

## Acceptance still open

These observations support a partial deployed-state record. The items below
are the team's own extended acceptance and hardening checks. They are **not**
minimum requirements of the project brief (Section 4 requires at least one
implemented scalability/resilience mechanism with an observed result, one
security control tested against a named threat, and one operational test,
alert or query). The brief-mapped test records are `evidence/test-*.md` and
`evidence/monitoring.md`; the read-only configuration capture is in
`evidence/cloud-capture-2026-10-03/`. Remaining optional checks include:

- Independent direct API tests for CSRF and cookie handling, server-side
  ownership across accounts, and successful processing of a valid PDF padded
  to the formal 6 MiB multipart boundary. The request-size cap and oversized
  PDF rejection have the partial negative-probe evidence above; the CSRF and
  cookie observations remain operator-reported.
- Cold and warm privacy-check/save latency, the 30-second integration limit,
  and timeout/retry behavior without duplicate saves.
- Automatic target failure and recovery, untrusted certificate-chain
  rejection, and a complete production renewal/deploy cycle. The isolated
  hostname-mismatch behavior was exercised as described above.
- Queue alarm threshold behavior, notification delivery, current metrics for
  every queue, worker retry/DLQ behavior, temporary-object lifecycle, and
  database snapshot restore.
- Cleanup of retained resources. A read-only inventory and list-price cost
  estimate were captured later on 2026-10-03 in
  `evidence/cloud-capture-2026-10-03/10-resource-inventory-and-cost.txt`
  (3 unassociated EIPs, 1 manual RDS snapshot, 1 `ROLLBACK_COMPLETE` stack);
  removal remains a separate approval decision.
- Team review of the operator-reported items above. Redacted read-only
  configuration exports now exist in `evidence/cloud-capture-2026-10-03/`.

The deployment does not complete the coursework submission. Keep the related
checklist items open until the required test records, report, manifest, and
submission package have been reviewed.
