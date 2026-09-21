"""Team-triggered catalogue import (not a public endpoint).

    python -m app.catalogue.import_jobs --file data/synthetic_jobs.json --dry-run
    python -m app.catalogue.import_jobs --file data/synthetic_jobs.json

Run offline or in a maintenance window, not beside student traffic. Needs DATABASE_URL (SQLAlchemy URL such as
postgresql+psycopg://...) and the locally cached embedding model (`python -m app.processing.embeddings --download`
once). Dry-run validates the whole file and, when DATABASE_URL is set, compares it with the database; it prints
counts and error locations only, never job descriptions. Exit status: 0 ok, 1 invalid batch, 2 usage/runtime error.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from app.catalogue.importer import import_catalogue
from app.catalogue.schema import DEFAULT_ALLOWED_SOURCES


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Import a prepared internship catalogue (JSON)")
    ap.add_argument("--file", required=True, type=Path)
    ap.add_argument("--dry-run", action="store_true", help="validate and plan; write nothing")
    ap.add_argument("--allow-source", action="append", default=[],
                    help="additional provenance-labelled source name (default: SYNTHETIC only)")
    args = ap.parse_args(argv)
    try:
        raw = args.file.read_bytes()
    except OSError:
        print("error: cannot read file", file=sys.stderr)
        return 2
    allowed = tuple(DEFAULT_ALLOWED_SOURCES) + tuple(args.allow_source)

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    db_url = os.environ.get("DATABASE_URL")
    if not args.dry_run and not db_url:
        print("error: DATABASE_URL is required for a real import", file=sys.stderr)
        return 2
    embedder = None
    from app.processing.embeddings import EmbeddingModel
    try:
        embedder = EmbeddingModel()          # local cache only; no network
    except Exception as exc:                 # noqa: BLE001
        if not args.dry_run:
            print(f"error: embedding model unavailable ({type(exc).__name__}); run --download once", file=sys.stderr)
            return 2
    session = Session(create_engine(db_url)) if db_url else None
    try:
        s = import_catalogue(session, raw, embedder, allowed_sources=allowed, dry_run=args.dry_run)
    finally:
        if session is not None:
            session.close()
    mode = "DRY RUN" if s.dry_run else "IMPORT"
    if not s.ok:
        print(f"{mode} INVALID: {len(s.issues)} issue(s); nothing written")
        for i in s.issues[:50]:
            print(f"  job[{i.index}] id={i.source_job_id!r} field={i.field} code={i.code}")
        return 1
    print(f"{mode} ok: created={s.created} updated={s.updated} unchanged={s.unchanged} "
          f"embeddings_computed={s.embeddings_computed} embeddings_reused={s.embeddings_reused} "
          f"requirements_deduplicated={s.requirements_deduplicated} catalogue_revision={s.catalogue_revision}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
