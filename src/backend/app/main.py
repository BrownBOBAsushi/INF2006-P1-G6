from fastapi import FastAPI, Response
from sqlalchemy import create_engine, text
import os
from app.auth.router import router as auth_router
from app.api.me import router as me_router
from app.api.resume import router as resume_router
app = FastAPI()
app.include_router(auth_router)
app.include_router(me_router)
app.include_router(resume_router)


engine = create_engine(os.environ["DATABASE_URL"])



REQUIRED_TABLES = {"users", "sessions", "resume_profiles", "resume_chunks"}
EXPECTED_EMBEDDING_DIM = 384

@app.get("/health/live")
def live():
    return {"status": "alive"}

@app.get("/health/ready")
def ready():
    try:
        with engine.connect() as conn:
            # 1. Basic connectivity
            conn.execute(text("SELECT 1"))

            # 2. Required schema exists
            existing_tables = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public' AND table_name = ANY(:names)"
                    ),
                    {"names": list(REQUIRED_TABLES)},
                )
            }
            if existing_tables != REQUIRED_TABLES:
                return Response(status_code=503)

            # 3. vector extension enabled
            has_vector_ext = conn.execute(
                text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            ).first()
            if not has_vector_ext:
                return Response(status_code=503)

            # 4. resume_chunks.embedding dimension matches expected model output
            dim = conn.execute(
                text(
                    "SELECT atttypmod FROM pg_attribute "
                    "WHERE attrelid = 'resume_chunks'::regclass "
                    "AND attname = 'embedding'"
                )
            ).scalar()
            if dim != EXPECTED_EMBEDDING_DIM:
                return Response(status_code=503)

        # Model-cache readiness (embedding model actually loaded/warm) is
        # Chuying's processing component — not yet available to check here.
        # Wire this in once her interface exposes a model-loaded signal.

        return {"status": "ready"}
    except Exception:
        return Response(status_code=503)