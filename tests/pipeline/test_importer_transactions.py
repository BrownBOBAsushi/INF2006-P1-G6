"""Lightweight SQLAlchemy session lifecycle regressions for catalogue import."""
import uuid

import numpy as np
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.catalogue import importer
from app.catalogue.models import AppState
from app.catalogue.schema import validate_import


class _NoopEmbedder:
    version = "test@1"

    def validate_text(self, text):
        pass

    def embed(self, texts):
        raise AssertionError("unchanged imports must reuse the existing vectors")


def test_successful_import_returns_clean_default_expiring_session_and_allows_next_import(jobs_raw, monkeypatch):
    engine = create_engine("sqlite://")
    AppState.__table__.create(engine)
    raw = {"schema_version": 1, "jobs": [jobs_raw["jobs"][0]]}
    job = validate_import(raw)[0][0]
    embedded_texts = {
        text
        for requirement in job.requirements
        for text in importer.requirement_texts(requirement)
    }
    monkeypatch.setattr(
        importer,
        "_load_existing",
        lambda session, keys: {
            (job.source, job.source_job_id): importer._Existing(
                job_id=uuid.uuid4(),
                content_hash=importer.job_content_hash(job),
                vectors={text: (np.zeros(384), "test@1") for text in embedded_texts},
            )
        },
    )

    try:
        with Session(engine) as session:
            assert session.expire_on_commit is True
            session.add(AppState(id=1, catalogue_revision=0))
            session.commit()

            first = importer.import_catalogue(session, raw, _NoopEmbedder())
            assert first.ok and first.unchanged == 1 and first.catalogue_revision == 0
            assert not session.in_transaction()

            second = importer.import_catalogue(session, raw, _NoopEmbedder())
            assert second.ok and second.unchanged == 1 and second.catalogue_revision == 0
            assert not session.in_transaction()
    finally:
        engine.dispose()


def test_rejected_import_preserves_callers_pending_work(jobs_raw):
    engine = create_engine("sqlite://")
    AppState.__table__.create(engine)
    try:
        with Session(engine) as session:
            pending = AppState(id=1, catalogue_revision=7)
            session.add(pending)

            try:
                importer.import_catalogue(session, jobs_raw, _NoopEmbedder())
            except ValueError as error:
                assert "clean database session" in str(error)
            else:
                raise AssertionError("an active caller transaction must be rejected")

            assert pending in session.new
            assert session.in_transaction()
            session.commit()
            assert session.scalar(select(AppState.catalogue_revision)) == 7
    finally:
        engine.dispose()
