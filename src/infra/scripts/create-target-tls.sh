#!/usr/bin/env bash
set -euo pipefail
set +x

target_dir="${1:-/etc/inf2006/tls}"
command -v openssl >/dev/null || { echo 'OpenSSL is required.' >&2; exit 2; }
install -d -m 0750 "$target_dir"
cert_path="$target_dir/target.crt"
key_path="$target_dir/target.key"
if [[ -e "$cert_path" || -L "$cert_path" || -e "$key_path" || -L "$key_path" ]]; then
  [[ -f "$cert_path" && ! -L "$cert_path" && -s "$cert_path" \
    && -f "$key_path" && ! -L "$key_path" && -s "$key_path" ]] || {
    echo 'An incomplete or non-regular target certificate pair exists; refusing to replace it.' >&2
    exit 1
  }
  openssl x509 -in "$cert_path" -noout >/dev/null
  openssl pkey -in "$key_path" -noout >/dev/null
  cert_pub="$(openssl x509 -in "$cert_path" -pubkey -noout | openssl pkey -pubin -outform DER | openssl dgst -sha256)"
  key_pub="$(openssl pkey -in "$key_path" -pubout -outform DER | openssl dgst -sha256)"
  [[ "$cert_pub" == "$key_pub" ]] || {
    echo 'Existing target certificate and private key do not match; refusing to replace either file.' >&2
    exit 1
  }
  echo 'Existing per-instance target certificate is valid; it was preserved.'
  exit 0
fi

tmpdir="$(mktemp -d "${target_dir}/.target-tls.XXXXXX")"
trap 'rm -rf "$tmpdir"' EXIT
openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 365 \
  -subj '/CN=inf2006-target.local' \
  -addext 'subjectAltName=DNS:inf2006-target.local' \
  -keyout "$tmpdir/target.key" -out "$tmpdir/target.crt" >/dev/null 2>&1
chmod 0400 "$tmpdir/target.key"
chmod 0444 "$tmpdir/target.crt"
install -m 0400 "$tmpdir/target.key" "$target_dir/target.key.tmp"
install -m 0444 "$tmpdir/target.crt" "$target_dir/target.crt.tmp"
mv -f "$target_dir/target.key.tmp" "$target_dir/target.key"
mv -f "$target_dir/target.crt.tmp" "$target_dir/target.crt"
echo 'Generated a per-instance encryption-only certificate; ALB target TLS does not validate it.'
