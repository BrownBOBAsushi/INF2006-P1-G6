#!/usr/bin/env bash
set -euo pipefail
set +x

region="${AWS_DEFAULT_REGION:-${AWS_REGION:-}}"
[[ -n "$region" ]] || { echo 'AWS region is not configured.' >&2; exit 2; }

if curl --fail --silent --show-error --max-time 5 \
  "${HEALTHCHECK_URL:-http://127.0.0.1:8080/health/ready}" >/dev/null; then
  ready=1
else
  ready=0
fi

if [[ "${1:-}" == "--dry-run" ]]; then
  printf '{"namespace":"INF2006/Service","metric":"Ready","value":%s}\n' "$ready"
  exit 0
fi

token="$(curl --fail --silent --show-error \
  --request PUT \
  --header 'X-aws-ec2-metadata-token-ttl-seconds: 60' \
  http://169.254.169.254/latest/api/token)"
instance_id="$(curl --fail --silent --show-error \
  --header "X-aws-ec2-metadata-token: $token" \
  http://169.254.169.254/latest/meta-data/instance-id)"
unset token
[[ "$instance_id" =~ ^i-[a-f0-9]+$ ]] || { echo 'EC2 instance identity metadata was unavailable.' >&2; exit 1; }

aws cloudwatch put-metric-data --region "$region" \
  --namespace INF2006/Service \
  --metric-data "MetricName=Ready,Dimensions=[{Name=InstanceId,Value=$instance_id}],Value=$ready,Unit=None"
