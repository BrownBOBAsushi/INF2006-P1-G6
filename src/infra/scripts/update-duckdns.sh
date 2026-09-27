#!/usr/bin/env bash
set -euo pipefail
set +x

if [[ "${1:-}" != "--apply" ]]; then
  echo 'No DNS change made. Re-run with --apply only after deployment authorization.'
  exit 0
fi
for name in AWS_DEFAULT_REGION PUBLIC_HOSTNAME PUBLIC_IP DUCKDNS_TOKEN_SECRET_ARN; do
  [[ -n "${!name:-}" ]] || { printf 'Required setting is missing: %s\n' "$name" >&2; exit 2; }
done
[[ "$PUBLIC_HOSTNAME" == *.duckdns.org ]] || { echo 'Hostname must be under duckdns.org.' >&2; exit 2; }
subdomain="${PUBLIC_HOSTNAME%.duckdns.org}"
[[ "$subdomain" =~ ^[A-Za-z0-9-]+$ ]] || { echo 'DuckDNS subdomain is invalid.' >&2; exit 2; }
[[ "$PUBLIC_IP" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || { echo 'Expected a public IPv4 address.' >&2; exit 2; }

secret_json="$(aws secretsmanager get-secret-value \
  --region "$AWS_DEFAULT_REGION" \
  --secret-id "$DUCKDNS_TOKEN_SECRET_ARN" \
  --query SecretString --output text)"
token="$(jq -er '.token' <<<"$secret_json")"
unset secret_json
[[ "$token" =~ ^[A-Fa-f0-9-]{24,64}$ ]] || { echo 'DuckDNS token format is invalid.' >&2; exit 2; }

curl_config_dir="${DUCKDNS_CURL_CONFIG_DIR:-/run}"
curl_config="$(mktemp "$curl_config_dir/inf2006-duckdns.XXXXXX")"
chmod 0600 "$curl_config"
trap 'rm -f "$curl_config"; unset token' EXIT
cat > "$curl_config" <<EOF
url = "https://www.duckdns.org/update?domains=$subdomain&token=$token&ip=$PUBLIC_IP"
silent
show-error
EOF
unset token
result="$(curl --config "$curl_config" 2>/dev/null)"
[[ "$result" == OK ]] || { echo 'DuckDNS did not confirm the update.' >&2; exit 1; }
printf 'DuckDNS A record update confirmed for %s. Verify public DNS before requesting a certificate.\n' "$PUBLIC_HOSTNAME"
