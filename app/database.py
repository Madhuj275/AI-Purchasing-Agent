"""Database engine, sessions, and initialization."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models.entities import Base

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _ensure_sqlite_dir(url: str) -> None:
    if url.startswith("sqlite:///./"):
        Path("data").mkdir(parents=True, exist_ok=True)


def _normalize_database_url(url: str) -> str:
    normalized = url.strip()
    if not normalized:
        raise ValueError("DATABASE_URL must not be empty")
    if normalized.startswith("postgres://"):
        normalized = "postgresql://" + normalized[len("postgres://") :]
    return normalized



def get_engine(url: str | None = None) -> Engine:
    global _engine, _SessionLocal

    settings = get_settings()
    db_url = _normalize_database_url(
        url if url is not None else settings.database_url
    )
    database_backend = make_url(db_url).get_backend_name()

    _ensure_sqlite_dir(db_url)

    connect_args = (
        {"check_same_thread": False}
        if database_backend == "sqlite"
        else {}
    )

    engine_options = {
        "connect_args": connect_args,
        "future": True,
        "pool_pre_ping": True,
    }

    if database_backend == "postgresql":
        engine_options["pool_recycle"] = 300
        engine_options["use_native_hstore"] = False

    _engine = create_engine(db_url, **engine_options)

    if database_backend == "sqlite":

        @event.listens_for(_engine, "connect")
        def _fk_on(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    _SessionLocal = sessionmaker(
        bind=_engine,
        autoflush=False,
        autocommit=False,
        future=True,
    )

    return _engine



def get_session_factory() -> sessionmaker[Session]:
    if _SessionLocal is None:
        get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def init_db(url: str | None = None) -> None:
    engine = get_engine(url)
    Base.metadata.create_all(bind=engine)


def reset_engine() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def reset_db(url: str | None = None) -> None:
    settings = get_settings()
    db_url = _normalize_database_url(url if url is not None else settings.database_url)
    if make_url(db_url).get_backend_name() != "sqlite" and not settings.allow_database_reset:
        raise RuntimeError(
            "Refusing to drop tables in a remote database. Set ALLOW_DATABASE_RESET=true "
            "only when using a disposable database."
        )
    engine = get_engine(db_url)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
