from configparser import ConfigParser
import importlib.util
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
import unittest
from urllib.parse import quote
from urllib.parse import unquote, urlsplit

import yaml


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "src/infra/scripts"
TEMPLATE = ROOT / "src/infra/cloudformation/main.yaml"


class CloudFormationLoader(yaml.SafeLoader):
    pass


def _intrinsic(loader, tag_suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


CloudFormationLoader.add_multi_constructor("!", _intrinsic)


def load_template():
    return yaml.load(TEMPLATE.read_text(), Loader=CloudFormationLoader)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class CloudRepairRegressionTests(unittest.TestCase):
    def test_migration_url_percent_escapes_round_trip_through_configparser(self):
        module = load_module("alembic_url", ROOT / "src/backend/app/db/alembic_url.py")
        raw_url = "postgresql+psycopg://app_migrator:p%40ss%3Aword%25@db.example:5432/app"
        parser = ConfigParser()

        class ConfigAdapter:
            def set_main_option(self, name, value):
                parser.set("alembic", name, value)

            def get_main_option(self, name):
                return parser.get("alembic", name)

        parser.add_section("alembic")
        module.set_database_url(ConfigAdapter(), raw_url)
        parsed = urlsplit(parser.get("alembic", "sqlalchemy.url"))
        self.assertEqual(unquote(parsed.password), "p@ss:word%")

    def test_database_role_defaults_are_set_by_the_migrator_and_master_password_is_rds_safe(self):
        bootstrap = (SCRIPTS / "bootstrap-db-roles.sh").read_text()
        roles = (SCRIPTS / "configure-app-roles.sql").read_text()
        migration = (SCRIPTS / "run-migrations.sh").read_text()
        self.assertIn("master_password\" =~ [/@", bootstrap)
        self.assertNotIn("migrator_password\" =~", bootstrap)
        self.assertNotIn("runtime_password\" =~", bootstrap)
        self.assertNotRegex(bootstrap, r"ALTER DEFAULT PRIVILEGES FOR ROLE app_migrator")
        self.assertIn("CREATE ROLE app_migrator LOGIN PASSWORD %L NOSUPERUSER", roles)
        self.assertNotRegex(roles, r"ALTER ROLE app_(?:migrator|runtime)[^\n]*NOSUPERUSER")
        self.assertIn("OR NOT rolcanlogin OR rolinherit", roles)
        self.assertIn("OR rolreplication OR rolbypassrls", roles)
        self.assertIn("Existing application role has an unexpected role membership", roles)
        self.assertIn("ALTER DEFAULT PRIVILEGES IN SCHEMA public", migration)
        self.assertIn('quote(os.environ["MIGRATOR_PASSWORD"], safe="")', migration)
        self.assertEqual(quote("migrator!@:%/pass", safe=""), "migrator%21%40%3A%25%2Fpass")
        self.assertLess(roles.index("SET log_statement"), roles.index("CREATE ROLE app_migrator"))
        self.assertNotIn("SET log_statement = 'none' 2>/dev/null", bootstrap)

    def test_pg16_creator_membership_predicate_allows_only_the_expected_admin_grant(self):
        roles = (SCRIPTS / "configure-app-roles.sql").read_text()
        match = re.search(
            r"WHERE (\(granted_role\.rolname IN \('app_migrator', 'app_runtime'\).*?)\n  \) THEN",
            roles,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        predicate = match.group(1).replace("current_user", ":current_user")
        connection = sqlite3.connect(":memory:")
        connection.executescript("""
            CREATE TABLE pg_auth_members (
                roleid INTEGER, member INTEGER,
                admin_option BOOLEAN, inherit_option BOOLEAN, set_option BOOLEAN
            );
            CREATE TABLE pg_roles (oid INTEGER, rolname TEXT);
            INSERT INTO pg_roles VALUES (1, 'app_migrator'), (2, 'app_runtime'), (3, 'dbadmin'), (4, 'other');
        """)
        query = f"""SELECT EXISTS (
            SELECT 1 FROM pg_auth_members AS membership
            JOIN pg_roles AS granted_role ON granted_role.oid = membership.roleid
            JOIN pg_roles AS member_role ON member_role.oid = membership.member
            WHERE {predicate}
        )"""
        cases = (
            ([(1, 3, True, False, False), (2, 3, True, False, False)], 0),
            ([(1, 3, False, False, False)], 1),
            ([(1, 3, True, True, False)], 1),
            ([(1, 3, True, False, True)], 1),
            ([(1, 4, True, False, False)], 1),
            ([(4, 1, True, False, False)], 1),
        )
        for memberships, expected_violation in cases:
            with self.subTest(memberships=memberships):
                connection.execute("DELETE FROM pg_auth_members")
                connection.executemany("INSERT INTO pg_auth_members VALUES (?, ?, ?, ?, ?)", memberships)
                violation = connection.execute(query, {"current_user": "dbadmin"}).fetchone()[0]
                self.assertEqual(violation, expected_violation)
        connection.close()

    def test_master_password_guard_rejects_only_rds_forbidden_characters(self):
        bootstrap = (SCRIPTS / "bootstrap-db-roles.sh").read_text()
        guard = next(line.strip().split(" ||", 1)[0] for line in bootstrap.splitlines()
                     if line.startswith("[[ ! \"$master_password\" =~"))
        check = guard.replace("$master_password", "$PASSWORD")
        for password, expected in (("safe-punctuation!#%", 0), ("bad/password", 1),
                                   ('bad"password', 1), ("bad@password", 1), ("bad password", 1)):
            result = subprocess.run(
                ["bash", "-c", check], env={**os.environ, "PASSWORD": password},
                capture_output=True,
            )
            self.assertEqual(result.returncode, expected, password)

    def test_al2023_user_data_installs_cfn_signal_before_other_packages(self):
        parsed = load_template()
        script = parsed["Resources"]["ApiHost"]["Properties"]["UserData"]["Fn::Base64"]["Fn::Sub"][0]
        self.assertNotRegex(script, r"dnf install -y[^\n]*\bcurl\b|\bcoreutils\b")
        self.assertLess(script.index("dnf install -y aws-cfn-bootstrap"), script.index("dnf install -y awscli-2"))
        self.assertIn("docker compose version", script)

    def test_bootstrap_checks_compose_config_and_public_build_identity(self):
        bootstrap = (SCRIPTS / "bootstrap-api.sh").read_text()
        self.assertIn("docker compose --env-file /etc/inf2006/compose.env", bootstrap)
        self.assertIn("config --quiet", bootstrap)
        self.assertIn("org.opencontainers.image.google-client-id-sha256", bootstrap)

    def test_dockerfiles_keep_local_defaults_and_put_build_identity_on_web_image(self):
        backend = (ROOT / "src/backend/Dockerfile").read_text()
        frontend = (ROOT / "src/frontend/Dockerfile").read_text()
        bootstrap = (ROOT / "src/infra/Dockerfile.bootstrap").read_text()
        self.assertIn("ARG API_BASE_IMAGE=python:3.11-slim", backend)
        self.assertIn("ARG NODE_BASE_IMAGE=node:24.21.0-alpine", frontend)
        self.assertIn("ARG NGINX_BASE_IMAGE=nginx:1.29-alpine", frontend)
        self.assertLess(frontend.index("ARG NGINX_BASE_IMAGE"), frontend.index("FROM ${NODE_BASE_IMAGE}"))
        self.assertRegex(frontend, r"FROM \$\{NGINX_BASE_IMAGE\}[^\n]*\nARG GOOGLE_CLIENT_ID_SHA256\nLABEL org\.opencontainers\.image\.google-client-id-sha256")
        self.assertIn("ARG BOOTSTRAP_BASE_IMAGE=public.ecr.aws/amazonlinux/amazonlinux:2023", bootstrap)

    def test_compose_installer_is_pinned_and_checksum_checked(self):
        userdata = load_template()["Resources"]["ApiHost"]["Properties"]["UserData"]["Fn::Base64"]["Fn::Sub"][0]
        self.assertIn("v2.39.4", userdata)
        checksum = "7af95166a730b87e172d4fc9aefea8725d3c6c7327d59149267b452114ddb7d4"
        self.assertIn(checksum, userdata)
        line = next(line.strip() for line in userdata.splitlines() if "sha256sum --check --status" in line)
        self.assertIn(checksum, line)
        with tempfile.TemporaryDirectory(prefix="inf2006-compose-checksum-") as temp:
            payload = Path(temp) / "invalid-compose-binary"
            target = Path(temp) / "installed-compose"
            payload.write_text("not the pinned Docker Compose binary", encoding="utf-8")
            check = line.replace('"$compose_tmp"', '"$COMPOSE_TMP"')
            result = subprocess.run(
                ["bash", "-e", "-c", f"{check}\ninstall -m 0755 \"$COMPOSE_TMP\" \"$COMPOSE_TARGET\""],
                env={**os.environ, "COMPOSE_TMP": str(payload), "COMPOSE_TARGET": str(target)},
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(target.exists(), "a failed checksum must stop before install")

    def test_source_snapshot_porcelain_parser_consumes_rename_source_path(self):
        module = load_module("snapshot_script", SCRIPTS / "create-source-snapshot.py")
        records = module.parse_porcelain_status(b"R  docs/new.md\0src/old.md\0 M README.md\0")
        self.assertEqual(records, ["docs/new.md", "README.md"])

    def test_container_rehearsal_builds_or_accepts_only_immutable_api_images(self):
        script = (ROOT / "tests/infra/rehearse-containers.sh").read_text()
        role_script = (SCRIPTS / "configure-app-roles.sql").read_text()
        self.assertIn("--iidfile", script)
        self.assertIn("--platform linux/amd64", script)
        self.assertIn('"$api_image" == *@sha256:*', script)
        self.assertIn('^sha256:[a-f0-9]{64}$', script)
        self.assertIn('local_api_tag="inf2006-api-rehearsal:$(basename "$tmp_dir")"', script)
        self.assertEqual(script.count("run_role_configuration\n"), 2)
        self.assertIn("--file - \\\n    < src/infra/scripts/configure-app-roles.sql", script)
        self.assertIn("ALTER ROLE app_migrator", role_script)
        self.assertIn('catalogue_fixture="$PWD/data/synthetic_jobs.json"', script)
        self.assertIn('dry_run_before="$(catalogue_db_state)"', script)
        self.assertIn('[[ "$dry_run_before" == "$dry_run_after" ]] ||', script)
        self.assertIn('created=$expected_jobs([[:space:]]|$)', script)
        self.assertIn('unchanged=$expected_jobs', script)
        self.assertIn('catalogue_revision=$apply_revision', script)
        self.assertIn('app.main:app', script)
        self.assertIn('/health/ready', script)
        self.assertIn("echo 'PASS: AL2023 install", script)
        self.assertNotIn("aws ", script)

    def test_build_artifacts_record_base_digests_and_client_id_identity(self):
        script = (SCRIPTS / "build-and-publish-images.sh").read_text()
        self.assertIn("docker buildx imagetools inspect", script)
        self.assertIn("GOOGLE_CLIENT_ID_SHA256", script)
        self.assertIn('"$artifact_dir/build-provenance.json"', script)
        self.assertIn('"$artifact_dir/image-digests.env"', script)

    @unittest.skipUnless((ROOT / ".git").exists(), "needs a git checkout (not present in the submission ZIP)")
    def test_mocked_image_build_writes_one_parseable_digest_record_per_line(self):
        with tempfile.TemporaryDirectory(prefix="inf2006-image-digests-") as temp_dir:
            root = Path(temp_dir)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            source_docker_config = root / "docker-config"
            (source_docker_config / "cli-plugins").mkdir(parents=True)
            (source_docker_config / "contexts").mkdir()
            source_plugin = source_docker_config / "cli-plugins/docker-buildx"
            source_plugin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            source_plugin.chmod(0o755)
            (fake_bin / "aws").write_text("""#!/bin/bash
case "$*" in
  *get-login-password*) printf 'mock-login-token' ;;
  *describe-images*) printf 'sha256:%064d\\n' 0 ;;
  *) exit 2 ;;
esac
""", encoding="utf-8")
            (fake_bin / "docker").write_text("""#!/bin/bash
if [[ "$1 $2" == "login --username" ]]; then cat >/dev/null; exit 0; fi
if [[ "$1 $2" == "buildx imagetools" ]]; then printf 'Digest: sha256:%064d\\n' 1; exit 0; fi
if [[ "$1 $2" == "context show" ]]; then printf 'desktop-linux\\n'; exit 0; fi
if [[ "$1 $2" == "buildx version" ]]; then
  [[ -x "$DOCKER_CONFIG/cli-plugins/docker-buildx" ]] || { echo 'Buildx missing from isolated config' >&2; exit 1; }
  [[ "$DOCKER_CONTEXT" == "desktop-linux" ]] || { echo 'Docker context was not preserved' >&2; exit 1; }
  [[ -L "$DOCKER_CONFIG/contexts" ]] || { echo 'Docker contexts were not staged' >&2; exit 1; }
  [[ "$(readlink "$DOCKER_CONFIG/contexts")" == "$SOURCE_DOCKER_CONFIG/contexts" ]] || { echo 'Unexpected contexts source' >&2; exit 1; }
  exit 0
fi
exit 0
""", encoding="utf-8")
            for executable in fake_bin.iterdir():
                executable.chmod(0o755)

            artifacts = root / "artifacts"
            env = {
                **os.environ,
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "AWS_REGION": "us-east-1",
                "ECR_REGISTRY": "123456789012.dkr.ecr.us-east-1.amazonaws.com",
                "GOOGLE_CLIENT_ID": "rehearsal-client-id",
                "ARTIFACT_DIR": str(artifacts),
                "DOCKER_CONFIG": os.path.relpath(source_docker_config, ROOT),
                "SOURCE_DOCKER_CONFIG": str(source_docker_config),
            }
            result = subprocess.run(
                ["bash", str(SCRIPTS / "build-and-publish-images.sh")],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            env_file = next(artifacts.glob("inf2006-*/image-digests.env"))
            records = env_file.read_text(encoding="utf-8").splitlines()
            self.assertEqual([record.partition("=")[0] for record in records], [
                "API_IMAGE_URI", "WEB_IMAGE_URI", "BOOTSTRAP_IMAGE_URI",
                "SOURCE_SNAPSHOT_SHA256", "REPOSITORY_COMMIT",
            ])
            self.assertTrue(all(record.count("=") == 1 for record in records))
            for record in records[:3]:
                self.assertRegex(record, r"^\w+=[^@]+@sha256:" + "0" * 64 + r"$")

    @unittest.skipUnless((ROOT / ".git").exists(), "needs a git checkout (not present in the submission ZIP)")
    def test_buildx_preflight_failure_stops_before_ecr_login_and_cleans_up(self):
        with tempfile.TemporaryDirectory(prefix="inf2006-buildx-preflight-") as temp_dir:
            root = Path(temp_dir)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            source_docker_config = root / "docker-config"
            (source_docker_config / "cli-plugins").mkdir(parents=True)
            (source_docker_config / "contexts").mkdir()
            plugin = source_docker_config / "cli-plugins/docker-buildx"
            plugin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            plugin.chmod(0o755)
            login_marker = root / "ecr-login-started"
            config_marker = root / "isolated-config-path"
            (fake_bin / "aws").write_text("""#!/bin/bash
if [[ "$*" == *get-login-password* ]]; then touch "$LOGIN_MARKER"; printf 'mock-login-token'; exit 0; fi
exit 2
""", encoding="utf-8")
            (fake_bin / "docker").write_text("""#!/bin/bash
if [[ "$1 $2" == "context show" ]]; then printf 'desktop-linux\\n'; exit 0; fi
if [[ "$1 $2" == "buildx imagetools" ]]; then printf 'Digest: sha256:%064d\\n' 1; exit 0; fi
if [[ "$1 $2" == "buildx version" ]]; then
  printf '%s' "$DOCKER_CONFIG" > "$CONFIG_MARKER"
  [[ "$DOCKER_HOST" == "tcp://docker.example:2376" && -z "${DOCKER_CONTEXT:-}" ]] || { echo 'DOCKER_HOST override was not preserved' >&2; exit 3; }
  echo 'docker: unknown command: docker buildx' >&2
  exit 1
fi
exit 0
""", encoding="utf-8")
            for executable in fake_bin.iterdir():
                executable.chmod(0o755)
            env = {
                **os.environ,
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "AWS_REGION": "us-east-1",
                "ECR_REGISTRY": "123456789012.dkr.ecr.us-east-1.amazonaws.com",
                "GOOGLE_CLIENT_ID": "rehearsal-client-id",
                "ARTIFACT_DIR": str(root / "artifacts"),
                "DOCKER_CONFIG": str(source_docker_config),
                "DOCKER_HOST": "tcp://docker.example:2376",
                "LOGIN_MARKER": str(login_marker),
                "CONFIG_MARKER": str(config_marker),
            }
            result = subprocess.run(
                ["bash", str(SCRIPTS / "build-and-publish-images.sh")],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("refusing to log in", result.stderr)
            self.assertFalse(login_marker.exists(), "ECR login must not start when isolated Buildx preflight fails")
            self.assertTrue(config_marker.exists(), "Buildx preflight must run under the isolated config")
            self.assertFalse(Path(config_marker.read_text(encoding="utf-8")).exists(), "failed preflight must clean up temporary Docker config")

    def test_web_nginx_access_log_omits_query_strings(self):
        config = (ROOT / "src/infra/nginx/web-cloud.conf").read_text()
        self.assertIn("access_log /dev/stdout inf2006_sanitized", config)
        self.assertIn("$request_method $uri $server_protocol", config)

    def test_log_group_is_removed_on_create_rollback(self):
        parsed = load_template()
        self.assertEqual(parsed["Resources"]["ApiHostLogGroup"]["DeletionPolicy"], "RetainExceptOnCreate")


if __name__ == "__main__":
    unittest.main()
