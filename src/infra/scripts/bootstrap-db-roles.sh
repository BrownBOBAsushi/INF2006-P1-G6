#!/usr/bin/env bash
set -euo pipefail
set +x

for name in AWS_DEFAULT_REGION DB_ENDPOINT DB_NAME DB_MASTER_SECRET_ARN DB_MIGRATOR_SECRET_ARN DB_RUNTIME_SECRET_ARN; do
  [[ -n "${!name:-}" ]] || { printf 'Required setting is missing: %s\n' "$name" >&2; exit 2; }
done
[[ "$(id -u)" -eq 0 ]] || { echo 'Run as root.' >&2; exit 2; }
command -v psql >/dev/null
command -v jq >/dev/null

secret_json() {
  aws secretsmanager get-secret-value \
    --region "$AWS_DEFAULT_REGION" \
    --secret-id "$1" \
    --query SecretString \
    --output text
}

master_secret="$(secret_json "$DB_MASTER_SECRET_ARN")"
migrator_secret="$(secret_json "$DB_MIGRATOR_SECRET_ARN")"
runtime_secret="$(secret_json "$DB_RUNTIME_SECRET_ARN")"
[[ "$(jq -er '.username' <<<"$master_secret")" == dbadmin ]] || { echo 'Database master secret username must be dbadmin.' >&2; exit 2; }
[[ "$(jq -er '.username' <<<"$migrator_secret")" == app_migrator ]] || { echo 'Migrator secret username must be app_migrator.' >&2; exit 2; }
[[ "$(jq -er '.username' <<<"$runtime_secret")" == app_runtime ]] || { echo 'Runtime secret username must be app_runtime.' >&2; exit 2; }

master_password="$(jq -er '.password' <<<"$master_secret")"
migrator_password="$(jq -er '.password' <<<"$migrator_secret")"
runtime_password="$(jq -er '.password' <<<"$runtime_secret")"
unset master_secret migrator_secret runtime_secret
[[ ! "$master_password" =~ [/@\"\ ] ]] || {
  echo 'Database master password contains a character rejected by RDS PostgreSQL.' >&2
  exit 2
}

ca_file=/etc/pki/tls/certs/rds-global-bundle.pem
if [[ ! -s "$ca_file" ]]; then
  curl --fail --silent --show-error --location \
    https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem \
    --output "$ca_file.tmp"
  install -m 0644 "$ca_file.tmp" "$ca_file"
  rm -f "$ca_file.tmp"
fi

export PGPASSWORD="$master_password"
export APP_MIGRATOR_PASSWORD="$migrator_password"
export APP_RUNTIME_PASSWORD="$runtime_password"
unset master_password migrator_password runtime_password

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
psql "host=$DB_ENDPOINT port=5432 dbname=$DB_NAME user=dbadmin sslmode=verify-full sslrootcert=$ca_file" \
  --no-psqlrc --set=ON_ERROR_STOP=1 --set=DB_NAME="$DB_NAME" \
  --file "$script_dir/configure-app-roles.sql"

unset PGPASSWORD APP_MIGRATOR_PASSWORD APP_RUNTIME_PASSWORD
printf 'Database extension and restricted app roles are ready. Secret values were not printed.\n'
