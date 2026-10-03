# Private async cloud rollout preparation

**Status as of 2026-10-03: the private target is deployed, with partial
acceptance evidence from direct CUA browser observations and operator-reported
checks.** The private-base retry reached
`UPDATE_COMPLETE`; ingress and app reached `CREATE_COMPLETE`. Worker health,
certificate, browser, queue, monitoring, and controlled single-target
continuity observations are recorded in
[`evidence/cloud-acceptance-2026-10-03.md`](../evidence/cloud-acceptance-2026-10-03.md).
The direct CUA observations cover browser behavior described in that record;
deployment, worker, certificate, queue, monitoring, and continuity details are
operator-reported. This document update did not query AWS or repeat the
operator's CLI checks. Full coursework acceptance remains open. The older
synchronous foundation (`src/infra/cloudformation/main.yaml`,
`deploy-foundation.py`, and `compose.cloud.yml`) remains a separate historical
path. The sequence and placeholder commands below are retained as rollout
guidance, not as a transcript of the reported deployment. No secrets, image
digests, AWS credentials, account IDs, or public URLs belong in this file.

## Layers and dependency order

1. Build and review immutable API, web, and bootstrap images from one source
   snapshot using `src/infra/scripts/build-and-publish-images.sh`. Copy only
   their digest URIs and the matching snapshot SHA into an operator-reviewed
   parameter plan. Do not use mutable image tags.
2. Deploy `private-base.yaml` into a new stack. It creates a fresh tagged VPC,
   two public NAT subnets with two new tagged EIPs/NAT gateways, two private
   app/ingress subnets, two isolated database subnets, an S3 gateway endpoint,
   one private Single-AZ encrypted PostgreSQL 16.15 `db.t3.micro`/20 GiB gp2,
   a private temporary-input bucket, two separately encrypted SQS queues and
   their DLQs, and one private worker in AZ A. It uses the existing
   `LabInstanceProfile`; it creates no IAM role or policy. The worker has no
   public IP or SSH ingress, requires IMDSv2 with hop limit 2, creates the DB
   roles and applies migrations once, then starts separate extraction and
   embedding workers. Its root-only ACME environment file contains the
   hostname and DuckDNS secret ARN only. It installs the existing renewal unit
   files. The earlier preparation left the timer disabled and did not request
   or import a certificate. The operator now reports a production import,
   successful same-resource reimport, and an active custom timer; see the dated
   evidence above. A due renewal through the complete hook and deployment path
   has not yet been demonstrated.
   Worker egress retains HTTPS and database access and adds UDP/TCP port 53 to
   `0.0.0.0/0` for DNS queries to DuckDNS authoritative nameservers; no inbound
   rule is added. The ACME hook script is a separate operational overlay and
   must be installed on the current worker before certificate issuance. It is
   not present in the already published worker image/source snapshot.
3. The operator reports installing Certbot 2.6, saving the certificate ARN in
   protected worker configuration, and passing a separate renewal dry run.
   The custom renewal timer is reported active and the generic timer disabled.
   The updated hook is an operational overlay on the current worker, not part
   of the published worker image. Do not treat these separate checks as proof
   of a complete due-renewal/redeployment cycle. For any future certificate or
   DNS operation, obtain its own concrete approval and never put a DuckDNS
   token value in a parameter, document, command line, or log.
4. Deploy `ingress-http-api.yaml` with
   `TargetRegistrationMode=asg`, the new VPC and the two app/ingress subnet
   IDs, the imported certificate ARN, and the verified DuckDNS name. This
   creates the public HTTP API, VPC Link, internal ALB HTTPS listener, and an
   initially empty target group. It outputs the execute-api origin, target
   group ARN, and app target SG. The existing default `instances` mode still
   registers two static instance IDs and preserves the earlier ingress path.
