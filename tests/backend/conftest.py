import os
import pytest
from sqlalchemy import create_engine

@pytest.fixture(scope="session")
def db_engine():
    return create_engine(os.environ["DATABASE_URL"])

@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)