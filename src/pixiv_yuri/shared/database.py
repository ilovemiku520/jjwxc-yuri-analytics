"""SQLAlchemy foundation for the PostgreSQL source-of-truth database."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import BigInteger, Integer, MetaData, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# SQLite is used only for fast repository tests. PostgreSQL remains the target database.
PRIMARY_KEY_TYPE = BigInteger().with_variant(Integer, "sqlite")


class Base(DeclarativeBase):
    """Base for all versioned SQLAlchemy models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utc_now() -> datetime:
    """Return one timezone-aware UTC timestamp for application-side defaults."""
    return datetime.now(UTC)


def build_engine(database_url: str, *, echo: bool = False) -> Engine:
    """Create a conservative synchronous engine without logging credentials."""
    return create_engine(normalize_database_url(database_url), echo=echo, pool_pre_ping=True)


def normalize_database_url(database_url: str) -> str:
    """Select psycopg 3 for provider-issued generic PostgreSQL URLs."""
    if database_url.startswith("postgres://"):
        return "postgresql+psycopg://" + database_url.removeprefix("postgres://")
    if database_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + database_url.removeprefix("postgresql://")
    return database_url


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create sessions with explicit transaction and expiry behavior."""
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Commit one application transaction or roll it back on failure."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