5. Update the Google GIS authorized JavaScript origin separately to the exact
   execute-api origin from ingress. Then deploy `private-app.yaml` with that
   origin, the ingress target-group/app-target-SG outputs, the base app SG and
   subnet/database/bucket/queue outputs, existing secret ARNs, and immutable
   image digests. Its two-instance ASG is private in both AZs, min/max/desired
   capacity 2, has IMDSv2 hop limit 2, and attaches to the target group. App
   bootstrap fetches only runtime/signing secrets; it does not run DB role
   setup or migrations. Each instance publishes with the DB-leased outbox
   publisher already configured in the API. The app `APP_ORIGIN` is the
   execute-api hostname, while target TLS remains the existing per-instance
   encryption-only HTTPS hop on 8443.
6. Check both ALB targets healthy, API readiness, same-origin SPA/API behavior,
   synthetic upload/extraction/save/embedding, duplicate SQS delivery,
   retries/DLQs, instance replacement, queue-age/DLQ alarms, cross-instance
   sessions, and database snapshot restore into a separate recovery database.
   Only claim acceptance for checks with dated commands and captured sanitized
   results. The shared lab role, service availability, model memory, and lab
   runtime limits remain verification gates.

Run the safe local preflight from the repository root:

```sh
src/backend/.venv/bin/python src/infra/scripts/plan-private.py --plan
```

It parses the three templates and prints their dependency order. It does not
look up credentials, read `.env` files, contact AWS, create a change set, or
apply infrastructure. Unknown options such as `--apply` are rejected. The
template parameter values should be reviewed separately and supplied only
after the operator approves a concrete deployment step. The preflight may
optionally check a reviewed JSON parameter-name map with `--parameters`, but
never prints parameter values and rejects literal secret-value fields.

The placeholder commands below are retained as a reproducible preparation
recipe; they are not the operator's execution transcript. The operator reports
that the stacks are now deployed as summarized above. These examples use
`--no-execute-changeset`; resolve placeholders from stack outputs and inspect
each change set before any separately approved future execution:

```sh
aws cloudformation deploy --region us-east-1 \
  --stack-name inf2006-private-base \
  --template-file src/infra/cloudformation/private-base.yaml \
  --no-execute-changeset \
  --parameter-overrides \
    AmiId='<reviewed-al2023-x86-ami>' \
    ApiImageUri='<api-digest-uri>' BootstrapImageUri='<bootstrap-digest-uri>' \
    SourceSnapshotSha256='<64-hex-source-snapshot-sha256>' \
    DatabaseMasterPasswordSecretArn='<existing-master-secret-arn>' \
    DatabaseMigratorSecretArn='<existing-migrator-secret-arn>' \
    DatabaseRuntimeSecretArn='<existing-runtime-secret-arn>' \
    DuckDnsTokenSecretArn='<existing-duckdns-token-secret-arn>'
```

The operator reports that staging issuance, production issuance/import, a
same-resource reimport, and a separate Certbot dry run passed. DNS/ACM changes
remain external operations; the local preflight does not perform them. A full
production renewal through DNS propagation, ACM replacement, and deployment
after certificate expiry remains an acceptance gate.

Create ingress first with its empty ASG-mode target group:

```sh
aws cloudformation deploy --region us-east-1 \
  --stack-name inf2006-private-ingress \
  --template-file src/infra/cloudformation/ingress-http-api.yaml \
  --no-execute-changeset \
  --parameter-overrides \
    TargetRegistrationMode=asg \
    VpcId='<private-base-VpcId-output>' \
    IngressCertificateArn='<operator-reviewed-acm-certificate-arn>' \
    BackendTlsServerName='internshipmatcher.duckdns.org' \
    VpcLinkSubnetIdA='<private-base-AppSubnetAId-output>' \
    VpcLinkSubnetIdB='<private-base-AppSubnetBId-output>'
```

After reviewing/executing that change set, copy `PublicApiOrigin`,
`AppHttpsTargetGroupArn`, and `AppTargetSecurityGroupId` from ingress outputs.
Configure that exact origin in the Google GIS client under separate approval.
Then create the app change set:

```sh
aws cloudformation deploy --region us-east-1 \
  --stack-name inf2006-private-app \
  --template-file src/infra/cloudformation/private-app.yaml \
  --no-execute-changeset \
  --parameter-overrides \
    AmiId='<reviewed-al2023-x86-ami>' \
    ApiImageUri='<api-digest-uri>' WebImageUri='<web-digest-uri>' BootstrapImageUri='<bootstrap-digest-uri>' \
    SourceSnapshotSha256='<same-64-hex-source-snapshot-sha256>' \
    AppOrigin='<exact-PublicApiOrigin-output>' TlsServerName='internshipmatcher.duckdns.org' \
    GoogleClientId='<reviewed-public-google-web-client-id>' \
    AppSubnetAId='<private-base-AppSubnetAId-output>' AppSubnetBId='<private-base-AppSubnetBId-output>' \
    BaseAppSecurityGroupId='<private-base-AppSecurityGroupId-output>' \
    AppTargetSecurityGroupId='<ingress-AppTargetSecurityGroupId-output>' \
    IngressTargetGroupArn='<ingress-AppHttpsTargetGroupArn-output>' \
    DatabaseEndpoint='<private-base-DatabaseEndpoint-output>' \
    DatabaseName='<private-base-DatabaseName-output>' \
    DatabaseRuntimeSecretArn='<private-base-DatabaseRuntimeSecretArn-output>' \
    AppSigningKeySecretArn='<existing-signing-key-secret-arn>' \
    TemporaryInputBucket='<private-base-TemporaryInputBucket-output>' \
    ExtractionQueueUrl='<private-base-ExtractionQueueUrl-output>' \
    EmbeddingQueueUrl='<private-base-EmbeddingQueueUrl-output>'
```

`--no-execute-changeset` only prepares the change set. Inspect each resource
addition/replacement/deletion and execute it only after the corresponding
separate approval. The app template accepts only immutable image digests and
does not create a public IP or invoke migrations.

Base creates replacement EIPs only for its own NAT gateways. The two AZ IDs
default to the supported `use1-az2` and `use1-az4`; the template rejects equal
IDs. Do not select the unsupported `use1-az3` mapping. RDS is Single-AZ even
though its subnet group spans both AZs. RDS deletion snapshots are retained.
The S3 bucket itself is retained at stack deletion and has a one-day expiration
backstop; manually inspect and empty/delete only that bucket after separate
approval. SQS queues use SSE-SQS, 900-second visibility, long polling, and
maxReceiveCount 5 to distinct 14-day DLQs. S3 is private, blocks public access,
denies insecure transport, and expires incomplete multipart uploads.

The worker uses the DB lease as authority; SQS visibility and its database
lease are both 15 minutes. The API only acknowledges outbox sends after SQS
confirms publication. The app and worker runtime use S3/SQS via normal SDK TLS
validation and IMDSv2 role credentials. The approved-content embedding worker
reads PostgreSQL only and never reads PDFs. The API's synchronous owner/privacy
checks remain unchanged. Queue/DLQ alarms and CloudWatch streams are scoped to
the new stack. Worker/app bootstrap does not pass secret values in user data.

## Failed first base-stack create — 2026-10-02 history

This section preserves the earlier failure and recovery guidance. On
2026-10-03, the operator reported that a later base-stack update completed and
the worker became healthy; see the [dated evidence](../evidence/cloud-acceptance-2026-10-03.md).
The current resource inventory was not independently checked during this
documentation update. Do not use the historical failed-state commands below
without first reviewing current stack state and obtaining the applicable
approval.

**User-reported evidence on 2026-10-02:** the `inf2006-private-base` stack is in
`ROLLBACK_COMPLETE`. CloudFormation recorded `WorkerInstance CREATE_FAILED`
after an explicit `FAILURE` signal at 2026-10-02T14:49:28.377Z. The worker EC2
instance was removed during rollback, and the worker CloudWatch log group is
absent. This confirms that worker bootstrap signalled failure; it does not
identify which command or dependency failed.

