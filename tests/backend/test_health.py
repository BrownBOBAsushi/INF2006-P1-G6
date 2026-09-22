from sqlalchemy import text

def test_health_live(client):
    resp = client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "alive"}

def test_health_ready_when_schema_correct(client):
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready"}

def test_health_ready_fails_when_table_missing(client, db_engine):
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