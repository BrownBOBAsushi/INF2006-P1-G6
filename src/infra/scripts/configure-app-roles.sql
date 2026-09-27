SET log_statement = 'none';
SET log_min_error_statement = 'panic';
SET log_parameter_max_length_on_error = 0;
CREATE EXTENSION IF NOT EXISTS vector;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE TEMPORARY ON DATABASE :"DB_NAME" FROM PUBLIC;

\getenv migrator_password APP_MIGRATOR_PASSWORD
\getenv runtime_password APP_RUNTIME_PASSWORD

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_roles
    WHERE rolname IN ('app_migrator', 'app_runtime')
      AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls
           OR NOT rolcanlogin OR rolinherit)
  ) THEN
    RAISE EXCEPTION 'Existing application role has attributes outside the expected restricted login contract';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM pg_auth_members AS membership
    JOIN pg_roles AS granted_role ON granted_role.oid = membership.roleid
    JOIN pg_roles AS member_role ON member_role.oid = membership.member
    WHERE (granted_role.rolname IN ('app_migrator', 'app_runtime')
       OR member_role.rolname IN ('app_migrator', 'app_runtime'))
      AND NOT (
        granted_role.rolname IN ('app_migrator', 'app_runtime')
        AND member_role.rolname = current_user
        AND membership.admin_option IS TRUE
        AND membership.inherit_option IS FALSE
        AND membership.set_option IS FALSE
      )
  ) THEN
    RAISE EXCEPTION 'Existing application role has an unexpected role membership';
  END IF;
END
$$;

SELECT format(
  'CREATE ROLE app_migrator LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT',
  :'migrator_password'
) WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_migrator') \gexec
SELECT format(
  'ALTER ROLE app_migrator LOGIN PASSWORD %L NOCREATEDB NOCREATEROLE NOINHERIT',
  :'migrator_password'
) \gexec
SELECT format(
  'CREATE ROLE app_runtime LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT',
  :'runtime_password'
) WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_runtime') \gexec
SELECT format(
  'ALTER ROLE app_runtime LOGIN PASSWORD %L NOCREATEDB NOCREATEROLE NOINHERIT',
  :'runtime_password'
) \gexec

GRANT CONNECT ON DATABASE :"DB_NAME" TO app_migrator, app_runtime;
GRANT USAGE, CREATE ON SCHEMA public TO app_migrator;
GRANT USAGE ON SCHEMA public TO app_runtime;
