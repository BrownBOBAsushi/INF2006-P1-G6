#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077

action="${1:-}"
case "$action" in auth|cleanup) ;; *) echo 'Expected auth or cleanup hook action.' >&2; exit 2 ;; esac
[[ "${INF2006_ACME_LOCK_HELD:-0}" == 1 ]] || { echo 'Run DNS hooks through the locked ingress-certificate helper.' >&2; exit 2; }
for name in AWS_DEFAULT_REGION DUCKDNS_TOKEN_SECRET_ARN TLS_SERVER_NAME CERTBOT_DOMAIN CERTBOT_VALIDATION; do
  [[ -n "${!name:-}" ]] || { printf 'Required setting is missing: %s\n' "$name" >&2; exit 2; }
done
[[ "$TLS_SERVER_NAME" == "$CERTBOT_DOMAIN" && "$TLS_SERVER_NAME" == *.duckdns.org ]] || {
  echo 'Certificate domain does not match the approved DuckDNS hostname.' >&2; exit 2;
}
subdomain="${TLS_SERVER_NAME%.duckdns.org}"
[[ "$subdomain" =~ ^[A-Za-z0-9-]+$ && "$CERTBOT_VALIDATION" =~ ^[A-Za-z0-9_-]+$ ]] || {
  echo 'DuckDNS challenge parameters are invalid.' >&2; exit 2;
}
command -v aws >/dev/null && command -v curl >/dev/null && command -v dig >/dev/null || {
  echo 'aws, curl, and dig are required.' >&2; exit 2;
}

timeout="${DUCKDNS_PROPAGATION_TIMEOUT_SECONDS:-120}"
[[ "$timeout" =~ ^[0-9]+$ && "$timeout" -ge 1 && "$timeout" -le 600 ]] || {
  echo 'DNS propagation timeout must be an integer from 1 to 600 seconds.' >&2; exit 2;
}
query_dns() {
  local label="$1"; shift
  local require_authoritative=0 response status flags rc
  if [[ "${1:-}" == authoritative ]]; then require_authoritative=1; shift; fi
  if response="$(dig +time=2 +tries=1 +comments +answer "$@" 2>/dev/null)"; then
    rc=0
  else
    rc=$?
  fi
  status="$(sed -nE 's/^;; ->>HEADER<<- opcode: [^,]+, status: ([A-Z]+),.*/\1/p' <<<"$response" | head -n 1)"
  flags="$(sed -nE 's/^;; flags: ([^;]*);.*/\1/p' <<<"$response" | head -n 1)"
  if (( rc != 0 )); then
    printf 'DNS query failed for %s (dig exit %s).\n' "$label" "$rc" >&2
    return 1
  fi
  if [[ "$status" != NOERROR ]]; then
    printf 'DNS query failed for %s (response status %s).\n' "$label" "${status:-missing}" >&2
    return 1
  fi
  if (( require_authoritative )) && [[ " $flags " != *' aa '* ]]; then
    printf 'DNS query failed for %s (response was not authoritative).\n' "$label" >&2
    return 1
  fi
  printf '%s\n' "$response"
}

ns_output="$(query_dns 'DuckDNS nameservers' NS duckdns.org)" || exit 1
nameservers=()
while IFS= read -r ns; do [[ -n "$ns" ]] && nameservers+=("${ns%.}"); done < <(
  awk '$4 == "NS" { sub(/\.$/, "", $5); print $5 }' <<<"$ns_output" | sort -u
)
(( ${#nameservers[@]} > 0 )) || { echo 'Could not discover DuckDNS authoritative nameservers.' >&2; exit 1; }

challenge_name="_acme-challenge.$TLS_SERVER_NAME"
read_txt_values() {
  local ns raw
  for ns in "${nameservers[@]}"; do
    raw="$(query_dns "$challenge_name at $ns" authoritative "@$ns" TXT "$challenge_name")" || return 1
    awk '$4 == "TXT" { value=""; for (i=5; i<=NF; i++) { gsub(/"/, "", $i); value = value $i } if (value != "") print value }' <<<"$raw"
  done | sort -u
}
authoritative_value_is() {
  local expected="$1" ns raw normalized rc
  for ns in "${nameservers[@]}"; do
    raw="$(query_dns "$challenge_name at $ns" authoritative "@$ns" TXT "$challenge_name")" || return 2
    normalized="$(awk '$4 == "TXT" { value=""; for (i=5; i<=NF; i++) { gsub(/"/, "", $i); value = value $i } if (value != "") print value }' <<<"$raw" | sort -u)"
    [[ "$normalized" == "$expected" ]] || return 1
  done
  return 0
}
records="$(read_txt_values)" || exit 1

