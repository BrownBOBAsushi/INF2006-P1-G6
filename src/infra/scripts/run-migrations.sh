#!/usr/bin/env bash
set -euo pipefail
set +x

for name in AWS_DEFAULT_REGION DB_ENDPOINT DB_NAME DB_MIGRATOR_SECRET_ARN API_IMAGE_URI; do
  [[ -n "${!name:-}" ]] || { printf 'Required setting is missing: %s\n' "$name" >&2; exit 2; }
done
[[ "$(id -u)" -eq 0 ]] || { echo 'Run as root.' >&2; exit 2; }

secret_json="$(aws secretsmanager get-secret-value \
  --region "$AWS_DEFAULT_REGION" \
  --secret-id "$DB_MIGRATOR_SECRET_ARN" \
  --query SecretString --output text)"
[[ "$(jq -er '.username' <<<"$secret_json")" == app_migrator ]] || { echo 'Migrator secret username must be app_migrator.' >&2; exit 2; }
migrator_password="$(jq -er '.password' <<<"$secret_json")"
unset secret_json
trap 'unset DATABASE_URL PGPASSWORD migrator_password' EXIT

ca_file=/etc/pki/tls/certs/rds-global-bundle.pem
[[ -s "$ca_file" ]] || { echo 'RDS CA bundle is missing; run the database bootstrap first.' >&2; exit 2; }
export DATABASE_URL="$(MIGRATOR_PASSWORD="$migrator_password" python3 - "$DB_ENDPOINT" "$DB_NAME" <<'PY'
import os
import sys
from urllib.parse import quote

host, database = sys.argv[1:]
user = quote("app_migrator", safe="")
password = quote(os.environ["MIGRATOR_PASSWORD"], safe="")
print(
    f"postgresql+psycopg://{user}:{password}@{host}:5432/{quote(database, safe='')}"
    "?sslmode=verify-full&sslrootcert=/etc/pki/tls/certs/rds-global-bundle.pem"
)
PY
)"
docker run --rm --network host \
  --env DATABASE_URL \
  --volume "$ca_file:$ca_file:ro" \
  --entrypoint alembic \
  "$API_IMAGE_URI" upgrade head

export PGPASSWORD="$migrator_password"
psql "host=$DB_ENDPOINT port=5432 dbname=$DB_NAME user=app_migrator sslmode=verify-full sslrootcert=$ca_file" \
  --no-psqlrc --set=ON_ERROR_STOP=1 \
  -c 'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_runtime;' \
  -c 'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO app_runtime;' \
  -c 'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_runtime;' \
  -c 'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_runtime;' \
  -c 'REVOKE ALL ON TABLE public.alembic_version FROM app_runtime;'
unset PGPASSWORD
unset DATABASE_URL
printf 'Migration completed with app_migrator; runtime Alembic access is revoked.\n'
