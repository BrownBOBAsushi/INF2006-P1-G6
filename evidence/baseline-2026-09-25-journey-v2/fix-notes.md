# Journey v2 harness fixes

These changes correct harness behavior after review. They do not change the application or its data.

- Synthetic account creation stages token and exact-ID manifest files, commits, then atomically publishes them. If commit or publication fails, it removes accounts from that invocation by exact user IDs. The accumulated manifest preserves IDs from earlier scenarios. Container helper, token, and manifest paths are isolated under a unique per-run directory.
- Browse samples count as successful only when the HTTP 200 body matches the `JobPage` envelope, pagination, item summary fields, and active synthetic catalogue records in `data/evaluation/jobs.json`.
- Retry steps reject a response returned at or after the monotonic deadline and record elapsed-deadline exhaustion. Python `urllib` socket timeouts cannot cancel a slow-drip body read, so the harness records that limit and does not claim a hard wall-clock transport deadline.
- `selfcheck.py` now covers commit/publication failure compensation and prior-manifest preservation, malformed and wrong-catalogue browse bodies, plus late success and slow-read deadline outcomes.

The existing files under `runs/` are historical results from before these fixes. They were preserved and were not rerun. A new Docker metrics run remains pending because Docker access was denied in this session. Local mocked checks and syntax compilation passed; they are harness verification, not new application performance measurements.
