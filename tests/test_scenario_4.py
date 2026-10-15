from __future__ import annotations

from app.agents.purchasing_agent import PurchasingAgent
from app.models.entities import PurchaseOrder


def test_s4_budget_exhaustion(session):
    agent = PurchasingAgent(session)
    agent.reset_fixture("s4", "budget")
    result = agent.run("s4", "budget", execute=True, auto_approve=True)
    assert result.decision.calculation.recommended_raw > 0
    if result.executed:
        for c in result.validation.checks:
            if c.name == "budget_not_negative":
                assert c.passed
        pos = session.query(PurchaseOrder).filter(PurchaseOrder.sku == "OIL-1L", PurchaseOrder.node_id == "NODE-NORTH").all()
        for po in pos:
            assert po.ordered_qty * po.unit_price <= 7000
    else:
        assert result.decision.action in {"escalate", "modify", "alternative_supplier"}
        assert result.outcome in {"ESCALATED", "BLOCKED", "SUCCESS", "PARTIAL_SUCCESS"}


def test_s4_insufficient_storage(session):
    agent = PurchasingAgent(session)
    agent.reset_fixture("s4", "storage")
    result = agent.run("s4", "storage", execute=True, auto_approve=True)
    assert "storage" in result.decision.hard_constraint_violations or result.decision.action in {"modify", "escalate", "alternative_supplier"}
    if result.executed:
        for c in result.validation.checks:
            if c.name == "storage_not_overfilled":
                assert c.passed


def test_s4_moq_conflict(session):
    agent = PurchasingAgent(session)
    agent.reset_fixture("s4", "moq")
    result = agent.run("s4", "moq", execute=True, auto_approve=True)
    assert result.decision.action in {"escalate", "modify", "alternative_supplier"}
    # never silently order 500 if that was not a feasible constrained choice
    if result.executed:
        assert result.validation.outcome in {"SUCCESS", "PARTIAL_SUCCESS"}


def test_s4_supplier_capacity(session):
    agent = PurchasingAgent(session)
    agent.reset_fixture("s4", "capacity")
    result = agent.run("s4", "capacity", execute=True, auto_approve=True)
    assert "supplier_capacity" in result.decision.hard_constraint_violations or result.decision.action in {"modify", "escalate"}


def test_s4_multiple_constraints(session):
    agent = PurchasingAgent(session)
    agent.reset_fixture("s4", "multi")
    result = agent.run("s4", "multi", execute=True, auto_approve=True)
    assert result.decision.action in {"escalate", "modify", "alternative_supplier"}
    assert result.decision.hard_constraint_violations
    assert result.executed is False or result.decision.recommended_qty < result.decision.calculation.recommended_rounded


def test_s4_feasible_alternative_supplier(session):
    agent = PurchasingAgent(session)
    agent.reset_fixture("s4", "feasible_alt")
    result = agent.run("s4", "feasible_alt", execute=True, auto_approve=True)
    assert result.decision.action in {"alternative_supplier", "modify", "split_order"}
    if result.decision.action == "alternative_supplier":
        assert result.decision.supplier_id == "SUP-ALTSOURCE"
        assert result.executed
        assert result.validation.outcome in {"SUCCESS", "PARTIAL_SUCCESS"}


def test_s4_never_bypasses_hard_constraint(session):
    agent = PurchasingAgent(session)
    agent.reset_fixture("s4", "multi")
    result = agent.run("s4", "multi", execute=True, auto_approve=True)
    failed_hard = [c.name for c in result.decision.constraints if c.hard and not c.passed]
    if failed_hard and result.decision.selected_option_id in {None, "original"}:
        assert result.executed is False
