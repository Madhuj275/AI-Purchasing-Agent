from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_session_factory, init_db, reset_engine
from app.seed.demo_data import seed_database


@pytest.fixture
def db_url(tmp_path, monkeypatch) -> str:
    url = f"sqlite:///{tmp_path.as_posix()}/test.db"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    reset_engine()
    init_db(url)
    return url


@pytest.fixture
def session(db_url: str) -> Generator[Session, None, None]:
    sess = get_session_factory()()
    seed_database(sess)
    try:
        yield sess
    finally:
        sess.close()


@pytest.fixture
def client(db_url: str) -> Generator[TestClient, None, None]:
    from app.main import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c
