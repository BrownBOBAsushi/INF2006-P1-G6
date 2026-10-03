#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
validator="$repo_root/src/infra/scripts/validate-ingress-config.sh"

INGRESS_MODE=private TLS_SERVER_NAME=internshipmatcher.duckdns.org \
  APP_ORIGIN=https://sample.execute-api.us-east-1.amazonaws.com bash "$validator"

INGRESS_MODE=foundation PUBLIC_HOSTNAME=internshipmatcher.duckdns.org \
  TLS_SERVER_NAME=internshipmatcher.duckdns.org \
  APP_ORIGIN=https://internshipmatcher.duckdns.org \
  DUCKDNS_TOKEN_SECRET_ARN=arn:aws:secretsmanager:us-east-1:000000000000:secret:fixture \
  bash "$validator"

if INGRESS_MODE=foundation PUBLIC_HOSTNAME=internshipmatcher.duckdns.org \
  TLS_SERVER_NAME=internshipmatcher.duckdns.org \
  APP_ORIGIN=https://sample.execute-api.us-east-1.amazonaws.com \
  DUCKDNS_TOKEN_SECRET_ARN=arn:fixture bash "$validator" >/dev/null 2>&1; then
  echo 'Foundation mode unexpectedly accepted a split origin.' >&2
  exit 1
fi

if INGRESS_MODE=private TLS_SERVER_NAME=internshipmatcher.duckdns.org \
  APP_ORIGIN=https://sample.execute-api.us-east-1.amazonaws.com/path bash "$validator" >/dev/null 2>&1; then
  echo 'Private mode unexpectedly accepted an origin path.' >&2
  exit 1
fi
echo 'PASS: private mode splits APP_ORIGIN/TLS_SERVER_NAME; foundation keeps its public-host equality gate.'
