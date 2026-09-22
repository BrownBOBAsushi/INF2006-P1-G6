# Backend tests

Status: implemented. Owner: Jiaxin.

Covers: health/live and health/ready (including dependency-failure behavior),
migration idempotency and downgrade/upgrade roundtrip, and schema invariants
for all five core tables (users, sessions, resume_profiles, resume_chunks,
save_operations) — including pgvector extension, embedding dimension,
indexes, check constraints, and foreign keys.

Run with:
    docker compose exec api pytest tests/backend/ -v

Last verified: 15/15 passing, against synthetic/empty local dev DB.

Note: test_downgrade_and_upgrade_roundtrip is destructive to schema state —
only run against a disposable dev database.
