# Synchronous AWS foundation preparation

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

Sources: [EC2 sizing rate reference](https://docs.aws.amazon.com/prescriptive-guidance/latest/optimize-costs-microsoft-workloads/right-size-selection.html), [EBS pricing](https://docs.aws.amazon.com/en_en/emr/latest/ManagementGuide/emr-plan-storage-compare-volume-types.html), [VPC public IPv4 pricing](https://aws.amazon.com/vpc/pricing/), [Secrets Manager pricing](https://aws.amazon.com/secrets-manager/pricing/), [RDS PostgreSQL calculator](https://calculator.aws/#/createCalculator/RDSPostgreSQL), [CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/), [ECR pricing](https://aws.amazon.com/ecr/pricing/).

Preparation evidence, exact validation scope, observed permission limits, and runtime blockers are in [`evidence/cloud-foundation-preparation-2026-09-27.md`](../../evidence/cloud-foundation-preparation-2026-09-27.md). The dated run record distinguishes user-reported temporary resources and scoped checks from current state and full application acceptance; Google login, backup/restore, and complete end-to-end acceptance remain incomplete.
