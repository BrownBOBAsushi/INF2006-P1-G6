from fastapi import FastAPI, Response
from sqlalchemy import create_engine, text
import os

from fastapi.middleware.cors import CORSMiddleware
from app.auth.router import router as auth_router
from app.api.me import router as me_router
from app.api.resume import router as resume_router
from app.core.config import settings

if os.environ.get("TEST_AUTH_BYPASS") == "true" and not settings.is_dev:
    raise RuntimeError(
        "TEST_AUTH_BYPASS is enabled but the APP_ENV is not 'development'. "
        "Refusing to start - this would disable real authentication in a"
        "non-test environment. "
        
    )

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ["APP_ORIGIN"]],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)

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
            conn.execute(text("SELECT 1"))

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

            has_vector_ext = conn.execute(
                text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            ).first()
            if not has_vector_ext:
                return Response(status_code=503)

            dim = conn.execute(
                text(
                    "SELECT atttypmod FROM pg_attribute "
                    "WHERE attrelid = 'resume_chunks'::regclass "
                    "AND attname = 'embedding'"
                )
            ).scalar()
            if dim != EXPECTED_EMBEDDING_DIM:
                return Response(status_code=503)

        return {"status": "ready"}
    except Exception:
        return Response(status_code=503)