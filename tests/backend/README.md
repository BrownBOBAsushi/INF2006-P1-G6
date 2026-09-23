# Backend tests

Status: implemented. Owner: Jiaxin.

Covers: health/live and health/ready (including dependency-failure behavior),
migration idempotency and downgrade/upgrade roundtrip, and schema invariants
for all five core tables (users, sessions, resume_profiles, resume_chunks,
save_operations) — including pgvector extension, embedding dimension,
indexes, check constraints, and foreign keys.

Run with:
    docker compose -f docker-compose.dev.yml --profile test run --rm backend-tests
    docker compose -f docker-compose.dev.yml --profile test down

The test runner mounts this directory read-only and uses a temporary pgvector
database. It does not run against the persistent application database.

Note: test_downgrade_and_upgrade_roundtrip is destructive to schema state —
only run against a disposable dev database.
