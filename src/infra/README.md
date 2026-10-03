# Synchronous AWS foundation preparation

The final private async target is prepared separately in [`docs/PRIVATE_CLOUD_ROLLOUT.md`](../../docs/PRIVATE_CLOUD_ROLLOUT.md). It does not replace this historical foundation path. Its templates and bootstrap helpers are preparation only and have not been deployed or cloud-validated.


This directory contains the synchronous foundation implementation and runbook for the existing API. A temporary deployment and scoped user-reported checks, followed by user-reported teardown, are recorded in [`evidence/cloud-foundation-run-2026-09-27.md`](../../evidence/cloud-foundation-run-2026-09-27.md); current AWS state was not independently verified by Codex. The proposed split asynchronous target remains separate and undeployed. The foundation adds no worker, S3, SQS, outbox, NAT gateway, load balancer, or custom IAM role. The app stays stopped until the operator explicitly verifies DuckDNS and activates HTTPS. Future resource changes, DNS updates, certificate requests, Google-origin changes, and teardown require operator authorization.

## What the templates propose

`cloudformation/images.yaml` creates three private, immutable, scan-on-push ECR repositories for API, web, and bootstrap images. `cloudformation/main.yaml` proposes one public x86_64 AL2023 `t3.medium` EC2 host with IMDSv2 and the supplied `LabInstanceProfile`, public IPv4, and security-group access only on HTTP/HTTPS; a private Single-AZ PostgreSQL 16.15 `db.t3.micro` (20 GiB gp2); private database subnets; five Secrets Manager ARN inputs; a CloudWatch log group with `RetainExceptOnCreate`; host/readiness alarms; and a successful bootstrap signal. Database snapshots and ECR repositories are retained by the current template, so stack deletion is not full cleanup.

The 4 GiB `t3.medium` is a provisional choice. The user-provided 2026-09-27 terminal transcript records the earlier API-image, AL2023, PostgreSQL, and Nginx rehearsal passing, but that script did not start the API. It therefore did not measure cold or ready API memory. The earlier warm measurement is not enough to establish a safe minimum. Do not reduce the instance based on that measurement.

The hostname and origin are `internshipmatcher.duckdns.org` and `https://internshipmatcher.duckdns.org`. The supplied public Google web client ID is `712181478711-b51rrs85d2vmvt52vr6ajo3bkv93vafi.apps.googleusercontent.com`; the authorized JavaScript origin has not been changed or verified. HTTP-01 is the selected certificate path, with port 80 retained for challenge and redirect. No DuckDNS token or database/signing secret values are stored here.

## Source identity and image flow

The source snapshot script includes only its explicit repository allowlist, hashes every included working-tree file (including dirty docs and untracked files), preserves executable modes, rejects `.env*` and generated directories, and writes a deterministic archive outside the repository. It rechecks staged bytes and modes against the manifest and aborts if files changed during snapshotting. Its SHA-256 identity covers the current commit and included file hashes. The build script saves the archive and manifest under `ARTIFACT_DIR/inf2006-<snapshot-sha>/`, resolves and pins every base-image digest, builds `linux/amd64` API/web/bootstrap images with a per-attempt immutable tag, attaches source labels, pushes them to the three ECR repositories, and saves `image-digests.env` plus `build-provenance.json`. The provenance records base-image digests and the hash of the public Google client-ID build argument; bootstrap compares that hash with the CloudFormation parameter before proceeding. Run the build on the user's Docker-enabled Mac; Apple Silicon builds use amd64 emulation and may take time. Keep `ARTIFACT_DIR` on persistent storage outside `/tmp` and `/var/tmp`, and preserve the build log, archive, manifest, provenance, and emitted digests. A failed partial push can leave an unused immutable image in retained ECR; review that storage before cleanup.

