"""Shared fixtures for the processing / matching / catalogue tests (Chuying).

Run from the repo root with the processing environment (src/backend/requirements-processing.txt):
    pytest tests/pipeline
Real components are used wherever practical: the pinned MiniLM model (from the local cache), Presidio with spaCy,
and a real PostgreSQL 16 + pgvector started by the `pgserver` package (no Docker needed). Nothing is mocked
unless a test says so.
"""
import logging
import os
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "src" / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / "analytics"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

def pytest_configure(config):
    config.addinivalue_line("markers", "slow: takes about a minute (real 60 s deadline)")


def reenable_loggers():
    """Alembic's env.py calls logging.config.fileConfig, which disables every existing logger (ours included). Re-enable
    them so that log-content assertions are never vacuous."""
    for lg in logging.root.manager.loggerDict.values():
        if hasattr(lg, "disabled"):
            lg.disabled = False


PDF_DIR = ROOT / "tests" / "fixtures" / "pdf"
EVAL_DIR = ROOT / "data" / "evaluation"


@pytest.fixture(scope="session")
def model():
    from app.processing.embeddings import EmbeddingModel
    return EmbeddingModel()          # local cache only; fails loudly if the pinned weights are not cached


@pytest.fixture(scope="session")
def redactor():
    from app.processing.privacy import get_redactor
    return get_redactor()


@pytest.fixture(scope="session")
def profiles():
    import json
    return {p["profile_id"]: p for p in json.loads((EVAL_DIR / "profiles.json").read_text(encoding="utf-8"))["profiles"]}


@pytest.fixture(scope="session")
def jobs_raw():
    import json
    return json.loads((EVAL_DIR / "jobs.json").read_text(encoding="utf-8"))


class HashEmbedder:
    """Deterministic fake embedder for pure-logic importer tests (real-model tests use the `model` fixture)."""
    version = "fake-hash-embedder@1"
    dim = 384

    def validate_text(self, text):
        from app.processing.errors import EmptyTextError, TokenLimitError
        if not text.strip():
            raise EmptyTextError("empty")
        if len(text.split()) > 200:
            raise TokenLimitError("long")

    def embed(self, texts):
        out = []
        for t in texts:
            rng = np.random.default_rng(abs(hash_text(t)) % (2**32))
            v = rng.normal(size=self.dim).astype(np.float32)
            out.append(v / np.linalg.norm(v))
        return np.stack(out)


def hash_text(t: str) -> int:
    import hashlib
    return int.from_bytes(hashlib.sha256(t.encode()).digest()[:8], "big")


@pytest.fixture()
def fake_embedder():
    return HashEmbedder()


@pytest.fixture(scope="session")
def pg_url(tmp_path_factory):
    """Real PostgreSQL 16 + pgvector on loopback, migrated to alembic head (this also tests the migration chain)."""
    pgserver = pytest.importorskip("pgserver")
    server = pgserver.get_server(tmp_path_factory.mktemp("pgdata"), cleanup_mode="stop")
    url = server.get_uri().replace("postgresql://", "postgresql+psycopg://", 1)
    os.environ["DATABASE_URL"] = url
    from alembic import command
    from alembic.config import Config
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.upgrade(cfg, "head")
    reenable_loggers()
    yield url
    server.cleanup()


@pytest.fixture()
def db(pg_url):
    """A session on a clean catalogue: catalogue rows and resume data are emptied before each test."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session
    engine = create_engine(pg_url)
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE requirement_embeddings, job_requirements, jobs, resume_chunks, resume_profiles, users CASCADE"))
        conn.execute(text("UPDATE app_state SET catalogue_revision = 0"))
    with Session(engine) as session:
        yield session
    engine.dispose()
