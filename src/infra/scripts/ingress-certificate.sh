#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
action=""
apply=0
if [[ "${1:-}" == check && $# -eq 1 ]]; then
  action=check
elif [[ "${1:-}" == --apply && $# -eq 2 ]]; then
  apply=1
  action="$2"
else
  echo 'Usage: ingress-certificate.sh check | --apply {issue|issue-staging|renew|reimport}' >&2
  exit 2
fi

if [[ "$action" == check ]]; then
  for name in AWS_DEFAULT_REGION TLS_SERVER_NAME; do
    [[ -n "${!name:-}" ]] || { printf 'Required setting is missing: %s\n' "$name" >&2; exit 2; }
  done
  [[ "$TLS_SERVER_NAME" == *.duckdns.org ]] || { echo 'TLS_SERVER_NAME must be the approved DuckDNS hostname.' >&2; exit 2; }
  command -v certbot >/dev/null && command -v openssl >/dev/null && command -v aws >/dev/null && command -v dig >/dev/null && command -v flock >/dev/null || {
    echo 'certbot, openssl, aws, dig, and flock are required.' >&2; exit 1;
  }
  [[ -x "$script_dir/duckdns-acme-hook.sh" ]] || { echo 'duckdns-acme-hook.sh must be installed and executable beside this script.' >&2; exit 1; }
  echo 'Certificate tooling and hostname configuration are present; no external operation was run.'
  exit 0
fi

case "$action" in issue|issue-staging|renew|reimport) ;; *) echo 'Unknown certificate action.' >&2; exit 2 ;; esac
[[ "${EUID:-$(id -u)}" -eq 0 ]] || { echo 'Apply actions must run as root.' >&2; exit 2; }
config_file="${INGRESS_ACME_ENV_FILE:-/etc/inf2006/ingress-acme.env}"
[[ -f "$config_file" && ! -L "$config_file" ]] || { echo 'A root-only /etc/inf2006/ingress-acme.env file is required.' >&2; exit 2; }
if stat --version >/dev/null 2>&1; then
  owner="$(stat -c '%u' "$config_file")"
  mode="$(stat -c '%a' "$config_file")"
else
  owner="$(stat -f '%u' "$config_file")"
  mode="$(stat -f '%Lp' "$config_file")"
fi
[[ "$owner" == 0 && "$mode" =~ ^[0-7]{3,4}$ ]] || { echo 'The ingress environment file must be owned by root with an octal mode.' >&2; exit 2; }
(( (8#$mode & 077) == 0 )) || { echo 'The ingress environment file must not be accessible to group or other users.' >&2; exit 2; }
unset AWS_DEFAULT_REGION TLS_SERVER_NAME DUCKDNS_TOKEN_SECRET_ARN INGRESS_CERTIFICATE_ARN
while IFS= read -r line || [[ -n "$line" ]]; do
  [[ -z "$line" || "$line" == \#* ]] && continue
  [[ "$line" =~ ^([A-Z_]+)=([A-Za-z0-9._:/-]+)$ ]] || { echo 'The ingress environment file contains an invalid setting.' >&2; exit 2; }
  name="${BASH_REMATCH[1]}"
  value="${BASH_REMATCH[2]}"
  case "$name" in AWS_DEFAULT_REGION|TLS_SERVER_NAME|DUCKDNS_TOKEN_SECRET_ARN|INGRESS_CERTIFICATE_ARN) ;; *) echo 'The ingress environment file contains an unsupported setting.' >&2; exit 2 ;; esac
  export "$name=$value"
done < "$config_file"
for name in AWS_DEFAULT_REGION TLS_SERVER_NAME; do
  [[ -n "${!name:-}" ]] || { printf 'Required setting is missing: %s\n' "$name" >&2; exit 2; }
done
[[ "$TLS_SERVER_NAME" == *.duckdns.org ]] || { echo 'TLS_SERVER_NAME must be the approved DuckDNS hostname.' >&2; exit 2; }
[[ "$TLS_SERVER_NAME" =~ ^[A-Za-z0-9-]+\.duckdns\.org$ ]] || { echo 'TLS_SERVER_NAME is invalid.' >&2; exit 2; }
command -v flock >/dev/null || { echo 'flock is required for serialized certificate operations.' >&2; exit 2; }

if [[ "$action" == issue || "$action" == issue-staging || "$action" == renew ]]; then
  [[ -n "${DUCKDNS_TOKEN_SECRET_ARN:-}" ]] || { echo 'DUCKDNS_TOKEN_SECRET_ARN is required for DNS-01 issuance.' >&2; exit 2; }
fi
if [[ "$action" == renew ]]; then
  [[ "${INGRESS_CERTIFICATE_ARN:-}" =~ ^arn:aws:acm:[a-z0-9-]+:[0-9]{12}:certificate/[0-9a-fA-F-]+$ ]] || {
    echo 'Renewal and reimport require the existing INGRESS_CERTIFICATE_ARN.' >&2; exit 2;
  }
fi

lock_path="${INGRESS_CERT_LOCK_PATH:-/run/lock/inf2006-ingress-cert.lock}"
mkdir -p "$(dirname "$lock_path")"
exec 9>"$lock_path"
if [[ "${INF2006_ACME_LOCK_HELD:-0}" != 1 ]]; then
  flock -n 9 || { echo 'Another certificate operation holds the lock.' >&2; exit 1; }
  export INF2006_ACME_LOCK_HELD=1
fi

case "$action" in
  issue|issue-staging)
    command -v certbot >/dev/null || { echo 'certbot is required.' >&2; exit 2; }
    certbot_args=(certonly --manual --preferred-challenges dns --manual-auth-hook "$script_dir/duckdns-acme-hook.sh auth" \
      --manual-cleanup-hook "$script_dir/duckdns-acme-hook.sh cleanup" --agree-tos --non-interactive \
      --register-unsafely-without-email --key-type rsa --rsa-key-size 2048 --cert-name "$TLS_SERVER_NAME" -d "$TLS_SERVER_NAME")
    if [[ "$action" == issue-staging ]]; then
      certbot --config-dir /etc/letsencrypt-staging --work-dir /var/lib/letsencrypt-staging \
        --logs-dir /var/log/letsencrypt-staging --server https://acme-staging-v02.api.letsencrypt.org/directory \
        "${certbot_args[@]}"
      echo 'Staging certificate issued for rehearsal only; it was not imported to ACM.'
    else
      certbot "${certbot_args[@]}"
      "$0" --apply reimport
    fi
    ;;
  renew)
    command -v certbot >/dev/null || { echo 'certbot is required.' >&2; exit 2; }
    certbot renew --cert-name "$TLS_SERVER_NAME" --non-interactive \
      --manual-auth-hook "$script_dir/duckdns-acme-hook.sh auth" \
      --manual-cleanup-hook "$script_dir/duckdns-acme-hook.sh cleanup" \
      --deploy-hook "$0 --apply reimport"
    ;;
  reimport)
    command -v aws >/dev/null && command -v openssl >/dev/null || { echo 'aws and openssl are required.' >&2; exit 2; }
    cert_dir="${INGRESS_CERT_LIVE_DIR:-/etc/letsencrypt/live/$TLS_SERVER_NAME}"
    leaf="$cert_dir/cert.pem"
    chain="$cert_dir/chain.pem"
    fullchain="$cert_dir/fullchain.pem"
    key="$cert_dir/privkey.pem"
    for path in "$leaf" "$chain" "$fullchain" "$key"; do
      [[ -s "$path" ]] || { printf 'Required certificate file is missing: %s\n' "$path" >&2; exit 1; }
    done
    openssl x509 -in "$leaf" -noout -checkhost "$TLS_SERVER_NAME" >/dev/null
    openssl verify -purpose sslserver -untrusted "$chain" "$leaf" >/dev/null
    openssl pkey -in "$key" -check -noout >/dev/null
    leaf_pub="$(openssl x509 -in "$leaf" -pubkey -noout | openssl pkey -pubin -outform DER | openssl dgst -sha256)"
    key_pub="$(openssl pkey -in "$key" -pubout -outform DER | openssl dgst -sha256)"
    [[ "$leaf_pub" == "$key_pub" ]] || { echo 'Certificate and private key do not match.' >&2; exit 1; }
    aws_args=(acm import-certificate --region "$AWS_DEFAULT_REGION" --certificate fileb://"$leaf" \
      --private-key fileb://"$key" --certificate-chain fileb://"$chain")
    if [[ -n "${INGRESS_CERTIFICATE_ARN:-}" ]]; then
      aws_args+=(--certificate-arn "$INGRESS_CERTIFICATE_ARN")
    fi
    result="$(aws "${aws_args[@]}" --query CertificateArn --output text)"
    [[ "$result" =~ ^arn:aws:acm:[a-z0-9-]+:[0-9]{12}:certificate/[0-9a-fA-F-]+$ ]] || {
      echo 'ACM returned an invalid certificate ARN.' >&2; exit 1;
    }
    if [[ -n "${INGRESS_CERTIFICATE_ARN:-}" && "$result" != "$INGRESS_CERTIFICATE_ARN" ]]; then
      echo 'ACM returned a different ARN than the configured listener certificate.' >&2; exit 1
    fi
    printf 'ACM certificate ARN: %s\n' "$result"
    ;;
esac