For a fresh environment, the setup order is: create the ECR repository stack; build and publish the snapshot; create the five secret values in Secrets Manager; then deploy the foundation stack. The current prepared run reuses the already-built image digests and existing five Secrets Manager records; it does not create or rotate secret values. Database secret JSON shapes are `{"username":"dbadmin","password":"…"}`, `{"username":"app_migrator","password":"…"}`, and `{"username":"app_runtime","password":"…"}`. Generate database passwords with `aws secretsmanager create-secret --generate-secret-string '{"SecretStringTemplate":"{\"username\":\"app_migrator\"}","GenerateStringKey":"password","PasswordLength":32,"ExcludePunctuation":true}'` (use the matching username/name for each secret). This keeps the generated value inside Secrets Manager instead of printing it into terminal output or shell history. The role bootstrap accepts punctuation in migrator/runtime passwords and percent-encodes them for SQLAlchemy; the master password is checked for RDS-forbidden characters before any database role SQL. The other secret shapes are `{"key":"base64url-signing-key"}` and `{"token":"DuckDNS-token"}`. The scripts accept secret ARNs and retrieve values at runtime; they do not put secret values in CloudFormation parameters, image layers, or shell output.

Run `bash tests/infra/rehearse-containers.sh` on the user's Docker-enabled Mac before any provisioning decision. The user-provided transcript records a successful run of the earlier version: local amd64 API image build, AL2023 package and pinned Compose install, PostgreSQL 16 non-superuser migrations/runtime grants, and `nginx -t` on all three configs. The current script additionally imports the root `data/synthetic_jobs.json` fixture through `app_runtime` (dry-run, apply, idempotent reapply), starts the API using the cloud Uvicorn override, checks `/health/ready`, and reports idle API/model-child container memory. These added checks have not yet run. The script makes no ECR push or AWS call and removes its disposable containers and one-day test certificate. The PostgreSQL rehearsal explicitly grants `SET` on the tested logging parameters to local `dbadmin`; this exercises the fail-closed SQL path but does not prove Learner Lab RDS permissions. Do not retry or bypass the agent's denied Docker socket; execute the current script from the user's terminal and retain its output.

For a changed teammate source tree, first run the separate image build helper after Docker and ECR access are available. It produces a new pinned artifact directory; keep that output outside the repository. For today's already-built image set, the deployment runner uses the checked-in nonsecret defaults and saved artifact directory directly.

```sh
# Preview: read-only AWS preflight and exact artifact/stack comparison.
python3 src/infra/scripts/deploy-foundation.py

# Deployment: only after the user has approved billable resource creation and activation.
python3 src/infra/scripts/deploy-foundation.py --apply

# For a later build, explicitly select that build's saved artifact directory.
python3 src/infra/scripts/deploy-foundation.py --artifacts \
  "$HOME/Documents/inf2006-artifacts/inf2006-<source-snapshot-sha256>" --apply
```

The runner validates the archive hash, archived manifest, every archived file hash/mode, the exact archived CloudFormation template, image digests, build provenance, and public Google client-ID hash. It performs a read-only preflight first, including caller identity, ECR digest existence, metadata-only lookup of all five named Secrets Manager records, latest AL2023 AMI, and a fail-closed existing-stack check. It never calls `GetSecretValue`. It defaults to preview; only `--apply` creates resources or activates the host. A matching healthy existing stack is left untouched; a mismatched or failed stack is preserved for diagnosis. The runner has no teardown path. It writes timestamped nonsecret progress logs beside the saved artifacts.

The first deployment may create billable EC2/RDS/network resources. `--apply` retains a failed stack for diagnosis, does not clean up resources automatically, and may leave resources that continue to incur charges. On an apply failure, use CloudFormation events and the instance's Systems Manager command output for diagnosis; do not retry over a failed stack or delete it without reviewing retained database snapshots, logs, ECR images, and secrets. The existing `build-and-publish-images.sh` remains a separate helper when source changes; rebuild/publish first, then pass the resulting artifact directory with `--artifacts`.
On first stack creation, the host bootstraps the vector extension and restricted database roles and runs Alembic using `app_migrator`. The deployment runner then imports the saved synthetic catalogue, updates and verifies DNS, activates HTTPS if needed, and checks public readiness. A healthy existing stack is left running without reimporting catalogue data. The API uses only `app_runtime`; that role has no DDL and cannot read `alembic_version`. Runtime PostgreSQL connections use `verify-full` with the RDS CA bundle mounted read-only. Access logs omit query strings, and API access logging is disabled. The privileged role-setup session explicitly sets PostgreSQL statement/error-statement logging controls with `ON_ERROR_STOP`; a denied setting stops bootstrap before role SQL. The Learner Lab RDS permission for these settings remains unverified and is a runtime gate. No RDS log export is configured.

