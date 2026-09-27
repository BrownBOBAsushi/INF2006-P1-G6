#!/usr/bin/env bash
set -euo pipefail
set +x

command -v docker >/dev/null || { echo 'Docker CLI is required.' >&2; exit 2; }
docker info >/dev/null 2>&1 || { echo 'Docker daemon access is unavailable; no rehearsal was run.' >&2; exit 2; }

tmp_dir="$(mktemp -d)"
cleanup() {
  [[ -z "${api_container:-}" ]] || docker rm -f "$api_container" >/dev/null 2>&1 || true
  [[ -z "${database:-}" ]] || docker rm -f "$database" >/dev/null 2>&1 || true
  [[ -z "${network:-}" ]] || docker network rm "$network" >/dev/null 2>&1 || true
  [[ -z "${local_api_tag:-}" ]] || docker image rm "$local_api_tag" >/dev/null 2>&1 || true
  rm -rf "$tmp_dir"
}
trap cleanup EXIT
api_image="${API_IMAGE_URI:-}"
if [[ -z "$api_image" ]]; then
  local_api_tag="inf2006-api-rehearsal:$(basename "$tmp_dir")"
  docker build --platform linux/amd64 --iidfile "$tmp_dir/api.iid" --tag "$local_api_tag" \
    --file src/backend/Dockerfile src/backend
  api_image="$(cat "$tmp_dir/api.iid")"
fi
[[ "$api_image" == *@sha256:* || "$api_image" =~ ^sha256:[a-f0-9]{64}$ ]] || {
  echo 'Use API_IMAGE_URI with a digest-pinned repository image or let this script build a local image ID.' >&2
  exit 2
}

echo 'AL2023 package and pinned Compose installation rehearsal'
docker run --rm --platform linux/amd64 public.ecr.aws/amazonlinux/amazonlinux:2023 bash -ceu '
  dnf install -y aws-cfn-bootstrap
  dnf install -y awscli-2 docker nginx postgresql16 jq python3
  install -d -m 0755 /usr/local/lib/docker/cli-plugins
  curl --fail --silent --show-error --location \
    https://github.com/docker/compose/releases/download/v2.39.4/docker-compose-linux-x86_64 \
    --output /tmp/docker-compose
  printf "%s  %s\n" "7af95166a730b87e172d4fc9aefea8725d3c6c7327d59149267b452114ddb7d4" /tmp/docker-compose | sha256sum --check --status
  install -m 0755 /tmp/docker-compose /usr/local/lib/docker/cli-plugins/docker-compose
  docker compose version
'

echo 'PostgreSQL 16 non-superuser migration and default-privilege rehearsal'
network="inf2006-rehearsal-$$"
database="inf2006-pg16-$$"
docker network create "$network" >/dev/null
docker run --detach --name "$database" --network "$network" \
  --env POSTGRES_PASSWORD=postgres_rehearsal_password \
  pgvector/pgvector:pg16 >/dev/null
deadline=$((SECONDS + 180))
until docker exec "$database" pg_isready -U postgres >/dev/null 2>&1; do
  (( SECONDS < deadline )) || { echo 'PostgreSQL 16 container did not become ready.' >&2; exit 1; }
  sleep 1
done

docker exec -i "$database" psql -U postgres -d postgres --set=ON_ERROR_STOP=1 <<'SQL'
CREATE ROLE dbadmin LOGIN PASSWORD 'dbadmin_rehearsal_password' CREATEROLE CREATEDB;
CREATE DATABASE foundation_test OWNER dbadmin;
GRANT SET ON PARAMETER log_statement TO dbadmin;
GRANT SET ON PARAMETER log_min_error_statement TO dbadmin;
GRANT SET ON PARAMETER log_parameter_max_length_on_error TO dbadmin;
SQL
docker exec -i "$database" psql -U postgres -d foundation_test --set=ON_ERROR_STOP=1 \
  -c 'CREATE EXTENSION vector' \
  -c 'REVOKE CREATE ON SCHEMA public FROM PUBLIC' \
  -c 'GRANT USAGE, CREATE ON SCHEMA public TO dbadmin'

migrator_password='migrator!@:%/rehearsal-password'
runtime_password='runtime_rehearsal_password'
run_role_configuration() {
  docker exec --interactive \
    --env PGPASSWORD=dbadmin_rehearsal_password \
    --env "APP_MIGRATOR_PASSWORD=$migrator_password" \
    --env "APP_RUNTIME_PASSWORD=$runtime_password" \
    "$database" psql --host 127.0.0.1 --username dbadmin --dbname foundation_test \
    --set=ON_ERROR_STOP=1 --set=DB_NAME=foundation_test --file - \
    < src/infra/scripts/configure-app-roles.sql
}
run_role_configuration

