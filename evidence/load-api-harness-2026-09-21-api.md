# API-level load measurements (2026-09-21)

Code version: git `c95f9624c6`.

> **Target: the REFERENCE HARNESS (`tests/load/harness_app.py`), not the project's API.** It has no authentication, CSRF or database, so these numbers describe the processing slot and child process over real HTTP on this machine. They are not evidence about Jiaxin's routes, which do not exist yet.

- harness readiness time (child loading models): 15.7 s
- PDF: resume_P10.pdf (5320 bytes)
- child deadline: 60.0 s

```json
{
  "platform": "Windows-10-10.0.26200-SP0",
  "cpu": "AMD64 Family 25 Model 117 Stepping 2, AuthenticAMD",
  "logical_cpus": 16,
  "ram_gb": 31.3,
  "python": "3.11.9",
  "numpy": "2.4.6",
  "blas_threads_env": {
    "OMP_NUM_THREADS": null,
    "MKL_NUM_THREADS": null
  }
}
```

## api-concurrency

closed-loop concurrent resume-prepare requests. 'busy' (503 PROCESSING_BUSY) is a controlled rejection, not useful throughput; 'admitted_ok_per_s' counts only completed preparations.

| concurrency | requests | wall_s | admitted_ok_per_s | busy_rate | error_rate | ok p50/p95/max ms | busy p50/p95/max ms | timeout n | error n |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 15 | 13.1 | 1.14 | 0.0 | 0.0 | 811.3 / 1086.3 / 1087.6 | - | 0 | 0 |
| 5 | 30 | 1.39 | 0.72 | 0.967 | 0.0 | 793.6 / 793.6 / 793.6 | 2.6 / 4.8 / 5.2 | 0 | 0 |
| 10 | 50 | 1.54 | 0.65 | 0.98 | 0.0 | 818.4 / 818.4 / 818.4 | 1.9 / 11.9 / 23.5 | 0 | 0 |
| 25 | 100 | 2.08 | 0.48 | 0.99 | 0.0 | 984.4 / 984.4 / 984.4 | 1.4 / 3.2 / 24.1 | 0 | 0 |

## browse-during-processing

4 browse clients (GET /api/jobs, 50 ms think time) alone for 5 s, then for 25 s together with 5 clients repeatedly submitting resume-prepare requests (closed loop).

- **Browse alone (baseline):** 330 requests; ok 330 (p50 3.2 ms, p95 4.8 ms, max 15.0 ms); errors 0 
- **Browse while processing is busy:** 1720 requests; ok 1720 (p50 5.3 ms, p95 8.7 ms, max 21.1 ms); errors 0 
- **Processing clients:** 26599 requests: admitted ok 27 (p50 901.2 ms, p95 1180.4 ms, max 1203.4 ms), busy 503 26572 (p50 3.4 ms, p95 5.9 ms, max 35.7 ms), timeout 504 0, other errors 0 
- ARCHITECTURE.md targets, for reference only: {"busy_response_target_ms": 1000, "busy_response_p95_ms_measured": 5.9, "admitted_processing_target_s": 60, "admitted_processing_max_s_measured": 1.2, "note": "targets come from ARCHITECTURE.md 'Local acceptance'; they concern the real API, so they are only indicative here."}