The bootstrap image contains the `data/synthetic_jobs.json` fixture from the same source snapshot, and `/etc/inf2006/stack.env` records its digest-pinned URI. After SSM access is established and the database/migrations are ready, extract that fixture onto the EC2 host and validate the catalogue there through its private RDS route. The Mac cannot connect directly to the private database. From a Session Manager shell:

```sh
source /etc/inf2006/stack.env
fixture_container="$(docker create "$BOOTSTRAP_IMAGE_URI")"
trap 'docker rm -f "$fixture_container" >/dev/null 2>&1 || true' EXIT
docker cp "$fixture_container:/opt/inf2006/data/synthetic_jobs.json" /tmp/synthetic_jobs.json
docker rm "$fixture_container" >/dev/null
trap - EXIT
chmod 0600 /tmp/synthetic_jobs.json
docker compose --env-file /etc/inf2006/compose.env \
  -f /opt/inf2006/compose.cloud.yml run --rm --no-deps \
  -v /tmp/synthetic_jobs.json:/data/synthetic_jobs.json:ro \
  --entrypoint python api -m app.catalogue.import_jobs \
  --file /data/synthetic_jobs.json --dry-run
```

Review the dry-run counts and status before repeating the same command with `--file /data/synthetic_jobs.json` and no `--dry-run`; the apply run writes the synthetic jobs and embeddings. The API image already contains the pinned embedding model. Do not print or expand `/etc/inf2006/api.env` while troubleshooting.

The readiness alarm treats missing metrics as breaching. It is expected to alarm while the application is intentionally stopped before DNS/HTTPS activation; after activation, an absent metric indicates that the health-reporting timer or its permission path needs investigation.

The runner retrieves the current EC2 public IPv4, explicitly runs `update-duckdns.sh --apply`, and waits for public DNS before calling `enable-https.sh --apply` when readiness is not already healthy. Google browser sign-in remains a separate manual verification. The instance has a dynamic public IPv4, not an Elastic IP. After stop/start, the old CloudFormation IP output may be stale: use the instance ID output to query the live EC2 address, then repeat DNS verification/update and HTTPS checks. Automatic address recovery is not configured.

```sh
instance_id="$(aws cloudformation describe-stacks --region us-east-1 \
  --stack-name inf2006-foundation \
  --query "Stacks[0].Outputs[?OutputKey=='ApiHostInstanceId'].OutputValue | [0]" --output text)"
public_ip="$(aws ec2 describe-instances --region us-east-1 --instance-ids "$instance_id" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)"
# On the host, after operator review of the current IP and origin:
source /etc/inf2006/stack.env
export PUBLIC_IP='<current-public-ip>'
bash /opt/inf2006/src/infra/scripts/update-duckdns.sh --apply
```

## Cost and limits

The dated us-east-1 estimate is **$53.878/month ($1.7713/day at 730 hours)** before ECR image storage, CloudWatch log ingestion/storage, data transfer, snapshots, and other request charges. Components are: EC2 `t3.medium` $30.368; one public IPv4 $3.65; 24 GiB gp3 $1.92; five secrets $2.00; RDS `db.t3.micro` compute $13.14 and 20 GiB gp2 $2.30; two standard alarms plus one custom metric $0.50. The RDS compute and storage rates are from the AWS Pricing Calculator's us-east-1 PostgreSQL, Single-AZ, 100% utilization selection; the PostgreSQL 16.15 minor version was separately orderable-checked. This is an estimate, not a bill guarantee. EC2 is proposed in Standard credit mode: sustained use above baseline can exhaust earned credits and reduce CPU to baseline; no EC2 surplus charge is assumed. RDS T3 CPU-credit surplus charges are excluded from this estimate and must be checked against the selected RDS credit mode and observed use.

