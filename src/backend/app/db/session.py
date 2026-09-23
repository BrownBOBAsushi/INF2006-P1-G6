import os
from sqlalchemy import create_engine
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

engine = create_engine(os.environ["DATABASE_URL"])


def configure_transaction_timeouts(db_engine) -> None:
    """Apply bounded statement and lock waits to every application connection."""
    if db_engine.url.get_backend_name() != "postgresql":
        return

    def _set_timeouts(connection):
        # `SET LOCAL` is transaction-scoped. The begin hook runs after
        # SQLAlchemy starts every transaction, so pool reset/rollback cannot
        # silently remove the limits.
        connection.exec_driver_sql("SET LOCAL statement_timeout = '5s'")
        connection.exec_driver_sql("SET LOCAL lock_timeout = '5s'")

    event.listen(db_engine, "begin", _set_timeouts)


configure_transaction_timeouts(engine)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
