# Synchronous foundation preparation evidence — 2026-09-27

Status: prepared for independent review; provisioning remains paused. No CloudFormation stack, EC2 host, RDS instance, ECR repository, secret, DNS record, or certificate was created by this work. All AWS checks recorded below were read-only except the EC2/VPC dry-run requests. Dry-run success is not resource creation or blanket deploy permission.

## User-provided local rehearsal transcript and current extension status

The user supplied a terminal transcript dated 2026-09-27 showing the earlier `tests/infra/rehearse-containers.sh` run completed to the shell prompt. It records a local `linux/amd64` API image build; successful AL2023 package installation and pinned Docker Compose v2.39.4 checksum/version; PostgreSQL 16 migrations and repeated role setup; successful `app_runtime` data access; expected denials when `app_runtime` attempted DDL and read `alembic_version`; and successful `nginx -t` for all three checked-in configurations. This is pasted user-run local evidence, not a run performed by this agent. The transcript shows the rehearsal explicitly granting local `dbadmin` permission to set the protected logging parameters. It does not settle whether Learner Lab RDS permits those settings.

That earlier script built the API image but did not run the catalogue importer or start the API. The current rehearsal script adds catalogue dry-run, import, and idempotent re-import from the root `data/synthetic_jobs.json` through `app_runtime`, then starts Uvicorn with the cloud entrypoint override, waits for actual `/health/ready`, and reports idle API plus model-child memory. These newly added stages are prepared but unrun. The earlier terminal transcript must not be treated as evidence for them. The agent Docker socket is denied; no additional socket attempt is made. The required next local check is for the user to run `bash tests/infra/rehearse-containers.sh` in their Docker-enabled terminal after reviewing the changed script and retain the output. The memory sample, if that run succeeds, is an idle ready-state observation and does not establish peak/workload capacity.

The scoped S5.1-A02 alternatives record is now present in `docs/CLOUD_ARCHITECTURE.md`: it captures the proposed EC2 plus private RDS choice and alternatives, while leaving formal team-owner/professor confirmation, deployment permissions, and provisioning authorization open. No architecture sign-off or resource approval is inferred.

## Foundation repair follow-up — supersedes prior readiness wording

The follow-up repairs address the verified AL2023 package conflict, Compose plugin availability, Alembic percent interpolation, PostgreSQL default-privilege ownership, fail-closed privileged logging checks, source snapshot rename parsing, image build provenance, log query-string exposure, and CloudFormation rollback log retention. The catalogue runbook now obtains its fixture from the digest-pinned bootstrap image on the EC2 host before dry-run/apply; no assumption of Mac-to-private-RDS connectivity is made. The stack failure mode is explicitly `DO_NOTHING`, with manual review and cleanup costs documented. These code and documentation changes do not establish deployed behavior.

The independent review then found that PostgreSQL 16 rejects `NOSUPERUSER` in the non-superuser `ALTER ROLE` statement. The role setup now uses one shared SQL file in both production bootstrap and the container rehearsal; it checks existing target roles for unexpected elevated attributes or memberships before changing credentials/attributes, allowing only PostgreSQL 16's creator grant to each target role by the current admin with `ADMIN TRUE`, `INHERIT FALSE`, and `SET FALSE`. It omits `NOSUPERUSER` from `ALTER` while retaining it on `CREATE`. The rehearsal applies this same create/alter sequence twice as non-superuser `dbadmin`, around the Alembic migration. Its locally built API image tag is unique to the temporary run directory, so cleanup cannot delete an operator's fixed tag.

Before the updates recorded in this evidence addendum, `python3 -m unittest tests.infra.test_cloud_repairs tests.infra.test_template_contract -v` passed **30 tests**, including behavior coverage of the actual membership-query predicate against allowed and rejected membership fixtures, PG16 ALTER attributes, shared twice-invoked role SQL, and unique rehearsal image tag; `bash -n` passed for the rehearsal and every infra shell script, `py_compile` passed for the source snapshot builder and Alembic URL helper, and `git diff --check` passed. The user-supplied transcript documents a successful earlier local image/AL2023/PostgreSQL/Nginx rehearsal as described above. The expanded catalogue/API readiness stages are not covered by those checks or that transcript. No ECR push or cloud runtime test is claimed. Learner Lab RDS permission to set the protected logging parameters remains an explicit fail-closed deployment gate.