## Failure recovery and operator access

The runner uses `create-stack --disable-rollback` so failed resources remain available for diagnosis. An earlier live attempt using `--on-failure DO_NOTHING` was rejected by AWS; the prepared runner uses the supported rollback setting. A failed create can continue billing for EC2, RDS, EBS, and secrets until an operator reviews logs and deliberately removes the failed stack. Capture the bootstrap output and CloudFormation events before any cleanup; stack deletion may create the retained RDS final snapshot, and the log group/ECR repositories/secrets have their own retention and cleanup behavior. A retry with the same stack name cannot proceed while the failed stack exists. The log group's `RetainExceptOnCreate` policy removes it on a CloudFormation create rollback, but retains it on later stack deletion.

The host has no SSH key and port 22 is closed. Operator access uses Systems Manager Session Manager, subject to the supplied `LabRole`, SSM Agent readiness, and available lab endpoints/egress. These conditions have not been tested. After deployment approval, use the CloudFormation `ApiHostInstanceId` output and run `aws ssm start-session --region us-east-1 --target "$instance_id"`; confirm the session opens before relying on it for recovery. After an RDS restart or network outage, once database reachability has returned, restart the API and verify readiness:

```sh
docker compose --env-file /etc/inf2006/compose.env \
  -f /opt/inf2006/compose.cloud.yml restart api
docker compose --env-file /etc/inf2006/compose.env \
  -f /opt/inf2006/compose.cloud.yml ps
curl --fail --silent --show-error http://127.0.0.1:8080/health/ready
```

This is the documented manual recovery path; automated container recovery does not clear the app's latched readiness failure.

## Private API Gateway ingress preparation (local only)

The approved ingress preparation is deliberately separate from `cloudformation/main.yaml` and its legacy public-host HTTP-01 flow. `cloudformation/ingress-http-api.yaml` creates the HTTP API, `$default` route/stage, VPC Link, a dedicated internal ALB HTTPS listener, HTTPS target group for two existing app instances, and least-privilege ingress/egress security-group rules. Parameters identify the existing VPC, private subnets, app instances and ACM certificate. To suppress the EC2 default allow-all egress, each new group includes the documented `127.0.0.1/32` allow-all-protocol sentinel; explicit standalone rules add only VPC Link→ALB TCP 443 and ALB→app TCP 8443. The app target group permits ingress only from the ALB SG. Attach the output `AppTargetSecurityGroupId` to both existing app instances alongside required dependency/egress security groups, and inspect/remove any broader inbound rules that would defeat the intended source restriction. Existing security groups are additive, so the new target group must not replace unrelated groups. [CloudFormation security-group egress behavior](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-ec2-securitygroup.html). The full multi-instance/async target is not implemented or deployed. The template does not add Cognito, Lambda, DynamoDB, or CloudFront.

The execute-api origin serves both SPA assets and `/api/*`, so `APP_ORIGIN` is the exact `https://<api-id>.execute-api.<region>.amazonaws.com` origin. The `$default` route proxies paths without a stage prefix. API Gateway validates `TLS_SERVER_NAME` using SNI and hostname verification against the certificate on the ALB HTTPS listener. `TLS_SERVER_NAME` is independent of `APP_ORIGIN`. The existing foundation still defaults it to `PUBLIC_HOSTNAME` and still requires `APP_ORIGIN=https://PUBLIC_HOSTNAME`; private bootstrap mode does not call the DuckDNS A/AAAA update or legacy HTTP-01 activation helpers and does not require the DNS token on app hosts.

Private mode uses `compose.private-ingress.yml` and Nginx on host port 8443. It publishes no 8080 listener. A per-instance self-signed key and certificate are generated under `/etc/inf2006/tls`, outside the image. The ALB encrypts this target hop but does **not** validate its certificate; the template limits ALB egress to the target SG on 8443 and target ingress to ALB SG on 8443. The VPC Link SG may reach only ALB SG TCP 443, and the ALB accepts only that VPC Link SG on 443. The target group health check uses HTTPS `/health/ready`. Nginx forwards `Origin`, `Cookie`, `X-CSRF-Token`, request paths and multiple `Set-Cookie` response headers through the same origin. Missing `/assets/*` and known static asset extensions return 404 rather than SPA HTML. Access logs record the URI without query strings and do not log cookies, headers, or request bodies. Container-local Nginx-to-FastAPI remains HTTP.

