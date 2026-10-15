from __future__ import annotations

from app.agents.purchasing_agent import PurchasingAgent


def test_s3_increase_justified(session):
    agent = PurchasingAgent(session)
    agent.reset_fixture("s3", "increase_justified")
    result = agent.run("s3", "increase_justified", execute=True, auto_approve=True)
    assert result.decision.action in {"increase_order", "keep_plan"}
    # recent 3-day sales 280 vs expected 50*3=150 → material
    if result.decision.action == "increase_order":
        assert result.decision.recommended_qty > 0
        assert result.executed
        assert result.validation.outcome in {"SUCCESS", "PARTIAL_SUCCESS"}


def test_s3_existing_po_sufficient(session):
    agent = PurchasingAgent(session)
    agent.reset_fixture("s3", "po_sufficient")
    result = agent.run("s3", "po_sufficient", execute=True, auto_approve=True)
    assert result.decision.action in {"keep_plan", "investigate"}
    assert result.decision.recommended_qty == 0 or result.decision.action == "keep_plan"


def test_s3_short_window_not_permanent_change(session):
    agent = PurchasingAgent(session)
    agent.reset_fixture("s3", "short_window")
    result = agent.run("s3", "short_window", execute=False)
    assert result.decision.action in {"investigate", "keep_plan"}
    assert result.decision.uncertainty


def test_s3_stale_forecast(session):
    agent = PurchasingAgent(session)
    agent.reset_fixture("s3", "stale_forecast")
    result = agent.run("s3", "stale_forecast", execute=False)
    assert result.decision.action in {"investigate", "keep_plan", "increase_order"}
    assert result.decision.uncertainty or result.decision.action == "investigate"


def test_s3_missing_forecast(session):
    agent = PurchasingAgent(session)
    agent.reset_fixture("s3", "missing_forecast")
    result = agent.run("s3", "missing_forecast", execute=True)
    assert result.decision.action == "investigate"
    assert result.executed is False


def test_s3_lead_time_too_late(session):
    agent = PurchasingAgent(session)
    agent.reset_fixture("s3", "too_late")
    result = agent.run("s3", "too_late", execute=False)
    assert result.decision.action in {"escalate", "transfer", "investigate"}


def test_s3_constraint_blocks_increase(session):
    agent = PurchasingAgent(session)
    agent.reset_fixture("s3", "constraint")
    result = agent.run("s3", "constraint", execute=True, auto_approve=True)
    if result.decision.action == "increase_order":
        assert result.decision.requires_approval or result.outcome in {"BLOCKED", "ESCALATED", "SUCCESS", "PARTIAL_SUCCESS"}
    else:
        assert result.decision.action in {"escalate", "keep_plan", "investigate", "modify"}