database_url="$(MIGRATOR_PASSWORD="$migrator_password" python3 - "$database" <<'PY'
import os
import sys
from urllib.parse import quote

print(f"postgresql+psycopg://app_migrator:{quote(os.environ['MIGRATOR_PASSWORD'], safe='')}@{sys.argv[1]}:5432/foundation_test")
PY
)"
docker run --rm --network "$network" --env "DATABASE_URL=$database_url" \
  --entrypoint alembic "$api_image" upgrade head

run_role_configuration
docker exec --env "PGPASSWORD=$migrator_password" "$database" \
  psql --host 127.0.0.1 --username app_migrator --dbname foundation_test --set=ON_ERROR_STOP=1 \
  -c 'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_runtime' \
  -c 'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO app_runtime' \
  -c 'CREATE TABLE public.rehearsal_future_table (id integer PRIMARY KEY, value text)' \
  -c 'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_runtime' \
  -c 'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_runtime' \
  -c 'REVOKE ALL ON TABLE public.alembic_version FROM app_runtime'
docker exec --env PGPASSWORD=runtime_rehearsal_password "$database" \
  psql --host 127.0.0.1 --username app_runtime --dbname foundation_test --set=ON_ERROR_STOP=1 \
  -c "INSERT INTO public.rehearsal_future_table VALUES (1, 'runtime grants work')" \
  -c 'SELECT * FROM public.rehearsal_future_table'
if docker exec --env PGPASSWORD=runtime_rehearsal_password "$database" \
  psql --host 127.0.0.1 --username app_runtime --dbname foundation_test --set=ON_ERROR_STOP=1 \
  -c 'CREATE TABLE public.runtime_must_not_create (id integer)'; then
  echo 'app_runtime unexpectedly created a table.' >&2
  exit 1
fi
if docker exec --env PGPASSWORD=runtime_rehearsal_password "$database" \
  psql --host 127.0.0.1 --username app_runtime --dbname foundation_test --set=ON_ERROR_STOP=1 \
  -c 'SELECT version_num FROM public.alembic_version'; then
  echo 'app_runtime unexpectedly read alembic_version.' >&2
  exit 1
fi

echo 'Catalogue dry-run, import, and idempotence rehearsal through app_runtime'
runtime_database_url="$(RUNTIME_PASSWORD="$runtime_password" python3 - "$database" <<'PY'
import os
import sys
from urllib.parse import quote

print(f"postgresql+psycopg://app_runtime:{quote(os.environ['RUNTIME_PASSWORD'], safe='')}@{sys.argv[1]}:5432/foundation_test")
PY
)"
catalogue_fixture="$PWD/data/synthetic_jobs.json"
expected_jobs="$(python3 -c 'import json, sys; print(len(json.load(open(sys.argv[1], encoding="utf-8")).get("jobs", [])))' "$catalogue_fixture")"
run_catalogue_import() {
  docker run --rm --network "$network" \
    --env "DATABASE_URL=$runtime_database_url" \
    --volume "$catalogue_fixture:/data/synthetic_jobs.json:ro" \
    --entrypoint python "$api_image" -m app.catalogue.import_jobs "$@"
}
catalogue_db_state() {
  docker exec --env "PGPASSWORD=$runtime_password" "$database" \
    psql --host 127.0.0.1 --username app_runtime --dbname foundation_test \
    --no-psqlrc --set=ON_ERROR_STOP=1 --tuples-only --no-align --field-separator='|' \
    -c 'SELECT count(*), COALESCE((SELECT catalogue_revision FROM public.app_state WHERE id = 1), 0) FROM public.jobs'
}
dry_run_before="$(catalogue_db_state)"
echo 'Catalogue dry-run:'
dry_run_summary="$(run_catalogue_import --file /data/synthetic_jobs.json --dry-run)"
printf '%s\n' "$dry_run_summary"
dry_run_after="$(catalogue_db_state)"
[[ "$dry_run_before" == "$dry_run_after" ]] || {
  echo 'Catalogue dry-run changed the job count or catalogue revision.' >&2
  exit 1
}
echo 'Catalogue apply:'
apply_summary="$(run_catalogue_import --file /data/synthetic_jobs.json)"
printf '%s\n' "$apply_summary"
[[ "$apply_summary" =~ (^|[[:space:]])created=$expected_jobs([[:space:]]|$) ]] || {
  echo 'Catalogue apply did not create exactly the fixture job count.' >&2
  exit 1
}
[[ "$apply_summary" =~ (^|[[:space:]])updated=0([[:space:]]|$) ]] || {
  echo 'Catalogue apply unexpectedly updated existing jobs.' >&2
  exit 1
}
[[ "$apply_summary" =~ (^|[[:space:]])unchanged=0([[:space:]]|$) ]] || {
  echo 'Catalogue apply unexpectedly found unchanged jobs in the fresh database.' >&2
  exit 1
}
[[ "$apply_summary" =~ catalogue_revision=([0-9]+) ]] || { echo 'Catalogue apply did not report its revision.' >&2; exit 1; }
apply_revision="${BASH_REMATCH[1]}"
echo 'Catalogue idempotence reapply:'
idempotent_summary="$(run_catalogue_import --file /data/synthetic_jobs.json)"
printf '%s\n' "$idempotent_summary"
[[ "$idempotent_summary" =~ created=0[[:space:]]updated=0[[:space:]]unchanged=$expected_jobs ]] || {
  echo 'Catalogue reapply was not fully unchanged.' >&2
  exit 1
}
[[ "$idempotent_summary" =~ embeddings_computed=0 ]] || {
  echo 'Catalogue reapply unexpectedly recomputed embeddings.' >&2
  exit 1
}
[[ "$idempotent_summary" =~ catalogue_revision=$apply_revision([[:space:]]|$) ]] || {
  echo 'Catalogue reapply changed the catalogue revision.' >&2
  exit 1
}