The Gateway quota remains 10 MB per request, 30 seconds integration time, and 10,240 bytes for request line plus headers. Nginx's 6 MiB limit is above the 5,242,880-byte PDF limit with multipart overhead and below Gateway's payload cap. Existing code performs upload preparation, preview privacy checks and save privacy checks synchronously. The 30-second deadline is **not yet validated** on the proposed host class, including cold model loading and concurrent requests. Keep deployment blocked until synthetic near-limit multipart requests, authenticated preview/save, timeouts and retry idempotency are measured below a proposed 25-second engineering gate; this margin is a proposal, not a requirement. If those checks exceed the Gateway limit, stop and design explicit async state semantics rather than skipping privacy checks. The source does not currently prove API Gateway behavior for cookie duplication, static asset MIME/gzip, or Gateway-generated 429/502/504 responses.

### Local checks

These checks make no AWS, DNS, OAuth, certificate, or deployment request:

```sh
for script in src/infra/scripts/bootstrap-api.sh \
  src/infra/scripts/duckdns-acme-hook.sh \
  src/infra/scripts/ingress-certificate.sh \
  src/infra/scripts/create-target-tls.sh \
  src/infra/scripts/validate-ingress-config.sh \
  tests/infra/test-duckdns-acme-hook.sh \
  tests/infra/test-ingress-config.sh; do bash -n "$script"; done
python3 tests/infra/test_private_ingress_config.py
bash tests/infra/test-ingress-config.sh
bash tests/infra/test-duckdns-acme-hook.sh
```

The structural ingress suite substitutes temporary dummy bind paths before running Docker Compose config parsing. This avoids requiring the deployed host's `/etc/inf2006/api.env`, certificate, or RDS bundle, and does not start containers.

Offline checks on 2026-10-02: `src/backend/.venv/bin/python -m pytest -q tests/infra` passed 53 tests and 6 subtests; the dedicated ingress structural and mocked-certificate suite passed 7 tests; ingress-mode and mocked authoritative DNS hook shell checks passed; `bash -n` passed for changed shell scripts; and `git diff --check` passed. `npm run build -- --outDir /tmp/inf2006-ingress-dist` passed; the largest local asset was `assets/index-Ctxb8-E1.js` at 369,355 bytes (below the 10 MB Gateway payload ceiling). Earlier focused backend auth/Origin/CSRF tests passed 3 tests, and frontend auth/upload/save recovery tests passed 62 tests. Mocks verify new-ARN first import, in-place ARN reuse, failed-renew no-import, safe config parsing, and that the DNS hook refuses conflicting or partially propagated TXT state and only issues a TXT-scoped clear for the exact challenge value. No DuckDNS, AWS, certificate authority, Gateway, ALB, browser, or live multipart behavior was exercised. Gateway/ALB behavior, multiple `Set-Cookie` delivery, timeouts and cross-target recovery remain unverified.

### Separate execution approval checklist

Nothing below has been run. The operator must first verify DuckDNS control without printing the token; inspect actual account AZ IDs and choose two VPC Link eligible AZs (current us-east-1 VPC Link support lists `use1-az1`, `use1-az2`, `use1-az4`, `use1-az5`, and `use1-az6`, excluding `use1-az3`); check Learner Lab create permissions and service-linked role/ENI capabilities; confirm the app/ALB network and target stack; verify the complete certificate chain is trusted by API Gateway; and measure full synchronous request timing on the intended host.

