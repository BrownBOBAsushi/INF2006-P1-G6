#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
hook="$repo_root/src/infra/scripts/duckdns-acme-hook.sh"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir "$tmp/bin" "$tmp/run"
cat > "$tmp/bin/aws" <<'MOCK'
#!/usr/bin/env bash
printf 'called\n' >> "$AWS_CALLS"
printf '%s\n' '{"token":"0123456789abcdef0123456789abcdef"}'
MOCK
cat > "$tmp/bin/curl" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
printf 'called\n' >> "$CURL_CALLS"
[[ "$1" == --config ]]
cp "$2" "$CURL_CAPTURE"
[[ -z "${DNS_UPDATED:-}" ]] || touch "$DNS_UPDATED"
printf OK
MOCK
cat > "$tmp/bin/sleep" <<'MOCK'
#!/usr/bin/env bash
[[ "$1" == 5 ]]
MOCK
cat > "$tmp/bin/dig" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == *" NS duckdns.org" ]]; then
  case "${MOCK_DNS_FAILURE:-}" in
    ns-timeout-stdout) printf ';; communications error to resolver#53: timed out\n'; exit 0 ;;
    ns-timeout-nonzero) printf ';; communications error to resolver#53: timed out\n'; exit 9 ;;
    ns-servfail) printf ';; ->>HEADER<<- opcode: QUERY, status: SERVFAIL, id: 1\n;; flags: qr; QUERY: 1, ANSWER: 0, AUTHORITY: 0, ADDITIONAL: 0\n'; exit 0 ;;
    ns-refused) printf ';; ->>HEADER<<- opcode: QUERY, status: REFUSED, id: 1\n;; flags: qr; QUERY: 1, ANSWER: 0, AUTHORITY: 0, ADDITIONAL: 0\n'; exit 0 ;;
  esac
  printf ';; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 1\n;; flags: qr; QUERY: 1, ANSWER: 2, AUTHORITY: 0, ADDITIONAL: 0\n'
  printf 'duckdns.org. 3600 IN NS ns1.duckdns.org.\nduckdns.org. 3600 IN NS ns2.duckdns.org.\n'
elif [[ "$*" == *" TXT _acme-challenge.internshipmatcher.duckdns.org" ]]; then
  [[ "$1" == +time=2 && "$2" == +tries=1 ]]
  [[ "$*" == *"@ns1.duckdns.org"* || "$*" == *"@ns2.duckdns.org"* ]]
  case "${MOCK_DNS_FAILURE:-}" in
    txt-timeout-stdout) printf ';; communications error to authoritative#53: timed out\n'; exit 0 ;;
    txt-timeout-nonzero) printf ';; communications error to authoritative#53: timed out\n'; exit 9 ;;
    txt-servfail) printf ';; ->>HEADER<<- opcode: QUERY, status: SERVFAIL, id: 2\n;; flags: qr; QUERY: 1, ANSWER: 0, AUTHORITY: 0, ADDITIONAL: 0\n'; exit 0 ;;
    txt-refused) printf ';; ->>HEADER<<- opcode: QUERY, status: REFUSED, id: 2\n;; flags: qr; QUERY: 1, ANSWER: 0, AUTHORITY: 0, ADDITIONAL: 0\n'; exit 0 ;;
    txt-nonauthoritative) printf ';; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 2\n;; flags: qr; QUERY: 1, ANSWER: 0, AUTHORITY: 0, ADDITIONAL: 0\n'; exit 0 ;;
  esac
  empty=0
  if [[ "${MOCK_NS2_EMPTY:-0}" == 1 && "$*" == *"@ns2.duckdns.org"* ]]; then empty=1; fi
  if [[ "${MOCK_START_EMPTY:-0}" == 1 && ( -z "${DNS_UPDATED:-}" || ! -e "$DNS_UPDATED" ) ]]; then empty=1; fi
  answer_count=1
  [[ "$empty" == 1 ]] && answer_count=0
  printf ';; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 2\n;; flags: qr aa; QUERY: 1, ANSWER: %s, AUTHORITY: 0, ADDITIONAL: 0\n' "$answer_count"
  [[ "$empty" == 1 ]] && exit 0
  value="${MOCK_TXT:-synthetic_validation_value_123}"
  [[ -z "$value" ]] || printf '_acme-challenge.internshipmatcher.duckdns.org. 30 IN TXT "%s"\n' "$value"
