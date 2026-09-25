#!/usr/bin/env bash
# Corrected resume-to-matches journey baseline (v2) against the REAL app at localhost:8080.
# Run from the repository root:  bash evidence/baseline-2026-09-25-journey-v2/run_baseline.sh
# - Unique RUN_ID; creates and tracks ONLY this run's synthetic accounts (a manifest of exact user_ids).
# - Cleanup deletes ONLY this run's user_ids, on success AND on failure (trap), then VERIFIES none remain.
# - Tokens live in a restricted (0700) out-of-repo dir, mode 0600, never printed or committed.
# - Integrity is checked before/after over documented tables; a mismatch FAILS the run (exit 1).
# Changes nothing in the app. Nothing is committed.
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DIR="$ROOT/evidence/baseline-2026-09-25-journey-v2"
RUN_ID="$(date +%Y%m%dT%H%M%S)-$$-$(head -c6 /dev/urandom | od -An -tx1 | tr -d ' \n')"
OUT="$DIR/runs/$RUN_ID"; mkdir -p "$OUT"
EXT="$(mktemp -d "${TMPDIR:-/tmp}/inf2006-journey-v2.XXXXXX")"; chmod 700 "$EXT"
CONTAINER_DIR="/tmp/inf2006-journey-v2-$RUN_ID"
MANIFEST="$OUT/manifest.json"; echo '{"user_ids":[]}' > "$MANIFEST"
RUNPREFIX="loadtest-journey-v2:${RUN_ID}%"
API=inf2006-p1-g6-api-1; DBC=inf2006-p1-g6-db-1
U="$(docker exec $API printenv POSTGRES_USER)"; DBN="$(docker exec $API printenv POSTGRES_DB)"
psql() { docker exec -i $DBC psql -U "$U" -d "$DBN" "$@"; }
synth() { docker exec -e PYTHONPATH=/app $API python "$CONTAINER_DIR/synthetic.py" "$@"; }
echo "RUN_ID=$RUN_ID"; echo "OUT=$OUT"; echo "EXT=$EXT (restricted)"

SAMPLER=""
cleanup() {
  local rc=$?
  [ -n "$SAMPLER" ] && kill "$SAMPLER" 2>/dev/null || true
  # scoped cleanup: delete ONLY this run's user_ids from the manifest, then verify
  if docker exec $API test -s "$CONTAINER_DIR/manifest.json" 2>/dev/null; then
    local res; res="$(synth delete "$CONTAINER_DIR/manifest.json" 2>/dev/null || echo '{}')"
    echo "CLEANUP: $res"
    local remaining; remaining="$(printf '%s' "$res" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("remaining",-1))' 2>/dev/null || echo -1)"
    if [ "$remaining" != "0" ]; then echo "CLEANUP_FAILED: remaining=$remaining synthetic accounts NOT removed" >&2; rc=3; fi
  fi
  docker exec $API rm -rf "$CONTAINER_DIR" 2>/dev/null || true
  rm -rf "$EXT" 2>/dev/null || true
  exit $rc
}
trap cleanup EXIT

docker exec $API mkdir -m 700 "$CONTAINER_DIR"
docker cp "$DIR/synthetic.py" "$API:$CONTAINER_DIR/synthetic.py" >/dev/null

echo "== integrity BEFORE (excludes only this run: $RUNPREFIX) =="
psql -tA -v runprefix="$RUNPREFIX" -f - < "$DIR/integrity.sql" > "$OUT/integrity_before.txt"; cat "$OUT/integrity_before.txt"

echo "== idle baseline (no load), 6 samples =="
: > "$OUT/stats_raw.txt"
for i in $(seq 1 6); do
  docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}}' | sed "s/^/$(date +%s) idle /" >> "$OUT/stats_raw.txt"
done

echo "== start continuous resource sampler =="
( while true; do docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}}' | sed "s/^/$(date +%s) load /"; done ) >> "$OUT/stats_raw.txt" 2>&1 &
SAMPLER=$!