The DNS-01 hook obtains `DUCKDNS_TOKEN_SECRET_ARN` at runtime and runs only under the certificate helper's shared `flock` lock. DuckDNS TXT state is shared across all subdomains in the account. Auth refuses to overwrite a different value and polls every authoritative DuckDNS nameserver until all return the exact challenge. Cleanup rechecks that every authoritative answer is exactly the challenge value, then sends `txt=<challenge>&clear=true`; DuckDNS interprets this TXT-scoped request as clearing TXT only. It never calls generic address-record cleanup. If records differ, cleanup preserves them. Staging ACME certificates use separate `/etc/letsencrypt-staging`, `/var/lib/letsencrypt-staging`, and `/var/log/letsencrypt-staging` directories and are for renewal rehearsal only; the production timer does not inspect them and they must never be imported for service.

For manual `sudo` commands, the helper reads `/etc/inf2006/ingress-acme.env` itself; systemd loads the same file for timer invocations. It accepts only these plain `NAME=value` entries (no shell code), requires root ownership and mode 0600, and never accepts the DuckDNS token itself:

```sh
sudo install -d -o root -g root -m 0700 /etc/inf2006
sudo install -o root -g root -m 0600 /dev/null /etc/inf2006/ingress-acme.env
sudoedit /etc/inf2006/ingress-acme.env
```

Before the first certificate issue, add `AWS_DEFAULT_REGION=us-east-1`, `TLS_SERVER_NAME=internshipmatcher.duckdns.org`, and `DUCKDNS_TOKEN_SECRET_ARN=<secret-arn>`. After the first import prints a new ACM ARN, add `INGRESS_CERTIFICATE_ARN=<returned-arn>` before renewal or reimport. These values are configuration identifiers, not the DuckDNS credential.

After separate approval for DNS writes and any ACM update, configure the region, DNS hostname, and Secrets Manager ARN in root-only `/etc/inf2006/ingress-acme.env`, then use these commands on the certificate-owning worker. They read the DuckDNS token directly from Secrets Manager and do not print it:

```sh
# DNS TXT writes and staging ACME issuance; no ACM import.
sudo /opt/inf2006/src/infra/scripts/ingress-certificate.sh --apply issue-staging

# First production issuance imports a new ACM cert and prints its ARN; later runs set that ARN.
sudo /opt/inf2006/src/infra/scripts/ingress-certificate.sh --apply issue

# Scheduled by inf2006-ingress-cert-renew.timer; may renew and reimport in-place.
sudo /opt/inf2006/src/infra/scripts/ingress-certificate.sh --apply renew
```

For first import, omit `INGRESS_CERTIFICATE_ARN`; ACM returns a new ARN for the operator to configure on the listener and in the root-only environment file. Subsequent renewal/reimport requires that exact ARN and updates it in place. Mutating actions require the explicit `--apply` gate. Certbot uses RSA-2048; import uses leaf `cert.pem`, the matching private key, and `chain.pem` separately. Renewal is scoped to the configured certificate name and its ACM import runs only after Certbot succeeds. The helper validates SAN, system-trusted chain and key match before import. Actual API Gateway trust remains unverified.

The systemd unit expects the same root-only environment file. After the worker, secret read, DNS ownership, CA chain, ACM permissions and renewal alerting have passed their separately approved setup checks, the reviewed operator commands are:

```sh
sudo install -m 0644 src/infra/systemd/inf2006-ingress-cert-renew.service /etc/systemd/system/
sudo install -m 0644 src/infra/systemd/inf2006-ingress-cert-renew.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now inf2006-ingress-cert-renew.timer
```

These host changes were not made. ACM imported certificates do not renew themselves; reimport to the existing ARN retains its ALB listener association. Local checks do not confirm ACM reaches `ISSUED` or that API Gateway trusts the chain; the actual private-integration TLS handshake remains a release gate.

After separately approving the exact resource plan, deploy the prepared ingress stack with the existing VPC/subnets/app instances and the issued ACM certificate. The app instances must already serve the private Nginx target on 8443. Example command shape (replace every placeholder with values reviewed for the approved account and stack):

