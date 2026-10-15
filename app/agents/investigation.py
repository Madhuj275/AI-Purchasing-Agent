"""Evidence gathering for purchasing scenarios."""

from __future__ import annotations

from typing import Any

from app.schemas.domain import InvestigationReport
from app.seed.demo_data import SCENARIO_EVENTS
from app.tools.registry import ProcurementTools


def investigate(tools: ProcurementTools, scenario_id: str, fixture_key: str, event: dict[str, Any] | None = None) -> InvestigationReport:
    meta = SCENARIO_EVENTS[scenario_id]
    payload = dict(meta)
    if event:
        payload.update(event)
    sku = payload["sku"]
    node_id = payload["node_id"]
    product = tools.get_product_details(sku)
    node = tools.inventory.get_node(node_id)
    inventory = tools.get_inventory_by_node(sku, node_id)
    forecast = tools.get_demand_forecast(sku, node_id)
    sales = tools.get_actual_sales(sku, node_id)
    pos = tools.get_open_purchase_orders(sku, node_id)
    if payload.get("po_id"):
        detail = tools.get_purchase_order_details(payload["po_id"])
        if detail and detail not in pos:
            pos = [detail] + pos
    suppliers = tools.search_alternative_suppliers(sku)
    primary = None
    if suppliers:
        primary = suppliers[0]
    category = product["category"] if product else "grocery"
    budget_row = tools.budget.get(node_id, category)
    budget = None
    if budget_row:
        budget = {
            "period": budget_row.period,
            "node_id": budget_row.node_id,
            "category": budget_row.category,
            "allocated": budget_row.allocated,
            "committed": budget_row.committed,
            "remaining": budget_row.remaining,
        }
    storage_row = tools.storage.get(node_id)
    storage = None
    if storage_row:
        storage = {
            "node_id": storage_row.node_id,
            "total_capacity": storage_row.total_capacity,
            "current_utilization": storage_row.current_utilization,
            "reserved_space": storage_row.reserved_space,
            "free": tools.storage.free_space(node_id),
        }
    missing: list[str] = []
    stale: list[str] = []
    contradictions: list[str] = []
    if not product:
        missing.append("product")
    if not inventory:
        missing.append("inventory")
    if not forecast:
        missing.append("forecast")
    elif forecast.get("stale"):
        stale.append("forecast")
    if not suppliers:
        missing.append("supplier")
    if inventory and inventory["available"] < 0:
        contradictions.append("Reserved inventory exceeds on-hand stock")
    if inventory and inventory["on_hand"] < 0:
        contradictions.append("Negative on-hand inventory")
    node_dict = None
    if node:
        node_dict = {
            "node_id": node.node_id,
            "name": node.name,
            "location": node.location,
            "storage_capacity": node.storage_capacity,
            "current_utilization": node.current_utilization,
        }
    return InvestigationReport(
        scenario_id=scenario_id,
        fixture_key=fixture_key,
        event=payload,
        product=product,
        node=node_dict,
        inventory=inventory,
        forecast=forecast,
        sales=sales,
        purchase_orders=pos,
        suppliers=suppliers,
        budget=budget,
        storage=storage,
        missing=missing,
        stale=stale,
        contradictions=contradictions,
        data_freshness={"forecast_stale": bool(forecast and forecast.get("stale")), "primary_supplier": primary},
    )