A later user-approved retry used rollback-disabled creation and retained the
worker instance and supporting billable resources after `CREATE_FAILED`. The
captured sanitized marker identified `stage=system-packages`, `line=33`,
`exit_status=1`. The accompanying AL2023 package output confirmed the cause:
the image already had `curl-minimal` installed, while the bootstrap requested
the conflicting full `curl` package in the same `dnf install` transaction.
This was a package conflict, not evidence of an HTTPS or network failure.
The local template fix leaves `curl` out of that package list, uses the
preinstalled command when available, installs only `curl-minimal` if the
command is absent, and fails closed unless `curl --version` advertises HTTPS.
It does not use `--allowerasing` or `--skip-broken`. The app instance UserData
uses the same guarded package logic. The historical `main.yaml` path is
unchanged.

UserData already tees output to
`/var/log/inf2006-worker-bootstrap.log`, journald, and the EC2 console. The
local file disappeared with the rolled-back instance. The worker log group has
`DeletionPolicy: RetainExceptOnCreate`, so first-create rollback removes that
new group. Container `awslogs` streams start only when the two worker services
are launched later in bootstrap. An empty log group therefore does not locate
the failure.

The local diagnostic overlay adds only fixed bootstrap-stage, source-line, and
exit-status markers to that existing output. It does not print command text,
environment values, secret ARNs, or secret values, and it does not stream logs
to CloudWatch. `cfn-signal` resource signaling for this `CreationPolicy` accepts
an exit code but not a reason; AWS documents `--reason` only for wait-condition
handles ([`cfn-signal` options](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/cfn-signal.html)).
If `cfn-signal` is unavailable early in boot, the local marker is still written
but CloudFormation receives no explicit failure signal and will wait for the
creation timeout.

This diagnostic overlay and package correction change the CloudFormation
templates only. For a reviewed retry,
reuse the already approved published API/bootstrap image digests and the source
snapshot hash those image labels contain. Do not rebuild, relabel, or describe
those images as containing these template-only changes.

At that earlier preparation checkpoint, worker DNS egress and the fail-closed
DuckDNS hook were local-only. The operator now reports that the worker-only
security-group update was applied and the hook was installed on the current
worker as a separate overlay. The published image digests and recorded source
snapshot remain unchanged and do not contain the updated hook. No inbound
security-group rule was added for outbound DNS queries.

The earlier `ROLLBACK_COMPLETE` stack and rollback-disabled failed attempt are
distinct historical states. The operator's later `UPDATE_COMPLETE` report does
not establish what happened to every resource retained from those attempts.
Inspect the current stack and resource inventory before any recovery or cleanup;
do not delete retained resources or reuse a stack name without separate
approval.

The local template introduced the `WorkerInstanceRecovery` logical ID and
stable `WorkerInstanceId` output as a proposed retry mechanism. The operator
later reported a successful base-stack update, but the current logical
resource-to-instance mapping was not independently checked. Before a future
update, inspect its change set and current resources; do not assume the
historical expected worker replacement or that other retained resources are
unchanged.

Historical recovery command example only; do not reuse it as the current
recovery action. Any future update needs a fresh status review, a concrete
change-set review, and separate execution approval:

```sh
aws cloudformation execute-change-set --region us-east-1 \
  --stack-name inf2006-private-base \
  --change-set-name '<reviewed-update-change-set>' \
  --disable-rollback
```

Rollback-disabled failure preserves resources for diagnosis and can continue
charging for the EC2 instance, RDS, NAT gateways, EIPs, and other created
resources. After a failed update, read the stack events and resource list, then
retrieve the prior `WorkerInstance` console output or use Session Manager if
the instance is registered and reachable. Inspect
`/var/log/inf2006-worker-bootstrap.log` on the retained instance. Capture the
sanitized failure markers and required diagnostics before considering any
cleanup. Delete only the reviewed trial resources after separate approval;
inspect retained snapshots, buckets, and logs separately.

