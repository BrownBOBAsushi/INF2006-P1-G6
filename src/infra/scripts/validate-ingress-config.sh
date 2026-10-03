#!/usr/bin/env bash
set -euo pipefail
set +x

mode="${INGRESS_MODE:-foundation}"
case "$mode" in foundation|private) ;; *) echo 'INGRESS_MODE must be foundation or private.' >&2; exit 2 ;; esac
for name in APP_ORIGIN TLS_SERVER_NAME; do
  [[ -n "${!name:-}" ]] || { printf 'Required setting is missing: %s\n' "$name" >&2; exit 2; }
done
[[ "$TLS_SERVER_NAME" =~ ^[A-Za-z0-9.-]+$ ]] || { echo 'TLS_SERVER_NAME must be a DNS hostname.' >&2; exit 2; }
python3 - "$APP_ORIGIN" <<'PY'
import sys
from urllib.parse import urlsplit

origin = urlsplit(sys.argv[1])
if (origin.scheme != "https" or not origin.hostname or origin.username or origin.password
        or origin.path or origin.query or origin.fragment):
    raise SystemExit("APP_ORIGIN must be an HTTPS origin without path, query, or fragment.")
PY
if [[ "$mode" == foundation ]]; then
  [[ -n "${PUBLIC_HOSTNAME:-}" ]] || { echo 'PUBLIC_HOSTNAME is required in foundation mode.' >&2; exit 2; }
  [[ -n "${DUCKDNS_TOKEN_SECRET_ARN:-}" ]] || { echo 'DUCKDNS_TOKEN_SECRET_ARN is required in foundation mode.' >&2; exit 2; }
  [[ "$TLS_SERVER_NAME" == "$PUBLIC_HOSTNAME" ]] || { echo 'Foundation TLS_SERVER_NAME must match PUBLIC_HOSTNAME.' >&2; exit 2; }
  [[ "$APP_ORIGIN" == "https://$PUBLIC_HOSTNAME" ]] || { echo 'Foundation APP_ORIGIN must match PUBLIC_HOSTNAME.' >&2; exit 2; }
fi
