#!/usr/bin/env bash
set -euo pipefail
set +x

for name in AWS_DEFAULT_REGION API_IMAGE_URI WEB_IMAGE_URI APP_ORIGIN PUBLIC_HOSTNAME GOOGLE_CLIENT_ID DB_ENDPOINT DB_NAME DB_RUNTIME_SECRET_ARN DB_MASTER_SECRET_ARN DB_MIGRATOR_SECRET_ARN APP_SIGNING_KEY_SECRET_ARN DUCKDNS_TOKEN_SECRET_ARN SOURCE_SNAPSHOT_SHA256 LOG_GROUP; do
  [[ -n "${!name:-}" ]] || { printf 'Required setting is missing: %s\n' "$name" >&2; exit 2; }
done
[[ "$(id -u)" -eq 0 ]] || { echo 'Run as root.' >&2; exit 2; }
[[ "$APP_ORIGIN" == "https://$PUBLIC_HOSTNAME" ]] || { echo 'APP_ORIGIN must be the exact HTTPS hostname origin.' >&2; exit 2; }
[[ "$API_IMAGE_URI" == *@sha256:* && "$WEB_IMAGE_URI" == *@sha256:* ]] || { echo 'Application images must be digest-pinned.' >&2; exit 2; }
[[ "$SOURCE_SNAPSHOT_SHA256" =~ ^[A-Fa-f0-9]{64}$ ]] || { echo 'Source snapshot identifier must be a SHA-256 digest.' >&2; exit 2; }
docker compose version
if [[ -n "${BOOTSTRAP_IMAGE_URI:-}" ]]; then
  docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.source-snapshot-sha256"}}' "$BOOTSTRAP_IMAGE_URI" \
    | grep -Fqx "$SOURCE_SNAPSHOT_SHA256" \
    || { echo 'Bootstrap image source snapshot label does not match the approved manifest.' >&2; exit 2; }
fi

install -d -m 0750 /opt/inf2006 /etc/inf2006 /var/www/certbot
install -m 0644 /opt/inf2006/src/infra/compose.cloud.yml /opt/inf2006/compose.cloud.yml
install -m 0644 /opt/inf2006/src/infra/nginx/inf2006-http.conf /etc/nginx/conf.d/inf2006.conf
rm -f /etc/nginx/conf.d/default.conf
nginx -t
systemctl enable --now nginx docker

registry="$(printf '%s' "$API_IMAGE_URI" | cut -d/ -f1)"
docker_config="$(mktemp -d)"
trap 'rm -rf "$docker_config"' EXIT
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
  || { echo 'Web image Google client ID build argument does not match the stack parameter.' >&2; exit 2; }

export DB_ENDPOINT DB_NAME DB_RUNTIME_SECRET_ARN DB_MASTER_SECRET_ARN DB_MIGRATOR_SECRET_ARN
/opt/inf2006/src/infra/scripts/bootstrap-db-roles.sh
export AWS_DEFAULT_REGION API_IMAGE_URI DB_ENDPOINT DB_NAME DB_MIGRATOR_SECRET_ARN
/opt/inf2006/src/infra/scripts/run-migrations.sh --apply

secret_json="$(aws secretsmanager get-secret-value \
  --region "$AWS_DEFAULT_REGION" \
  --secret-id "$DB_RUNTIME_SECRET_ARN" \
  --query SecretString --output text)"
[[ "$(jq -er '.username' <<<"$secret_json")" == app_runtime ]] || { echo 'Runtime secret username must be app_runtime.' >&2; exit 2; }
signing_json="$(aws secretsmanager get-secret-value \
  --region "$AWS_DEFAULT_REGION" \
  --secret-id "$APP_SIGNING_KEY_SECRET_ARN" \
  --query SecretString --output text)"
runtime_password="$(jq -er '.password' <<<"$secret_json")"
signing_key="$(jq -er '.key' <<<"$signing_json")"
unset secret_json signing_json
[[ "$signing_key" =~ ^[A-Za-z0-9_-]{32,}$ ]] || { echo 'Signing key must be a base64url-style key of at least 32 characters.' >&2; exit 2; }

umask 077
RUNTIME_PASSWORD="$runtime_password" SIGNING_KEY="$signing_key" \
  python3 - "$DB_ENDPOINT" "$DB_NAME" "$APP_ORIGIN" "$GOOGLE_CLIENT_ID" <<'PY'
import json
import os
import sys
from urllib.parse import quote

host, database, origin, google_client_id = sys.argv[1:]
password = quote(os.environ["RUNTIME_PASSWORD"], safe="")
user = quote("app_runtime", safe="")
db_name = quote(database, safe="")
database_url = (
    f"postgresql+psycopg://{user}:{password}@{host}:5432/{db_name}"
    "?sslmode=verify-full&sslrootcert=/etc/ssl/certs/rds-global-bundle.pem"
)
lines = {
    "APP_ENV": "production",
    "APP_ORIGIN": origin,
    "GOOGLE_CLIENT_ID": google_client_id,
    "APP_SIGNING_KEY": os.environ["SIGNING_KEY"],
    "DATABASE_URL": database_url,
}
with open("/etc/inf2006/api.env", "w", encoding="utf-8") as output:
    for name, value in lines.items():
        output.write(f"{name}={json.dumps(value)}\n")
os.chmod("/etc/inf2006/api.env", 0o600)
PY
unset runtime_password signing_key

cat > /etc/inf2006/compose.env <<EOF
API_IMAGE_URI=$API_IMAGE_URI
WEB_IMAGE_URI=$WEB_IMAGE_URI
AWS_REGION=$AWS_DEFAULT_REGION
LOG_GROUP=$LOG_GROUP
EOF
chmod 0600 /etc/inf2006/compose.env
cat > /etc/inf2006/stack.env <<EOF
AWS_DEFAULT_REGION=$AWS_DEFAULT_REGION
BOOTSTRAP_IMAGE_URI=${BOOTSTRAP_IMAGE_URI:-}
PUBLIC_HOSTNAME=$PUBLIC_HOSTNAME
APP_ORIGIN=$APP_ORIGIN
DUCKDNS_TOKEN_SECRET_ARN=$DUCKDNS_TOKEN_SECRET_ARN
LOG_GROUP=$LOG_GROUP
EOF
chmod 0600 /etc/inf2006/stack.env

docker compose --env-file /etc/inf2006/compose.env \
  -f /opt/inf2006/compose.cloud.yml config --quiet

if [[ ! -s /etc/pki/tls/certs/rds-global-bundle.pem ]]; then
  curl --fail --silent --show-error --location \
    https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem \
    --output /etc/pki/tls/certs/rds-global-bundle.pem.tmp
  install -m 0644 /etc/pki/tls/certs/rds-global-bundle.pem.tmp /etc/pki/tls/certs/rds-global-bundle.pem
  rm -f /etc/pki/tls/certs/rds-global-bundle.pem.tmp
fi

nginx -t
systemctl reload nginx
printf 'Database and digest-pinned images are prepared. Application containers remain stopped until DNS and HTTPS are explicitly activated.\n'
