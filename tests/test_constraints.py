from __future__ import annotations

import pytest

from app.agents.decision_engine import calculate_replenishment, check_hard_constraints, max_feasible_qty, round_to_supplier_rules
from app.agents.investigation import investigate
from app.agents.langchain_agent import AgentDecision, apply_agent_decision
from app.agents.planner import plan
from app.agents.purchasing_agent import PurchasingAgent
from app.services.approval_service import ApprovalService, fingerprint
from app.tools.registry import ProcurementTools


def test_replenishment_formula():
    calc = calculate_replenishment(
        sku="X",
        node_id="N",
        on_hand=100,
        reserved=20,
        incoming_confirmed=50,
        incoming_unconfirmed=999,
        daily_demand=10,
        lead_time_days=3,
        review_horizon_days=1,
        safety_stock_days=1,
        moq=10,
        order_multiple=5,
    )
    assert calc.available == 80
    assert calc.inventory_position == 130
    assert calc.protection_period_days == 4
    assert calc.forecast_demand_protection == 40
    assert calc.safety_stock == 10
    assert calc.target_stock == 50
    assert calc.recommended_raw == 0
    assert calc.incoming_unconfirmed == 999


def test_rounding_and_no_silent_overbuy():
    assert round_to_supplier_rules(120, 100, 50) == 150
    qty = max_feasible_qty(
        unit_price=10,
        space_per_unit=1,
        budget_remaining=100,
        storage_free=1000,
        moq=20,
        order_multiple=10,
        supplier_capacity=50,
        desired=150,
    )
    # budget allows 10 units, MOQ 20 → infeasible 0 rather than silent extra
    assert qty == 0


def test_hard_constraints_fail_closed():
    checks = check_hard_constraints(
        qty=100,
        unit_price=5,
        sku="X",
        space_per_unit=1,
        budget_remaining=10,
        storage_free=10,
        moq=200,
        order_multiple=50,
        supplier_capacity=40,
        supplier_available=False,
        product_active=False,
    )
    names = {c.name: c.passed for c in checks}
    assert names["budget"] is False
    assert names["storage"] is False
    assert names["moq"] is False
    assert names["supplier_capacity"] is False
    assert names["supplier_available"] is False
    assert names["product_availability"] is False


def test_approval_fingerprint_invalidation(session):
    svc = ApprovalService(session)
    a = {"qty": 10, "supplier_id": "S"}
    b = {"qty": 11, "supplier_id": "S"}
    assert fingerprint(a) != fingerprint(b)
    assert svc.requires_approval(10) is False
    assert svc.requires_approval(500) is True


def test_invalid_quantity_zero_cost(session):
    checks = check_hard_constraints(
        qty=0,
        unit_price=1.1,
        sku="MILK-1L",
        space_per_unit=1,
        budget_remaining=100,
        storage_free=100,
        moq=100,
        order_multiple=50,
        supplier_capacity=5000,
        supplier_available=True,
        product_active=True,
    )
    assert all(c.passed for c in checks if c.name in {"moq", "order_multiple", "budget", "storage"})


def test_llm_fallback_mode(session):
    agent = PurchasingAgent(session)
    agent.reset_fixture("s1", "appropriate")
    result = agent.run("s1", "appropriate", execute=False)
    assert result.reasoning_mode == "deterministic"
    assert "deterministic fallback" in result.explanation.lower() or result.reasoning_mode == "deterministic"


def test_langchain_decision_recomputes_cost_and_checks_constraints(session):
    PurchasingAgent(session).reset_fixture("s1", "appropriate")
    tools = ProcurementTools(session)
    investigation = investigate(tools, "s1", "appropriate")
    baseline = plan(tools, investigation)
    supplier = investigation.suppliers[0]
    proposal = AgentDecision(
        action="accept",
        recommended_qty=baseline.recommended_qty,
        supplier_id=supplier["supplier_id"],
        explanation="The investigation supports this replenishment order.",
    )

    decision = apply_agent_decision(tools, investigation, baseline, proposal)

    assert decision.reasoning_mode == "langchain-agent"
    assert decision.unit_price == supplier["unit_price"]
    assert decision.total_cost == decision.recommended_qty * supplier["unit_price"]
    assert all(check.passed for check in decision.constraints if check.hard)


def test_langchain_decision_cannot_exceed_evidence_based_quantity(session):
    PurchasingAgent(session).reset_fixture("s1", "appropriate")
    tools = ProcurementTools(session)
    investigation = investigate(tools, "s1", "appropriate")
    baseline = plan(tools, investigation)
    supplier = investigation.suppliers[0]
    proposal = AgentDecision(
        action="accept",
        recommended_qty=baseline.recommended_qty + 1,
        supplier_id=supplier["supplier_id"],
        explanation="Propose purchasing more than the calculated recommendation.",
    )

    with pytest.raises(ValueError, match="exceeds the evidence-based recommendation"):
        apply_agent_decision(tools, investigation, baseline, proposal)
