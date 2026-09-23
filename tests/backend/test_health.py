from sqlalchemy import text

def test_health_live(client):
    resp = client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "alive"}

def test_health_ready_when_schema_correct(client, monkeypatch):
    monkeypatch.setattr("app.main.processing_service.is_ready", lambda: True)
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready"}

def test_health_ready_fails_when_table_missing(client, db_engine, monkeypatch):
    monkeypatch.setattr("app.main.processing_service.is_ready", lambda: True)
    with db_engine.connect() as conn:
        conn.execute(text("ALTER TABLE sessions RENAME TO sessions_tmp"))
        conn.commit()
    try:
        resp = client.get("/health/ready")
        assert resp.status_code == 503
    finally:
        with db_engine.connect() as conn:
            conn.execute(text("ALTER TABLE sessions_tmp RENAME TO sessions"))
            conn.commit()


def test_health_ready_fails_closed_when_processing_recovery_failed(client, monkeypatch):
    monkeypatch.setattr("app.main.processing_service.is_ready", lambda: True)
    monkeypatch.setattr("app.main.recovery_failed", True)
    resp = client.get("/health/ready")
    assert resp.status_code == 503
