#!/bin/bash
# Operator-run: compare the restored RDS instance with the source (table names, extensions, migration version, row counts).
# Runs restore_verify.py inside the api container of one app instance via SSM; credentials stay on the instance and are not printed.
# Usage: AWS_PROFILE=inf2006-lab AWS_REGION=us-east-1 tests/infra/verify_restore.sh <app-instance-id> <restored-db-instance-id>
set -euo pipefail
I="$1"; DB="$2"; HERE="$(cd "$(dirname "$0")" && pwd)"
EP=$(aws rds describe-db-instances --db-instance-identifier "$DB" --query 'DBInstances[0].Endpoint.Address' --output text)
B64=$(base64 < "$HERE/restore_verify.py" | tr -d '\n')
CID=$(aws ssm send-command --instance-ids "$I" --document-name AWS-RunShellScript \
  --parameters "commands=[\"echo $B64 | base64 -d > /tmp/verify.py\",\"docker cp /tmp/verify.py inf2006-api-1:/tmp/verify.py\",\"docker exec inf2006-api-1 python /tmp/verify.py $EP\",\"docker exec inf2006-api-1 rm -f /tmp/verify.py\",\"rm -f /tmp/verify.py\"]" \
  --query Command.CommandId --output text)
sleep 15
aws ssm get-command-invocation --command-id "$CID" --instance-id "$I" --query '[Status,StandardOutputContent,StandardErrorContent]' --output text | sed "s/$EP/<restored-endpoint>/g"
