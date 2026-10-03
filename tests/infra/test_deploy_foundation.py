import hashlib
import io
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tarfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "src/infra/scripts/deploy-foundation.py"
SPEC = importlib.util.spec_from_file_location("deploy_foundation", RUNNER_PATH)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def make_artifact_fixture(directory: Path, client_id: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    commit = "1" * 40
    sources = {
        "src/infra/cloudformation/main.yaml": b"AWSTemplateFormatVersion: '2010-09-09'\n",
        "data/synthetic_jobs.json": b'{"schema_version":1,"jobs":[{"source_job_id":"fixture-1"}]}\n',
    }
    records = [{"path": name, "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body), "mode": 0o644} for name, body in sources.items()]
    identity = {"commit": commit, "files": records}
    source_sha = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    manifest = {"format": 1, "repository_commit": commit, "source_snapshot_sha256": source_sha, "included_file_count": len(records), "files": records}
    with tarfile.open(directory / "source-snapshot.tar.gz", "w:gz") as archive:
        entries = {"source-snapshot.json": (json.dumps(manifest) + "\n").encode(), **sources}
        for name, body in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(body)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(body))
    archive_bytes = (directory / "source-snapshot.tar.gz").read_bytes()
    (directory / "archive.sha256").write_text("ARCHIVE_SHA256=" + hashlib.sha256(archive_bytes).hexdigest() + "\n")
    (directory / "source-snapshot.json").write_text(json.dumps(manifest) + "\n")
    digest_values = ("0" * 64, "1" * 64, "2" * 64)
    values = {
        "API_IMAGE_URI": "123456789012.dkr.ecr.us-east-1.amazonaws.com/inf2006/cloud-api@sha256:" + digest_values[0],
        "WEB_IMAGE_URI": "123456789012.dkr.ecr.us-east-1.amazonaws.com/inf2006/cloud-web@sha256:" + digest_values[1],
        "BOOTSTRAP_IMAGE_URI": "123456789012.dkr.ecr.us-east-1.amazonaws.com/inf2006/cloud-bootstrap@sha256:" + digest_values[2],
        "SOURCE_SNAPSHOT_SHA256": source_sha,
        "REPOSITORY_COMMIT": commit,
    }
    (directory / "image-digests.env").write_text("".join(f"{key}={value}\n" for key, value in values.items()))
    provenance = {"SOURCE_SNAPSHOT_SHA256": source_sha, "REPOSITORY_COMMIT": commit, "GOOGLE_CLIENT_ID_SHA256": hashlib.sha256(client_id.encode()).hexdigest()}
    (directory / "build-provenance.json").write_text(json.dumps(provenance))


class ArtifactValidationTests(unittest.TestCase):
    @unittest.skipUnless(Path("/Users/desmondchyezhihao/Documents/inf2006-artifacts/inf2006-f18034f19af1d8781d5b05667e2da64041df0c9706c906e186a96522a20bd968/source-snapshot.tar.gz").is_file(), "saved local deployment artifact is unavailable")
    def test_default_artifact_is_integrity_checked_without_aws(self):
        config = runner.load_config(ROOT / "src/infra/deploy-foundation.json")
        artifacts = Path(config["artifact_dir"]).expanduser()
        verified = runner.load_artifacts(artifacts, config["google_client_id"])
        self.assertTrue(verified["template_bytes"].startswith(b"AWSTemplateFormatVersion"))
        self.assertEqual(64, len(verified["source_sha"]))

    def test_archive_hash_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            for name, value in (("archive.sha256", "ARCHIVE_SHA256=" + "0" * 64 + "\n"),
                                ("source-snapshot.tar.gz", "bad"),
                                ("source-snapshot.json", "{}"),
                                ("image-digests.env", ""),
                                ("build-provenance.json", "{}")):
                (path / name).write_text(value)
            with self.assertRaisesRegex(runner.RunnerError, "archive hash"):
                runner.load_artifacts(path, "id")


class CommandConstructionTests(unittest.TestCase):
    def test_ssm_payload_contains_no_secret_values_and_quotes_ip(self):
        payload = runner.catalogue_reconciliation_script(
            append_dns_update=True,
            region="us-east-1", hostname="internshipmatcher.duckdns.org",
            public_ip="203.0.113.7",
            duckdns_arn="arn:secret:duckdns", bootstrap_image="123.dkr.ecr.us-east-1.amazonaws.com/x@sha256:" + "a" * 64,
        )
        self.assertIn("'203.0.113.7'", payload)
        self.assertIn("--dry-run", payload)
        self.assertIn("update-duckdns.sh --apply", payload)
        self.assertIn("--status running", payload)
        self.assertNotIn("get-secret-value", payload)
        self.assertNotIn("SECRET_VALUE", payload)

    def test_generated_resume_script_repairs_only_while_api_is_stopped(self):
        payload = runner.catalogue_reconciliation_script()
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            bin_dir = temp / "bin"
            bin_dir.mkdir()
            fixture = temp / "fixture.json"
            fixture.write_text('{"schema_version":1,"jobs":[]}')
            fake_docker = bin_dir / "docker"
            fake_docker.write_text('''#!/usr/bin/env python3
import os, shutil, sys
args = sys.argv[1:]
if args[0] == "create":
    print("fixture-container")
elif args[0] == "cp":
    shutil.copyfile(os.environ["FIXTURE"], args[-1])
elif args[0] == "rm":
    pass
elif args[0] == "compose" and "ps" in args:
    if os.environ.get("RUNNING_API") == "yes": print("api")
elif args[0] == "compose" and "run" in args:
    if "--dry-run" in args:
        print(os.environ["DRY_OUTPUT"])
        sys.exit(int(os.environ.get("DRY_STATUS", "0")))
    print("IMPORT_APPLIED")
''')
            fake_docker.chmod(0o755)

            def invoke(dry_output, running_api="no"):
                env = dict(os.environ, PATH=str(bin_dir) + os.pathsep + os.environ["PATH"], FIXTURE=str(fixture), DRY_OUTPUT=dry_output, RUNNING_API=running_api)
                return subprocess.run(["bash", "-c", payload], capture_output=True, text=True, env=env)

            unchanged = invoke("DRY RUN ok: created=0 updated=0 unchanged=1 embeddings_computed=0")
            self.assertEqual(0, unchanged.returncode, unchanged.stderr)
            self.assertNotIn("IMPORT_APPLIED", unchanged.stdout)
            missing_stopped = invoke("DRY RUN ok: created=1 updated=0 unchanged=0 embeddings_computed=1")
            self.assertEqual(0, missing_stopped.returncode, missing_stopped.stderr)
            self.assertIn("IMPORT_APPLIED", missing_stopped.stdout)
            missing_live = invoke("DRY RUN ok: created=1 updated=0 unchanged=0 embeddings_computed=1", "yes")
            self.assertNotEqual(0, missing_live.returncode)
            self.assertNotIn("IMPORT_APPLIED", missing_live.stdout)

    def test_secret_discovery_uses_metadata_only(self):
        config = runner.load_config(ROOT / "src/infra/deploy-foundation.json")
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        artifact_dir = Path(temp.name) / "artifacts"
        make_artifact_fixture(artifact_dir, config["google_client_id"])
        artifacts = runner.load_artifacts(artifact_dir, config["google_client_id"])
        calls = []

        def fake_json(args, **kwargs):
            calls.append(args)
            if args[:2] == ["sts", "get-caller-identity"]:
                return {"Account": "123456789012"}
            if args[:2] == ["secretsmanager", "describe-secret"]:
                return {"ARN": "arn:aws:secretsmanager:us-east-1:123456789012:secret:known"}
            if args[:2] == ["ec2", "describe-instances"]:
                return {}
            return {}

        def fake_aws(args, **kwargs):
            calls.append(args)
            if args[:2] == ["ssm", "get-parameter"]:
                return "ami-0123456789abcdef0"
            if args[:2] == ["ecr", "describe-images"]:
                return args[args.index("--image-ids") + 1].removeprefix("imageDigest=")
            return "sha256:" + "a" * 64

        with mock.patch.object(runner, "aws_json", side_effect=fake_json), mock.patch.object(runner, "aws", side_effect=fake_aws):
            secrets, ami, account = runner.discover_inputs(config, artifacts)
        self.assertEqual(5, len(secrets))
        self.assertEqual("ami-0123456789abcdef0", ami)
        self.assertEqual("123456789012", account)
        self.assertFalse(any("get-secret-value" in call for call in calls))


class DeploymentGuardTests(unittest.TestCase):
    def setUp(self):
        self.config = runner.load_config(ROOT / "src/infra/deploy-foundation.json")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        artifact_dir = Path(self.temp.name) / "artifacts"
        make_artifact_fixture(artifact_dir, self.config["google_client_id"])
        self.config["artifact_dir"] = str(artifact_dir)
        self.artifacts = runner.load_artifacts(artifact_dir, self.config["google_client_id"])
        self.expected = runner.expected_parameters(
            self.config, self.artifacts, "ami-0123456789abcdef0",
            {name: "arn:aws:secretsmanager:us-east-1:123456789012:secret:" + name for name in runner.SECRET_PARAMS},
        )

    def test_existing_parameter_mismatch_refuses_change(self):
        stack = {"Parameters": [{"ParameterKey": "GoogleClientId", "ParameterValue": "other"}]}
        with self.assertRaisesRegex(runner.RunnerError, "differ"):
            runner.ensure_stack_parameters(stack, self.expected)

    def test_permission_denial_is_classified_and_stops(self):
        denied = subprocess.CompletedProcess([], 254, "", "An error occurred (AccessDenied) not authorized")
        with mock.patch.object(runner.subprocess, "run", return_value=denied):
            with self.assertRaisesRegex(runner.RunnerError, "credentials or permissions"):
                runner.aws(["sts", "get-caller-identity"], region="us-east-1", profile="inf2006-lab")

    def test_create_uses_disable_rollback_and_completes_activation(self):
        commands = []
        def fake_aws(args, **kwargs):
            commands.append(args)
            return "{}"
        stack = {"Outputs": [{"OutputKey": "ApiHostInstanceId", "OutputValue": "i-123"}]}
        with mock.patch.object(runner, "aws", side_effect=fake_aws), \
             mock.patch.object(runner, "_wait_stack", return_value=stack), \
             mock.patch.object(runner, "_public_ip", return_value="203.0.113.7"), \
             mock.patch.object(runner, "_wait_ssm_online"), \
             mock.patch.object(runner, "_run_ssm") as run_ssm, \
             mock.patch.object(runner, "_wait_dns"), \
             mock.patch.object(runner, "_ready", side_effect=[False, True]):
            runner.apply_deployment(self.config, self.artifacts, self.expected, None)
        self.assertIn("--disable-rollback", commands[0])
        self.assertNotIn("--on-failure", commands[0])
        self.assertEqual(2, run_ssm.call_count)
        self.assertIn("203.0.113.7", run_ssm.call_args_list[0].args[2])

    def test_matching_live_stack_is_not_reimported_or_reactivated(self):
        stack = {"Outputs": [{"OutputKey": "ApiHostInstanceId", "OutputValue": "i-123"}]}
        with mock.patch.object(runner, "_public_ip", return_value="203.0.113.7"), \
             mock.patch.object(runner.socket, "getaddrinfo", return_value=[(None, None, None, None, ("203.0.113.7", 443))]), \
             mock.patch.object(runner, "_ready", return_value=True), \
             mock.patch.object(runner, "_wait_ssm_online"), \
             mock.patch.object(runner, "_run_ssm") as run_ssm:
            runner.apply_deployment(self.config, self.artifacts, self.expected, stack)
        run_ssm.assert_called_once()
        self.assertIn("--dry-run", run_ssm.call_args.args[2])
        self.assertNotIn("update-duckdns.sh --apply", run_ssm.call_args.args[2])

    def test_failed_stack_stops_before_create_or_replacement(self):
        stack = {"StackStatus": "ROLLBACK_COMPLETE", "Parameters": []}
        with self.assertRaisesRegex(runner.RunnerError, "ROLLBACK_COMPLETE"):
            runner.validate_existing_stack(stack, self.expected)

    def test_terminal_cloudformation_failure_never_returns_as_success(self):
        config = dict(self.config)
        config["timeouts_seconds"] = dict(self.config["timeouts_seconds"], stack=60)
        with mock.patch.object(runner, "stack_status", return_value={"StackStatus": "CREATE_FAILED"}):
            with self.assertRaisesRegex(runner.RunnerError, "CREATE_FAILED"):
                runner._wait_stack(config)

    def test_ssm_failure_does_not_copy_remote_output(self):
        invocation = subprocess.CompletedProcess([], 0, json.dumps({"Status": "Failed", "ResponseCode": 1, "StandardErrorContent": "secret-shaped remote output"}), "")
        with mock.patch.object(runner, "aws_json", return_value={"Command": {"CommandId": "cmd-1"}}), \
             mock.patch.object(runner.subprocess, "run", return_value=invocation):
            with self.assertRaisesRegex(runner.RunnerError, "inspect the instance command output securely"):
                runner._run_ssm(self.config, "i-123", "fixed harmless script")


class CliTests(unittest.TestCase):
    def test_help_and_preview_flag_surface(self):
        result = subprocess.run([sys.executable, str(RUNNER_PATH), "--help"], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("--apply", result.stdout)
        self.assertIn("preview", result.stdout.lower())

    def test_default_invocation_previews_and_never_enters_apply(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            artifacts_dir = temp / "artifacts"
            config = runner.load_config(ROOT / "src/infra/deploy-foundation.json")
            make_artifact_fixture(artifacts_dir, config["google_client_id"])
            config["artifact_dir"] = str(artifacts_dir)
            config_path = temp / "config.json"
            config_path.write_text(json.dumps(config))
            with mock.patch.object(runner, "discover_inputs", return_value=({}, "ami-0123456789abcdef0", "123456789012")), \
                 mock.patch.object(runner, "stack_status", return_value=None), \
                 mock.patch.object(runner, "verify_log_group"), \
                 mock.patch.object(runner, "apply_deployment") as apply, \
                 mock.patch("sys.stdout", new_callable=__import__("io").StringIO) as output:
                result = runner.main(["--config", str(config_path)])
            self.assertEqual(0, result)
            self.assertIn("Preview only", output.getvalue())
            apply.assert_not_called()


if __name__ == "__main__":
    unittest.main()
