from fastapi import FastAPI
from sqlalchemy import create_engine, text
import os

app = FastAPI()
engine = create_engine(os.environ["DATABASE_URL"])

@app.get("/health/live")
def live():
    return {"status": "alive"}

@app.get("/health/ready")
def ready():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception:
        from fastapi import Response
        return Response(status_code=503)