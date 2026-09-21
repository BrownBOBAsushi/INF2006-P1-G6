"""Processing slot and isolated child process (ARCHITECTURE.md "Processing topology and timeout").

What this implements (all in the API PROCESS'S SIDE; heavy work happens in the child, see worker.py):

* ONE process-wide slot shared by PDF preparation and embedding. Admission is non-blocking: `try_acquire()` either returns a
  lease immediately or raises ProcessingError("PROCESSING_BUSY") at once. Nothing is ever queued: work is only handed to a
  thread/executor AFTER the slot is held.
* ONE long-lived child process (spawn) that loads the privacy analyzer and embedding model once and does the CPU work off the
  API event loop. This module imports no ML library, so the API process stays small.
* A per-operation deadline (default 60 s). On expiry the child is terminated AND joined before the slot can be released, a
  fresh child is recreated in the background, and the caller gets ProcessingError("PROCESSING_TIMEOUT"). Cancelling an
  asyncio task does not stop CPU work, so this is the only real stop.
* A client disconnect cannot free a running slot: `Lease.release()` while an operation is still running is deferred until
  that operation has finished or its child has been terminated and joined.
* A child that crashes is handled like a timeout (INTERNAL_ERROR, child replaced). While a replacement loads (several
  seconds) new requests get PROCESSING_BUSY; if replacement keeps failing the service reports SERVICE_UNAVAILABLE.

What the API layer must still do (NOT done here): create/start one ProcessingService per API process, call it from the
routes, map ProcessingError to the HTTP error envelope (+ Retry-After for PROCESSING_BUSY), enforce upload size/page limits
while streaming, and include `is_ready()` in /health/ready. See src/backend/JIAXIN_INTEGRATION.md.

Threading rules: `try_acquire()` never blocks and is safe on the event loop. `Lease.run()` BLOCKS for up to the deadline and
must run in a worker thread (`run_async` does this correctly).
"""
from __future__ import annotations

import asyncio
import logging
import multiprocessing
import threading
import time
import uuid
from typing import Any, Callable

from app.processing.errors import CONTRACT_ERRORS, ProcessingError

log = logging.getLogger(__name__)

DEADLINE_SECONDS = 60.0            # ARCHITECTURE.md: preparation/embedding child deadline (proxy 90 s, client 100 s)
STARTUP_TIMEOUT_SECONDS = 180.0    # generous: the child loads spaCy + the embedding model
TERMINATE_GRACE_SECONDS = 5.0
RESPAWN_ATTEMPTS = 3
RESPAWN_BACKOFF_SECONDS = 2.0
_POLL_SECONDS = 0.1

STOPPED, STARTING, READY, RECOVERING, FAILED = "STOPPED", "STARTING", "READY", "RECOVERING", "FAILED"


class Lease:
    """Exclusive right to use the processing child. Obtain with ProcessingService.try_acquire()."""

    def __init__(self, service: "ProcessingService"):
        self._svc = service
        self._mutex = threading.Lock()
        self._running = False
        self._release_requested = False
        self._released = False

    def run(self, op: str, payload: dict, deadline_s: float | None = None) -> Any:
        """Run one operation in the child and return its result. BLOCKS up to the deadline: call from a thread."""
        with self._mutex:
            if self._released or self._release_requested:
                raise RuntimeError("lease has been released")
            if self._running:
                raise RuntimeError("only one operation may run per lease at a time")
            self._running = True
        try:
            return self._svc._call(op, payload, self._svc.deadline_s if deadline_s is None else deadline_s)
        finally:
            with self._mutex:
                self._running = False
                free_now = self._release_requested and not self._released
                if free_now:
                    self._released = True
            if free_now:                       # deferred release: the operation has now ended (or its child is dead)
                self._svc._slot.release()

    def release(self) -> None:
        """Give the slot back. Idempotent. If an operation is still running (for example the client disconnected and the
        route was cancelled) the release is deferred until that operation has ended."""
        with self._mutex:
            if self._released:
                return
            if self._running:
                self._release_requested = True
                return
            self._released = True
        self._svc._slot.release()

    def __enter__(self) -> "Lease":
        return self

    def __exit__(self, *_exc) -> None:
        self.release()


