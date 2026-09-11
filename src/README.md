# Application source

Status: no application implemented yet. See ../docs/handoff/IMPLEMENTATION_GUIDE.md.

- backend/: FastAPI app, migrations, processing, matching and importer.
- frontend/: React app.
- infra/: deployment/backup scripts after local acceptance.
- .env.example: placeholders only, never real credentials.

Bootstrap owner: Jiaxin coordinates Compose/backend; Xue E coordinates frontend.
Create a root compose.yaml in the first implementation slice. Do not claim `docker compose up` works until checked from a fresh checkout.
