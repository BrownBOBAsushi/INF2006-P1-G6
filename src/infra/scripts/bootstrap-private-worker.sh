#!/usr/bin/env bash
set -euo pipefail
set +x

for name in AWS_DEFAULT_REGION API_IMAGE_URI DB_ENDPOINT DB_NAME DB_MASTER_SECRET_ARN DB_MIGRATOR_SECRET_ARN DB_RUNTIME_SECRET_ARN TLS_SERVER_NAME DUCKDNS_TOKEN_SECRET_ARN PROCESSING_TEMP_BUCKET PROCESSING_TEMP_PREFIX PROCESSING_EXTRACTION_QUEUE_URL PROCESSING_EMBEDDING_QUEUE_URL LOG_GROUP SOURCE_SNAPSHOT_SHA256 WORKER_INSTANCE_ID; do
  [[ -n "${!name:-}" ]] || { printf 'Required setting is missing: %s\n' "$name" >&2; exit 2; }
done
[[ "$(id -u)" -eq 0 ]] || { echo 'Run as root.' >&2; exit 2; }
[[ "$API_IMAGE_URI" == *@sha256:* ]] || { echo 'Worker application image must be digest-pinned.' >&2; exit 2; }
[[ "$SOURCE_SNAPSHOT_SHA256" =~ ^[A-Fa-f0-9]{64}$ ]] || { echo 'Source snapshot identifier must be a SHA-256 digest.' >&2; exit 2; }
[[ "$PROCESSING_TEMP_PREFIX" =~ ^[A-Za-z0-9/_-]+$ && "$PROCESSING_TEMP_PREFIX" != *..* ]] || { echo 'Temporary input prefix is invalid.' >&2; exit 2; }
[[ "$PROCESSING_EXTRACTION_QUEUE_URL" == https://* && "$PROCESSING_EMBEDDING_QUEUE_URL" == https://* && "$PROCESSING_EXTRACTION_QUEUE_URL" != "$PROCESSING_EMBEDDING_QUEUE_URL" ]] || { echo 'Distinct HTTPS extraction and embedding queue URLs are required.' >&2; exit 2; }
[[ "$TLS_SERVER_NAME" =~ ^[A-Za-z0-9-]+\.duckdns\.org$ ]] || { echo 'TLS_SERVER_NAME must be the approved DuckDNS hostname.' >&2; exit 2; }

docker compose version >/dev/null
registry="${API_IMAGE_URI%%/*}"
docker_config="$(mktemp -d)"
trap 'rm -rf "$docker_config"; unset DB_RUNTIME_PASSWORD DATABASE_URL' EXIT
export DOCKER_CONFIG="$docker_config"
aws ecr get-login-password --region "$AWS_DEFAULT_REGION" | docker login --username AWS --password-stdin "$registry"
docker pull "$API_IMAGE_URI"
docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.source-snapshot-sha256"}}' "$API_IMAGE_URI" \
  | grep -Fqx "$SOURCE_SNAPSHOT_SHA256" \
  || { echo 'Application image source snapshot label does not match the approved manifest.' >&2; exit 2; }

export DB_RUNTIME_SECRET_ARN="$DB_RUNTIME_SECRET_ARN" DB_MASTER_SECRET_ARN="$DB_MASTER_SECRET_ARN" DB_MIGRATOR_SECRET_ARN="$DB_MIGRATOR_SECRET_ARN"
/opt/inf2006/src/infra/scripts/bootstrap-db-roles.sh
export API_IMAGE_URI DB_ENDPOINT DB_NAME DB_MIGRATOR_SECRET_ARN
/opt/inf2006/src/infra/scripts/run-migrations.sh --apply

secret_json="$(aws secretsmanager get-secret-value --region "$AWS_DEFAULT_REGION" --secret-id "$DB_RUNTIME_SECRET_ARN" --query SecretString --output text)"
[[ "$(jq -er '.username' <<<"$secret_json")" == app_runtime ]] || { echo 'Runtime secret username must be app_runtime.' >&2; exit 2; }
runtime_password="$(jq -er '.password' <<<"$secret_json")"
unset secret_json
ca_file=/etc/pki/tls/certs/rds-global-bundle.pem
if [[ ! -s "$ca_file" ]]; then
  curl --fail --silent --show-error --location \
    https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem \
    --output "$ca_file.tmp"
  install -m 0644 "$ca_file.tmp" "$ca_file"
  rm -f "$ca_file.tmp"
fi
RUNTIME_PASSWORD="$runtime_password" python3 - "$DB_ENDPOINT" "$DB_NAME" <<'PY'
import json
import os
import sys
from urllib.parse import quote

host, database = sys.argv[1:]
database_url = (
    f"postgresql+psycopg://app_runtime:{quote(os.environ['RUNTIME_PASSWORD'], safe='')}@{host}:5432/{quote(database, safe='')}"
    "?sslmode=verify-full&sslrootcert=/etc/ssl/certs/rds-global-bundle.pem"
)
with open('/etc/inf2006/api.env', 'w', encoding='utf-8') as output:
    output.write(f'APP_ENV={json.dumps("production")}\n')
    output.write(f'DATABASE_URL={json.dumps(database_url)}\n')
os.chmod('/etc/inf2006/api.env', 0o600)
PY
unset runtime_password

umask 077
cat > /etc/inf2006/ingress-acme.env <<EOF
AWS_DEFAULT_REGION=$AWS_DEFAULT_REGION
TLS_SERVER_NAME=$TLS_SERVER_NAME
DUCKDNS_TOKEN_SECRET_ARN=$DUCKDNS_TOKEN_SECRET_ARN
EOF
chmod 0600 /etc/inf2006/ingress-acme.env
install -m 0644 /opt/inf2006/src/infra/systemd/inf2006-ingress-cert-renew.service /etc/systemd/system/inf2006-ingress-cert-renew.service
install -m 0644 /opt/inf2006/src/infra/systemd/inf2006-ingress-cert-renew.timer /etc/systemd/system/inf2006-ingress-cert-renew.timer
systemctl daemon-reload
cat > /etc/inf2006/worker.env <<EOF
PROCESSING_MODE=aws
AWS_REGION=$AWS_DEFAULT_REGION
PROCESSING_TEMP_BUCKET=$PROCESSING_TEMP_BUCKET
PROCESSING_TEMP_PREFIX=$PROCESSING_TEMP_PREFIX
PROCESSING_TEMP_TTL_SECONDS=3600
PROCESSING_EXTRACTION_QUEUE_URL=$PROCESSING_EXTRACTION_QUEUE_URL
PROCESSING_EMBEDDING_QUEUE_URL=$PROCESSING_EMBEDDING_QUEUE_URL
EOF
chmod 0600 /etc/inf2006/worker.env
cat > /etc/inf2006/compose.env <<EOF
API_IMAGE_URI=$API_IMAGE_URI
AWS_REGION=$AWS_DEFAULT_REGION
LOG_GROUP=$LOG_GROUP
INSTANCE_ID=$WORKER_INSTANCE_ID
EOF
chmod 0600 /etc/inf2006/compose.env
docker compose --env-file /etc/inf2006/compose.env -f /opt/inf2006/src/infra/compose.private-worker.yml config --quiet
docker compose --env-file /etc/inf2006/compose.env -f /opt/inf2006/src/infra/compose.private-worker.yml up -d
ready_budget=2100
if [[ "${WORKER_READY_DEADLINE_EPOCH:-}" =~ ^[0-9]+$ ]]; then
  ready_budget=$((WORKER_READY_DEADLINE_EPOCH - $(date +%s)))
fi
(( ready_budget > 0 )) || { echo 'No worker startup budget remains before the CloudFormation signal deadline.' >&2; exit 1; }
deadline=$((SECONDS + ready_budget))
workers_ready=0
while (( SECONDS < deadline )); do
  all_healthy=1
  for service in extraction-worker embedding-worker; do
    container_id="$(docker compose --env-file /etc/inf2006/compose.env -f /opt/inf2006/src/infra/compose.private-worker.yml ps -q "$service")"
    if [[ -z "$container_id" ]]; then
      all_healthy=0
      break
    fi
    state="$(docker inspect --format '{{.State.Status}}' "$container_id" 2>/dev/null || true)"
    health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$container_id" 2>/dev/null || true)"
    if [[ "$state" == exited || "$state" == dead || "$state" == restarting || "$state" == paused || "$health" == unhealthy || "$health" == missing ]]; then
      echo "Private worker service failed before readiness: $service state=$state health=$health" >&2
      exit 1
    fi
    if [[ "$state" != running || "$health" != healthy ]]; then
      all_healthy=0
      break
    fi
  done
  if [[ "$all_healthy" == 1 ]]; then
    workers_ready=1
    break
  fi
  sleep 5
done
[[ "$workers_ready" == 1 ]] || { echo 'Private workers did not pass model, database and heartbeat readiness before the CloudFormation signal deadline.' >&2; exit 1; }
printf 'Private worker initialized; migration is complete and both workers are running in AWS mode.\n'
