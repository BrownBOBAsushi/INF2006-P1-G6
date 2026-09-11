# Team launch checklist

## Zhihao prepares

1. Confirm official group identifier, full names and student IDs for manifest; blanks are deliberate.
2. Ensure all four teammates can clone/push feature branches; agree review/merge owner and protect primary branches through the repository host. No remote permissions changed by this scaffold.
3. Own the Google Cloud project/configuration or designate one team-owned maintainer. Create a Web OAuth client for Google Identity Services. Authorised JavaScript origin for planned local proxy: http://localhost:8080. Add actual production origin later. Client ID is shared configuration, not an API secret. Configure test-user access if required by the chosen consent-screen mode; do not invent redirect URLs for a token-based integration.
4. Share configuration through an agreed private channel, never commits/screenshots. No AWS or job-provider credentials needed for local work. APP_SIGNING_KEY and database password are generated separately per developer environment.
5. Give the team docs/handoff and agree suggested feature owners. Review one complete local journey before adding scope. Zhihao controls future AWS budget/access approval; Jiaxin owns DB migrations, Chuying coordinates vector-related changes.

## Each teammate installs

Git, Docker Desktop/Compose and a code editor. Python/Node host installs are optional if tools run in containers; Jiaxin/Xue E pin exact runtime versions and lockfiles during bootstrap. Docker availability depends on each person's OS/architecture: record it before choosing images.

Each developer runs a private local PostgreSQL instance through Compose, using identical migrations and synthetic seeds. No shared database on Zhihao's laptop. Frontend uses API/mocks, never DB credentials. Named volumes preserve saved local data; document reset explicitly so it is never accidental.

## First implementation day

- Jiaxin: Compose networking, DB/migrations, auth configuration, health endpoint and typed schemas. Chuying: validate model/privacy imports on chosen runtime and provide synthetic import/prepare fixtures.
- Xue E: frontend scaffold/router/shared client; Nasya: resume-review and recommendation mock states using agreed schemas.
- Commit dependency locks and safe examples. Verify all four can start the SAME baseline; root README must then contain actual working commands.
- Generate OpenAPI and shared fixtures before divergent endpoint implementations. No feature needs a hosted LLM API key.

## Daily coordination

Small feature branches and reviewed PRs. Backend-owned migrations are committed files, not manual shared-DB edits. Resolve shared-client/contract changes with Jiaxin and Xue E. End each slice with command outputs/screenshots using synthetic data and a clear next blocker. Zhihao reviews product behaviour and risk, not every routine command.

## Definition of environment ready

Fresh clone + documented configuration + documented startup brings up UI/API/DB; migrations and seed import succeed; browser reaches health/catalogue; real Google login succeeds; tests can use explicit isolated test identity. This is a target, not achieved by the scaffold. AWS deployment starts only after the local MVP and tests pass.