The CloudFormation hashes validated in the historical observation section below refer to earlier template bytes. They do not validate the repaired templates. Frozen template hashes are `main.yaml` **66dfb5fb2ea1726317f3a30c8f6e1e824b7c891cd3d256d3a2d2a16bff42513c** and `images.yaml` **b2ae804fdaf58017e69fc563cf3c6f959b53a3d94c81bd4d1ee111bd0a51041f**. The parent’s read-only CloudFormation `ValidateTemplate` call passed against the current `main.yaml` bytes, matching SHA-256 `66dfb5fb2ea1726317f3a30c8f6e1e824b7c891cd3d256d3a2d2a16bff42513c`; it reported 24 parameters and no capabilities. The validation used `inf2006-repaired-66dfb5fb.yaml`. The initial CloudShell `GetEnvironmentStatus` request was denied; after the user restarted the Learner Lab, access returned. No bypass or alternate access path was used. The previous “independent review passed with concerns” wording is historical and is not a current approval recommendation.

## Local checks and artifact identity

Run from the repository root:

```sh
python3 tests/infra/test_template_contract.py
for script in src/infra/scripts/*.sh; do bash -n "$script"; done
python3 -m py_compile src/infra/scripts/create-source-snapshot.py
```

The contract tests parse CloudFormation YAML and assert the scoped resource inventory, private Single-AZ RDS exposure, digest-pinned image shapes, supplied profile reference, signal handling, runtime CA mount and HTTPS forwarding, failing-on-missing readiness, secret-handling guardrails, separated database roles/migrations, explicit DNS apply, unique immutable image-attempt tags, and deterministic secret-excluding source snapshots. Result: **17 tests passed**. All infra shell scripts passed `bash -n`; the source snapshot script passed `py_compile`; `git diff --check` passed. No Docker runtime or image build was involved.

The deterministic source builder includes dirty allowed files, records commit and per-file hashes/modes, refuses dirty paths outside the allowlist, excludes `.env*`/`.git`/generated directories, and rejects archive outputs inside the repository. The required image artifact archive and manifest persist outside the temporary build directory under `ARTIFACT_DIR/inf2006-<source-sha>/`. Docker builds, ECR pushes, and image digest resolution have not run because the local Docker socket was denied.

## AWS read-only and dry-run observations

The user's us-east-1 CloudShell session returned the following observations on 2026-09-27; account identifiers, role ARNs, secret ARNs, and values are omitted:

- `describe-instances`, `describe-db-instances`, `describe-nat-gateways`, `describe-volumes`, `describe-load-balancers`, and `describe-db-snapshots` returned no matching deployed resources. Two existing VPC Elastic IPs were unassociated and remain untouched.
- `get-instance-profile` found the supplied `LabInstanceProfile`; its attached role is `LabRole`. Policy simulation returned `allowed` for `secretsmanager:GetSecretValue`, `logs:CreateLogStream`, `logs:PutLogEvents`, and `cloudwatch:PutMetricData`. This is a policy simulation, not target-resource authorization or runtime proof.
- `ec2 create-vpc --region us-east-1 --cidr-block 10.60.0.0/16 --dry-run` returned `DryRunOperation`.
- `ec2 run-instances` dry-run passed for the then-current AL2023 x86_64 SSM AMI, `t3.medium`, `LabInstanceProfile`, IMDSv2 required, hop limit 1, CPU credits standard, count 1. No instance was launched.
- RDS orderability lookup succeeded for PostgreSQL 16.15, `db.t3.micro`, gp2. It does not prove RDS creation permission. The calculator rate selection is PostgreSQL engine/instance/storage/region/utilization pricing, not a minor-version-specific quote.
- `iam:GetRole` on the separate deployer role `voclabs` was explicitly denied; simulation was stopped. AWS Pricing `GetProducts` was denied; no alternate permission path was attempted. Resource-creation permissions and all deployment permissions are not established.
- `images.yaml` SHA-256 `b2ae804fdaf58017e69fc563cf3c6f959b53a3d94c81bd4d1ee111bd0a51041f` passed CloudFormation `validate-template`. Final `main.yaml` SHA-256 `0b88644d97c19f244773b324aecbd68cac13992a8ecdc6b4dae677b71a51343b` also passed CloudFormation `validate-template` from CloudShell; the service reported the expected description, 24 parameters, and no capabilities. This validates the template document only, not deploy permissions or resource creation.

## Runtime and deployment limits

The Docker socket returned permission denied on normal and narrow escalation attempts in the agent environment. Do not retry or bypass it. The user-provided earlier rehearsal passed its image, package, PostgreSQL, and Nginx stages, but did not start the API; the added importer and readiness/memory stages remain pending the user's terminal run. Cold synchronous memory use and the complete API/web/RDS runtime have not been measured. A previous warm measurement around 678–689 MiB does not establish a safe 1 GiB fit; `t3.medium` is a provisional 4 GiB choice only.

The template and runbook have not been exercised by creating resources. Google authorized-origin state has not been changed or verified. DuckDNS, HTTP-01, HTTPS, Google login, synthetic user isolation, database backup/restore, CloudWatch alarm fire/clear, and the real end-to-end journey remain pending. The instance uses a dynamic IPv4; after stop/start an operator must query the live EC2 `PublicIpAddress` by the `ApiHostInstanceId` output (the previous CloudFormation IP output may be stale), then update and verify DNS before rechecking the certificate and service.

