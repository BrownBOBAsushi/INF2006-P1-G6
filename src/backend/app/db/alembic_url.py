"""Helpers for putting SQLAlchemy URLs into Alembic's ConfigParser settings."""


def set_database_url(config, database_url: str) -> None:
    """Escape ConfigParser interpolation while retaining URL percent escapes."""
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
