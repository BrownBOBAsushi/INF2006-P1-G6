# Data and provenance

Status: synthetic evaluation fixtures created 2026-09-20 in `evaluation/` (30 jobs, 10 profiles, 300 labels; labels AI-drafted, human review pending). Synthetic resume PDFs (fictional PII, plus edge cases) are in `../tests/fixtures/pdf/`. `synthetic_jobs.json` for the importer is not yet created. Local development must use synthetic jobs and resumes.
Owner: Chuying; Zhihao reviews provenance and evaluation labels.

Create synthetic_jobs.json matching the import contract and synthetic PDF fixtures under tests/fixtures/. Label examples synthetic in the UI when used for demos. Never use real student resumes as committed fixtures.

JSearch returned relevant Singapore samples in user-provided responses. This does not establish bulk coverage or permission to retain/redistribute listings. Do not commit those responses or call live sources from tests. Record source, licence/permission, collection date, transformations, allowed retention and limitations before adding external data.

Evaluation: data/evaluation/ contains independently labelled synthetic relevance examples with development/held-out split. Detailed fields and bounds: ../docs/handoff/DATA_API_CONTRACT.md.
