#!/usr/bin/env bash
set -euo pipefail
set +x

for name in AWS_DEFAULT_REGION BOOTSTRAP_IMAGE_URI API_IMAGE_URI WEB_IMAGE_URI APP_ORIGIN TLS_SERVER_NAME GOOGLE_CLIENT_ID DB_ENDPOINT DB_NAME DB_RUNTIME_SECRET_ARN APP_SIGNING_KEY_SECRET_ARN PROCESSING_TEMP_BUCKET PROCESSING_TEMP_PREFIX PROCESSING_EXTRACTION_QUEUE_URL PROCESSING_EMBEDDING_QUEUE_URL API_LOG_GROUP WEB_LOG_GROUP SOURCE_SNAPSHOT_SHA256 APP_INSTANCE_ID; do
  [[ -n "${!name:-}" ]] || { printf 'Required setting is missing: %s\n' "$name" >&2; exit 2; }
done
[[ "$(id -u)" -eq 0 ]] || { echo 'Run as root.' >&2; exit 2; }
[[ "$API_IMAGE_URI" == *@sha256:* && "$WEB_IMAGE_URI" == *@sha256:* ]] || { echo 'Application images must be digest-pinned.' >&2; exit 2; }
[[ "$SOURCE_SNAPSHOT_SHA256" =~ ^[A-Fa-f0-9]{64}$ ]] || { echo 'Source snapshot identifier must be a SHA-256 digest.' >&2; exit 2; }
export INGRESS_MODE=private
/opt/inf2006/src/infra/scripts/validate-ingress-config.sh
/opt/inf2006/src/infra/scripts/create-target-tls.sh /etc/inf2006/tls
docker compose version >/dev/null

registry="${API_IMAGE_URI%%/*}"
bootstrap_label="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.source-snapshot-sha256"}}' "$BOOTSTRAP_IMAGE_URI" 2>/dev/null || true)"
[[ "$bootstrap_label" == "$SOURCE_SNAPSHOT_SHA256" ]] || { echo 'Bootstrap image source snapshot label does not match the approved manifest.' >&2; exit 2; }
docker_config="$(mktemp -d)"
trap 'rm -rf "$docker_config"; unset DATABASE_URL RUNTIME_PASSWORD SIGNING_KEY' EXIT
export DOCKER_CONFIG="$docker_config"
aws ecr get-login-password --region "$AWS_DEFAULT_REGION" | docker login --username AWS --password-stdin "$registry"
docker pull "$API_IMAGE_URI"
docker pull "$WEB_IMAGE_URI"
for image_uri in "$API_IMAGE_URI" "$WEB_IMAGE_URI"; do
  docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.source-snapshot-sha256"}}' "$image_uri" \
    | grep -Fqx "$SOURCE_SNAPSHOT_SHA256" \
    || { echo 'Application image source snapshot label does not match the approved manifest.' >&2; exit 2; }
done
google_client_id_sha256="$(printf '%s' "$GOOGLE_CLIENT_ID" | sha256sum | awk '{print $1}')"
docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.google-client-id-sha256"}}' "$WEB_IMAGE_URI" \
  | grep -Fqx "$google_client_id_sha256" \
  || { echo 'Web image Google client ID build argument does not match the configured client.' >&2; exit 2; }

runtime_json="$(aws secretsmanager get-secret-value --region "$AWS_DEFAULT_REGION" --secret-id "$DB_RUNTIME_SECRET_ARN" --query SecretString --output text)"
signing_json="$(aws secretsmanager get-secret-value --region "$AWS_DEFAULT_REGION" --secret-id "$APP_SIGNING_KEY_SECRET_ARN" --query SecretString --output text)"
[[ "$(jq -er '.username' <<<"$runtime_json")" == app_runtime ]] || { echo 'Runtime secret username must be app_runtime.' >&2; exit 2; }
runtime_password="$(jq -er '.password' <<<"$runtime_json")"
signing_key="$(jq -er '.key' <<<"$signing_json")"
unset runtime_json signing_json
[[ "$signing_key" =~ ^[A-Za-z0-9_-]{32,}$ ]] || { echo 'Signing key must be a base64url-style key of at least 32 characters.' >&2; exit 2; }

