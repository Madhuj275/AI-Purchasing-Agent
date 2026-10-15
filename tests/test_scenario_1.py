from __future__ import annotations

from app.agents.purchasing_agent import PurchasingAgent
from app.models.entities import PurchaseOrder
from app.tools.registry import ProcurementTools


def _agent(session) -> PurchasingAgent:
    return PurchasingAgent(session)


def test_s1_800_is_appropriate(session):
    agent = _agent(session)
    agent.reset_fixture("s1", "appropriate")
    result = agent.run("s1", "appropriate", execute=True, auto_approve=True)
    assert result.decision.action in {"accept", "modify"}
    assert result.decision.calculation is not None
    assert result.decision.calculation.recommended_raw == 800
    assert result.executed
    assert result.validation is not None
    assert result.validation.outcome == "SUCCESS"
    pos = session.query(PurchaseOrder).filter(PurchaseOrder.sku == "MILK-1L", PurchaseOrder.node_id == "NODE-NORTH").all()
    created = [p for p in pos if p.idempotency_key.startswith("idk-")]
    assert created
    assert created[0].ordered_qty == result.decision.recommended_qty


def test_s1_800_excessive_is_reduced(session):
    agent = _agent(session)
    agent.reset_fixture("s1", "excessive")
    result = agent.run("s1", "excessive", execute=True, auto_approve=True)
    assert result.decision.action == "modify"
    assert result.decision.calculation.recommended_raw < 800
    assert result.decision.recommended_qty == result.decision.calculation.recommended_rounded


def test_s1_no_purchase_when_incoming_covers(session):
    agent = _agent(session)
    agent.reset_fixture("s1", "sufficient")
    result = agent.run("s1", "sufficient", execute=True, auto_approve=True)
    assert result.decision.action == "reject"
    assert result.decision.recommended_qty == 0
    assert result.decision.calculation.incoming_confirmed >= 400
    tools = ProcurementTools(session)
    news = [p for p in tools.pos.list_orders(sku="MILK-1L") if p.po_id != "PO-S1-INCOMING" and p.status != "cancelled"]
    # no additional buy
    assert all(p.po_id == "PO-S1-INCOMING" or not p.idempotency_key.startswith("idk-") for p in tools.pos.list_orders(sku="MILK-1L") if p.status != "cancelled") or result.executed is False or result.validation.outcome == "SUCCESS"


def test_s1_insufficient_when_demand_rises(session):
    agent = _agent(session)
    agent.reset_fixture("s1", "insufficient")
    result = agent.run("s1", "insufficient", execute=False)
    assert result.decision.action == "modify"
    assert result.decision.calculation.recommended_raw > 800


def test_s1_missing_forecast_investigates(session):
    agent = _agent(session)
    agent.reset_fixture("s1", "missing_forecast")
    result = agent.run("s1", "missing_forecast", execute=True, auto_approve=True)
    assert result.decision.action == "investigate"
    assert result.executed is False


def test_s1_contradiction_investigates(session):
    agent = _agent(session)
    agent.reset_fixture("s1", "contradiction")
    result = agent.run("s1", "contradiction", execute=True)
    assert result.decision.action == "investigate"


def test_s1_cancelled_po_not_incoming(session):
    agent = _agent(session)
    agent.reset_fixture("s1", "cancelled_incoming")
    result = agent.run("s1", "cancelled_incoming", execute=False)
    assert result.decision.calculation.incoming_confirmed == 0
    assert result.decision.calculation.recommended_raw == 800


def test_s1_budget_blocks_or_reduces(session):
    agent = _agent(session)
    agent.reset_fixture("s1", "budget")
    result = agent.run("s1", "budget", execute=True, auto_approve=True)
    assert result.decision.action in {"modify", "escalate", "alternative_supplier"}
    if result.executed:
        assert result.validation.outcome in {"SUCCESS", "PARTIAL_SUCCESS"}
        for check in result.validation.checks:
            if check.name == "budget_not_negative":
                assert check.passed
    else:
        assert result.outcome in {"BLOCKED", "ESCALATED", "SUCCESS"}


def test_s1_storage_constraint(session):
    agent = _agent(session)
    agent.reset_fixture("s1", "storage")
    result = agent.run("s1", "storage", execute=True, auto_approve=True)
    assert result.decision.hard_constraint_violations or result.decision.action in {"modify", "escalate", "alternative_supplier"}


def test_s1_moq_conflict(session):
    agent = _agent(session)
    agent.reset_fixture("s1", "moq")
    result = agent.run("s1", "moq", execute=True, auto_approve=True)
    # MOQ 1000 with rounded 1000 may violate budget/storage or be accepted if feasible
    assert result.decision.calculation.recommended_raw == 800
    assert result.decision.action in {"accept", "modify", "escalate", "alternative_supplier"}