run_scenario() { # mode clients rounds browse warmup scenario suffix
  synth create 60 "${RUN_ID}:$7" "$CONTAINER_DIR/tokens.json" "$CONTAINER_DIR/manifest.json" >/dev/null
  # The helper publishes the exact-ID manifest atomically with token creation. Keep
  # an auditable host copy; trap cleanup can still use the container manifest if cp fails.
  docker cp "$API:$CONTAINER_DIR/manifest.json" "$MANIFEST"
  docker cp "$API:$CONTAINER_DIR/tokens.json" "$EXT/tokens.json" >/dev/null; chmod 600 "$EXT/tokens.json"
  docker exec $API rm -f "$CONTAINER_DIR/tokens.json"
  python3 "$DIR/journey_load.py" --base-url http://localhost:8080 --sessions "$EXT/tokens.json" \
    --pdf-dir "$ROOT/tests/fixtures/pdf" --repo-root "$ROOT" --scenario "$6" --mode "$1" --clients "$2" \
    --rounds "$3" --browse-workers "$4" --warmup "$5" --step-deadline 30 --max-attempts 10 \
    --out "$OUT/results_$7.json" --timeline "$OUT/timeline_$7.json"
}

echo "== scenario 1: sequential single-user journeys (15/round x3) =="
run_scenario sequential 15 3 0 3 sequential seq
echo "== scenario 2: synchronised burst of 5, browsing concurrently (x3) =="
run_scenario burst 5 3 4 2 burst5 burst5
echo "== scenario 3: synchronised burst of 10, browsing concurrently (x3) =="
run_scenario burst 10 3 4 2 burst10 burst10

kill "$SAMPLER" 2>/dev/null || true; SAMPLER=""

echo "== DB embedding/persistence evidence for THIS run (no content shown) =="
# RUNPREFIX is a generated, quote-free literal; inline it (psql -v is not interpolated under -c).
psql -tA -c "
select 'run_profiles', count(*) from resume_profiles p join users u on u.user_id=p.user_id where u.google_sub like '${RUNPREFIX}'
union all select 'run_chunks', count(*) from resume_chunks c join users u on u.user_id=c.user_id where u.google_sub like '${RUNPREFIX}'
union all select 'run_chunks_384dim_nonnull', count(*) from resume_chunks c join users u on u.user_id=c.user_id where u.google_sub like '${RUNPREFIX}' and c.embedding is not null and vector_dims(c.embedding)=384
union all select 'run_saveops_succeeded', count(*) from save_operations o join users u on u.user_id=o.user_id where u.google_sub like '${RUNPREFIX}' and o.state='SUCCEEDED';" > "$OUT/db_evidence.txt"; cat "$OUT/db_evidence.txt"

echo "== DB + table sizes =="
psql -tA -c "select 'database', pg_size_pretty(pg_database_size('$DBN'));
select 'resume_chunks', pg_size_pretty(pg_total_relation_size('resume_chunks'));
select 'requirement_embeddings', pg_size_pretty(pg_total_relation_size('requirement_embeddings'));
select 'jobs', pg_size_pretty(pg_total_relation_size('jobs'));" > "$OUT/db_size.txt"; cat "$OUT/db_size.txt"

echo "== scoped cleanup of THIS run's accounts, then verify + integrity AFTER =="
DEL="$(synth delete "$CONTAINER_DIR/manifest.json")"; echo "delete: $DEL"
echo '{"user_ids":[]}' > "$MANIFEST"   # emptied so the EXIT trap does not double-delete
REMAIN="$(printf '%s' "$DEL" | python3 -c 'import sys,json;print(json.load(sys.stdin)["remaining"])')"
if [ "$REMAIN" != "0" ]; then echo "CLEANUP_VERIFY_FAILED remaining=$REMAIN" >&2; exit 3; fi
docker exec $API rm -f "$CONTAINER_DIR/manifest.json"
psql -tA -v runprefix="$RUNPREFIX" -f - < "$DIR/integrity.sql" > "$OUT/integrity_after.txt"
if diff -q "$OUT/integrity_before.txt" "$OUT/integrity_after.txt" >/dev/null; then
  echo "INTEGRITY_RESULT: covered fields UNCHANGED (digests identical)"
else
  echo "INTEGRITY_RESULT: CHANGED — failing run" >&2; diff "$OUT/integrity_before.txt" "$OUT/integrity_after.txt" >&2 || true; exit 1
fi
echo "RUN_DIR=$OUT"
echo "== done =="
