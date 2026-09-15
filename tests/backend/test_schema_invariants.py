from sqlalchemy import text

REQUIRED_TABLES = {"users", "sessions", "resume_profiles", "resume_chunks"}

def test_all_required_tables_exist(db_engine):
    with db_engine.connect() as conn:
        existing = {
            row[0] for row in conn.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
            )
        }
    assert REQUIRED_TABLES.issubset(existing)

def test_vector_extension_enabled(db_engine):
    with db_engine.connect() as conn:
        result = conn.execute(text("SELECT 1 FROM pg_extension WHERE extname='vector'")).first()
    assert result is not None

def test_resume_chunks_embedding_dimension(db_engine):
    with db_engine.connect() as conn:
        dim = conn.execute(text(
            "SELECT atttypmod FROM pg_attribute WHERE attrelid='resume_chunks'::regclass AND attname='embedding'"
        )).scalar()
    assert dim == 384

def test_users_resume_revision_has_db_default(db_engine):
    with db_engine.connect() as conn:
        default = conn.execute(text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_name='users' AND column_name='resume_revision'"
        )).scalar()
    assert default is not None

def test_sessions_indexes_exist(db_engine):
    with db_engine.connect() as conn:
        indexes = {
            row[0] for row in conn.execute(text(
                "SELECT indexname FROM pg_indexes WHERE tablename='sessions'"
            ))
        }
    assert {"ix_sessions_user_id", "ix_sessions_expires_at"}.issubset(indexes)


def test_resume_chunks_user_id_indexed(db_engine):
    with db_engine.connect() as conn:
        indexes = {
            row[0] for row in conn.execute(text(
                "SELECT indexname FROM pg_indexes WHERE tablename='resume_chunks'"
            ))
        }
    assert "ix_resume_chunks_user_id" in indexes

def test_save_operations_composite_pk(db_engine):
    with db_engine.connect() as conn:
        pk_cols = [
            row[0] for row in conn.execute(text(
                "SELECT a.attname FROM pg_index i "
                "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
                "WHERE i.indrelid = 'save_operations'::regclass AND i.indisprimary "
                "ORDER BY array_position(i.indkey, a.attnum)"
            ))
        ]
    assert pk_cols == ["user_id", "operation_id"]

def test_save_operations_state_check_constraint(db_engine):
    with db_engine.connect() as conn:
        result = conn.execute(text(
            "SELECT conname FROM pg_constraint WHERE conname = 'ck_save_operations_state'"
        )).first()
    assert result is not None

def test_save_operations_expires_at_indexed(db_engine):
    with db_engine.connect() as conn:
        indexes = {
            row[0] for row in conn.execute(text(
                "SELECT indexname FROM pg_indexes WHERE tablename='save_operations'"
            ))
        }
    assert "ix_save_operations_expires_at" in indexes

def test_save_operations_fk_to_users_cascade(db_engine):
    with db_engine.connect() as conn:
        result = conn.execute(text(
            "SELECT confdeltype FROM pg_constraint "
            "WHERE conname = 'save_operations_user_id_fkey'"
        )).scalar()
    assert result == "c"