class ProcessingService:
    def __init__(self, *, deadline_s: float = DEADLINE_SECONDS, worker_target: Callable | None = None,
                 worker_args: tuple = (), startup_timeout_s: float = STARTUP_TIMEOUT_SECONDS):
        from app.processing.worker import production_main    # light module: heavy imports happen only inside the child
        self.deadline_s = float(deadline_s)
        self._target = worker_target or production_main
        self._args = tuple(worker_args)
        self._startup_timeout_s = startup_timeout_s
        self._ctx = multiprocessing.get_context("spawn")      # never fork a process that may hold torch/threads
        self._slot = threading.Lock()                         # THE slot: process-wide, non-blocking acquire only
        self._lock = threading.RLock()                        # guards state / proc / conn
        self._state = STOPPED
        self._proc = None
        self._conn = None
        self._respawn_thread: threading.Thread | None = None

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        """Start the child and wait until it has loaded its models (several seconds). Call once, at API startup."""
        with self._lock:
            if self._state in (READY, STARTING):
                return
            self._state = STARTING
        try:
            proc, conn = self._spawn()
        except BaseException:
            with self._lock:
                self._state = FAILED
            raise
        with self._lock:
            self._proc, self._conn, self._state = proc, conn, READY

    def stop(self) -> None:
        """Stop the child (API shutdown). A running operation fails with SERVICE_UNAVAILABLE/INTERNAL_ERROR."""
        with self._lock:
            proc, conn = self._proc, self._conn
            self._proc = self._conn = None
            self._state = STOPPED
        if conn is not None:
            try:
                conn.send(None)
            except (OSError, ValueError):
                pass
        if proc is not None:
            proc.join(2.0)
            self._kill(proc)
        if conn is not None:
            conn.close()

    def is_ready(self) -> bool:
        """True when the child is up with its models loaded. Suitable for /health/ready. False while recovering."""
        with self._lock:
            return self._state == READY and self._proc is not None and self._proc.is_alive()

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def child_pid(self) -> int | None:
        with self._lock:
            return self._proc.pid if self._proc is not None else None

    # ------------------------------------------------------------------ admission
    def try_acquire(self) -> Lease:
        """Take the single slot WITHOUT waiting. Raises PROCESSING_BUSY at once when it is taken or the child is being
        replaced, SERVICE_UNAVAILABLE when the service is stopped or could not start."""
        if not self._slot.acquire(blocking=False):
            raise ProcessingError("PROCESSING_BUSY", "slot_taken")
        with self._lock:
            state, proc = self._state, self._proc
            if state == READY and (proc is None or not proc.is_alive()):
                self._state = state = RECOVERING            # the child died while idle
                self._proc = self._conn = None
                self._begin_respawn()
        if state == READY:
            return Lease(self)
        self._slot.release()
        if state in (RECOVERING, STARTING):
            raise ProcessingError("PROCESSING_BUSY", "child_recovering")
        raise ProcessingError("SERVICE_UNAVAILABLE", f"service_{state.lower()}")

    async def run_async(self, op: str, payload: dict, deadline_s: float | None = None) -> Any:
        """acquire (non-blocking, on the loop) -> run in a worker thread -> release. Cancelling the awaiting task (client
        disconnect) does NOT free the slot early: the thread keeps running and the deferred release fires when it ends."""
        lease = self.try_acquire()
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, lambda: lease.run(op, payload, deadline_s))
        finally:
            lease.release()

    # ------------------------------------------------------------------ internals
    def _spawn(self):
        parent_conn, child_conn = self._ctx.Pipe(duplex=True)
        proc = self._ctx.Process(target=self._target, args=(child_conn, *self._args), daemon=True)
        proc.start()
        child_conn.close()
        end = time.monotonic() + self._startup_timeout_s
        msg: tuple = ("fatal", "startup_timeout")
        while True:
            try:
                if parent_conn.poll(_POLL_SECONDS):
                    msg = parent_conn.recv()
                    break
            except (EOFError, OSError):
                msg = ("fatal", "pipe_closed")
                break
            if not proc.is_alive():
                msg = ("fatal", "child_exited")
                break
            if time.monotonic() > end:
                break
        if not msg or msg[0] != "ready":
            self._kill(proc)
            parent_conn.close()
            reason = str(msg[1]) if len(msg) > 1 else "unknown"          # an exception CLASS name, never a message
            log.error("processing_child_start_failed reason=%s", reason)
            raise ProcessingError("SERVICE_UNAVAILABLE", f"child_start_failed:{reason}")
        return proc, parent_conn

    @staticmethod
    def _kill(proc) -> None:
        """Terminate and JOIN. Windows TerminateProcess / POSIX SIGTERM, then SIGKILL if it does not die in the grace time."""
        if proc.is_alive():
            proc.terminate()
            proc.join(TERMINATE_GRACE_SECONDS)
            if proc.is_alive():
                proc.kill()
        proc.join()

    def _begin_respawn(self) -> None:
        with self._lock:
            if self._respawn_thread is not None and self._respawn_thread.is_alive():
                return
            self._respawn_thread = threading.Thread(target=self._respawn_loop, name="processing-respawn", daemon=True)
            self._respawn_thread.start()

    def _respawn_loop(self) -> None:
        for attempt in range(RESPAWN_ATTEMPTS):
            with self._lock:
                if self._state == STOPPED:
                    return
            try:
                proc, conn = self._spawn()
            except ProcessingError:
                time.sleep(RESPAWN_BACKOFF_SECONDS)
                continue
            with self._lock:
                if self._state == STOPPED:                    # stopped while we were loading
                    self._kill(proc)
                    conn.close()
                    return
                self._proc, self._conn, self._state = proc, conn, READY
            log.info("processing_child_recreated attempt=%d", attempt + 1)
            return
        with self._lock:
            if self._state != STOPPED:
                self._state = FAILED
        log.error("processing_child_recreate_failed attempts=%d", RESPAWN_ATTEMPTS)

    def _terminate_and_recover(self, cause: str) -> None:
        """Called from the slot holder. Marks RECOVERING first (so nothing new is admitted), terminates and JOINS the child,
        then recreates it in the background. The caller still holds the slot, so it is released only after the join."""
        with self._lock:
            proc, conn = self._proc, self._conn
            self._proc = self._conn = None
            if self._state != STOPPED:
                self._state = RECOVERING
        if proc is not None:
            self._kill(proc)
            log.warning("processing_child_stopped cause=%s exit_code=%s", cause, proc.exitcode)
        if conn is not None:
            conn.close()
        with self._lock:
            still = self._state == RECOVERING
        if still:
            self._begin_respawn()

    def _call(self, op: str, payload: dict, deadline_s: float) -> Any:
        with self._lock:
            proc, conn, state = self._proc, self._conn, self._state
        if state != READY or proc is None or conn is None or not proc.is_alive():
            self._terminate_and_recover("not_running")
            raise ProcessingError("SERVICE_UNAVAILABLE", "child_not_running")
        req_id = uuid.uuid4().hex
        try:
            conn.send((req_id, op, payload))
        except (OSError, ValueError, EOFError):
            self._terminate_and_recover("send_failed")
            raise ProcessingError("INTERNAL_ERROR", "child_pipe") from None
        end = time.monotonic() + deadline_s
        reply, outcome = None, "timeout"
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                break
            try:
                if conn.poll(min(remaining, _POLL_SECONDS)):
                    reply, outcome = conn.recv(), "reply"
                    break
            except (EOFError, OSError):
                outcome = "crash"
                break
            if not proc.is_alive():
                try:
                    if conn.poll(0):                          # the child may have answered just before exiting
                        reply, outcome = conn.recv(), "reply"
                        break
                except (EOFError, OSError):
                    pass
                outcome = "crash"
                break
        if outcome == "timeout":
            self._terminate_and_recover("deadline")
            raise ProcessingError("PROCESSING_TIMEOUT", "deadline")
        if outcome == "crash":
            self._terminate_and_recover("crash")
            raise ProcessingError("INTERNAL_ERROR", "child_died")
        if not isinstance(reply, tuple) or len(reply) < 3 or reply[0] != req_id:
            self._terminate_and_recover("protocol")
            raise ProcessingError("INTERNAL_ERROR", "protocol")
        if reply[1] == "ok":
            return reply[2]
        code, reason = (reply[2], reply[3]) if len(reply) >= 4 else ("INTERNAL_ERROR", "malformed_error")
        raise ProcessingError(code if code in CONTRACT_ERRORS else "INTERNAL_ERROR", str(reason))
