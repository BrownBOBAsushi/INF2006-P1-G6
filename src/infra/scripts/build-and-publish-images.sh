#!/usr/bin/env bash
set -euo pipefail
set +x

for name in AWS_REGION ECR_REGISTRY GOOGLE_CLIENT_ID ARTIFACT_DIR; do
  [[ -n "${!name:-}" ]] || { printf 'Required setting is missing: %s\n' "$name" >&2; exit 2; }
done
command -v docker >/dev/null || { echo 'Docker CLI is required.' >&2; exit 2; }
command -v aws >/dev/null || { echo 'AWS CLI is required for ECR login and digest lookup.' >&2; exit 2; }
[[ "$ECR_REGISTRY" =~ ^[0-9]{12}\.dkr\.ecr\.$AWS_REGION\.amazonaws\.com$ ]] || { echo 'ECR_REGISTRY must be the account registry in AWS_REGION.' >&2; exit 2; }
API_BASE_IMAGE="${API_BASE_IMAGE:-python:3.11-slim}"
NODE_BASE_IMAGE="${NODE_BASE_IMAGE:-node:24.21.0-alpine}"
NGINX_BASE_IMAGE="${NGINX_BASE_IMAGE:-nginx:1.29-alpine}"
BOOTSTRAP_BASE_IMAGE="${BOOTSTRAP_BASE_IMAGE:-public.ecr.aws/amazonlinux/amazonlinux:2023}"

resolve_digest() {
  local reference="$1" digest repository last_component
  if [[ "$reference" =~ @sha256:[a-f0-9]{64}$ ]]; then
    printf '%s\n' "$reference"
    return
  fi
  digest="$(docker buildx imagetools inspect "$reference" | awk '$1 == "Digest:" { print $2; exit }')"
  [[ "$digest" =~ ^sha256:[a-f0-9]{64}$ ]] || { printf 'Could not resolve an immutable digest for %s.\n' "$reference" >&2; exit 2; }
  last_component="${reference##*/}"
  if [[ "$last_component" == *:* ]]; then repository="${reference%:*}"; else repository="$reference"; fi
  printf '%s@%s\n' "$repository" "$digest"
}
API_BASE_IMAGE="$(resolve_digest "$API_BASE_IMAGE")"
NODE_BASE_IMAGE="$(resolve_digest "$NODE_BASE_IMAGE")"
NGINX_BASE_IMAGE="$(resolve_digest "$NGINX_BASE_IMAGE")"
BOOTSTRAP_BASE_IMAGE="$(resolve_digest "$BOOTSTRAP_BASE_IMAGE")"
GOOGLE_CLIENT_ID_SHA256="$(printf '%s' "$GOOGLE_CLIENT_ID" | shasum -a 256 | awk '{print $1}')"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
snapshot="$tmp_dir/source-snapshot.tar.gz"
snapshot_sha="$(python3 "$repo_root/src/infra/scripts/create-source-snapshot.py" "$snapshot")"
mkdir "$tmp_dir/source"
tar -xzf "$snapshot" -C "$tmp_dir/source"
commit="$(jq -er '.repository_commit' "$tmp_dir/source/source-snapshot.json")"
attempt_id="$(date -u +%Y%m%dT%H%M%SZ)-$$"
image_tag="src-${snapshot_sha:0:20}-${attempt_id}"
artifact_dir="$ARTIFACT_DIR/inf2006-$snapshot_sha"
mkdir -p "$artifact_dir"
install -m 0444 "$snapshot" "$artifact_dir/source-snapshot.tar.gz"
install -m 0444 "$tmp_dir/source/source-snapshot.json" "$artifact_dir/source-snapshot.json"
printf 'ARCHIVE_SHA256=%s\n' "$(shasum -a 256 "$snapshot" | awk '{print $1}')" > "$artifact_dir/archive.sha256"
chmod 0444 "$artifact_dir/archive.sha256"

source_docker_config="${DOCKER_CONFIG:-${HOME}/.docker}"
source_docker_config="$(python3 -c 'import os, sys; print(os.path.abspath(sys.argv[1]))' "$source_docker_config")"
active_docker_context="$(docker context show)"
buildx_plugin=""
for candidate in \
  "$source_docker_config/cli-plugins/docker-buildx" \
  /usr/local/lib/docker/cli-plugins/docker-buildx \
  /usr/local/libexec/docker/cli-plugins/docker-buildx \
  /usr/lib/docker/cli-plugins/docker-buildx \
  /usr/libexec/docker/cli-plugins/docker-buildx \
  /opt/homebrew/lib/docker/cli-plugins/docker-buildx \
  /Applications/Docker.app/Contents/Resources/cli-plugins/docker-buildx; do
  if [[ -x "$candidate" ]]; then
    buildx_plugin="$candidate"
    break
  fi
done
[[ -n "$buildx_plugin" ]] || {
  echo 'Docker Buildx CLI plugin was not found in the active config or standard plugin directories.' >&2
  exit 2
}

docker_config="$(mktemp -d)"
builder_name="inf2006-${snapshot_sha:0:12}-${attempt_id}"
builder_created=0
cleanup() {
  if [[ "$builder_created" == 1 ]]; then
    docker buildx rm "$builder_name" >/dev/null 2>&1 || true
  fi
  rm -rf "$tmp_dir" "$docker_config"
}
trap cleanup EXIT
mkdir -p "$docker_config/cli-plugins"
ln -s "$buildx_plugin" "$docker_config/cli-plugins/docker-buildx"
if [[ -d "$source_docker_config/contexts" ]]; then
  ln -s "$source_docker_config/contexts" "$docker_config/contexts"
