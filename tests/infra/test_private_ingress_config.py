#!/usr/bin/env python3
"""Offline structural checks for the API Gateway ingress preparation."""

from pathlib import Path
import os
import stat
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "src/infra"


class CloudFormationLoader(yaml.SafeLoader):
    pass


def _intrinsic(loader, tag_suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    raise TypeError(f"unsupported CloudFormation node: {type(node).__name__}")


CloudFormationLoader.add_multi_constructor("!", _intrinsic)


class PrivateIngressConfigTests(unittest.TestCase):
    def test_http_api_is_private_proxy_with_explicit_snapshot_stage(self):
        template = yaml.load(
            (INFRA / "cloudformation/ingress-http-api.yaml").read_text(),
            Loader=CloudFormationLoader,
        )
        resources = template["Resources"]
        api = resources["HttpApi"]["Properties"]
        link = resources["VpcLink"]["Properties"]
        integration = resources["ProxyIntegration"]["Properties"]
        route = resources["DefaultRoute"]["Properties"]
        stage = resources["DefaultStage"]["Properties"]

        self.assertEqual(api["ProtocolType"], "HTTP")
        self.assertFalse(api["DisableExecuteApiEndpoint"])
        self.assertEqual(link["SubnetIds"], ["VpcLinkSubnetIdA", "VpcLinkSubnetIdB"])
        self.assertEqual(integration["IntegrationType"], "HTTP_PROXY")
        self.assertEqual(integration["ConnectionType"], "VPC_LINK")
        self.assertEqual(integration["IntegrationUri"], "InternalAlbHttpsListener")
        self.assertEqual(integration["TimeoutInMillis"], 30000)
        self.assertEqual(integration["TlsConfig"]["ServerNameToVerify"], "BackendTlsServerName")
        self.assertEqual(integration["RequestParameters"]["overwrite:path"], "$request.path")
        self.assertEqual(route["RouteKey"], "$default")
        self.assertFalse(stage["AutoDeploy"])
        self.assertEqual(stage["DeploymentId"], "DeploymentR1")
        self.assertNotIn("DeploymentRevision", template["Parameters"])
        self.assertIn("increment the logical ID", resources["DeploymentR1"]["Properties"]["Description"])
        self.assertNotRegex(stage["AccessLogSettings"]["Format"], r"cookie|authorization|sourceIp|requestTimeEpoch")

        self.assertEqual(resources["InternalAlb"]["Properties"]["Scheme"], "internal")
        self.assertEqual(resources["AppHttpsTargetGroup"]["Properties"]["Protocol"], "HTTPS")
        self.assertEqual(resources["AppHttpsTargetGroup"]["Properties"]["Port"], 8443)
        self.assertEqual(resources["AppHttpsTargetGroup"]["Properties"]["HealthCheckPath"], "/health/ready")
        self.assertEqual(resources["InternalAlbHttpsListener"]["Properties"]["Port"], 443)
        self.assertEqual(resources["VpcLink"]["Properties"]["SecurityGroupIds"], ["VpcLinkSecurityGroup"])
        self.assertEqual(resources["VpcLinkToAlbEgress"]["Properties"]["ToPort"], 443)
        self.assertEqual(resources["AlbFromVpcLinkIngress"]["Properties"]["FromPort"], 443)
        self.assertEqual(resources["AlbToAppEgress"]["Properties"]["ToPort"], 8443)
        self.assertEqual(resources["AppFromAlbIngress"]["Properties"]["SourceSecurityGroupId"], "InternalAlbSecurityGroup")
        for group in ("VpcLinkSecurityGroup", "InternalAlbSecurityGroup", "AppTargetSecurityGroup"):
            sentinel = resources[group]["Properties"]["SecurityGroupEgress"][0]
            self.assertEqual(sentinel["IpProtocol"], "-1")
            self.assertEqual(sentinel["CidrIp"], "127.0.0.1/32")
        self.assertIn("AlbFromVpcLinkIngress", resources["InternalAlb"]["DependsOn"])
        self.assertEqual(resources["VpcLink"]["DependsOn"], "VpcLinkToAlbEgress")
        self.assertEqual(template["Outputs"]["InternalAlbHttpsListenerArn"]["Value"], "InternalAlbHttpsListener")

    def test_private_nginx_and_compose_publish_tls_only(self):
        nginx = (INFRA / "nginx/web-private-https.conf").read_text()
        compose = yaml.safe_load((INFRA / "compose.private-ingress.yml").read_text())
        web = compose["services"]["web"]
        ports = [str(item) for item in web["ports"]]
        api_proxy = nginx.split("location ^~ /api/ {", 1)[1].split("# Build assets", 1)[0]

        self.assertIn("listen 8443 ssl default_server;", nginx)
        self.assertIn("client_max_body_size 6m;", nginx)
        self.assertIn("proxy_set_header Origin $http_origin;", api_proxy)
        self.assertIn("proxy_set_header Cookie $http_cookie;", api_proxy)
        self.assertIn("proxy_set_header X-CSRF-Token $http_x_csrf_token;", api_proxy)
        self.assertIn("proxy_set_header X-Forwarded-Proto https;", api_proxy)
        self.assertIn("proxy_read_timeout 25s;", api_proxy)
        self.assertIn("location ^~ /assets/", nginx)
        self.assertIn("try_files $uri =404;", nginx)
        self.assertNotIn("8080", nginx + " ".join(ports))
        self.assertEqual(ports, ["8443:8443"])
        self.assertTrue(any("web-private-https.conf" in item for item in web["volumes"]))
        self.assertTrue(any("/etc/inf2006/tls" in item for item in web["volumes"]))

    def test_certificate_tool_requires_explicit_apply_and_validates_leaf_before_import(self):
        script = (INFRA / "scripts/ingress-certificate.sh").read_text()
        chain_check = script.index("openssl verify -purpose sslserver")
        import_call = script.index("aws_args=(acm import-certificate")
        self.assertIn("--config-dir /etc/letsencrypt-staging --work-dir /var/lib/letsencrypt-staging", script)
        self.assertIn("--logs-dir /var/log/letsencrypt-staging", script)
        self.assertIn("--key-type rsa --rsa-key-size 2048", script)
        self.assertIn('certbot renew --cert-name "$TLS_SERVER_NAME"', script)
        self.assertIn('[[ "${1:-}" == --apply && $# -eq 2 ]]', script)
        self.assertIn('leaf="$cert_dir/cert.pem"', script)
        self.assertIn('--certificate fileb://"$leaf"', script)
        self.assertIn('--certificate-chain fileb://"$chain"', script)
        self.assertIn('aws_args+=(--certificate-arn "$INGRESS_CERTIFICATE_ARN")', script)
        self.assertIn('exec 9>"$lock_path"', script)
        self.assertLess(chain_check, import_call)
        self.assertIn("Staging certificate issued for rehearsal only; it was not imported to ACM.", script)

    def test_certificate_check_requires_hook_and_flock_without_external_operations(self):
        with tempfile.TemporaryDirectory(prefix="ingress-cert-check-") as temporary:
            root = Path(temporary)
            fakebin = root / "bin"
            fakebin.mkdir()
            script_dir = root / "scripts"
            script_dir.mkdir()
            helper = script_dir / "ingress-certificate.sh"
            helper.write_text((INFRA / "scripts/ingress-certificate.sh").read_text())
            helper.chmod(0o755)
            called = root / "external-command-called"
            for tool in ("certbot", "openssl", "aws"):
                path = fakebin / tool
                path.write_text(f"#!/bin/sh\nprintf %s {tool} >> '{called}'\nexit 99\n")
                path.chmod(0o755)
            (fakebin / "dirname").symlink_to("/usr/bin/dirname")
            environment = dict(
                os.environ,
                PATH=str(fakebin),
                AWS_DEFAULT_REGION="us-east-1",
                TLS_SERVER_NAME="internshipmatcher.duckdns.org",
            )
            missing_prerequisites = subprocess.run(
                ["/bin/bash", str(helper), "check"], env=environment,
                capture_output=True, text=True, timeout=2,
            )
            self.assertNotEqual(missing_prerequisites.returncode, 0)
            self.assertIn("flock", missing_prerequisites.stderr)
            self.assertFalse(called.exists())

            (fakebin / "flock").write_text("#!/bin/sh\nexit 99\n")
            (fakebin / "flock").chmod(0o755)
            missing_dig = subprocess.run(
                ["/bin/bash", str(helper), "check"], env=environment,
                capture_output=True, text=True, timeout=2,
            )
            self.assertNotEqual(missing_dig.returncode, 0)
            self.assertIn("dig", missing_dig.stderr)
            self.assertFalse(called.exists())

            (fakebin / "dig").write_text("#!/bin/sh\nexit 99\n")
            (fakebin / "dig").chmod(0o755)
            missing_hook = subprocess.run(
                ["/bin/bash", str(helper), "check"], env=environment,
                capture_output=True, text=True, timeout=2,
            )
            self.assertNotEqual(missing_hook.returncode, 0)
            self.assertIn("duckdns-acme-hook.sh", missing_hook.stderr)
            self.assertFalse(called.exists())

            hook = script_dir / "duckdns-acme-hook.sh"
            hook.write_text("#!/bin/sh\nexit 99\n")
            hook.chmod(0o755)
            complete = subprocess.run(
                ["/bin/bash", str(helper), "check"], env=environment,
                capture_output=True, text=True, timeout=2,
            )
            self.assertEqual(complete.returncode, 0, complete.stderr)
            self.assertIn("no external operation was run", complete.stdout)
            self.assertFalse(called.exists())

    def test_bare_actions_do_nothing_and_failed_renew_skips_import(self):
        original = (INFRA / "scripts/ingress-certificate.sh").read_text()
        with tempfile.TemporaryDirectory(prefix="ingress-cert-failure-") as temporary:
            root = Path(temporary)
            fakebin = root / "bin"
            fakebin.mkdir()
            calls = root / "calls"
            config = root / "ingress-acme.env"
            config.write_text(
                "AWS_DEFAULT_REGION=us-east-1\n"
                "TLS_SERVER_NAME=internshipmatcher.duckdns.org\n"
                "DUCKDNS_TOKEN_SECRET_ARN=arn:aws:secretsmanager:us-east-1:000000000000:secret:test\n"
                "INGRESS_CERTIFICATE_ARN=arn:aws:acm:us-east-1:000000000000:certificate/00000000-0000-0000-0000-000000000000\n"
            )
            config.chmod(0o600)
            for action in ("issue", "renew"):
                result = subprocess.run(
                    ["bash", str(INFRA / "scripts/ingress-certificate.sh"), action],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                self.assertNotEqual(result.returncode, 0)

            (fakebin / "certbot").write_text(f"#!/bin/sh\nprintf certbot >> '{calls}'\nexit 42\n")
            (fakebin / "aws").write_text(f"#!/bin/sh\nprintf aws >> '{calls}'\nexit 99\n")
            (fakebin / "flock").write_text("#!/bin/sh\nexit 0\n")
            (fakebin / "stat").write_text("#!/bin/sh\ncase \"$1:$2\" in '-f:%u') echo 0 ;; '-f:%Lp') echo 600 ;; *) exit 3 ;; esac\n")
            for tool in ("certbot", "aws", "flock", "stat"):
                (fakebin / tool).chmod(0o755)
            # Run the exact helper logic with only its root privilege guard removed;
            # all external commands are local stubs and no network can be reached.
            test_helper = root / "ingress-certificate.sh"
            root_guard = '[[ "${EUID:-$(id -u)}" -eq 0 ]] || { echo \'Apply actions must run as root.\' >&2; exit 2; }'
            self.assertIn(root_guard, original)
            test_helper.write_text(original.replace(root_guard, "true", 1))
            test_helper.chmod(0o755)
            environment = dict(
                os.environ,
                PATH=f"{fakebin}:{os.environ['PATH']}",
                INGRESS_ACME_ENV_FILE=str(config),
                AWS_DEFAULT_REGION="us-east-1",
                TLS_SERVER_NAME="internshipmatcher.duckdns.org",
                DUCKDNS_TOKEN_SECRET_ARN="arn:aws:secretsmanager:us-east-1:000000000000:secret:test",
                INGRESS_CERTIFICATE_ARN="arn:aws:acm:us-east-1:000000000000:certificate/00000000-0000-0000-0000-000000000000",
                INGRESS_CERT_LOCK_PATH=str(root / "lock"),
            )
            marker = root / "should-not-run"
            config.write_text(f"AWS_DEFAULT_REGION=$(touch {marker})\n")
            rejected_config = subprocess.run(
                ["bash", str(test_helper), "--apply", "issue"],
                env=environment,
                capture_output=True,
                text=True,
                timeout=2,
            )
            self.assertNotEqual(rejected_config.returncode, 0)
            self.assertFalse(marker.exists())
            config.write_text(
                "AWS_DEFAULT_REGION=us-east-1\n"
                "TLS_SERVER_NAME=internshipmatcher.duckdns.org\n"
                "DUCKDNS_TOKEN_SECRET_ARN=arn:aws:secretsmanager:us-east-1:000000000000:secret:test\n"
                "INGRESS_CERTIFICATE_ARN=arn:aws:acm:us-east-1:000000000000:certificate/00000000-0000-0000-0000-000000000000\n"
            )
            config.chmod(0o600)
            failed_renew = subprocess.run(
                ["bash", str(test_helper), "--apply", "renew"],
                env=environment,
                capture_output=True,
                text=True,
                timeout=2,
            )
            self.assertEqual(failed_renew.returncode, 42, failed_renew.stderr)
            self.assertEqual(calls.read_text(), "certbot")

    def test_issue_creates_first_arn_then_reimport_reuses_it(self):
        original = (INFRA / "scripts/ingress-certificate.sh").read_text()
        with tempfile.TemporaryDirectory(prefix="ingress-cert-lifecycle-") as temporary:
            root = Path(temporary)
            fakebin = root / "bin"
            fakebin.mkdir()
            live = root / "live"
            logs = root / "aws-args"
            certificate_arn = "arn:aws:acm:us-east-1:000000000000:certificate/00000000-0000-0000-0000-000000000000"
            stubs = {
                "stat": "#!/bin/sh\ncase \"$1:$2\" in '-f:%u') echo 0 ;; '-f:%Lp') echo 600 ;; *) exit 3 ;; esac\n",
                "flock": "#!/bin/sh\nexit 0\n",
                "certbot": (
                    "#!/bin/sh\n"
                    f"mkdir -p '{live}'\n"
                    f"for name in cert.pem chain.pem fullchain.pem privkey.pem; do printf synthetic > '{live}/'$name; done\n"
                ),
                "openssl": (
                    "#!/bin/sh\n"
                    "case \"$*\" in\n"
                    "  *checkhost*|*verify*purpose*|*pkey*check*) exit 0 ;;\n"
                    "  *x509*pubkey*|*pkey*pubout*) printf matching-public-key ;;\n"
                    "  *pkey*pubin*) cat ;;\n"
                    "  *dgst*sha256*) cat >/dev/null; printf 'SHA256 matching-public-key\\n' ;;\n"
                    "  *) exit 4 ;;\n"
                    "esac\n"
                ),
                "aws": (
                    "#!/bin/sh\nprintf '%s\\n' \"$@\" >> \"$AWS_ARGS_LOG\"\n"
                    f"printf '%s\\n' '{certificate_arn}'\n"
                ),
            }
            for name, content in stubs.items():
                path = fakebin / name
                path.write_text(content)
                path.chmod(0o755)
            config = root / "ingress-acme.env"
            config.write_text(
                "AWS_DEFAULT_REGION=us-east-1\n"
                "TLS_SERVER_NAME=internshipmatcher.duckdns.org\n"
                "DUCKDNS_TOKEN_SECRET_ARN=arn:aws:secretsmanager:us-east-1:000000000000:secret:test\n"
            )
            config.chmod(0o600)
            # Remove only the root guard in this temporary copy; all command
            # boundaries are local stubs and all certificate paths are temp files.
            root_guard = '[[ "${EUID:-$(id -u)}" -eq 0 ]] || { echo \'Apply actions must run as root.\' >&2; exit 2; }'
            self.assertIn(root_guard, original)
            test_helper = root / "ingress-certificate.sh"
            test_helper.write_text(original.replace(root_guard, "true", 1))
            test_helper.chmod(0o755)
            environment = dict(
                os.environ,
                PATH=f"{fakebin}:{os.environ['PATH']}",
                INGRESS_ACME_ENV_FILE=str(config),
                INGRESS_CERT_LOCK_PATH=str(root / "lock"),
                INGRESS_CERT_LIVE_DIR=str(live),
                AWS_ARGS_LOG=str(logs),
            )
            first_import = subprocess.run(
                ["bash", str(test_helper), "--apply", "issue"],
                env=environment,
                capture_output=True,
                text=True,
                timeout=3,
            )
            self.assertEqual(first_import.returncode, 0, first_import.stderr)
            self.assertIn(certificate_arn, first_import.stdout)
            first_args = logs.read_text()
            self.assertIn("fileb://" + str(live / "cert.pem"), first_args)
            self.assertNotIn("--certificate-arn", first_args)

            with config.open("a") as config_file:
                config_file.write(f"INGRESS_CERTIFICATE_ARN={certificate_arn}\n")
            config.chmod(0o600)
            reuse_environment = dict(environment)
            reuse = subprocess.run(
                ["bash", str(test_helper), "--apply", "reimport"],
                env=reuse_environment,
                capture_output=True,
                text=True,
                timeout=3,
            )
            self.assertEqual(reuse.returncode, 0, reuse.stderr)
            all_args = logs.read_text()
            self.assertIn("--certificate-arn", all_args)
            self.assertIn(certificate_arn, all_args)

    def test_compose_config_parses_with_local_placeholder_mounts(self):
        text = (INFRA / "compose.private-ingress.yml").read_text()
        with tempfile.TemporaryDirectory(prefix="ingress-compose-check-") as temporary:
            root = Path(temporary)
            for name, content in {
                "api.env": "APP_ENV=production\n",
                "rds.pem": "synthetic placeholder\n",
                "nginx.conf": "synthetic placeholder\n",
                "target.crt": "synthetic placeholder\n",
                "target.key": "synthetic placeholder\n",
            }.items():
                (root / name).write_text(content)
            for original, replacement in {
                "/etc/inf2006/api.env": str(root / "api.env"),
                "/etc/pki/tls/certs/rds-global-bundle.pem": str(root / "rds.pem"),
                "/opt/inf2006/src/infra/nginx/web-private-https.conf": str(root / "nginx.conf"),
                "/etc/inf2006/tls": str(root),
            }.items():
                text = text.replace(original, replacement)
            compose_file = root / "compose.yml"
            compose_file.write_text(text)
            compose_env = root / "compose.env"
            environment = os.environ | {
                "API_IMAGE_URI": "example.invalid/api@sha256:" + "a" * 64,
                "WEB_IMAGE_URI": "example.invalid/web@sha256:" + "b" * 64,
                "AWS_DEFAULT_REGION": "us-east-1",
                "API_LOG_GROUP": "/inf2006/local-api",
                "WEB_LOG_GROUP": "/inf2006/local-web",
                "APP_INSTANCE_ID": "i-test12345678",
            }
            subprocess.run(
                ["bash", str(INFRA / "scripts/write-private-app-compose-env.sh"), str(compose_env)],
                env=environment, check=True, capture_output=True, text=True,
            )
            generated_environment = dict(environment)
            for line in compose_env.read_text().splitlines():
                key, value = line.split("=", 1)
                generated_environment[key] = value
            self.assertEqual(generated_environment["WEB_LOG_GROUP"], "/inf2006/local-web")
            subprocess.run(
                ["docker", "compose", "--env-file", str(compose_env), "-f", str(compose_file), "config", "--quiet"],
                env=generated_environment,
                check=True,
                capture_output=True,
                text=True,
            )

    def test_target_tls_is_created_locally_with_restricted_key_mode(self):
        with tempfile.TemporaryDirectory(prefix="ingress-target-tls-") as temporary:
            tls_dir = Path(temporary) / "tls"
            helper = ["bash", str(INFRA / "scripts/create-target-tls.sh")]
            subprocess.run(
                [*helper, str(tls_dir)],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["openssl", "x509", "-in", str(tls_dir / "target.crt"), "-noout", "-checkhost", "inf2006-target.local"],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(stat.S_IMODE((tls_dir / "target.key").stat().st_mode), 0o400)
            cert_path = tls_dir / "target.crt"
            key_path = tls_dir / "target.key"
            matched_cert = cert_path.read_bytes()
            matched_key = key_path.read_bytes()
            subprocess.run([*helper, str(tls_dir)], check=True, capture_output=True, text=True)
            self.assertEqual(cert_path.read_bytes(), matched_cert)
            self.assertEqual(key_path.read_bytes(), matched_key)

            mismatched_key = Path(temporary) / "other.key"
            subprocess.run(
                ["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", str(mismatched_key)],
                check=True,
                capture_output=True,
                text=True,
            )
            mismatched_key_bytes = mismatched_key.read_bytes()
            key_path.chmod(0o600)
            key_path.write_bytes(mismatched_key_bytes)
            key_path.chmod(0o400)
            failed = subprocess.run([*helper, str(tls_dir)], capture_output=True, text=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("do not match", failed.stderr)
            self.assertEqual(cert_path.read_bytes(), matched_cert)
            self.assertEqual(key_path.read_bytes(), mismatched_key_bytes)

            partial_dir = Path(temporary) / "partial"
            partial_dir.mkdir()
            partial_cert = partial_dir / "target.crt"
            partial_cert.write_bytes(matched_cert)
            failed_partial = subprocess.run([*helper, str(partial_dir)], capture_output=True, text=True)
            self.assertNotEqual(failed_partial.returncode, 0)
            self.assertTrue(partial_cert.is_file())
            self.assertFalse((partial_dir / "target.key").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
