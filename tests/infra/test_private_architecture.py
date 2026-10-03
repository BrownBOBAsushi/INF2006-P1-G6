"""Offline contracts for the separately staged private cloud target."""

from pathlib import Path
import os
import re
import tempfile
import unittest
import subprocess

import yaml


ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "src/infra"


class CloudFormationLoader(yaml.SafeLoader):
    pass


def _intrinsic(loader, tag_suffix, node):
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node)
    else:
        value = loader.construct_mapping(node)
    return {tag_suffix: value}


CloudFormationLoader.add_multi_constructor("!", _intrinsic)


def read_template(name):
    return yaml.load(
        (INFRA / "cloudformation" / name).read_text(), Loader=CloudFormationLoader
    )


class PrivateArchitectureTests(unittest.TestCase):
    def test_private_userdata_reuses_al2023_curl_minimal_and_checks_https(self):
        marker = "# Ensure AL2023 HTTPS curl is available without replacing curl-minimal.\n"
        end_marker = "# End AL2023 HTTPS curl check.\n"

        for template_name, resource_name in (
            ("private-base.yaml", "WorkerInstanceRecovery"),
            ("private-app.yaml", "AppLaunchTemplate"),
        ):
            with self.subTest(template=template_name):
                template = read_template(template_name)
                resource = template["Resources"][resource_name]
                userdata = str(resource["Properties"].get("UserData") or resource["Properties"]["LaunchTemplateData"]["UserData"])
                if isinstance(resource["Properties"].get("UserData"), dict):
                    userdata = resource["Properties"]["UserData"]["Fn::Base64"]["Fn::Sub"][0]
                else:
                    userdata = resource["Properties"]["LaunchTemplateData"]["UserData"]["Fn::Base64"]["Fn::Sub"][0]
                install_lines = re.findall(r"^dnf install[^\n]*$", userdata, re.MULTILINE)
                self.assertTrue(install_lines)
                self.assertTrue(all(not re.search(r"(?:^|\s)curl(?:\s|$)", line) for line in install_lines))
                start = userdata.index(marker) + len(marker)
                end = userdata.index(end_marker, start)
                curl_check = userdata[start:end]
                self.assertIn("dnf install -y curl-minimal", curl_check)
                self.assertIn('curl_version="$(curl --version)"', curl_check)

                with tempfile.TemporaryDirectory(prefix="private-curl-check-") as temporary:
                    root = Path(temporary)
                    bin_dir = root / "bin"
                    bin_dir.mkdir()
                    dnf_log = root / "dnf-arguments"
                    dnf = bin_dir / "dnf"
                    dnf.write_text(
                        "#!/bin/bash\n"
                        "printf '%s\\n' \"$@\" > \"$DNF_ARGUMENTS\"\n"
                        "[[ \"$*\" == 'install -y curl-minimal' ]] || exit 92\n"
                        "cat > \"$FAKE_BIN/curl\" <<'CURL'\n"
                        "#!/bin/bash\n"
                        "[[ \"$1\" == --version ]] || exit 93\n"
                        "printf 'curl 8.21.0\\nProtocols: https\\n'\n"
                        "CURL\n"
                        "chmod +x \"$FAKE_BIN/curl\"\n"
                    )
                    dnf.chmod(0o755)
                    # These local helpers operate only on the temporary stub directory.
                    for helper in ("grep", "cat", "chmod"):
                        helper_path = Path("/usr/bin") / helper
                        if not helper_path.exists():
                            helper_path = Path("/bin") / helper
                        (bin_dir / helper).symlink_to(helper_path)

                    for initially_installed in (False, True):
                        curl = bin_dir / "curl"
                        curl.unlink(missing_ok=True)
                        dnf_log.unlink(missing_ok=True)
                        if initially_installed:
                            curl.write_text(
                                "#!/bin/bash\n"
                                "[[ \"$1\" == --version ]] || exit 93\n"
                                "printf 'curl 8.21.0 (minimal)\\nProtocols: https\\n'\n"
                            )
                            curl.chmod(0o755)
                        result = subprocess.run(
                            ["/bin/bash", "-c", "set -euo pipefail\n" + curl_check],
                            env={
                                "PATH": str(bin_dir),
                                "FAKE_BIN": str(bin_dir),
                                "DNF_ARGUMENTS": str(dnf_log),
                            },
                            capture_output=True,
                            text=True,
                            timeout=2,
                        )
                        self.assertEqual(result.returncode, 0, result.stderr)
                        if initially_installed:
                            self.assertFalse(dnf_log.exists())
                        else:
                            self.assertEqual(dnf_log.read_text().splitlines(), ["install", "-y", "curl-minimal"])

                    (bin_dir / "curl").write_text(
                        "#!/bin/bash\n"
                        "printf 'curl 8.21.0 (minimal)\\nProtocols: http\\n'\n"
                    )
                    (bin_dir / "curl").chmod(0o755)
                    missing_https = subprocess.run(
                        ["/bin/bash", "-c", "set -euo pipefail\n" + curl_check],
                        env={"PATH": str(bin_dir), "FAKE_BIN": str(bin_dir), "DNF_ARGUMENTS": str(dnf_log)},
                        capture_output=True,
                        text=True,
                        timeout=2,
                    )
                    self.assertNotEqual(missing_https.returncode, 0)

    def test_private_base_provisions_isolated_network_data_and_durable_queues(self):
        template = read_template("private-base.yaml")
        resources = template["Resources"]
        types = {item["Type"] for item in resources.values()}

        self.assertEqual(template["AWSTemplateFormatVersion"], "2010-09-09")
        self.assertEqual(sum(item["Type"] == "AWS::EC2::Subnet" for item in resources.values()), 6)
        self.assertEqual(sum(item["Type"] == "AWS::EC2::NatGateway" for item in resources.values()), 2)
        self.assertEqual(sum(item["Type"] == "AWS::SQS::Queue" for item in resources.values()), 4)
        self.assertIn("AWS::S3::Bucket", types)
        self.assertIn("AWS::RDS::DBInstance", types)
        self.assertFalse(any(item["Type"].startswith("AWS::IAM::") for item in resources.values()))

        self.assertNotIn("WorkerInstance", resources)
        worker = resources["WorkerInstanceRecovery"]["Properties"]
        self.assertEqual(worker["MetadataOptions"]["HttpTokens"], "required")
        self.assertEqual(worker["MetadataOptions"]["HttpPutResponseHopLimit"], 2)
        self.assertEqual(worker["SubnetId"], {"Ref": "AppSubnetA"})
        worker_userdata = str(worker["UserData"])
        self.assertNotIn("APP_ORIGIN", worker_userdata)
        self.assertIn("DuckDnsTokenSecretArn", worker_userdata)

        database = resources["Database"]["Properties"]
        self.assertFalse(database["PubliclyAccessible"])
        self.assertFalse(database["MultiAZ"])
        self.assertEqual(database["StorageType"], "gp2")
        self.assertEqual(database["AllocatedStorage"], 20)

        queues = [item["Properties"] for item in resources.values() if item["Type"] == "AWS::SQS::Queue"]
        for queue in queues:
            self.assertEqual(queue["VisibilityTimeout"], 900)
            self.assertTrue(queue["SqsManagedSseEnabled"])
        self.assertEqual(
            sum("RedrivePolicy" in queue for queue in queues), 2
        )

        bucket = resources["TemporaryInputBucket"]["Properties"]
        self.assertTrue(bucket["PublicAccessBlockConfiguration"]["BlockPublicAcls"])
        self.assertEqual(bucket["LifecycleConfiguration"]["Rules"][0]["ExpirationInDays"], 1)

    def test_worker_security_group_allows_outbound_dns_without_adding_ingress(self):
        resources = read_template("private-base.yaml")["Resources"]
        worker_sg = resources["WorkerSecurityGroup"]["Properties"]
        egress = worker_sg["SecurityGroupEgress"]
        self.assertIn(
            {"IpProtocol": "udp", "FromPort": 53, "ToPort": 53, "CidrIp": "0.0.0.0/0"},
            egress,
        )
        self.assertIn(
            {"IpProtocol": "tcp", "FromPort": 53, "ToPort": 53, "CidrIp": "0.0.0.0/0"},
            egress,
        )
        self.assertIn(
            {"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443, "CidrIp": "0.0.0.0/0"},
            egress,
        )
        self.assertIn(
            {
                "IpProtocol": "tcp",
                "FromPort": 5432,
                "ToPort": 5432,
                "DestinationSecurityGroupId": {"Ref": "DatabaseSecurityGroup"},
            },
            egress,
        )
        self.assertFalse(any(
            item["Type"] == "AWS::EC2::SecurityGroupIngress"
            and item["Properties"].get("GroupId") == {"Ref": "WorkerSecurityGroup"}
            for item in resources.values()
        ))

    def test_private_app_is_two_instance_asg_and_uses_digest_pinned_images(self):
        template = read_template("private-app.yaml")
        parameters = template["Parameters"]
        self.assertNotIn("VpcId", parameters)
        resources = template["Resources"]
        self.assertEqual(resources["AppAutoScalingGroup"]["Type"], "AWS::AutoScaling::AutoScalingGroup")
        self.assertEqual(resources["AppAutoScalingGroup"]["Properties"]["MinSize"], "2")
        self.assertEqual(resources["AppAutoScalingGroup"]["Properties"]["MaxSize"], "2")
        self.assertEqual(resources["AppAutoScalingGroup"]["Properties"]["DesiredCapacity"], "2")
        self.assertIn("@sha256:", parameters["ApiImageUri"]["AllowedPattern"])
        self.assertIn("@sha256:", parameters["WebImageUri"]["AllowedPattern"])
        self.assertEqual(resources["AppLaunchTemplate"]["Properties"]["LaunchTemplateData"]["MetadataOptions"]["HttpPutResponseHopLimit"], 2)
        self.assertNotIn("DatabaseMasterPassword", str(resources["AppLaunchTemplate"]["Properties"]["LaunchTemplateData"]["UserData"]))
        app_bootstrap = (INFRA / "scripts/bootstrap-private-app.sh").read_text()
        self.assertNotIn("run-migrations.sh", app_bootstrap)
        self.assertNotIn("bootstrap-db-roles.sh", app_bootstrap)

    def test_ingress_supports_empty_target_group_for_layered_private_rollout(self):
        template = read_template("ingress-http-api.yaml")
        parameters = template["Parameters"]
        targets = template["Resources"]["AppHttpsTargetGroup"]["Properties"].get("Targets", {})
        self.assertEqual(parameters["TargetRegistrationMode"]["Default"], "instances")
        self.assertEqual(targets["If"][0], "StaticInstanceRegistration")
        self.assertEqual(targets["If"][2], {"Ref": "AWS::NoValue"})

    def test_private_worker_runtime_is_separate_and_explicitly_aws_mode(self):
        compose = (INFRA / "compose.private-worker.yml").read_text()
        script = (INFRA / "scripts/bootstrap-private-worker.sh").read_text()
        local_worker = (ROOT / "src/backend/app/processing/local_worker.py").read_text()
        self.assertIn("PROCESSING_MODE=aws", script)
        self.assertIn("extraction-worker", compose)
        self.assertIn("embedding-worker", compose)
        self.assertIn("run-migrations.sh --apply", script)
        self.assertIn("bootstrap-db-roles.sh", script)
        self.assertIn("ingress-acme.env", script)
        self.assertNotIn("enable --now inf2006-ingress-cert-renew.timer", script)
        self.assertNotIn("APP_ORIGIN", script)
        self.assertIn("healthcheck:", compose)
        self.assertIn("is_ready()", local_worker)
        self.assertIn('text("SELECT 1")', local_worker)
        self.assertIn("ready_budget=2100", script)
        self.assertIn("deadline=$((SECONDS + ready_budget))", script)
        self.assertIn("health\" == unhealthy", script)
        base_template = read_template("private-base.yaml")
        base_userdata = str(base_template["Resources"]["WorkerInstanceRecovery"]["Properties"]["UserData"])
        self.assertIn("--resource WorkerInstanceRecovery", base_userdata)
        self.assertEqual(base_template["Outputs"]["WorkerInstanceId"]["Value"], {"Ref": "WorkerInstanceRecovery"})
        self.assertIn("+ 2400", base_userdata)
        self.assertEqual(
            base_template["Resources"]["WorkerInstanceRecovery"]["CreationPolicy"]["ResourceSignal"]["Timeout"],
            "PT45M",
        )

    def test_worker_userdata_diagnostics_are_sanitized_and_signal_keeps_exit_status(self):
        userdata = read_template("private-base.yaml")["Resources"]["WorkerInstanceRecovery"]["Properties"]["UserData"]["Fn::Base64"]["Fn::Sub"][0]
        self.assertIn("--resource WorkerInstanceRecovery", userdata)
        marker = "cat > /etc/inf2006/worker-bootstrap-diagnostics.bash <<'DIAGNOSTICS'\n"
        diagnostics_start = userdata.index(marker) + len(marker)
        diagnostics_end = userdata.index("\nDIAGNOSTICS\n", diagnostics_start)
        diagnostics = userdata[diagnostics_start:diagnostics_end] + "\n"
        self.assertIn("set -E", diagnostics)
        self.assertIn('"$LINENO"', diagnostics)
        self.assertNotIn("BASH_COMMAND", diagnostics)
        self.assertNotIn("--reason", userdata)

        with tempfile.TemporaryDirectory(prefix="worker-bootstrap-diagnostics-") as temporary:
            root = Path(temporary)
            rendered_userdata = re.sub(r"\$\{[^}]+\}", "synthetic", userdata)
            userdata_script = root / "worker-userdata.sh"
            userdata_script.write_text(rendered_userdata)
            subprocess.run(["bash", "-n", str(userdata_script)], check=True, capture_output=True, text=True)

            diagnostic_file = root / "diagnostics.bash"
            diagnostic_file.write_text(diagnostics)
            failing_script = root / "failing-bootstrap.sh"
            secret_argument = "synthetic-secret-argument-must-not-appear"
            failing_script.write_text(
                "set -euo pipefail\n"
                f"secret_argument='{secret_argument}'\n"
                "fail_stub() { return 37; }\n"
                "fail_stub \"$secret_argument\"\n"
            )
            failing_env = os.environ | {
                "BASH_ENV": str(diagnostic_file),
                "BOOTSTRAP_STAGE": "worker-runtime",
            }
            failure = subprocess.run(
                ["bash", str(failing_script)], env=failing_env,
                capture_output=True, text=True, timeout=2,
            )
            self.assertEqual(failure.returncode, 37)
            self.assertIn("stage=worker-runtime", failure.stderr)
            self.assertIn("exit_status=37", failure.stderr)
            self.assertRegex(failure.stderr, r"line=[0-9]+")
            self.assertNotIn(secret_argument, failure.stdout + failure.stderr)

            fake_signal = root / "cfn-signal-stub"
            signal_arguments = root / "signal-arguments"
            fake_signal.write_text("#!/bin/bash\nprintf '%s\\n' \"$@\" > \"$SIGNAL_ARGUMENTS\"\n")
            fake_signal.chmod(0o755)
            function_marker = "signal_on_exit() {\n"
            function_start = userdata.index(function_marker) + len(function_marker)
            function_end = userdata.index("\n}\ntrap signal_on_exit EXIT", function_start)
            function_body = userdata[function_start:function_end]
            signal_function = "signal_on_exit() {\n" + function_body + "\n}"
            self.assertNotIn("dnf", signal_function)
            self.assertNotIn("curl", signal_function)
            signal_function = signal_function.replace("/opt/aws/bin/cfn-signal", '"$FAKE_CFN_SIGNAL"')
            signal_function = signal_function.replace("'${AWS::StackName}'", "'test-stack'")
            signal_function = signal_function.replace("'${AWS::Region}'", "'us-east-1'")

            for expected_status in (0, 37):
                signal_arguments.unlink(missing_ok=True)
                signal_script = (
                    "BOOTSTRAP_FAILURE_RECORDED=1\n"
                    + signal_function
                    + "\ntrap signal_on_exit EXIT\n"
                    + f"exit {expected_status}\n"
                )
                signal_result = subprocess.run(
                    ["bash", "-c", signal_script],
                    env=os.environ | {
                        "FAKE_CFN_SIGNAL": str(fake_signal),
                        "SIGNAL_ARGUMENTS": str(signal_arguments),
                    },
                    capture_output=True, text=True, timeout=2,
                )
                self.assertEqual(signal_result.returncode, expected_status)
                arguments = signal_arguments.read_text().splitlines()
                self.assertEqual(arguments[arguments.index("--exit-code") + 1], str(expected_status))
                self.assertNotIn("--reason", arguments)

    def test_private_log_groups_use_valid_retention_policies(self):
        for name in ("private-base.yaml", "private-app.yaml", "ingress-http-api.yaml"):
            template = read_template(name)
            for resource in template["Resources"].values():
                if resource["Type"] == "AWS::Logs::LogGroup":
                    self.assertEqual(resource["DeletionPolicy"], "RetainExceptOnCreate")
                    self.assertEqual(resource["UpdateReplacePolicy"], "Retain")

    def test_private_plan_is_offline_and_has_no_apply_boundary(self):
        plan = INFRA / "scripts/plan-private.py"
        result = subprocess.run(
            [str(ROOT / "src/backend/.venv/bin/python"), str(plan), "--plan"],
            check=True,
            capture_output=True,
            text=True,
            env={"PATH": "/usr/bin:/bin"},
        )
        self.assertIn("1. private-base.yaml", result.stdout)
        self.assertIn("2. certificate", result.stdout)
        self.assertIn("3. ingress-http-api.yaml", result.stdout)
        self.assertIn("4. private-app.yaml", result.stdout)
        self.assertIn("No AWS API or credential lookup was performed", result.stdout)
        denied = subprocess.run(
            [str(ROOT / "src/backend/.venv/bin/python"), str(plan), "--apply"],
            capture_output=True,
            text=True,
            env={"PATH": "/usr/bin:/bin"},
        )
        self.assertEqual(denied.returncode, 2)


if __name__ == "__main__":
    unittest.main()
