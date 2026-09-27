#!/usr/bin/env python3
"""Validate pinned build artifacts, preview by default, and explicitly deploy the INF2006 foundation."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = ROOT / "src/infra/deploy-foundation.json"
TEMPLATE_PATH = "src/infra/cloudformation/main.yaml"
SECRET_PARAMS = (
    "DatabaseMasterPasswordSecretArn", "DatabaseMigratorSecretArn",
    "DatabaseRuntimeSecretArn", "AppSigningKeySecretArn", "DuckDnsTokenSecretArn",
)
IMAGE_PARAMS = ("ApiImageUri", "WebImageUri", "BootstrapImageUri")
TERMINAL_STACK = {"CREATE_FAILED", "ROLLBACK_FAILED", "ROLLBACK_COMPLETE", "DELETE_FAILED", "UPDATE_FAILED", "UPDATE_ROLLBACK_FAILED", "UPDATE_ROLLBACK_COMPLETE"}


class RunnerError(RuntimeError):
    pass


def load_config(path: Path) -> dict:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunnerError(f"Cannot read nonsecret deployment config: {exc}") from exc
    required = {"profile", "region", "artifact_dir", "stack_name", "hostname", "google_client_id", "instance_profile", "instance_type", "database_class", "postgres_engine_version", "secret_ids", "timeouts_seconds"}
    if set(config) != required or set(config["secret_ids"]) != set(SECRET_PARAMS):
        raise RunnerError("Deployment config has missing or unexpected fields.")
    if not re.fullmatch(r"[a-z0-9-]+", config["region"]) or not re.fullmatch(r"[a-z0-9-]+", config["stack_name"]):
        raise RunnerError("Deployment config contains an invalid region or stack name.")
    if config["hostname"] != "internshipmatcher.duckdns.org" or config["google_client_id"].count(".apps.googleusercontent.com") != 1:
        raise RunnerError("Deployment config hostname or public Google client ID is invalid.")
    return config


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunnerError(f"Invalid build artifact {path.name}: {exc}") from exc


def load_artifacts(directory: Path, client_id: str) -> dict:
    directory = directory.expanduser().resolve()
    try:
        archive = (directory / "source-snapshot.tar.gz").read_bytes()
        archive_hash_text = (directory / "archive.sha256").read_text(encoding="ascii").strip()
    except OSError as exc:
        raise RunnerError(f"Cannot read saved build artifacts: {exc}") from exc
    archive_hash = hashlib.sha256(archive).hexdigest()
    if archive_hash_text != f"ARCHIVE_SHA256={archive_hash}":
        raise RunnerError("Saved source archive hash does not match archive.sha256.")
    external_manifest = _read_json(directory / "source-snapshot.json")
    provenance = _read_json(directory / "build-provenance.json")
    digest_data = {}
    try:
        for line in (directory / "image-digests.env").read_text(encoding="ascii").splitlines():
            key, value = line.split("=", 1)
            if key in digest_data or key not in {"API_IMAGE_URI", "WEB_IMAGE_URI", "BOOTSTRAP_IMAGE_URI", "SOURCE_SNAPSHOT_SHA256", "REPOSITORY_COMMIT"}:
                raise ValueError("unexpected key")
            digest_data[key] = value
    except (OSError, ValueError) as exc:
        raise RunnerError("Image digest file has missing, duplicate, or unexpected fields.") from exc
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
            members = {member.name: member for member in tar.getmembers()}
            embedded_raw = tar.extractfile("source-snapshot.json").read()
            embedded_manifest = json.loads(embedded_raw)
            if embedded_manifest != external_manifest:
                raise RunnerError("External source manifest differs from the archived manifest.")
            records = external_manifest["files"]
            identity = {"commit": external_manifest["repository_commit"], "files": records}
            identity_sha = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            source_sha = external_manifest["source_snapshot_sha256"]
            if identity_sha != source_sha or digest_data.get("SOURCE_SNAPSHOT_SHA256") != source_sha or provenance.get("SOURCE_SNAPSHOT_SHA256") != source_sha:
                raise RunnerError("Source snapshot identity disagrees across build artifacts.")
            if digest_data.get("REPOSITORY_COMMIT") != external_manifest["repository_commit"] or provenance.get("REPOSITORY_COMMIT") != external_manifest["repository_commit"]:
                raise RunnerError("Repository commit disagrees across build artifacts.")
            client_hash = hashlib.sha256(client_id.encode()).hexdigest()
            if provenance.get("GOOGLE_CLIENT_ID_SHA256") != client_hash:
                raise RunnerError("Saved web image was built for a different public Google client ID.")
            expected = {record["path"] for record in records} | {"source-snapshot.json"}
            if set(members) != expected:
                raise RunnerError("Archive contents do not match the source manifest.")
            for record in records:
                name = record["path"]
                member = members[name]
                if not member.isfile() or PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts:
                    raise RunnerError(f"Unsafe or non-file archive member: {name}")
                body = tar.extractfile(member).read()
                if len(body) != record["bytes"] or hashlib.sha256(body).hexdigest() != record["sha256"] or member.mode != record["mode"]:
                    raise RunnerError(f"Archived source file failed its manifest check: {name}")
            template_record = next((r for r in records if r["path"] == TEMPLATE_PATH), None)
            if template_record is None:
                raise RunnerError("Pinned archive has no foundation template.")
            template_bytes = tar.extractfile(TEMPLATE_PATH).read()
            if hashlib.sha256(template_bytes).hexdigest() != template_record["sha256"]:
                raise RunnerError("Pinned template hash is invalid.")
    except (tarfile.TarError, KeyError, TypeError, json.JSONDecodeError, AttributeError) as exc:
        if isinstance(exc, RunnerError):
            raise
        raise RunnerError(f"Cannot validate archived source snapshot: {exc}") from exc
    if set(digest_data) != {"API_IMAGE_URI", "WEB_IMAGE_URI", "BOOTSTRAP_IMAGE_URI", "SOURCE_SNAPSHOT_SHA256", "REPOSITORY_COMMIT"}:
        raise RunnerError("Image digest file is incomplete.")
    for key in ("API_IMAGE_URI", "WEB_IMAGE_URI", "BOOTSTRAP_IMAGE_URI"):
        uri = digest_data[key]
        if not re.fullmatch(r"[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/inf2006/cloud-(api|web|bootstrap)@sha256:[a-f0-9]{64}", uri):
            raise RunnerError(f"Saved {key} is not an immutable expected ECR URI.")
    expected_repositories = ("cloud-api", "cloud-web", "cloud-bootstrap")
    for key, repo in zip(("API_IMAGE_URI", "WEB_IMAGE_URI", "BOOTSTRAP_IMAGE_URI"), expected_repositories):
        if f"/inf2006/{repo}@sha256:" not in digest_data[key]:
            raise RunnerError(f"Saved {key} points to the wrong repository.")
    return {"source_sha": source_sha, "commit": external_manifest["repository_commit"], "digests": digest_data, "template_bytes": template_bytes, "archive_hash": archive_hash}


def aws(args: list[str], *, region: str, profile: str, timeout: int = 45, check: bool = True) -> str:
    command = ["aws", "--profile", profile, "--region", region, *args]
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        error = result.stderr.strip()
        if re.search(r"ExpiredToken|InvalidClientTokenId|UnrecognizedClientException|AccessDenied|UnauthorizedOperation|not authorized|Access Denied", error, re.I):
            raise RunnerError("AWS credentials or permissions are insufficient for this step; refresh credentials or correct the listed lab role policy, then rerun. AWS said: " + error[:700])
        raise RunnerError("AWS command failed: " + error[:700])
    return result.stdout.strip()


def aws_json(args: list[str], **kwargs) -> dict:
    try:
        return json.loads(aws([*args, "--output", "json"], **kwargs) or "{}")
    except json.JSONDecodeError as exc:
        raise RunnerError("AWS CLI returned invalid JSON.") from exc


def _parameter_list(parameters: dict) -> list[str]:
    return [f"ParameterKey={key},ParameterValue={value}" for key, value in parameters.items()]


def expected_parameters(config: dict, artifacts: dict, ami_id: str, secret_arns: dict) -> dict:
    return {
        "AmiId": ami_id, "ApiInstanceType": config["instance_type"], "DatabaseInstanceClass": config["database_class"],
        "PostgresEngineVersion": config["postgres_engine_version"], **secret_arns,
        "LabInstanceProfileName": config["instance_profile"], "PublicHostname": config["hostname"],
        "AppOrigin": "https://" + config["hostname"], "GoogleClientId": config["google_client_id"],
        "ApiImageUri": artifacts["digests"]["API_IMAGE_URI"], "WebImageUri": artifacts["digests"]["WEB_IMAGE_URI"],
        "BootstrapImageUri": artifacts["digests"]["BOOTSTRAP_IMAGE_URI"], "SourceSnapshotSha256": artifacts["source_sha"],
    }


def discover_inputs(config: dict, artifacts: dict) -> tuple[dict, str, str]:
    region, profile = config["region"], config["profile"]
    identity = aws_json(["sts", "get-caller-identity"], region=region, profile=profile)
    account = identity.get("Account")
    if not re.fullmatch(r"[0-9]{12}", str(account or "")):
        raise RunnerError("Could not verify the active AWS account identity.")
    for key in ("API_IMAGE_URI", "WEB_IMAGE_URI", "BOOTSTRAP_IMAGE_URI"):
        uri = artifacts["digests"][key]
        if uri.split(".", 1)[0] != account or f".ecr.{region}.amazonaws.com/" not in uri:
            raise RunnerError(f"Saved {key} does not belong to the active account and configured region.")
        repository, digest = uri.split("/", 1)[1].split("@", 1)
        observed_digest = aws(["ecr", "describe-images", "--repository-name", repository, "--image-ids", "imageDigest=" + digest, "--query", "imageDetails[0].imageDigest", "--output", "text"], region=region, profile=profile)
        if observed_digest != digest:
            raise RunnerError(f"ECR did not confirm the saved immutable digest for {repository}.")
    secret_arns = {}
    for parameter, secret_id in config["secret_ids"].items():
        secret = aws_json(["secretsmanager", "describe-secret", "--secret-id", secret_id], region=region, profile=profile)
        arn = secret.get("ARN")
        if secret.get("DeletedDate") is not None:
            raise RunnerError(f"Secret metadata for {secret_id} shows a scheduled deletion; refusing stack creation.")
        if not isinstance(arn, str) or not arn.startswith(f"arn:aws:secretsmanager:{region}:{account}:secret:"):
            raise RunnerError(f"Secret metadata for {secret_id} did not return an ARN in the active account/region.")
        secret_arns[parameter] = arn
    ami_id = aws(["ssm", "get-parameter", "--name", "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64", "--query", "Parameter.Value", "--output", "text"], region=region, profile=profile)
    if not re.fullmatch(r"ami-[a-f0-9]+", ami_id):
        raise RunnerError("Latest AL2023 parameter did not resolve to an AMI ID.")
    return secret_arns, ami_id, account


def stack_status(config: dict) -> dict | None:
    result = subprocess.run(["aws", "--profile", config["profile"], "--region", config["region"], "cloudformation", "describe-stacks", "--stack-name", config["stack_name"], "--output", "json"], capture_output=True, text=True, timeout=45)
    if result.returncode:
        if "ValidationError" in result.stderr and re.search(r"Stack with id .+ does not exist", result.stderr, re.I) and not re.search(r"AccessDenied|not authorized", result.stderr, re.I):
            return None
        raise RunnerError("Cannot safely determine existing stack state; failing closed. AWS said: " + result.stderr.strip()[:700])
    try:
        return json.loads(result.stdout)["Stacks"][0]
    except (ValueError, KeyError, IndexError) as exc:
        raise RunnerError("AWS returned an unreadable stack description.") from exc


def verify_log_group(config: dict, stack_exists: bool) -> None:
    name = f"/inf2006/{config['stack_name']}/api"
    response = aws_json(["logs", "describe-log-groups", "--log-group-name-prefix", name], region=config["region"], profile=config["profile"])
    exact = [group for group in response.get("logGroups", []) if group.get("logGroupName") == name]
    if stack_exists and not exact:
        raise RunnerError("Existing stack has no expected CloudWatch log group; refusing to resume against possible drift.")
    if not stack_exists and exact:
        raise RunnerError("Expected CloudWatch log group already exists without its stack; inspect retained resources before creating a stack.")


def ensure_stack_parameters(stack: dict, expected: dict) -> None:
    observed = {item["ParameterKey"]: item.get("ParameterValue", "") for item in stack.get("Parameters", [])}
    mismatches = [key for key, value in expected.items() if observed.get(key) != value]
    if mismatches:
        raise RunnerError("Existing stack parameters differ from the approved artifact/configuration: " + ", ".join(mismatches) + ". Refusing update or replacement.")


def validate_existing_stack(stack: dict, expected: dict) -> None:
    status = stack.get("StackStatus", "UNKNOWN")
    if status in TERMINAL_STACK or status.endswith("_FAILED"):
        raise RunnerError(f"Existing foundation stack is in {status}; inspect events and logs. It will not be replaced or deleted.")
    if status not in {"CREATE_COMPLETE", "UPDATE_COMPLETE"}:
        raise RunnerError(f"Existing foundation stack is in non-idle state {status}; inspect events before retrying. It will not be modified.")
    ensure_stack_parameters(stack, expected)


def _outputs(stack: dict) -> dict:
    return {item["OutputKey"]: item.get("OutputValue", "") for item in stack.get("Outputs", [])}


def _wait_stack(config: dict) -> dict:
    deadline = time.monotonic() + config["timeouts_seconds"]["stack"]
    while time.monotonic() < deadline:
        stack = stack_status(config)
        if stack is None:
            raise RunnerError("Foundation stack disappeared while waiting.")
        status = stack.get("StackStatus", "")
        print(f"CloudFormation: {status}", flush=True)
        if status in {"CREATE_COMPLETE", "UPDATE_COMPLETE"}:
            return stack
        if status in TERMINAL_STACK or status.endswith("_FAILED"):
            raise RunnerError(f"Foundation stack ended in {status}; inspect CloudFormation events and retained bootstrap logs. No cleanup was attempted.")
        time.sleep(15)
    raise RunnerError("Timed out waiting for CloudFormation; resources may still be creating and may incur charges. No cleanup was attempted.")


def _extract_template(artifacts: dict) -> Path:
    handle = tempfile.NamedTemporaryFile(prefix="inf2006-template-", suffix=".yaml", delete=False)
    handle.write(artifacts["template_bytes"])
    handle.close()
    return Path(handle.name)


def catalogue_reconciliation_script(append_dns_update: bool = False, region: str = "us-east-1", hostname: str = "internshipmatcher.duckdns.org", public_ip: str = "203.0.113.7", duckdns_arn: str = "", bootstrap_image: str = "") -> str:
    values = [region, hostname, public_ip, duckdns_arn, bootstrap_image]
    q = ["'" + value.replace("'", "'\\''") + "'" for value in values]
    dns_update = "bash /opt/inf2006/src/infra/scripts/update-duckdns.sh --apply\n" if append_dns_update else ""
    return f'''#!/bin/bash
set -euo pipefail
set +x
REGION={q[0]}
HOSTNAME={q[1]}
PUBLIC_IP={q[2]}
DUCKDNS_TOKEN_SECRET_ARN={q[3]}
BOOTSTRAP_IMAGE_URI={q[4]}
AWS_DEFAULT_REGION="$REGION"
export AWS_DEFAULT_REGION PUBLIC_HOSTNAME="$HOSTNAME" PUBLIC_IP DUCKDNS_TOKEN_SECRET_ARN
fixture_container="$(docker create "$BOOTSTRAP_IMAGE_URI")"
trap 'docker rm -f "$fixture_container" >/dev/null 2>&1 || true; rm -f /tmp/inf2006-synthetic-jobs.json' EXIT
docker cp "$fixture_container:/opt/inf2006/data/synthetic_jobs.json" /tmp/inf2006-synthetic-jobs.json
docker rm "$fixture_container" >/dev/null
chmod 0600 /tmp/inf2006-synthetic-jobs.json
compose=(docker compose --env-file /etc/inf2006/compose.env -f /opt/inf2006/compose.cloud.yml)
import=("${{compose[@]}}" run --rm --no-deps -v /tmp/inf2006-synthetic-jobs.json:/data/synthetic_jobs.json:ro --entrypoint python api -m app.catalogue.import_jobs --file /data/synthetic_jobs.json)
dry_run="$("${{import[@]}}" --dry-run)"
if [[ "$dry_run" =~ DRY[[:space:]]RUN[[:space:]]ok:[[:space:]]created=0[[:space:]]updated=0[[:space:]]unchanged=[1-9][0-9]* ]]; then
  echo 'Synthetic catalogue is present and current; no import was needed.'
else
  running_services="$("${{compose[@]}}" ps --services --status running)"
  if grep -qx 'api' <<<"$running_services"; then
    echo 'Synthetic catalogue is incomplete or differs while the API is running; refusing an importer maintenance write.' >&2
    exit 1
  fi
  echo 'Synthetic catalogue needs rows or embeddings; API is stopped, applying the idempotent import.'
  "${{import[@]}}"
fi
rm -f /tmp/inf2006-synthetic-jobs.json
trap - EXIT
{dns_update}'''


def _run_ssm(config: dict, instance_id: str, payload: str) -> None:
    region, profile = config["region"], config["profile"]
    params = json.dumps({"commands": ["bash <<'INF2006_RUNNER_SCRIPT'\n" + payload + "\nINF2006_RUNNER_SCRIPT"], "executionTimeout": [str(config["timeouts_seconds"]["ssm"])]})
    response = aws_json(["ssm", "send-command", "--instance-ids", instance_id, "--document-name", "AWS-RunShellScript", "--timeout-seconds", "60", "--parameters", params], region=region, profile=profile)
    command_id = response.get("Command", {}).get("CommandId")
    if not command_id:
        raise RunnerError("SSM did not return a command ID.")
    deadline = time.monotonic() + config["timeouts_seconds"]["ssm"] + 60
    last_state = "Pending"
    while time.monotonic() < deadline:
        result = subprocess.run(["aws", "--profile", profile, "--region", region, "ssm", "get-command-invocation", "--command-id", command_id, "--instance-id", instance_id, "--output", "json"], capture_output=True, text=True, timeout=45)
        if result.returncode:
            if "InvocationDoesNotExist" in result.stderr:
                time.sleep(4)
                continue
            if re.search(r"ExpiredToken|AccessDenied|not authorized", result.stderr, re.I):
                raise RunnerError("SSM status access failed; command may still be running. Refresh credentials or correct role access. No cleanup was attempted.")
            raise RunnerError("Could not read SSM command status; command may still be running. No cleanup was attempted.")
        try:
            invocation = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RunnerError("SSM returned invalid command status.") from exc
        last_state = invocation.get("Status", "Unknown")
        print(f"SSM activation: {last_state}", flush=True)
        if last_state == "Success":
            return
        if last_state in {"Failed", "TimedOut", "Cancelled", "Cancelling"}:
            response_code = invocation.get("ResponseCode", "unknown")
            raise RunnerError(f"SSM activation {last_state} (exit {response_code}); inspect the instance command output securely. Output is intentionally not copied to local logs.")
        time.sleep(10)
    raise RunnerError(f"SSM activation polling timed out in {last_state}; command may still run. No cleanup was attempted.")


def _public_ip(config: dict, instance_id: str) -> str:
    response = aws_json(["ec2", "describe-instances", "--instance-ids", instance_id], region=config["region"], profile=config["profile"])
    try:
        address = response["Reservations"][0]["Instances"][0]["PublicIpAddress"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RunnerError("EC2 has no current public IPv4 address.") from exc
    if not re.fullmatch(r"(?:[0-9]{1,3}\.){3}[0-9]{1,3}", address):
        raise RunnerError("EC2 returned an invalid public IPv4 address.")
    return address


def _wait_ssm_online(config: dict, instance_id: str) -> None:
    deadline = time.monotonic() + config["timeouts_seconds"]["ssm"]
    while time.monotonic() < deadline:
        response = aws_json(["ssm", "describe-instance-information", "--filters", f"Key=InstanceIds,Values={instance_id}"], region=config["region"], profile=config["profile"])
        records = response.get("InstanceInformationList", [])
        if any(record.get("InstanceId") == instance_id and record.get("PingStatus") == "Online" for record in records):
            return
        time.sleep(15)
    raise RunnerError("SSM Agent did not become Online before timeout; verify LabInstanceProfile permissions and network access. No cleanup was attempted.")


def _wait_dns(hostname: str, expected_ip: str, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)}
        except OSError:
            addresses = set()
        if expected_ip in addresses:
            return
        time.sleep(10)
    raise RunnerError("Public DNS did not resolve to the EC2 address before timeout; HTTPS activation was stopped.")


def _ready(hostname: str, timeout: int) -> bool:
    url = f"https://{hostname}/health/ready"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=15) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(10)
    return False


def apply_deployment(config: dict, artifacts: dict, expected: dict, stack: dict | None) -> None:
    region, profile, stack_name = config["region"], config["profile"], config["stack_name"]
    resuming = stack is not None
    template_file = _extract_template(artifacts)
    try:
        if stack is None:
            print("Creating foundation stack with rollback disabled for diagnosis.", flush=True)
            parameters = _parameter_list(expected)
            aws(["cloudformation", "create-stack", "--stack-name", stack_name, "--disable-rollback", "--template-body", "file://" + str(template_file), "--parameters", *parameters], region=region, profile=profile, timeout=120)
            stack = _wait_stack(config)
        outputs = _outputs(stack)
        instance_id = outputs.get("ApiHostInstanceId")
        if not instance_id:
            raise RunnerError("Stack output ApiHostInstanceId is missing.")
        instance_ip = _public_ip(config, instance_id)
        public_ready = False
        if resuming:
            try:
                addresses = {item[4][0] for item in socket.getaddrinfo(config["hostname"], 443, type=socket.SOCK_STREAM)}
            except OSError:
                addresses = set()
            public_ready = instance_ip in addresses and _ready(config["hostname"], 5)
            if public_ready:
                print("Existing endpoint is healthy; verifying catalogue contents read-only before declaring resume complete.", flush=True)
            else:
                print("Existing stack is not publicly ready; checking or repairing its catalogue before resuming DNS/HTTPS activation.", flush=True)
        _wait_ssm_online(config, instance_id)
        payload = catalogue_reconciliation_script(
            append_dns_update=not public_ready,
            region=region,
            hostname=config["hostname"],
            public_ip=instance_ip,
            duckdns_arn=expected["DuckDnsTokenSecretArn"],
            bootstrap_image=artifacts["digests"]["BOOTSTRAP_IMAGE_URI"],
        )
        _run_ssm(config, instance_id, payload)
        if public_ready:
            print("Existing stack has matching DNS, healthy readiness, and a current synthetic catalogue; no activation changes made.", flush=True)
            return
        _wait_dns(config["hostname"], instance_ip, config["timeouts_seconds"]["dns"])
        if not _ready(config["hostname"], 5):
            print("HTTPS is not ready yet; enabling HTTPS with the existing host script.", flush=True)
            https_script = f'''#!/bin/bash
set -euo pipefail
set +x
export AWS_DEFAULT_REGION={shlex.quote(region)}
export PUBLIC_HOSTNAME={shlex.quote(config['hostname'])}
export APP_ORIGIN={shlex.quote('https://' + config['hostname'])}
export PUBLIC_IP={shlex.quote(instance_ip)}
bash /opt/inf2006/src/infra/scripts/enable-https.sh --apply
'''
            _run_ssm(config, instance_id, https_script)
        else:
            print("Existing HTTPS readiness endpoint is healthy; certificate activation skipped.", flush=True)
        if not _ready(config["hostname"], config["timeouts_seconds"]["health"]):
            raise RunnerError("Public HTTPS /health/ready did not return HTTP 200 before timeout.")
        print(f"Verified public HTTPS readiness at https://{config['hostname']}/health/ready. Browser sign-in remains unverified.", flush=True)
    finally:
        template_file.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review and explicitly deploy the existing INF2006 AWS foundation.")
    parser.add_argument("--apply", action="store_true", help="perform the deployment and activation mutations; default only previews")
    parser.add_argument("--artifacts", type=Path, help="directory containing a validated saved build artifact set")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH, help="nonsecret deployment defaults JSON")
    args = parser.parse_args(argv)
    log_file = None
    original_stdout, original_stderr = sys.stdout, sys.stderr
    try:
        config = load_config(args.config)
        if args.artifacts:
            config["artifact_dir"] = str(args.artifacts)
        log_dir = Path(config["artifact_dir"]).expanduser().resolve().parent / "deployment-runs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = (log_dir / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".log")).open("x", encoding="utf-8")
        class Tee:
            def __init__(self, *streams): self.streams = streams
            def write(self, value):
                for stream in self.streams:
                    stream.write(value)
                    stream.flush()
            def flush(self):
                for stream in self.streams: stream.flush()
        sys.stdout = Tee(original_stdout, log_file)
        sys.stderr = Tee(original_stderr, log_file)
        artifacts = load_artifacts(Path(config["artifact_dir"]), config["google_client_id"])
        secret_arns, ami_id, account = discover_inputs(config, artifacts)
        expected = expected_parameters(config, artifacts, ami_id, secret_arns)
        stack = stack_status(config)
        verify_log_group(config, stack is not None)
        if stack:
            existing_parameters = {item["ParameterKey"]: item.get("ParameterValue", "") for item in stack.get("Parameters", [])}
            if re.fullmatch(r"ami-[a-f0-9]+", existing_parameters.get("AmiId", "")):
                # A healthy stack's reviewed AMI is immutable for resume even as the public latest pointer advances.
                expected["AmiId"] = existing_parameters["AmiId"]
            validate_existing_stack(stack, expected)
        print(f"Account: {account}; region: {config['region']}; stack: {config['stack_name']}")
        print(f"Source snapshot: {artifacts['source_sha']}; archived template SHA-256: {hashlib.sha256(artifacts['template_bytes']).hexdigest()}")
        print("Validated three immutable ECR image digests, five existing secret ARNs, current AL2023 AMI, and existing stack state.")
        print("Verified expected CloudWatch log group state.")
        print("Planned resources: one public EC2 API host, private Single-AZ PostgreSQL/RDS, networking, logs and alarms; no teardown path is available.")
        print("Pre-create limitation: the operator's AWS principal permissions for ssm:SendCommand and ssm:GetCommandInvocation cannot be verified without a target; the instance profile only enables the host agent. A denial after creation leaves retained resources for diagnosis.")
        if not args.apply:
            print("Preview only. No AWS resources, Secrets Manager values, DNS records or application state were changed. Pass --apply to execute deployment.")
            return 0
        if stack is None:
            print("WARNING: approved apply will create billable EC2/RDS/network resources; failed stacks are retained for diagnosis.", flush=True)
        apply_deployment(config, artifacts, expected, stack)
        return 0
    except (RunnerError, subprocess.TimeoutExpired, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        sys.stdout, sys.stderr = original_stdout, original_stderr
        if log_file:
            log_file.close()


if __name__ == "__main__":
    raise SystemExit(main())
