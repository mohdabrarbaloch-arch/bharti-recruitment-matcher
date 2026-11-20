"""Database session and engine setup.

SQLite is the default so the project runs with zero infrastructure. Postgres
works by setting DATABASE_URL, and the only difference in code is the
connect_args and the pool settings.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()

_connect_args = {"check_same_thread": False} if settings.is_sqlite else {}

engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    pool_pre_ping=True,
    future=True,
)

if settings.is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _connection_record):
        """WAL mode and foreign keys.

        WAL lets a reader and a writer work at the same time, which matters
        because the dashboard polls while a recruiter is saving a shortlist.
        Foreign keys are off by default in SQLite and must be enabled per
        connection — without this, deleting a job would orphan its matches.
        """
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    """Declarative base for all models."""


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a session that always closes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables. Fine for this scope; Alembic is the answer for schema
    evolution and is noted as a known limitation in the README."""
    from app import models  # noqa: F401  (import registers the models)

    Base.metadata.create_all(bind=engine)
