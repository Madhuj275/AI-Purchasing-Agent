from __future__ import annotations

import pytest

from app.config import get_settings
from app.database import _normalize_database_url, reset_db, reset_engine


def test_normalize_legacy_postgres_url_scheme():
    assert _normalize_database_url("postgres://user:pass@host/db") == "postgresql://user:pass@host/db"


def test_remote_database_reset_is_disabled_by_default(monkeypatch):
    monkeypatch.setenv("ALLOW_DATABASE_RESET", "false")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="Refusing to drop tables in a remote database"):
            reset_db("postgresql://user:pass@host/db")
    finally:
        get_settings.cache_clear()
        reset_engine()