## Cost estimate and cleanup behavior

The 730-hour component estimate is $53.878/month ($1.7713/day): EC2 `t3.medium` $30.368, one public IPv4 $3.65, 24 GiB gp3 $1.92, five secrets $2.00, RDS `db.t3.micro` $13.14 and 20 GiB gp2 $2.30, two standard alarms plus one custom metric $0.50. It excludes ECR bytes, CloudWatch log ingestion/storage, data transfer, snapshots, request charges, EC2 CPU-credit surplus charges (the proposal uses Standard mode), and RDS CPU-credit surplus charges. The RDS figure uses the AWS Pricing Calculator selection recorded on this date for us-east-1 PostgreSQL engine pricing, Single-AZ, db.t3.micro, 100% On-Demand utilization; it is not minor-version-specific and remains an estimate, not a bill guarantee. Check RDS credit mode and any surplus billing against the selected configuration before provisioning.

Sources: [RDS Pricing Calculator](https://calculator.aws/#/createCalculator/RDSPostgreSQL), [EC2 sizing reference](https://docs.aws.amazon.com/prescriptive-guidance/latest/optimize-costs-microsoft-workloads/right-size-selection.html), [EBS](https://docs.aws.amazon.com/en_en/emr/latest/ManagementGuide/emr-plan-storage-compare-volume-types.html), [public IPv4](https://aws.amazon.com/vpc/pricing/), [Secrets Manager](https://aws.amazon.com/secrets-manager/pricing/), [CloudWatch](https://aws.amazon.com/cloudwatch/pricing/), and [ECR](https://aws.amazon.com/ecr/pricing/).

Two pre-existing unassociated public IPv4 addresses are separate from this estimate and were left untouched (about $7.30/month combined at the cited public IPv4 hourly price). The current template retains the ECR repositories, CloudWatch log group, and an RDS final snapshot on stack deletion. Review retention and later cleanup costs before any creation approval.

## Historical review and JARVIS run record (superseded)

The independent final review passed with concerns and reported no remaining confirmed P1/P2 findings. The 17 local contract tests, shell syntax checks, Compose configuration check, and whitespace/diff check passed. The concern remains material: no image build, app runtime, live database, DNS/HTTPS, Google sign-in, backup/restore, or synchronous cold-memory test ran; the `t3.medium` remains provisional.

JARVIS scope stayed within the approved synchronous Task 6a preparation: preserve pre-existing dirty docs/review edits, exclude async/S3/SQS/workers and application/schema changes, and use an explicit allowlist for the pinned source snapshot. Docker socket probes in normal and narrow-escalation modes both returned permission denied; no further retries or bypass were attempted. No protected environment files or credential values were read; no secret values were created; no cloud resource, DNS record, Google origin, or production state was changed. No JARVIS control-plane memory was written because the user did not request a memory update.

## Final independent review — 2026-09-27

Final review verdict before this addendum: **PASS-WITH-CONCERNS**, with no remaining confirmed P1/P2 findings at that review point. The 30 local tests, infra shell syntax checks, and `git diff --check` passed; current `main.yaml` also passed read-only CloudFormation `ValidateTemplate`. Those review findings do not cover the changes below.

## Checks after this addendum

Fresh review verdict: **PASS-WITH-CONCERNS**, with no P1/P2 findings. Review noted one P3 gap: catalogue dry-run and initial apply did not assert database state or expected created-row counts. The current script closes that gap by comparing job count and catalogue revision before/after dry-run, requiring the first apply to create exactly the fixture count with zero updates/unchanged jobs, and retaining the second-apply unchanged-count/revision assertions. It now prints an explicit `PASS` summary only after all rehearsal stages complete.

After closing that P3, `python3 -m unittest tests.infra.test_cloud_repairs tests.infra.test_template_contract -v` passed **31 tests**; `bash -n tests/infra/rehearse-containers.sh src/infra/scripts/build-and-publish-images.sh` and `git diff --check` passed. The Docker rehearsal was not run in this environment; the catalogue importer, API readiness, and memory observation remain unverified until the required user-terminal command above is run. A later temporary deployment and teardown are described in the separate [cloud run record](cloud-foundation-run-2026-09-27.md); those events do not change what this preparation phase itself executed.

## Repository verification rerun — 2026-09-27

`python3 -m unittest discover -s tests/infra -p 'test_*.py'` passed **46 tests**. `bash -n` passed for `tests/infra/rehearse-containers.sh` and every `src/infra/scripts/*.sh`; `git diff --check` passed. This local rerun includes deployment-runner checks. It does not exercise Docker, AWS, DNS, or a live application.