echo 'API startup, model/database readiness, and idle memory observation as app_runtime'
api_container="inf2006-api-ready-$$"
docker run --detach --name "$api_container" --network "$network" \
  --env "DATABASE_URL=$runtime_database_url" \
  --env APP_ENV=production \
  --env APP_ORIGIN=https://example.invalid \
  --env GOOGLE_CLIENT_ID=rehearsal-client-id \
  --env APP_SIGNING_KEY=rehearsal-signing-key \
  --entrypoint python "$api_image" -m uvicorn app.main:app \
  --host 0.0.0.0 --port 8000 --workers 1 --no-access-log >/dev/null
ready_deadline=$((SECONDS + 240))
until docker exec "$api_container" python -c \
  'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/health/ready", timeout=5)' \
  >/dev/null 2>&1; do
  if (( SECONDS >= ready_deadline )); then
    docker logs "$api_container" >&2
    echo 'API readiness did not become healthy within 240 seconds.' >&2
    exit 1
  fi
  sleep 2
done
docker exec "$api_container" python -c \
  'import json, urllib.request; print(json.loads(urllib.request.urlopen("http://127.0.0.1:8000/health/ready", timeout=5).read()))'
docker stats --no-stream --format 'Idle API container memory (API plus model child): {{.MemUsage}}' "$api_container"


echo 'Nginx syntax rehearsal for all three checked-in configurations'
for source in src/infra/nginx/inf2006-http.conf src/infra/nginx/web-cloud.conf; do
  docker run --rm --add-host api:127.0.0.1 --volume "$PWD/$source:/etc/nginx/conf.d/default.conf:ro" nginx:1.29-alpine nginx -t
done
hostname=example.invalid
mkdir -p "$tmp_dir/live/$hostname"
command -v openssl >/dev/null || { echo 'OpenSSL is required to make a disposable syntax-test certificate.' >&2; exit 2; }
openssl req -x509 -nodes -newkey rsa:2048 -days 1 -subj "/CN=$hostname" \
  -keyout "$tmp_dir/live/$hostname/privkey.pem" -out "$tmp_dir/live/$hostname/fullchain.pem" >/dev/null 2>&1
sed "s/INF2006_HOSTNAME/$hostname/g" src/infra/nginx/inf2006-https.conf > "$tmp_dir/inf2006-https.conf"
docker run --rm \
  --add-host api:127.0.0.1 \
  --volume "$tmp_dir/inf2006-https.conf:/etc/nginx/conf.d/default.conf:ro" \
  --volume "$tmp_dir/live:/etc/letsencrypt/live:ro" \
  nginx:1.29-alpine nginx -t

echo 'PASS: AL2023 install, PG16 roles/migrations/runtime grants, catalogue dry-run/apply/idempotence, API readiness/idle memory, and Nginx syntax rehearsals completed.'
