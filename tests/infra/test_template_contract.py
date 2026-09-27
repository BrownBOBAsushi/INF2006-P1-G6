from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import unittest
import yaml


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_PATH = ROOT / "src/infra/cloudformation/main.yaml"
SCRIPTS = ROOT / "src/infra/scripts"


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


def template():
    return yaml.load(TEMPLATE_PATH.read_text(), Loader=CloudFormationLoader)


class FoundationTemplateContractTests(unittest.TestCase):
    def test_template_is_a_valid_yaml_cloudformation_document(self):
        parsed = template()
        self.assertEqual(parsed["AWSTemplateFormatVersion"], "2010-09-09")
        self.assertTrue(parsed["Resources"])
        self.assertTrue(parsed["Parameters"])


    def test_foundation_has_only_public_api_and_private_single_az_database(self):
        resources = template()["Resources"]
        types = {resource["Type"] for resource in resources.values()}
        self.assertIn("AWS::EC2::Instance", types)
        self.assertIn("AWS::RDS::DBInstance", types)
        self.assertIn("AWS::RDS::DBSubnetGroup", types)
        self.assertIn("AWS::Logs::LogGroup", types)
        self.assertIn("AWS::CloudWatch::Alarm", types)
        self.assertFalse(any(name.startswith("Worker") for name in resources))
        self.assertFalse(types.intersection({
            "AWS::S3::Bucket",
            "AWS::SQS::Queue",
            "AWS::IAM::Role",
            "AWS::IAM::User",
            "AWS::IAM::Group",
        }))
        self.assertFalse(types.intersection({"AWS::S3::Bucket", "AWS::SQS::Queue"}))


    def test_database_is_private_single_az_and_only_api_sg_can_reach_postgres(self):
        resources = template()["Resources"]
        database = resources["Database"]
        self.assertIs(database["Properties"]["PubliclyAccessible"], False)
        self.assertIs(database["Properties"]["MultiAZ"], False)
        db_ingress = resources["DatabaseIngress"]
        self.assertEqual(db_ingress["Properties"]["FromPort"], 5432)
        self.assertEqual(db_ingress["Properties"]["ToPort"], 5432)
        self.assertEqual(db_ingress["Properties"]["SourceSecurityGroupId"], {"Ref": "ApiSecurityGroup"})
        api_host = resources["ApiHost"]["Properties"]
        self.assertEqual(api_host["MetadataOptions"]["HttpTokens"], "required")
        self.assertEqual(api_host["BlockDeviceMappings"][0]["Ebs"]["VolumeSize"], 24)


    def test_public_host_requires_a_digest_pinned_image_and_supplied_lab_profile(self):
        parsed = template()
        parameters = parsed["Parameters"]
        self.assertIn("ApiImageUri", parameters)
        self.assertIn("WebImageUri", parameters)
        for name in ("ApiImageUri", "WebImageUri", "BootstrapImageUri"):
            pattern = re.compile(parameters[name]["AllowedPattern"])
            self.assertRegex(
                "123456789012.dkr.ecr.us-east-1.amazonaws.com/inf2006/app@sha256:" + "a" * 64,
                pattern,
            )
            self.assertNotRegex("123456789012.dkr.ecr.us-east-1.amazonaws.com/app:latest", pattern)
        self.assertIn("LabInstanceProfileName", parameters)
        instance = parsed["Resources"]["ApiHost"]["Properties"]
        self.assertEqual(instance["IamInstanceProfile"], {"Ref": "LabInstanceProfileName"})
        self.assertEqual(parsed["Resources"]["ApiHost"]["CreationPolicy"]["ResourceSignal"]["Count"], 1)


    def test_secret_values_are_not_parameters_or_user_data_literals(self):
        parsed = template()
        parameters = parsed["Parameters"]
        for name, definition in parameters.items():
            if "SecretArn" in name:
                self.assertRegex(definition["AllowedPattern"], r"secretsmanager")
        user_data = str(parsed["Resources"]["ApiHost"]["Properties"]["UserData"])
        self.assertNotIn("resolve:secretsmanager", user_data.lower())
        self.assertNotIn("SecretString", user_data)
        self.assertIn("DatabaseMasterPasswordSecretArn", user_data)
        self.assertNotIn("Password=", user_data)

    def test_ecr_repositories_are_immutable_and_separate_from_async_resources(self):
        images_path = ROOT / "src/infra/cloudformation/images.yaml"
        images = yaml.load(images_path.read_text(), Loader=CloudFormationLoader)["Resources"]
        self.assertEqual(set(images), {"ApiRepository", "WebRepository", "BootstrapRepository"})
        for repository in images.values():
            self.assertEqual(repository["Type"], "AWS::ECR::Repository")
            self.assertEqual(repository["Properties"]["ImageTagMutability"], "IMMUTABLE")
            self.assertEqual(repository["DeletionPolicy"], "Retain")

    def test_readiness_alarm_matches_published_health_metric(self):
        resources = template()["Resources"]
        alarm = resources["ApiReadinessAlarm"]["Properties"]
        metric_script = (SCRIPTS / "publish-health-metric.sh").read_text()
        self.assertEqual(alarm["Namespace"], "INF2006/Service")
        self.assertEqual(alarm["MetricName"], "Ready")
        self.assertEqual(alarm["TreatMissingData"], "breaching")
        self.assertIn("/health/ready", metric_script)
        self.assertIn("INF2006/Service", metric_script)
        self.assertIn("--dry-run", metric_script)


    def test_privileged_bootstrap_and_migrations_are_separate_from_runtime(self):
        bootstrap = (SCRIPTS / "bootstrap-db-roles.sh").read_text()
        role_sql = (SCRIPTS / "configure-app-roles.sql").read_text()
        migrate = (SCRIPTS / "run-migrations.sh").read_text()
        api = (SCRIPTS / "bootstrap-api.sh").read_text()
        self.assertIn("configure-app-roles.sql", bootstrap)
        self.assertIn("app_runtime", role_sql)
        self.assertIn("app_migrator", role_sql)
        self.assertNotIn("DROP EXTENSION", bootstrap.upper())
        self.assertIn("app_migrator", migrate)
        self.assertIn('--entrypoint alembic', migrate)
        self.assertRegex(migrate, r'"\$API_IMAGE_URI" upgrade head')
        self.assertNotIn("alembic upgrade head", api)
        self.assertIn("app_runtime", api)
        self.assertIn("sslmode=verify-full", bootstrap)
        self.assertIn("log_min_error_statement = 'panic'", role_sql)
        self.assertNotIn("GRANT TEMPORARY", role_sql)
        self.assertIn("REVOKE ALL ON TABLE public.alembic_version", migrate)
        cloud_compose = (ROOT / "src/infra/compose.cloud.yml").read_text()
        self.assertIn("--no-access-log", cloud_compose)
        self.assertNotIn("alembic upgrade head", cloud_compose)


    def test_scripts_refuse_to_print_or_trace_secret_values(self):
        for path in SCRIPTS.glob("*.sh"):
            contents = path.read_text()
            result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("set +x", contents)
            self.assertIsNone(re.search(
                r"(echo|printf)\s+.*(?:\$token|\$\{token\}|\$runtime_password|\$signing_key|\$migrator_password)",
                contents,
                re.IGNORECASE,
            ))

    def test_duckdns_requires_explicit_apply_before_any_network_or_secret_access(self):
        result = subprocess.run(
            ["bash", str(SCRIPTS / "update-duckdns.sh")],
            env={"PATH": "/usr/bin:/bin"},
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("No DNS change made", result.stdout)

    def test_cloud_bootstrap_signals_creation_after_cleaning_docker_config(self):
        user_data = template()["Resources"]["ApiHost"]["Properties"]["UserData"]["Fn::Base64"]["Fn::Sub"][0]
        self.assertIn("trap signal_on_exit EXIT", user_data)
        self.assertIn('rm -rf "$DOCKER_CONFIG"', user_data)
        self.assertIn("DOCKER_CONFIG=''", user_data)
        self.assertEqual(user_data.count("trap signal_on_exit EXIT"), 1)
        self.assertNotIn("trap 'rm -rf", user_data)
        self.assertNotIn('${DOCKER_CONFIG:-}', user_data)
        self.assertIn("--exit-code \"$status\"", user_data)

    def test_cloud_runtime_mounts_ca_and_preserves_outer_https_scheme(self):
        compose = (ROOT / "src/infra/compose.cloud.yml").read_text()
        api_bootstrap = (SCRIPTS / "bootstrap-api.sh").read_text()
        web_config = (ROOT / "src/infra/nginx/web-cloud.conf").read_text()
        self.assertIn("rds-global-bundle.pem:/etc/ssl/certs/rds-global-bundle.pem:ro", compose)
        self.assertIn("sslrootcert=/etc/ssl/certs/rds-global-bundle.pem", api_bootstrap)
        self.assertIn("X-Forwarded-Proto $http_x_forwarded_proto", web_config)

    def test_duckdns_captures_provider_response_without_discarding_it(self):
        script = (SCRIPTS / "update-duckdns.sh").read_text()
        self.assertIn('result="$(curl --config "$curl_config" 2>/dev/null)"', script)
        self.assertNotIn('output = "/dev/null"', script)

    def test_duckdns_apply_uses_provider_response_to_accept_or_reject_update(self):
        with tempfile.TemporaryDirectory(prefix="inf2006-duckdns-test-") as temp_dir:
            fake_bin = Path(temp_dir) / "bin"
            fake_bin.mkdir()
            (fake_bin / "aws").write_text("#!/bin/sh\nprintf '%s' '{\"token\":\"0123456789abcdef0123456789abcdef\"}'\n")
            (fake_bin / "jq").write_text("#!/bin/sh\nprintf '%s' '0123456789abcdef0123456789abcdef'\n")
            (fake_bin / "curl").write_text("#!/bin/sh\nprintf '%s' \"$CURL_RESULT\"\n")
            for tool in fake_bin.iterdir():
                tool.chmod(0o755)
            base_env = {
                "PATH": f"{fake_bin}:/usr/bin:/bin",
                "AWS_DEFAULT_REGION": "us-east-1",
                "PUBLIC_HOSTNAME": "internshipmatcher.duckdns.org",
                "PUBLIC_IP": "192.0.2.10",
                "DUCKDNS_TOKEN_SECRET_ARN": "arn:aws:secretsmanager:us-east-1:123456789012:secret:test",
                "DUCKDNS_CURL_CONFIG_DIR": temp_dir,
            }
            success = subprocess.run(
                ["bash", str(SCRIPTS / "update-duckdns.sh"), "--apply"],
                env={**base_env, "CURL_RESULT": "OK"},
                capture_output=True,
                text=True,
            )
            self.assertEqual(success.returncode, 0, success.stderr)
            self.assertIn("update confirmed", success.stdout)
            self.assertNotIn("0123456789abcdef", success.stdout + success.stderr)
            rejected = subprocess.run(
                ["bash", str(SCRIPTS / "update-duckdns.sh"), "--apply"],
                env={**base_env, "CURL_RESULT": "KO"},
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("did not confirm", rejected.stderr)

    def test_build_uses_unique_immutable_tag_attempts_with_a_stable_source_label(self):
        script = (SCRIPTS / "build-and-publish-images.sh").read_text()
        self.assertIn('attempt_id="$(date -u +%Y%m%dT%H%M%SZ)-$$"', script)
        self.assertIn('image_tag="src-${snapshot_sha:0:20}-${attempt_id}"', script)
        self.assertIn('org.opencontainers.image.source-snapshot-sha256=$snapshot_sha', script)

    def test_source_snapshot_contains_dirty_tree_hashes_but_excludes_env_files(self):
        with tempfile.TemporaryDirectory(prefix="inf2006-test-snapshot-") as temp_dir:
            archive_path = Path(temp_dir) / "snapshot.tar.gz"
            result = subprocess.run(
                ["python3", str(SCRIPTS / "create-source-snapshot.py"), str(archive_path)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
            with tarfile.open(archive_path, "r:gz") as archive:
                names = archive.getnames()
                self.assertIn("source-snapshot.json", names)
                self.assertIn("src/infra/cloudformation/main.yaml", names)
                self.assertFalse(any(Path(name).name.startswith(".env") for name in names))
                manifest = yaml.safe_load(archive.extractfile("source-snapshot.json"))
            self.assertEqual(manifest["source_snapshot_sha256"], result.stdout.strip())
            self.assertTrue(manifest["repository_commit"])
            self.assertGreater(manifest["included_file_count"], 100)
            self.assertTrue(all("mode" in item for item in manifest["files"]))
            second_archive = Path(temp_dir) / "snapshot-second.tar.gz"
            subprocess.run(
                ["python3", str(SCRIPTS / "create-source-snapshot.py"), str(second_archive)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(archive_path.read_bytes(), second_archive.read_bytes())

    def test_source_snapshot_rejects_an_archive_path_inside_the_repo(self):
        result = subprocess.run(
            ["python3", str(SCRIPTS / "create-source-snapshot.py"), str(ROOT / "recursive.tar.gz")],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("outside the repository", result.stderr)
        self.assertFalse((ROOT / "recursive.tar.gz").exists())


if __name__ == "__main__":
    unittest.main()