fi
export DOCKER_CONFIG="$docker_config"
# The selected context lives in the source config. Pin its name when no explicit
# host/context override exists, while leaving DOCKER_HOST semantics untouched.
if [[ -z "${DOCKER_CONTEXT:-}" && -z "${DOCKER_HOST:-}" ]]; then
  export DOCKER_CONTEXT="$active_docker_context"
fi
docker buildx version >/dev/null || {
  echo 'Docker Buildx is unavailable with the isolated Docker config; refusing to log in.' >&2
  exit 2
}
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$ECR_REGISTRY"
docker buildx create --name "$builder_name" --driver docker-container --use >/dev/null
builder_created=1
docker buildx inspect --bootstrap >/dev/null

docker buildx build --platform linux/amd64 --push \
  --build-arg "API_BASE_IMAGE=$API_BASE_IMAGE" \
  --label "org.opencontainers.image.revision=$commit" \
  --label "org.opencontainers.image.source-snapshot-sha256=$snapshot_sha" \
  --tag "$ECR_REGISTRY/inf2006/cloud-api:$image_tag" \
  --file "$tmp_dir/source/src/backend/Dockerfile" \
  "$tmp_dir/source/src/backend"
docker buildx build --platform linux/amd64 --push \
  --build-arg "NODE_BASE_IMAGE=$NODE_BASE_IMAGE" \
  --build-arg "NGINX_BASE_IMAGE=$NGINX_BASE_IMAGE" \
  --build-arg "VITE_GOOGLE_CLIENT_ID=$GOOGLE_CLIENT_ID" \
  --build-arg "GOOGLE_CLIENT_ID_SHA256=$GOOGLE_CLIENT_ID_SHA256" \
  --label "org.opencontainers.image.revision=$commit" \
  --label "org.opencontainers.image.source-snapshot-sha256=$snapshot_sha" \
  --tag "$ECR_REGISTRY/inf2006/cloud-web:$image_tag" \
  --file "$tmp_dir/source/src/frontend/Dockerfile" \
  "$tmp_dir/source/src/frontend"
docker buildx build --platform linux/amd64 --push \
  --build-arg "BOOTSTRAP_BASE_IMAGE=$BOOTSTRAP_BASE_IMAGE" \
  --label "org.opencontainers.image.revision=$commit" \
  --label "org.opencontainers.image.source-snapshot-sha256=$snapshot_sha" \
  --tag "$ECR_REGISTRY/inf2006/cloud-bootstrap:$image_tag" \
  --file "$tmp_dir/source/src/infra/Dockerfile.bootstrap" \
  "$tmp_dir/source"

digest_lines=""
for repository in cloud-api cloud-web cloud-bootstrap; do
  digest="$(aws ecr describe-images --region "$AWS_REGION" \
    --repository-name "inf2006/$repository" \
    --image-ids "imageTag=$image_tag" \
    --query 'imageDetails[0].imageDigest' --output text)"
  [[ "$digest" =~ ^sha256:[a-f0-9]{64}$ ]] || { echo "ECR digest is unavailable for $repository." >&2; exit 1; }
  case "$repository" in
    cloud-api) variable=API_IMAGE_URI ;;
    cloud-web) variable=WEB_IMAGE_URI ;;
    cloud-bootstrap) variable=BOOTSTRAP_IMAGE_URI ;;
  esac
  line="%s=%s/inf2006/%s@%s\n"
  printf -v rendered "$line" "$variable" "$ECR_REGISTRY" "$repository" "$digest"
  digest_lines+="$rendered"
done
printf '%sSOURCE_SNAPSHOT_SHA256=%s\nREPOSITORY_COMMIT=%s\n' "$digest_lines" "$snapshot_sha" "$commit" | tee "$artifact_dir/image-digests.env"
GOOGLE_CLIENT_ID_SHA256="$GOOGLE_CLIENT_ID_SHA256" \
API_BASE_IMAGE="$API_BASE_IMAGE" NODE_BASE_IMAGE="$NODE_BASE_IMAGE" \
NGINX_BASE_IMAGE="$NGINX_BASE_IMAGE" BOOTSTRAP_BASE_IMAGE="$BOOTSTRAP_BASE_IMAGE" \
SOURCE_SNAPSHOT_SHA256="$snapshot_sha" REPOSITORY_COMMIT="$commit" \
python3 - "$artifact_dir/build-provenance.json" <<'PY'
import json
import os
import sys

data = {key: os.environ[key] for key in (
    "SOURCE_SNAPSHOT_SHA256", "REPOSITORY_COMMIT", "GOOGLE_CLIENT_ID_SHA256",
    "API_BASE_IMAGE", "NODE_BASE_IMAGE", "NGINX_BASE_IMAGE", "BOOTSTRAP_BASE_IMAGE",
)}
with open(sys.argv[1], "w", encoding="utf-8") as output:
    json.dump(data, output, indent=2, sort_keys=True)
    output.write("\n")
PY
chmod 0444 "$artifact_dir/image-digests.env" "$artifact_dir/build-provenance.json"