else
  exit 9
fi
MOCK
chmod +x "$tmp/bin/"*

export PATH="$tmp/bin:$PATH" CURL_CAPTURE="$tmp/curl-config" AWS_CALLS="$tmp/aws-calls" CURL_CALLS="$tmp/curl-calls"
export DUCKDNS_CURL_CONFIG_DIR="$tmp/run" AWS_DEFAULT_REGION=us-east-1
export DUCKDNS_TOKEN_SECRET_ARN=arn:aws:secretsmanager:us-east-1:000000000000:secret:fixture
export TLS_SERVER_NAME=internshipmatcher.duckdns.org CERTBOT_DOMAIN=internshipmatcher.duckdns.org
export CERTBOT_VALIDATION=synthetic_validation_value_123 DUCKDNS_PROPAGATION_TIMEOUT_SECONDS=1
export INF2006_ACME_LOCK_HELD=1

bash "$hook" auth
grep -Fq 'domains=internshipmatcher' "$CURL_CAPTURE"
grep -Fq 'txt=synthetic_validation_value_123' "$CURL_CAPTURE"
grep -Fq 'token=0123456789abcdef0123456789abcdef' "$CURL_CAPTURE"
! grep -Eq '(^|[?&])(ip|ipv6|clear)=' "$CURL_CAPTURE"
[[ -z "$(find "$tmp/run" -type f -print -quit)" ]]

bash "$hook" cleanup
grep -Fq '&txt=synthetic_validation_value_123&clear=true' "$CURL_CAPTURE"
! grep -Eq '(^|[?&])(ip|ipv6)=' "$CURL_CAPTURE"
[[ -z "$(find "$tmp/run" -type f -print -quit)" ]]

if MOCK_TXT=someone_elses_record bash "$hook" auth >/dev/null 2>&1; then
  echo 'Conflicting shared TXT value was unexpectedly overwritten.' >&2; exit 1
fi
if MOCK_NS2_EMPTY=1 bash "$hook" auth >/dev/null 2>&1; then
  echo 'A single authoritative nameserver was incorrectly treated as propagation.' >&2; exit 1
fi
prior_config="$(cat "$CURL_CAPTURE")"
MOCK_TXT=someone_elses_record bash "$hook" cleanup >/dev/null 2>&1
[[ "$(cat "$CURL_CAPTURE")" == "$prior_config" ]]
if env -u INF2006_ACME_LOCK_HELD bash "$hook" auth >/dev/null 2>&1; then
  echo 'Unlocked DNS hook was unexpectedly accepted.' >&2; exit 1
fi

for failure in ns-timeout-stdout ns-timeout-nonzero ns-servfail ns-refused txt-timeout-stdout txt-timeout-nonzero txt-servfail txt-refused txt-nonauthoritative; do
  for action in auth cleanup; do
    rm -f "$AWS_CALLS" "$CURL_CALLS"
    if MOCK_DNS_FAILURE="$failure" bash "$hook" "$action" >"$tmp/failure.out" 2>"$tmp/failure.err"; then
      echo "DNS failure $failure was incorrectly accepted for $action." >&2; exit 1
    fi
    grep -Eq 'DNS query failed for .*\((dig exit [0-9]+|response status (SERVFAIL|REFUSED|missing)|response was not authoritative)\)' "$tmp/failure.err"
    [[ ! -e "$AWS_CALLS" && ! -e "$CURL_CALLS" ]]
    [[ -z "$(find "$tmp/run" -type f -print -quit)" ]]
  done
done

DNS_UPDATED="$tmp/dns-updated" MOCK_START_EMPTY=1 bash "$hook" auth
[[ -e "$tmp/dns-updated" ]]
echo 'PASS: DNS command/status failures fail closed, empty TXT is valid, conflicts and cleanup ownership remain enforced.'