if [[ "$action" == cleanup ]]; then
  if [[ "$records" != "$CERTBOT_VALIDATION" ]]; then
    echo 'TXT cleanup skipped because authoritative records are not exactly this challenge value.' >&2
    exit 0
  fi
  if authoritative_value_is "$CERTBOT_VALIDATION"; then :; else
    verify_rc=$?
    if (( verify_rc == 1 )); then
      echo 'TXT cleanup skipped because authoritative records are not exactly this challenge value.' >&2
      exit 0
    fi
    exit "$verify_rc"
  fi
  secret_json="$(aws secretsmanager get-secret-value --region "$AWS_DEFAULT_REGION" \
    --secret-id "$DUCKDNS_TOKEN_SECRET_ARN" --query SecretString --output text)"
  token="$(jq -er '.token' <<<"$secret_json")"
  unset secret_json
  [[ "$token" =~ ^[A-Fa-f0-9-]{24,64}$ ]] || { unset token; echo 'DuckDNS token format is invalid.' >&2; exit 2; }
  curl_config_dir="${DUCKDNS_CURL_CONFIG_DIR:-/run}"
  [[ -d "$curl_config_dir" && -w "$curl_config_dir" ]] || { unset token; echo 'Private curl-config directory is unavailable.' >&2; exit 2; }
  curl_config="$(mktemp "$curl_config_dir/inf2006-acme.XXXXXX")"
  chmod 0600 "$curl_config"
  trap 'rm -f "$curl_config"; unset token' EXIT
  cat >"$curl_config" <<EOF
url = "https://www.duckdns.org/update?domains=$subdomain&token=$token&txt=$CERTBOT_VALIDATION&clear=true"
silent
show-error
fail
max-time = 20
EOF
  unset token
  result="$(curl --config "$curl_config" 2>/dev/null)"
  [[ "$result" == OK ]] || { echo 'DuckDNS did not confirm the TXT cleanup.' >&2; exit 1; }
  exit 0
fi

if [[ -n "$records" && "$records" != "$CERTBOT_VALIDATION" ]]; then
  echo 'A different authoritative TXT value exists; refusing to overwrite shared DuckDNS state.' >&2
  exit 1
fi
secret_json="$(aws secretsmanager get-secret-value --region "$AWS_DEFAULT_REGION" \
  --secret-id "$DUCKDNS_TOKEN_SECRET_ARN" --query SecretString --output text)"
token="$(jq -er '.token' <<<"$secret_json")"
unset secret_json
[[ "$token" =~ ^[A-Fa-f0-9-]{24,64}$ ]] || { unset token; echo 'DuckDNS token format is invalid.' >&2; exit 2; }
curl_config_dir="${DUCKDNS_CURL_CONFIG_DIR:-/run}"
[[ -d "$curl_config_dir" && -w "$curl_config_dir" ]] || { unset token; echo 'Private curl-config directory is unavailable.' >&2; exit 2; }
curl_config="$(mktemp "$curl_config_dir/inf2006-acme.XXXXXX")"
chmod 0600 "$curl_config"
trap 'rm -f "$curl_config"; unset token' EXIT
cat >"$curl_config" <<EOF
url = "https://www.duckdns.org/update?domains=$subdomain&token=$token&txt=$CERTBOT_VALIDATION"
silent
show-error
fail
max-time = 20
EOF
unset token
result="$(curl --config "$curl_config" 2>/dev/null)"
[[ "$result" == OK ]] || { echo 'DuckDNS did not confirm the TXT update.' >&2; exit 1; }

deadline=$((SECONDS + timeout))
while (( SECONDS <= deadline )); do
  records="$(read_txt_values)"
  if [[ "$records" == "$CERTBOT_VALIDATION" ]] && authoritative_value_is "$CERTBOT_VALIDATION"; then exit 0; fi
  sleep 5
done
echo 'DuckDNS TXT value did not propagate to every authoritative nameserver before the deadline.' >&2
exit 1
