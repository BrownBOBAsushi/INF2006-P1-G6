# Evidence index

`test-data-ai.md` records a real, dated run (results provisional: labels pending human review). All other test documents currently say NOT RUN and are templates, not proof.
architecture.svg is a PLANNED architecture figure, not deployed-state evidence. Editable logical diagram is in ../docs/handoff/ARCHITECTURE.md. Update both to match implementation before final submission.

Each test record needs objective, setup/version/hardware, exact commands, expected/actual result, date, evidence path, interpretation and limitations. Redact identifiers and secrets. Do not overwrite failed results to suggest first-pass success; record reruns separately.

`test-processing-matching.md` (with `load-matching-2026-09-21.md/.json`) records real, dated tests and local load measurements for the processing, matching and catalogue modules (component level; not an API or cloud test).

`test-processing-isolation.md` (with `load-api-harness-2026-09-21-api.md/.json`) records the isolated processing child, the single slot with its 60 s deadline, and the HTTP load script. The HTTP numbers come from a reference harness, not from the project's API.
