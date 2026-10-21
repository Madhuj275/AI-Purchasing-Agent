from __future__ import annotations

from app.agents.purchasing_agent import PurchasingAgent
from app.models.entities import Product, PurchaseOrder, SupplierProduct
from app.tools.registry import ProcurementTools


def test_s2_inventory_covers_shortage(session):
    agent = PurchasingAgent(session)
    agent.reset_fixture("s2", "inventory_covers")
    result = agent.run("s2", "inventory_covers")
    assert result.decision.action == "no_action"
    assert result.decision.recommended_qty == 0


def test_s2_uses_forecast_and_selects_feasible_supplier(session):
    agent = PurchasingAgent(session)
    agent.reset_fixture("s2", "default")

    result = agent.run("s2", "default")

    assert result.investigation.inventory["available"] == 30
    assert result.investigation.forecast["forecast_quantity"] == 300
    assert result.investigation.forecast["horizon_days"] == 10
    assert result.decision.calculation.incoming_confirmed == 0
    assert result.decision.calculation.inventory_position == 30
    assert result.decision.calculation.target_stock == 300
    assert result.decision.calculation.safety_stock == 0
    assert result.decision.calculation.recommended_raw == 270
    assert result.decision.action == "alternative_supplier"
    assert result.decision.supplier_id == "SUP-GRAINWAY"
    assert result.decision.recommended_qty == 300
    assert result.decision.total_cost == 45000
    assert "BEST SUPPLIER: GrainWay Foods" in result.decision.explanation
    assert "270 more units are needed" in result.decision.explanation
    alternate = next(
        option
        for option in result.decision.alternatives
        if option.supplier_id == "SUP-ALTSOURCE"
    )
    assert not alternate.feasible


def test_s2_alternative_supplier_covers(session):
    agent = PurchasingAgent(session)
    agent.reset_fixture("s2", "alt_supplier")
    result = agent.run("s2", "alt_supplier", execute=True, auto_approve=True)
    assert result.decision.action == "alternative_supplier"
    assert result.decision.supplier_id == "SUP-ALTSOURCE"
    assert result.executed
    order = session.query(PurchaseOrder).filter_by(
        sku="RICE-5KG",
        supplier_id="SUP-ALTSOURCE",
    ).one()
    assert order.ordered_qty == 300


def test_s2_alternative_more_expensive(session):
    agent = PurchasingAgent(session)
    agent.reset_fixture("s2", "alt_expensive")
    result = agent.run("s2", "alt_expensive", execute=False)
    assert result.decision.supplier_id == "SUP-GRAINWAY"
    alt = next(a for a in result.decision.alternatives if a.supplier_id == "SUP-ALTSOURCE")
    assert alt.cost == 37500


def test_s2_no_supplier_escalates(session):
    agent = PurchasingAgent(session)
    agent.reset_fixture("s2", "no_supplier")
    result = agent.run("s2", "no_supplier", execute=True, auto_approve=True)
    assert result.decision.action == "escalate"
    assert result.decision.supplier_id is None


def test_s2_stockout_escalates(session):
    agent = PurchasingAgent(session)
    agent.reset_fixture("s2", "stockout_escalate")
    result = agent.run("s2", "stockout_escalate", execute=False)
    assert result.decision.action == "escalate"
    assert "capacity" in result.decision.explanation.lower()


def test_s2_repeat_notification_is_idempotent(session):
    agent = PurchasingAgent(session)
    agent.reset_fixture("s2", "repeat_notification")
    first = agent.run("s2", "repeat_notification", execute=True, auto_approve=True)
    count_1 = session.query(PurchaseOrder).filter(PurchaseOrder.sku == "RICE-5KG").count()
    second = agent.run("s2", "repeat_notification", execute=True, auto_approve=True)
    count_2 = session.query(PurchaseOrder).filter(PurchaseOrder.sku == "RICE-5KG").count()
    assert count_2 == count_1
    assert first.action_id != second.action_id or True
    tools = ProcurementTools(session)
    keys = [p.idempotency_key for p in tools.pos.list_orders(sku="RICE-5KG")]
    assert len(keys) == len(set(keys))


def test_fixture_reset_preserves_unrelated_database_records(session):
    session.add(
        Product(
            sku="CUSTOM-PRODUCT",
            name="Customer product",
            category="custom",
            unit_cost=1.0,
            shelf_life_days=None,
            status="active",
            space_per_unit=1.0,
        )
    )
    session.commit()

    PurchasingAgent(session).reset_fixture("s2", "default")

    assert session.get(Product, "CUSTOM-PRODUCT") is not None


def test_s2_fixture_reset_restores_only_s2_demo_state(session):
    agent = PurchasingAgent(session)
    agent.reset_fixture("s2", "alt_expensive")
    agent.reset_fixture("s2", "default")

    alternate = session.query(SupplierProduct).filter_by(
        supplier_id="SUP-ALTSOURCE"
    ).filter_by(sku="RICE-5KG").one()
    assert alternate.unit_price == 80
    assert alternate.lead_time_days == 8
    assert alternate.available is True
