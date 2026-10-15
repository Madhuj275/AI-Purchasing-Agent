from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.entities import AuditLog
from app.utils.ids import new_id, utcnow


class AuditService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record(
        self,
        *,
        actor: str,
        operation: str,
        entity: str,
        entity_id: str,
        correlation_id: str,
        before: Any = None,
        after: Any = None,
        reason: str | None = None,
    ) -> AuditLog:
        row = AuditLog(
            audit_id=new_id("AUD"),
            actor=actor,
            operation=operation,
            entity=entity,
            entity_id=entity_id,
            before_state=json.dumps(before, default=str) if before is not None else None,
            after_state=json.dumps(after, default=str) if after is not None else None,
            reason=reason,
            correlation_id=correlation_id,
            created_at=utcnow(),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def list_recent(self, limit: int = 50, correlation_id: str | None = None) -> list[AuditLog]:
        q = self.session.query(AuditLog)
        if correlation_id:
            q = q.filter(AuditLog.correlation_id == correlation_id)
        return q.order_by(AuditLog.created_at.desc()).limit(limit).all()
