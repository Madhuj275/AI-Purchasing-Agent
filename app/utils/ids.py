"""Stable identifiers for runs, actions, and audit correlation."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def idempotency_key(*parts: str) -> str:
    raw = "|".join(str(p) for p in parts)
    return f"idk-{uuid.uuid5(uuid.NAMESPACE_URL, raw).hex}"
