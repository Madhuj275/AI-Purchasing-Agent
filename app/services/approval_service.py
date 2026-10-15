from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.entities import ActionRecord, HumanApproval
from app.utils.ids import new_id, utcnow


def fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ApprovalService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()

    def requires_approval(self, total_cost: float, uncertain: bool = False, exception: bool = False) -> bool:
        if exception:
            return True
        if uncertain:
            return True
        return total_cost >= self.settings.approval_threshold

    def list_pending(self) -> list[HumanApproval]:
        return (
            self.session.query(HumanApproval)
            .filter(HumanApproval.status == "pending")
            .order_by(HumanApproval.created_at)
            .all()
        )

    def list_all(self) -> list[HumanApproval]:
        return self.session.query(HumanApproval).order_by(HumanApproval.created_at.desc()).all()

    def get(self, approval_id: str) -> HumanApproval | None:
        return self.session.get(HumanApproval, approval_id)

    def create(self, action: ActionRecord, payload: dict[str, Any]) -> HumanApproval:
        row = HumanApproval(
            approval_id=new_id("APR"),
            action_id=action.action_id,
            run_id=action.run_id,
            status="pending",
            approver=None,
            decision=None,
            action_fingerprint=fingerprint(payload),
            reason=None,
            created_at=utcnow(),
            decided_at=None,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def decide(self, approval_id: str, approved: bool, approver: str, reason: str, current_payload: dict[str, Any]) -> HumanApproval:
        row = self.get(approval_id)
        if row is None:
            raise ValueError("Approval not found")
        if row.status != "pending":
            raise ValueError("Approval already decided")
        current_fp = fingerprint(current_payload)
        if current_fp != row.action_fingerprint:
            row.status = "invalidated"
            row.reason = "Material fields changed after approval request; reapproval required"
            row.decided_at = utcnow()
            self.session.flush()
            raise ValueError("Approval invalidated because the proposed action changed")
        row.status = "approved" if approved else "rejected"
        row.decision = "approve" if approved else "reject"
        row.approver = approver
        row.reason = reason
        row.decided_at = utcnow()
        self.session.flush()
        return row

    def is_valid_for_action(self, action: ActionRecord, payload: dict[str, Any]) -> bool:
        row = (
            self.session.query(HumanApproval)
            .filter(HumanApproval.action_id == action.action_id, HumanApproval.status == "approved")
            .order_by(HumanApproval.decided_at.desc())
            .first()
        )
        if row is None:
            return False
        return row.action_fingerprint == fingerprint(payload)
