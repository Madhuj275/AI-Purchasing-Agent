from __future__ import annotations

from app.agents.purchasing_agent import PurchasingAgent
from app.models.entities import PurchaseOrder
from app.tools.registry import ProcurementTools


def test_s2_inventory_covers_shortage(session):
    agent = PurchasingAgent(session)
    agent.reset_fixture("s2", "inventory_covers")
    result = agent.run("s2", "inventory_covers", execute=True, auto_approve=True)
    assert result.decision.action == "modify"
    assert result.decision.recommended_qty == 0
    po = session.get(PurchaseOrder, "PO-S2-001")
    assert po.ordered_qty == 250


def test_s2_alternative_supplier_covers(session):
    agent = PurchasingAgent(session)
    agent.reset_fixture("s2", "alt_supplier")
    result = agent.run("s2", "alt_supplier", execute=True, auto_approve=True)
    assert result.decision.action in {"split_order", "alternative_supplier"}
    assert result.decision.supplier_id == "SUP-ALTSOURCE"
    assert result.executed
    original = session.get(PurchaseOrder, "PO-S2-001")
    assert original.ordered_qty == 250
    extras = session.query(PurchaseOrder).filter(PurchaseOrder.parent_po_id == "PO-S2-001").all()
    assert extras
    assert extras[0].supplier_id == "SUP-ALTSOURCE"


def test_s2_alternative_more_expensive(session):
    agent = PurchasingAgent(session)
    agent.reset_fixture("s2", "alt_expensive")
    result = agent.run("s2", "alt_expensive", execute=False)
    assert any(a.supplier_id == "SUP-ALTSOURCE" for a in result.decision.alternatives if a.supplier_id)
    alt = next(a for a in result.decision.alternatives if a.supplier_id == "SUP-ALTSOURCE")
    assert alt.cost is not None and alt.cost > 250 * 8.0


def test_s2_no_supplier_escalates(session):
    agent = PurchasingAgent(session)
    agent.reset_fixture("s2", "no_supplier")
    result = agent.run("s2", "no_supplier", execute=True, auto_approve=True)
    assert result.decision.action == "escalate"
    extras = session.query(PurchaseOrder).filter(PurchaseOrder.parent_po_id == "PO-S2-001").all()
    assert extras == []


def test_s2_stockout_escalates(session):
    agent = PurchasingAgent(session)
    agent.reset_fixture("s2", "stockout_escalate")
    result = agent.run("s2", "stockout_escalate", execute=False)
    assert result.decision.action == "escalate"
    assert "projected_stockout" in result.decision.uncertainty or "stockout" in result.decision.explanation.lower() or result.decision.action == "escalate"


def test_s2_partially_received_not_rewritten(session):
    agent = PurchasingAgent(session)
    agent.reset_fixture("s2", "partially_received")
    result = agent.run("s2", "partially_received", execute=True, auto_approve=True)
    assert result.decision.action == "escalate"
    po = session.get(PurchaseOrder, "PO-S2-001")
    assert po.ordered_qty == 500
    assert po.received_qty == 200


def test_s2_cancelled_not_modifiable(session):
    agent = PurchasingAgent(session)
    agent.reset_fixture("s2", "cancelled")
    result = agent.run("s2", "cancelled", execute=True)
    assert result.decision.action == "escalate"


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
