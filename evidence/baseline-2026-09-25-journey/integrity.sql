-- Content-level integrity digests of EXISTING (non-synthetic) data.
-- Synthetic accounts created by this run use google_sub prefixed 'loadtest-'; every synthetic
-- prefix (this run's 'loadtest-journey-%' and any earlier 'loadtest-%') is excluded so the
-- digests depend only on pre-existing data. Row COUNT alone is not trusted: each digest hashes
-- the ordered column values (including resume_chunks.embedding vectors), so any content change
-- flips the hash. Tokens/PII are never emitted — only md5 hashes and counts.
\pset footer off
WITH synth AS (SELECT user_id FROM users WHERE google_sub LIKE 'loadtest-%')
SELECT 'users' AS t, count(*) AS n,
       md5(coalesce(string_agg(user_id::text||'|'||google_sub||'|'||coalesce(display_name,'')||'|'||resume_revision::text||'|'||created_at::text||'|'||updated_at::text, ',' ORDER BY user_id),'')) AS digest
FROM users WHERE user_id NOT IN (SELECT user_id FROM synth)
UNION ALL
SELECT 'sessions', count(*),
       md5(coalesce(string_agg(token_hash||'|'||user_id::text||'|'||csrf_token||'|'||expires_at::text||'|'||last_active_at::text, ',' ORDER BY token_hash),''))
FROM sessions WHERE user_id NOT IN (SELECT user_id FROM synth)
UNION ALL
SELECT 'resume_profiles', count(*),
       md5(coalesce(string_agg(user_id::text||'|'||revision::text||'|'||content_hash||'|'||embedding_version||'|'||content::text, ',' ORDER BY user_id),''))
FROM resume_profiles WHERE user_id NOT IN (SELECT user_id FROM synth)
UNION ALL
SELECT 'resume_chunks', count(*),
       md5(coalesce(string_agg(chunk_id::text||'|'||user_id::text||'|'||profile_revision::text||'|'||section||'|'||entry_index::text||'|'||chunk_index::text||'|'||text||'|'||embedding::text||'|'||embedding_version, ',' ORDER BY chunk_id),''))
FROM resume_chunks WHERE user_id NOT IN (SELECT user_id FROM synth)
UNION ALL
SELECT 'save_operations', count(*),
       md5(coalesce(string_agg(user_id::text||'|'||operation_id::text||'|'||payload_hash||'|'||state||'|'||coalesce(result_revision::text,'')||'|'||coalesce(failure_code,''), ',' ORDER BY user_id, operation_id),''))
FROM save_operations WHERE user_id NOT IN (SELECT user_id FROM synth)
UNION ALL
SELECT 'jobs', count(*),
       md5(coalesce(string_agg(job_id::text||'|'||source_job_id||'|'||title||'|'||company_name||'|'||coalesce(description,'')||'|'||is_active::text||'|'||content_hash, ',' ORDER BY job_id),''))
FROM jobs
UNION ALL
SELECT 'job_requirements', count(*),
       md5(coalesce(string_agg(requirement_id::text||'|'||job_id::text||'|'||ordinal::text||'|'||requirement_text||'|'||importance, ',' ORDER BY requirement_id),''))
FROM job_requirements
UNION ALL
SELECT 'requirement_embeddings', count(*),
       md5(coalesce(string_agg(embedding_id::text||'|'||requirement_id::text||'|'||alternative_index::text||'|'||embedding::text||'|'||embedding_version, ',' ORDER BY embedding_id),''))
FROM requirement_embeddings
UNION ALL
SELECT 'app_state', count(*),
       md5(coalesce(string_agg(id::text||'|'||catalogue_revision::text, ',' ORDER BY id),''))
FROM app_state
ORDER BY t;
