"""Fake worker entry points for tests/pipeline/test_processing_slot.py.

They use the REAL request loop and protocol (app.processing.worker.serve) with cheap handlers, so slot, deadline, crash and
recovery behaviour can be tested without loading any model. Spawned children import this module by name.
"""
import os
import socket
import time

from app.processing.errors import ProcessingError
from app.processing.worker import restrict_child, serve


def _handlers():
    def sleep(p):
        time.sleep(p["seconds"])
        return {"slept": p["seconds"], "pid": os.getpid()}

    def crash(_p):
        os._exit(3)

    def boom(p):
        raise RuntimeError(p["secret"])           # message contains the (fake) resume text: it must never reach the parent

    def proc_error(p):
        raise ProcessingError(p["code"], "from_child")

    def connect(p):
        try:
            socket.create_connection(("127.0.0.1", p["port"]), timeout=2).close()
            return "connected"
        except OSError:
            return "blocked"

    return {"echo": lambda p: {"echo": p, "pid": os.getpid()}, "sleep": sleep, "crash": crash, "boom": boom,
            "proc_error": proc_error, "connect": connect, "pid": lambda _p: os.getpid(),
            "big": lambda p: b"x" * p["n"]}


def main(conn):
    conn.send(("ready", {}))
    serve(conn, _handlers())


def main_restricted(conn):
    restrict_child()
    conn.send(("ready", {}))
    serve(conn, _handlers())


def main_fatal(conn):
    conn.send(("fatal", "ModelLoadError"))


def main_never_ready(conn):
    time.sleep(60)


def main_ok_once(conn, marker_path):
    """Starts fine the first time (creating the marker); every later start fails: tests permanent recovery failure."""
    if os.path.exists(marker_path):
        conn.send(("fatal", "SecondStartFails"))
        return
    open(marker_path, "w").close()
    conn.send(("ready", {}))
    serve(conn, _handlers())


def main_http(conn):
    """Stand-in for the production `prepare` op, driven by the request body (used by the HTTP harness tests)."""
    def prepare(p):
        body = p["pdf"]
        if body.startswith(b"sleep:"):
            time.sleep(float(body[6:]))
        elif body == b"crash":
            os._exit(3)
        elif body.startswith(b"error:"):
            raise ProcessingError(body[6:].decode(), "from_child")
        return {"draft": {"skills": [], "projects": [], "experience": [], "education": []}, "unassigned_text": "", "warnings": []}

    conn.send(("ready", {}))
    serve(conn, {"prepare": prepare})
