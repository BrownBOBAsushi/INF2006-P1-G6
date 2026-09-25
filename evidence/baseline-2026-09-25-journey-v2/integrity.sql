-- Content-level integrity digests (v2). Deterministic + NULL-safe.
-- COVERED tables/fields (any change to these flips the md5): users(user_id, google_sub, display_name,
--   resume_revision, created_at, updated_at); sessions(token_hash, user_id, csrf_token, expires_at,
--   last_active_at); resume_profiles(user_id, revision, content_hash, embedding_version, content);
--   resume_chunks(chunk_id, user_id, profile_revision, section, entry_index, chunk_index, text,
--   embedding, embedding_version); save_operations(user_id, operation_id, payload_hash, state,
--   result_revision, failure_code); jobs(job_id, source_job_id, title, company_name, description,
--   is_active, content_hash); job_requirements(requirement_id, job_id, ordinal, requirement_text,
--   importance); requirement_embeddings(embedding_id, requirement_id, alternative_index, embedding,
--   embedding_version); app_state(id, catalogue_revision).
-- NOT covered (documented, not claimed unchanged): other columns, sequences, physical size/bloat,
--   pg catalogs. This does NOT prove "all database content" is unchanged — only the fields above.
-- SCOPE: excludes ONLY THIS run's users (google_sub LIKE :'runprefix'); every pre-existing row and
-- every OTHER run's synthetic row is included and therefore protected. Every nullable column is
-- wrapped in coalesce so NULLs never silently drop a row from string_agg. Emits md5 + counts only
-- (no tokens, no PII, no resume text).
\pset footer off
WITH synth AS (SELECT user_id FROM users WHERE google_sub LIKE :'runprefix')
SELECT 'users' AS t, count(*) AS n,
  md5(coalesce(string_agg(user_id::text||'|'||google_sub||'|'||coalesce(display_name,'')||'|'||resume_revision::text||'|'||created_at::text||'|'||updated_at::text, ',' ORDER BY user_id),'EMPTY')) AS digest
FROM users WHERE user_id NOT IN (SELECT user_id FROM synth)
UNION ALL SELECT 'sessions', count(*),
  md5(coalesce(string_agg(token_hash||'|'||user_id::text||'|'||csrf_token||'|'||expires_at::text||'|'||last_active_at::text, ',' ORDER BY token_hash),'EMPTY'))
FROM sessions WHERE user_id NOT IN (SELECT user_id FROM synth)
UNION ALL SELECT 'resume_profiles', count(*),
  md5(coalesce(string_agg(user_id::text||'|'||revision::text||'|'||content_hash||'|'||embedding_version||'|'||content::text, ',' ORDER BY user_id),'EMPTY'))
FROM resume_profiles WHERE user_id NOT IN (SELECT user_id FROM synth)
UNION ALL SELECT 'resume_chunks', count(*),
  md5(coalesce(string_agg(chunk_id::text||'|'||user_id::text||'|'||profile_revision::text||'|'||section||'|'||entry_index::text||'|'||chunk_index::text||'|'||text||'|'||embedding::text||'|'||embedding_version, ',' ORDER BY chunk_id),'EMPTY'))
FROM resume_chunks WHERE user_id NOT IN (SELECT user_id FROM synth)
UNION ALL SELECT 'save_operations', count(*),
  md5(coalesce(string_agg(user_id::text||'|'||operation_id::text||'|'||payload_hash||'|'||state||'|'||coalesce(result_revision::text,'')||'|'||coalesce(failure_code,''), ',' ORDER BY user_id, operation_id),'EMPTY'))
FROM save_operations WHERE user_id NOT IN (SELECT user_id FROM synth)
UNION ALL SELECT 'jobs', count(*),
  md5(coalesce(string_agg(job_id::text||'|'||source_job_id||'|'||title||'|'||company_name||'|'||coalesce(description,'')||'|'||is_active::text||'|'||content_hash, ',' ORDER BY job_id),'EMPTY'))
FROM jobs
UNION ALL SELECT 'job_requirements', count(*),
  md5(coalesce(string_agg(requirement_id::text||'|'||job_id::text||'|'||ordinal::text||'|'||requirement_text||'|'||importance, ',' ORDER BY requirement_id),'EMPTY'))
FROM job_requirements
UNION ALL SELECT 'requirement_embeddings', count(*),
  md5(coalesce(string_agg(embedding_id::text||'|'||requirement_id::text||'|'||alternative_index::text||'|'||embedding::text||'|'||embedding_version, ',' ORDER BY embedding_id),'EMPTY'))
FROM requirement_embeddings
UNION ALL SELECT 'app_state', count(*),
  md5(coalesce(string_agg(id::text||'|'||catalogue_revision::text, ',' ORDER BY id),'EMPTY'))
FROM app_state
ORDER BY t;