ca_file=/etc/pki/tls/certs/rds-global-bundle.pem
if [[ ! -s "$ca_file" ]]; then
  curl --fail --silent --show-error --location \
    https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem \
    --output "$ca_file.tmp"
  install -m 0644 "$ca_file.tmp" "$ca_file"
  rm -f "$ca_file.tmp"
fi

umask 077
RUNTIME_PASSWORD="$runtime_password" SIGNING_KEY="$signing_key" \
  python3 - "$DB_ENDPOINT" "$DB_NAME" "$APP_ORIGIN" "$GOOGLE_CLIENT_ID" "$TLS_SERVER_NAME" "$PROCESSING_TEMP_BUCKET" "$PROCESSING_TEMP_PREFIX" "$PROCESSING_EXTRACTION_QUEUE_URL" "$PROCESSING_EMBEDDING_QUEUE_URL" "$AWS_DEFAULT_REGION" <<'PY'
import json
import os
import sys
from urllib.parse import quote

(host, database, origin, google_client_id, tls_name, bucket, prefix,
 extraction_queue, embedding_queue, region) = sys.argv[1:]
database_url = (
    f"postgresql+psycopg://app_runtime:{quote(os.environ['RUNTIME_PASSWORD'], safe='')}@{host}:5432/{quote(database, safe='')}"
    "?sslmode=verify-full&sslrootcert=/etc/ssl/certs/rds-global-bundle.pem"
)
values = {
    "APP_ENV": "production",
    "APP_ORIGIN": origin,
    "GOOGLE_CLIENT_ID": google_client_id,
    "APP_SIGNING_KEY": os.environ["SIGNING_KEY"],
    "DATABASE_URL": database_url,
    "TLS_SERVER_NAME": tls_name,
    "PROCESSING_MODE": "aws",
    "AWS_REGION": region,
    "PROCESSING_TEMP_BUCKET": bucket,
    "PROCESSING_TEMP_PREFIX": prefix,
    "PROCESSING_TEMP_TTL_SECONDS": "3600",
    "PROCESSING_EXTRACTION_QUEUE_URL": extraction_queue,
    "PROCESSING_EMBEDDING_QUEUE_URL": embedding_queue,
}
with open("/etc/inf2006/api.env", "w", encoding="utf-8") as output:
    for name, value in values.items():
        output.write(f"{name}={json.dumps(value)}\n")
os.chmod("/etc/inf2006/api.env", 0o600)
PY
unset runtime_password signing_key

API_IMAGE_URI="$API_IMAGE_URI" WEB_IMAGE_URI="$WEB_IMAGE_URI" AWS_DEFAULT_REGION="$AWS_DEFAULT_REGION" \
  API_LOG_GROUP="$API_LOG_GROUP" WEB_LOG_GROUP="$WEB_LOG_GROUP" APP_INSTANCE_ID="$APP_INSTANCE_ID" \
  /opt/inf2006/src/infra/scripts/write-private-app-compose-env.sh /etc/inf2006/compose.env
install -m 0644 /opt/inf2006/src/infra/compose.private-ingress.yml /opt/inf2006/compose.private-ingress.yml
docker compose --env-file /etc/inf2006/compose.env -f /opt/inf2006/compose.private-ingress.yml config --quiet
docker compose --env-file /etc/inf2006/compose.env -f /opt/inf2006/compose.private-ingress.yml up -d
ready=0
for attempt in $(seq 1 60); do
  if curl --insecure --fail --silent --show-error https://127.0.0.1:8443/health/ready >/dev/null; then
    ready=1
    break
  fi
  sleep 5
done
[[ "$ready" == 1 ]] || { echo 'Private API target did not become ready before the bootstrap deadline.' >&2; exit 1; }
printf 'Private app target is ready; no migrations or privileged database bootstrap were run on this instance.\n'