```sh
aws cloudformation deploy --region us-east-1 \
  --stack-name inf2006-private-ingress \
  --template-file src/infra/cloudformation/ingress-http-api.yaml \
  --parameter-overrides \
    VpcId='<existing-vpc-id>' \
    AppInstanceIdA='<private-app-instance-a>' \
    AppInstanceIdB='<private-app-instance-b>' \
    IngressCertificateArn='<acm-certificate-arn-from-first-issue>' \
    BackendTlsServerName='internshipmatcher.duckdns.org' \
    VpcLinkSubnetIdA='<private-subnet-a>' \
    VpcLinkSubnetIdB='<private-subnet-b>'
```

The template creates the internal ALB, HTTPS listener, target group, VPC Link, and restricted VPC Link/ALB/app ingress rules. It outputs the API origin and listener ARN; the listener ARN is also exported for a separately managed integration if the stack is split later. Attach `AppTargetSecurityGroupId` to both existing app instances while preserving their required egress groups. `Deployment` resources are snapshots while `$default` has `AutoDeploy: false`. For every route/integration release, change `DeploymentR1` to the next unused logical ID (for example `DeploymentR2`) and update `DefaultStage.DeploymentId` to reference that ID. A `DeploymentRevision` label or description change does not create a deployment. Inspect the change set for a new deployment and stage update, and only then execute under separate approval. VPC Link subnet/security-group changes require replacement planning; do not silently mutate the existing link.

After separately approved stack creation and SG attachment, inspect deployment health with:

```sh
aws cloudformation describe-stacks --region us-east-1 --stack-name inf2006-private-ingress \
  --query 'Stacks[0].Outputs[?OutputKey==`PublicApiOrigin` || OutputKey==`AppHttpsTargetGroupArn`].[OutputKey,OutputValue]' \
  --output table
aws elbv2 describe-target-health --region us-east-1 --target-group-arn '<AppHttpsTargetGroupArn-output>'
curl --fail --show-error 'https://<api-id>.execute-api.us-east-1.amazonaws.com/health/ready'
curl --fail --show-error 'https://<api-id>.execute-api.us-east-1.amazonaws.com/'
```

Before attaching the app target SG, inspect the current security-group IDs for each instance. Include all required existing egress/dependency groups when adding the output group; the `--groups` argument replaces the instance's SG list, so omitting an existing group can interrupt database, ECR, SSM or NAT access. Do not accept the route until both targets report healthy and the same-origin browser acceptance checks below pass.

Before enabling users, verify execute-api HTTPS loads `/`, hashed JS/CSS/fonts/images, and deep-link refresh; confirm MIME, content encoding, cache-control and query handling; upload synthetic PDFs near 5 MiB and over the application limit and verify body bytes/hash, content type and expected errors; preserve bootstrap cookie deletion plus session cookie issuance and multiple `Set-Cookie` headers; test cookie reuse, Origin and CSRF, 204 logout, two-account isolation, request/response headers, and no-CORS same-origin behavior; test 4xx/5xx envelopes, 429/502/504 retry UI, integration failure, and timeout with idempotent save recovery; remove one target and observe service recovery; and measure cold/warm/concurrent upload, preview, privacy checks, and saves against the 30-second Gateway limit. Do not log cookies, authorization, PDF body, OAuth credentials, or DuckDNS tokens. Fresh local app tests are useful regressions but cannot establish these Gateway/ALB properties.

Capture sanitized Gateway status/latency/integration errors/throttles, ALB target health, app health, queue age/DLQ counts and certificate expiry. The template's access log excludes source headers and query strings. Prove Gateway-to-ALB TLS with the real imported certificate; test an incorrect server name and certificate failure only using a temporary test integration. ALB-to-target TLS is encryption-only. Record the test date, exact command, fixture and expected/actual result before making any acceptance claim.

### Cost, rollback, and teardown planning

