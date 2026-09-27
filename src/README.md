# Application source

> Historical scaffold note: this source tree is implemented. The local Compose entry points and current developer workflow are documented in [the root README](../README.md) and [local integration runbook](../docs/LOCAL_INTEGRATION.md). Cloud deployment remains proposed and unverified; see [cloud architecture](../docs/CLOUD_ARCHITECTURE.md).

The next section records the original bootstrap assumptions for history; its “no application” and “create a root compose.yaml” instructions are superseded by the current tree.

- backend/: FastAPI app, migrations, processing, matching and importer.
- frontend/: React app.
- infra/: deployment/backup scripts after local acceptance.
- .env.example: placeholders only, never real credentials.

Bootstrap owner: Jiaxin coordinates Compose/backend; Xue E coordinates frontend.
The current repository entry points are `docker-compose.yml` and `docker-compose.dev.yml`; follow the linked runbook for current commands.