The package correction alone does not restart UserData on a retained
instance. Rebooting it or updating its launch template must not be treated as
replaying bootstrap. Session Manager access may be used only for separately
approved read-only inspection until CloudFormation convergence and a safe
resume boundary are established. Do not replay a whole UserData script
blindly: it may repeat completed actions. The 2026-10-02 preparation described
here performed no repair, stack-state change, new retry, or cleanup; the later
operator-reported update is documented separately above.

## Cost and evidence boundaries

The **2026-10-02 template-planning estimate** was about $172.30/month at 730
hours under its stated us-east-1 assumptions. It is historical, not a current
bill or estimate for the deployed footprint. Recalculate using the actual
two-app plus worker sizes, storage, and any resources retained from failed
attempts; no current bill or complete retained-resource inventory was verified
for the 2026-10-03 evidence record. NAT data, ALB LCUs, API requests, log
ingestion, snapshots, storage, and credits add variable cost. Measure real
synthetic cold and warm workloads before making worker capacity claims.

### App rollout recovery

For a failed **first create**, capture the app stack events and retained app
bootstrap logs before changing anything. If the app stack is in a failed terminal
state, remove only `inf2006-private-app` after review; keep the private base,
database, worker, queues, bucket, and ingress stack intact so the failure can be
diagnosed and the same app layer retried. Do not delete the base stack as an app
rollback.

For a failed **update**, first inspect the stack status and events. CloudFormation
normally restores the prior launch-template content and app parameters during
automatic rollback. If it reports `UPDATE_ROLLBACK_FAILED`, correct the reported
cause, then continue the stack rollback without skipping resources:

```sh
aws cloudformation describe-stack-events --region us-east-1 --stack-name inf2006-private-app
aws cloudformation continue-update-rollback --region us-east-1 --stack-name inf2006-private-app
aws cloudformation wait stack-update-rollback-complete --region us-east-1 --stack-name inf2006-private-app
```

If an update completed but the new release fails acceptance, restore the saved
previous template and full parameter set, including API/web image digests,
configuration, and capacity, by preparing an app-only change set. Review that
it changes only the app launch template/ASG and expected app settings, then
execute it after separate approval. Check both prior-release targets healthy
before re-enabling user traffic. Preserve ingress, database, queues, and S3 data
throughout. Do not guess the prior image or config from the current stack; use
the recorded pre-update parameter set and release manifest.

The documentation preparation itself did not query AWS, read secret values,
launch Docker, connect to a database, or change deployment state. The
operator-reported cloud actions and their limits are recorded in
[`evidence/cloud-acceptance-2026-10-03.md`](../evidence/cloud-acceptance-2026-10-03.md).
Review a fresh change set before any future infrastructure update.

## Scoped teardown

After separate teardown approval, disable the execute-api entry point, stop the
renewal timer on the worker and remove only the trial DNS challenge value after
confirming issuance is inactive. Delete in reverse dependency order:

```sh
aws cloudformation delete-stack --region us-east-1 --stack-name inf2006-private-app
aws cloudformation wait stack-delete-complete --region us-east-1 --stack-name inf2006-private-app
aws cloudformation delete-stack --region us-east-1 --stack-name inf2006-private-ingress
aws cloudformation wait stack-delete-complete --region us-east-1 --stack-name inf2006-private-ingress
aws cloudformation delete-stack --region us-east-1 --stack-name inf2006-private-base
aws cloudformation wait stack-delete-complete --region us-east-1 --stack-name inf2006-private-base
```

The base stack retains its RDS snapshot, CloudWatch log group, and S3 bucket.
Review and remove only its own tagged bucket after verifying temporary-object
expiry and operator authorization. Confirm the stack-tagged NAT gateways and
their two new EIPs were removed. Preserve the four pre-existing EIPs, both
pre-existing VPCs, ECR repositories, shared Secrets Manager entries, and all
unrelated resources. No teardown helper deletes retained data automatically.
