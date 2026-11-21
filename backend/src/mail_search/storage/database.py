"""Connection lifecycle. Offline commands never import this module."""
import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url


def database_engine(url=None):
    value = url or os.environ.get("DATABASE_URL")
    if not value:
        raise ValueError("Set DATABASE_URL for PostgreSQL commands")
    try:
        parsed = make_url(value)
        if parsed.drivername not in ("postgresql", "postgresql+psycopg"):
            raise ValueError
        parsed = parsed.set(drivername="postgresql+psycopg")
    except Exception:
        raise ValueError("DATABASE_URL must be a valid PostgreSQL URL") from None
    return create_engine(parsed, pool_size=5, max_overflow=5, pool_timeout=30,
                         pool_pre_ping=True, hide_parameters=True,
                         connect_args={"connect_timeout": 10})


@contextmanager
def open_database(url=None):
    engine = database_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()
