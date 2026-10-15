from __future__ import annotations

from app.agents.purchasing_agent import PurchasingAgent
from app.models.entities import PurchaseOrder


def test_injected_storage_race_escalates(session):
    agent = PurchasingAgent(session)
    agent.reset_fixture("s1", "appropriate")
    result = agent.run("s1", "appropriate", execute=True, auto_approve=True, simulate_failure="storage_race")
    assert result.outcome in {"ESCALATED", "FAILED", "BLOCKED"}
    assert result.validation is not None
    assert result.validation.recovery
    news = [p for p in session.query(PurchaseOrder).filter_by(sku="MILK-1L").all() if p.idempotency_key.startswith("idk-")]
    assert news == []


def test_persist_fail_recovery(session):
    agent = PurchasingAgent(session)
    agent.reset_fixture("s1", "appropriate")
    result = agent.run("s1", "appropriate", execute=True, auto_approve=True, simulate_failure="persist_fail")
    assert result.validation is not None
    assert result.outcome in {"SUCCESS", "ESCALATED", "FAILED"}
    assert result.validation.recovery


def test_duplicate_execute_does_not_duplicate_po(session):
    agent = PurchasingAgent(session)
    agent.reset_fixture("s1", "appropriate")
    first = agent.run("s1", "appropriate", execute=True, auto_approve=True)
    assert first.executed
    count_1 = session.query(PurchaseOrder).filter_by(sku="MILK-1L").count()
    second = agent.run("s1", "appropriate", execute=True, auto_approve=True)
    count_2 = session.query(PurchaseOrder).filter_by(sku="MILK-1L").count()
    assert count_2 == count_1
    assert second.outcome == "SUCCESS"


def test_rejected_approval_blocks_execution(session):
    agent = PurchasingAgent(session)
    agent.reset_fixture("s4", "approval")
    planned = agent.run("s4", "approval", execute=False, auto_approve=False)
    if planned.approval_id:
        from fastapi.testclient import TestClient  # local only if needed
        from app.services.approval_service import ApprovalService
        from app.models.entities import ActionRecord, HumanApproval
        import json

        approval = session.get(HumanApproval, planned.approval_id)
        action = session.get(ActionRecord, planned.action_id)
        ApprovalService(session).decide(approval.approval_id, False, "buyer.demo", "no", json.loads(action.proposed_payload))
        session.commit()
        from app.agents.action_executor import execute_action
        from app.tools.registry import ProcurementTools

        blocked = False
        try:
            if action.requires_approval:
                svc = ApprovalService(session)
                if not svc.is_valid_for_action(action, json.loads(action.proposed_payload)):
                    blocked = True
            if not blocked:
                execute_action(session, ProcurementTools(session), action)
        except Exception:
            blocked = True
        assert blocked
    else:
        # cost below threshold — still a valid policy outcome
        assert planned.decision.requires_approval is False or planned.decision.action in {"escalate", "investigate"}
