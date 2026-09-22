"""REFERENCE HARNESS: a minimal FastAPI app that puts the processing slot behind real HTTP endpoints.

This is NOT the project's API and does not replace or modify Jiaxin's routes (src/backend/app/api). It exists for two reasons:
1. so tests/load/api_load.py can be run and verified end to end before the real routes exist;
2. as a working example of the integration pattern the real routes must follow (admission BEFORE reading the upload, work in a
   thread only after the slot is held, deferred release on client disconnect, contract error envelope + Retry-After).

It has no authentication, no CSRF, no database and reads a raw PDF body (`application/octet-stream`), so its numbers say nothing
about the real API's auth/DB cost. Run:  python -m uvicorn --app-dir tests/load harness_app:app --port 8765
Environment: HARNESS_DEADLINE_SECONDS (default 60).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "backend"))

from fastapi import FastAPI, Request                                   # noqa: E402
from fastapi.concurrency import run_in_threadpool                      # noqa: E402
from fastapi.responses import JSONResponse                             # noqa: E402

from app.processing.errors import ProcessingError                      # noqa: E402
from app.processing.slot import DEADLINE_SECONDS, ProcessingService    # noqa: E402

MAX_PDF_BYTES = 5_242_880

_JOBS = json.loads((ROOT / "data" / "evaluation" / "jobs.json").read_text(encoding="utf-8"))["jobs"]


def error_response(exc: ProcessingError) -> JSONResponse:
    """Contract error envelope (DATA_API_CONTRACT.md); details stay empty (whitelist only)."""
    headers = {"Retry-After": str(exc.retry_after_seconds)} if exc.retry_after_seconds else None
    return JSONResponse(status_code=exc.status_code, headers=headers, content={"error": {
        "code": exc.code, "message": exc.message, "request_id": uuid.uuid4().hex, "retryable": exc.retryable, "details": {}}})


def create_app(service: ProcessingService | None = None) -> FastAPI:
    svc = service or ProcessingService(deadline_s=float(os.environ.get("HARNESS_DEADLINE_SECONDS", DEADLINE_SECONDS)))

    @asynccontextmanager
    async def lifespan(_app):
        await run_in_threadpool(svc.start)          # blocks for the child's model load: run it off the event loop
        yield
        await run_in_threadpool(svc.stop)

    app = FastAPI(lifespan=lifespan)
    app.state.service = svc

    @app.get("/health/live")
    def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    def ready():
        ok = svc.is_ready()                         # child up with models loaded (False while it is being replaced)
        return JSONResponse(status_code=200 if ok else 503, content={"status": "ready" if ok else "not_ready"})

    @app.get("/api/jobs")
    def browse(limit: int = 20, offset: int = 0):   # stand-in for the real browse endpoint: cheap, never touches the slot
        items = [{"job_id": j["source_job_id"], "title": j["title"], "company_name": j["company_name"],
                  "location": j["location"], "job_type": j["job_type"]} for j in _JOBS[offset:offset + limit]]
        return {"items": items, "total": len(_JOBS), "limit": limit, "offset": offset, "catalogue_revision": 1}

    @app.post("/api/resume/prepare")
    async def prepare(request: Request):
        try:
            lease = svc.try_acquire()               # 1. non-blocking admission BEFORE consuming the upload
        except ProcessingError as exc:
            return error_response(exc)              #    busy / unavailable: immediate, nothing queued
        try:
            chunks, size = [], 0
            async for chunk in request.stream():    # 2. bounded read (the real route also enforces multipart/page limits)
                size += len(chunk)
                if size > MAX_PDF_BYTES:
                    return error_response(ProcessingError("FILE_TOO_LARGE", "byte_limit"))
                chunks.append(chunk)
            data = b"".join(chunks)
            loop = asyncio.get_running_loop()       # 3. only now hand work to a thread; the slot is already ours
            result = await loop.run_in_executor(None, lambda: lease.run("prepare", {"pdf": data}))
            return result
        except ProcessingError as exc:
            return error_response(exc)
        finally:
            lease.release()                         # 4. deferred automatically if the client disconnected mid-run

    return app


app = create_app() if os.environ.get("HARNESS_NO_AUTOSTART") != "1" else None