Planning-only monthly baseline for the current private template at 730 hours is approximately **$172.30/month**, conditional on assumed us-east-1 rates: two app `t3.small` ($30.51); one provisional worker `t3.medium` ($30.51); ALB base hours ($16.43) before LCU; two NAT gateways at assumed $0.045/hour each ($65.70); two public IPv4 addresses at $0.005/hour ($7.30); 80 GiB gp3 across the current 24+24+32 GiB disks ($6.40); and 20 GiB gp2 RDS at assumed $0.115/GiB-month plus assumed $0.018/hour `db.t3.micro` compute ($15.44). The RDS us-east-1 prices and NAT rate need final calculator confirmation; NAT's cited rate is an Ohio example. One average ALB LCU adds about $5.84/month. Also exclude API requests (first tier $1/million metered in 512 KiB units), transfer, ECR ($0.10/GB-month), Secrets Manager ($0.40/secret-month plus API calls), CloudWatch ingestion (example $0.50/GB), snapshots, tax, RDS/EC2 credit effects, and variable usage. These values are assumptions and public-rate examples, not a quote or a free-tier claim. Recalculate before requesting execution approval.

For an approved trial rollback, first disable the public route or API stage, then delete its HTTP API stack. Delete the VPC Link only after all integrations release it. Remove only the tagged trial internal ALB/target groups/security groups and trial certificate if separately approved. Stop/disable the renewal timer and remove only the trial DNS challenge TXT value after confirming no issuance is active. Inspect retained access logs, secrets, ECR, EBS and RDS snapshots; preserve shared EIPs/resources and required evidence. No cleanup is automatic, and this preparation task performed no provisioning or teardown.

After a separate cleanup approval, stop the renewal timer, disable the execute-api endpoint, remove the attached app-target SG from each existing instance while specifying its complete reviewed pre-existing SG list, and delete only this stack:

```sh
sudo systemctl disable --now inf2006-ingress-cert-renew.timer
aws apigatewayv2 update-api --region us-east-1 --api-id '<ApiId-output>' \
  --disable-execute-api-endpoint
aws ec2 modify-instance-attribute --region us-east-1 --instance-id '<app-instance-id>' \
  --groups '<reviewed-existing-security-group-id-1>' '<reviewed-existing-security-group-id-2>'
aws cloudformation delete-stack --region us-east-1 --stack-name inf2006-private-ingress
aws cloudformation wait stack-delete-complete --region us-east-1 --stack-name inf2006-private-ingress
```

Repeat the EC2 command for the other instance with its complete reviewed SG list. CloudFormation retains the configured API access log group; inspect and remove that retained log group only if separately approved. The template does not own the ACM certificate, application instances, database, EIPs or DNS records.

Official pricing references: [EC2 T3](https://aws.amazon.com/ec2/instance-types/t3/), [ELB](https://aws.amazon.com/elasticloadbalancing/pricing/), [VPC public IPv4 and NAT](https://aws.amazon.com/vpc/pricing/), [RDS PostgreSQL](https://aws.amazon.com/rds/postgresql/pricing/), [EBS](https://aws.amazon.com/ebs/pricing/), [API Gateway](https://aws.amazon.com/api-gateway/pricing/), [ECR](https://aws.amazon.com/ecr/pricing/), [Secrets Manager](https://aws.amazon.com/secrets-manager/pricing/), and [CloudWatch](https://aws.amazon.com/cloudwatch/pricing/).

Sources: [EC2 sizing rate reference](https://docs.aws.amazon.com/prescriptive-guidance/latest/optimize-costs-microsoft-workloads/right-size-selection.html), [EBS pricing](https://docs.aws.amazon.com/en_en/emr/latest/ManagementGuide/emr-plan-storage-compare-volume-types.html), [VPC public IPv4 pricing](https://aws.amazon.com/vpc/pricing/), [Secrets Manager pricing](https://aws.amazon.com/secrets-manager/pricing/), [RDS PostgreSQL calculator](https://calculator.aws/#/createCalculator/RDSPostgreSQL), [CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/), [ECR pricing](https://aws.amazon.com/ecr/pricing/).

Preparation evidence, exact validation scope, observed permission limits, and runtime blockers are in [`evidence/cloud-foundation-preparation-2026-09-27.md`](../../evidence/cloud-foundation-preparation-2026-09-27.md). The dated run record distinguishes user-reported temporary resources and scoped checks from current state and full application acceptance; Google login, backup/restore, and complete end-to-end acceptance remain incomplete.
