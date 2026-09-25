#!/usr/bin/env bash
# Reproducible full resume-to-matches journey baseline against the REAL app at localhost:8080.
# Run from the repository root:  bash evidence/baseline-2026-09-25-journey/run_baseline.sh
# Changes NOTHING in the app; creates only isolated synthetic accounts and deletes them on exit
# (including on failure, via the trap). Session tokens are written OUTSIDE the repo and never printed.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DIR="$ROOT/evidence/baseline-2026-09-25-journey"
EXT="${TMPDIR:-/tmp}/inf2006-journey"; mkdir -p "$EXT"
API=inf2006-p1-g6-api-1; DBC=inf2006-p1-g6-db-1
U="$(docker exec $API printenv POSTGRES_USER)"; DBN="$(docker exec $API printenv POSTGRES_DB)"
psql() { docker exec -i $DBC psql -U "$U" -d "$DBN" "$@"; }
synth() { docker exec -e PYTHONPATH=/app $API python /tmp/synthetic.py "$@"; }

SAMPLER=""
cleanup() {
  [ -n "$SAMPLER" ] && kill "$SAMPLER" 2>/dev/null || true
  synth delete >/dev/null 2>&1 || true
  rm -f "$EXT/sessions.json" 2>/dev/null || true
  docker exec $API rm -f /tmp/js.json /tmp/synthetic.py 2>/dev/null || true
}
trap cleanup EXIT

docker cp "$DIR/synthetic.py" $API:/tmp/synthetic.py >/dev/null
synth delete >/dev/null 2>&1 || true          # known-clean start

echo "== integrity BEFORE =="
psql -tA -f - < "$DIR/integrity.sql" > "$DIR/integrity_before.txt"; cat "$DIR/integrity_before.txt"

echo "== idle baseline (no load), 6 samples =="
: > "$DIR/stats_raw.txt"
for i in $(seq 1 6); do
  docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}}' | sed "s/^/$(date +%s) idle /" >> "$DIR/stats_raw.txt"
done

echo "== start continuous resource sampler =="
( while true; do docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}}' | sed "s/^/$(date +%s) load /"; done ) >> "$DIR/stats_raw.txt" 2>&1 &
SAMPLER=$!

run_scenario() { # mode clients rounds browse warmup scenario suffix
  synth delete >/dev/null; synth create 60 /tmp/js.json >/dev/null
  docker cp $API:/tmp/js.json "$EXT/sessions.json" >/dev/null; docker exec $API rm -f /tmp/js.json
  python3 "$DIR/journey_load.py" --base-url http://localhost:8080 --sessions "$EXT/sessions.json" \
    --pdf-dir "$ROOT/tests/fixtures/pdf" --scenario "$6" --mode "$1" --clients "$2" --rounds "$3" \
    --browse-workers "$4" --warmup "$5" --out "$DIR/results_$7.json" --timeline "$DIR/timeline_$7.json"
}

echo "== scenario 1: sequential single-user journeys (15/round x3) =="
run_scenario sequential 15 3 0 3 sequential seq
echo "== scenario 2: synchronised burst of 5, browsing concurrently (x3) =="
run_scenario burst 5 3 4 2 burst5 burst5
echo "== scenario 3: synchronised burst of 10, browsing concurrently (x3) =="
run_scenario burst 10 3 4 2 burst10 burst10

kill "$SAMPLER" 2>/dev/null || true; SAMPLER=""

echo "== DB embedding/persistence evidence (last burst's synthetic users, no content shown) =="
psql -tA -c "
select 'synthetic_profiles', count(*) from resume_profiles p join users u on u.user_id=p.user_id where u.google_sub like 'loadtest-journey-2026-09-25:%'
union all select 'synthetic_chunks', count(*) from resume_chunks c join users u on u.user_id=c.user_id where u.google_sub like 'loadtest-journey-2026-09-25:%'
union all select 'chunks_384dim_nonnull', count(*) from resume_chunks c join users u on u.user_id=c.user_id where u.google_sub like 'loadtest-journey-2026-09-25:%' and c.embedding is not null and vector_dims(c.embedding)=384
union all select 'synthetic_save_ops_succeeded', count(*) from save_operations o join users u on u.user_id=o.user_id where u.google_sub like 'loadtest-journey-2026-09-25:%' and o.state='SUCCEEDED';" > "$DIR/db_evidence_after.txt"; cat "$DIR/db_evidence_after.txt"

echo "== DB + table sizes =="
psql -tA -c "select 'database', pg_size_pretty(pg_database_size('$DBN'));
select 'resume_chunks', pg_size_pretty(pg_total_relation_size('resume_chunks'));
select 'requirement_embeddings', pg_size_pretty(pg_total_relation_size('requirement_embeddings'));
select 'jobs', pg_size_pretty(pg_total_relation_size('jobs'));" > "$DIR/db_size.txt"; cat "$DIR/db_size.txt"

echo "== cleanup synthetic accounts, then integrity AFTER =="
synth delete
psql -tA -f - < "$DIR/integrity.sql" > "$DIR/integrity_after.txt"
if diff -q "$DIR/integrity_before.txt" "$DIR/integrity_after.txt" >/dev/null; then
  echo "INTEGRITY_RESULT: existing data content UNCHANGED (digests identical)"
else
  echo "INTEGRITY_RESULT: CHANGED — investigate"; diff "$DIR/integrity_before.txt" "$DIR/integrity_after.txt" || true
fi
echo "== done =="
