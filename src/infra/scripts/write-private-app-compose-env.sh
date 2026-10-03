#!/usr/bin/env bash
set -euo pipefail
set +x

for name in API_IMAGE_URI WEB_IMAGE_URI AWS_DEFAULT_REGION API_LOG_GROUP WEB_LOG_GROUP APP_INSTANCE_ID; do
  [[ -n "${!name:-}" ]] || { printf 'Required setting is missing: %s\n' "$name" >&2; exit 2; }
done
[[ $# -eq 1 ]] || { echo 'Usage: write-private-app-compose-env.sh <output-path>' >&2; exit 2; }
[[ "$API_IMAGE_URI" =~ @sha256:[a-f0-9]{64}$ && "$WEB_IMAGE_URI" =~ @sha256:[a-f0-9]{64}$ ]] || { echo 'Application images must be digest-pinned.' >&2; exit 2; }
[[ "$AWS_DEFAULT_REGION" =~ ^[a-z0-9-]+$ ]] || { echo 'AWS_DEFAULT_REGION is invalid.' >&2; exit 2; }
[[ "$API_LOG_GROUP" =~ ^/inf2006/[A-Za-z0-9._/-]+$ && "$WEB_LOG_GROUP" =~ ^/inf2006/[A-Za-z0-9._/-]+$ ]] || { echo 'CloudWatch log group names are invalid.' >&2; exit 2; }
[[ "$APP_INSTANCE_ID" =~ ^i-[A-Za-z0-9]+$ ]] || { echo 'APP_INSTANCE_ID is invalid.' >&2; exit 2; }

output="$1"
install -d -m 0750 "$(dirname "$output")"
umask 077
cat > "$output" <<EOF
API_IMAGE_URI=$API_IMAGE_URI
WEB_IMAGE_URI=$WEB_IMAGE_URI
AWS_REGION=$AWS_DEFAULT_REGION
LOG_GROUP=$API_LOG_GROUP
WEB_LOG_GROUP=$WEB_LOG_GROUP
INSTANCE_ID=$APP_INSTANCE_ID
EOF
chmod 0600 "$output"
