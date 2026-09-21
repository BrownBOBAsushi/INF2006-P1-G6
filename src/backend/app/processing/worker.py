"""Code that runs INSIDE the isolated processing child (ARCHITECTURE.md "Processing topology and timeout").

The child loads the privacy analyzer and the embedding model once, then serves one request at a time over a pipe
until told to stop or until the parent goes away. Heavy libraries (torch, spaCy, Presidio, pdfplumber) are imported
only here, never in the API process.

Operations (payloads and results are plain dicts, pickled over the pipe):
    "prepare": {"pdf": bytes}     -> {"draft", "unassigned_text", "warnings"}          (PDF -> extraction -> privacy -> sections)
    "save":    {"content": dict}  -> {"review_required": True, "cleaned": dict}        (privacy re-check changed something)
                                  |  {"review_required": False, "version", "chunks", "vectors", "content_hash"}
Errors: a ProcessingError raised by a handler is sent back as (code, reason); any other exception is sent back as
INTERNAL_ERROR with only the exception CLASS NAME as reason, never its message (it can contain resume text).

"Restricted" here is best effort: environment offline flags, one ML thread and an in-process socket guard. It is NOT an
operating-system sandbox; real network/file isolation must come from the container or network policy.
"""
from __future__ import annotations

import os
from typing import Any, Callable

from app.processing.errors import ProcessingError

Handler = Callable[[dict], Any]


def restrict_child() -> None:
    """Best-effort restrictions, applied before any model or parser is loaded."""
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1",
                      TOKENIZERS_PARALLELISM="false")
    import socket

    def blocked(*_a, **_k):
        raise OSError("network access is disabled in the processing child")

    for name in ("connect", "connect_ex"):
        setattr(socket.socket, name, blocked)
    for name in ("create_connection", "getaddrinfo", "gethostbyname"):
        setattr(socket, name, blocked)


def serve(conn, handlers: dict[str, Handler]) -> None:
    """Serve requests until the parent sends None or closes the pipe. One request at a time."""
    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            return                                            # parent is gone: exit instead of lingering
        if msg is None:
            return
        req_id, op, payload = msg
        try:
            handler = handlers.get(op)
            if handler is None:
                raise ProcessingError("INTERNAL_ERROR", "unknown_operation")
            reply = (req_id, "ok", handler(payload))
        except ProcessingError as exc:
            reply = (req_id, "err", exc.code, exc.reason)
        except BaseException as exc:                          # noqa: BLE001 - deliberate: report the class only
            reply = (req_id, "err", "INTERNAL_ERROR", type(exc).__name__)
        try:
            conn.send(reply)
        except (BrokenPipeError, OSError):
            return
        payload = None                                        # drop references to resume data as soon as possible


def build_production_handlers() -> dict[str, Handler]:
    """Load the privacy analyzer and the embedding model once (slow: several seconds), then warm both up."""
    from app.processing import pipeline
    from app.processing.content import content_hash, validate_resume_content
    from app.processing.embeddings import EmbeddingModel
    from app.processing.privacy import get_redactor

    redactor = get_redactor()
    model = EmbeddingModel()                                  # local cache only; raises if the pinned weights are missing
    redactor.redact_lines(["warm up"])
    model.embed(["warm up"])

    def prepare(payload: dict) -> dict:
        pdf = payload.get("pdf")
        if not isinstance(pdf, (bytes, bytearray)):
            raise ProcessingError("INVALID_CONTENT", "pdf_payload")
        result = pipeline.prepare_resume(bytes(pdf), redactor)
        return {"draft": result.draft, "unassigned_text": result.unassigned_text, "warnings": result.warnings}

    def save(payload: dict) -> dict:
        content = payload.get("content")
        validate_resume_content(content)
        changed, cleaned = pipeline.recheck_privacy(content, redactor)
        if changed:
            return {"review_required": True, "cleaned": cleaned}
        emb = pipeline.embed_resume(content, model)
        return {"review_required": False, "version": emb.version, "chunks": emb.chunks, "vectors": emb.vectors,
                "content_hash": content_hash(content)}

    return {"prepare": prepare, "save": save}


def production_main(conn) -> None:
    """Spawn target of the production child."""
    restrict_child()
    try:
        handlers = build_production_handlers()
    except BaseException as exc:                              # noqa: BLE001
        try:
            conn.send(("fatal", type(exc).__name__))
        finally:
            return
    conn.send(("ready", {"operations": sorted(handlers)}))
    serve(conn, handlers)
