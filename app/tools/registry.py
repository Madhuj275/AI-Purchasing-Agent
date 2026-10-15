"""Explicit tool functions. Read-only tools never write; mutating tools persist."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.agents.decision_engine import calculate_replenishment, check_hard_constraints, stockout_estimate
from app.services.approval_service import ApprovalService
from app.services.audit_service import AuditService
from app.services.budget_service import BudgetService
from app.services.demand_service import DemandService
from app.services.inventory_service import InventoryService
from app.services.purchase_order_service import PurchaseOrderService
from app.services.storage_service import StorageService
from app.services.supplier_service import SupplierService


class ProcurementTools:
    """Typed tools used by the purchasing agent."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.inventory = InventoryService(session)
        self.demand = DemandService(session)
        self.suppliers = SupplierService(session)
        self.pos = PurchaseOrderService(session)
        self.budget = BudgetService(session)
        self.storage = StorageService(session)
        self.approvals = ApprovalService(session)
        self.audit = AuditService(session)

    # --- read-only ---
    def get_product_details(self, sku: str) -> dict[str, Any] | None:
        p = self.inventory.get_product(sku)
        if not p:
            return None
        return {
            "sku": p.sku,
            "name": p.name,
            "category": p.category,
            "unit_cost": p.unit_cost,
            "shelf_life_days": p.shelf_life_days,
            "status": p.status,
            "space_per_unit": p.space_per_unit,
        }

    def get_inventory_by_node(self, sku: str, node_id: str) -> dict[str, Any] | None:
        row = self.inventory.get_inventory(sku, node_id)
        if not row:
            return None
        return {
            "sku": row.sku,
            "node_id": row.node_id,
            "on_hand": row.on_hand,
            "reserved": row.reserved,
            "available": row.on_hand - row.reserved,
            "last_updated": row.last_updated.isoformat() if row.last_updated else None,
        }

    def get_demand_forecast(self, sku: str, node_id: str) -> dict[str, Any] | None:
        f = self.demand.get_forecast(sku, node_id)
        if not f:
            return None
        return {
            "sku": f.sku,
            "node_id": f.node_id,
            "horizon_days": f.horizon_days,
            "forecast_quantity": f.forecast_quantity,
            "daily_demand": f.daily_demand,
            "forecast_timestamp": f.forecast_timestamp.isoformat(),
            "stale": self.demand.is_stale(f),
            "source": f.source,
        }

    def get_actual_sales(self, sku: str, node_id: str) -> list[dict[str, Any]]:
        rows = self.demand.get_sales(sku, node_id)
        return [
            {
                "sku": s.sku,
                "node_id": s.node_id,
                "period_start": s.period_start.isoformat(),
                "period_end": s.period_end.isoformat(),
                "quantity_sold": s.quantity_sold,
            }
            for s in rows
        ]

    def get_open_purchase_orders(self, sku: str, node_id: str) -> list[dict[str, Any]]:
        return [self.pos.to_dict(p) for p in self.pos.list_orders(sku=sku, node_id=node_id, open_only=True)]

    def get_purchase_order_details(self, po_id: str) -> dict[str, Any] | None:
        po = self.pos.get(po_id)
        return self.pos.to_dict(po) if po else None

    def get_supplier_details(self, supplier_id: str, sku: str) -> dict[str, Any] | None:
        s = self.suppliers.get(supplier_id)
        o = self.suppliers.offering(supplier_id, sku)
        if not s or not o:
            return None
        committed = self.pos.committed_qty_for_supplier(supplier_id, sku)
        return {
            "supplier_id": s.supplier_id,
            "name": s.name,
            "active": s.active,
            "reliability_score": s.reliability_score,
            "unit_price": o.unit_price,
            "lead_time_days": o.lead_time_days,
            "min_order_qty": o.min_order_qty,
            "order_multiple": o.order_multiple,
            "capacity": o.capacity,
            "remaining_capacity": max(0, o.capacity - committed),
            "available": o.available,
        }

    def search_alternative_suppliers(self, sku: str, exclude: str | None = None) -> list[dict[str, Any]]:
        out = []
        for o in self.suppliers.offerings_for_sku(sku):
            if exclude and o.supplier_id == exclude:
                continue
            detail = self.get_supplier_details(o.supplier_id, sku)
            if detail:
                out.append(detail)
        out.sort(key=lambda d: (d["lead_time_days"], d["unit_price"], d["supplier_id"]))
        return out

    def check_supplier_capacity(self, supplier_id: str, sku: str, qty: int) -> dict[str, Any]:
        detail = self.get_supplier_details(supplier_id, sku)
        remaining = 0 if not detail else detail["remaining_capacity"]
        return {"ok": qty <= remaining, "remaining": remaining, "requested": qty}

    def check_budget(self, node_id: str, category: str, amount: float) -> dict[str, Any]:
        row = self.budget.get(node_id, category)
        remaining = row.remaining if row else None
        return {
            "ok": remaining is not None and amount <= remaining + 1e-9,
            "remaining": remaining,
            "requested": amount,
            "allocated": row.allocated if row else None,
            "committed": row.committed if row else None,
        }

    def check_storage_capacity(self, node_id: str, sku: str, qty: int) -> dict[str, Any]:
        free = self.storage.free_space(node_id)
        need = self.storage.required_space(sku, qty)
        return {"ok": need <= free + 1e-9, "free": free, "required": need}

    def calculate_order_cost(self, qty: int, unit_price: float) -> float:
        return round(qty * unit_price, 2)

    def calculate_stockout_risk(self, sku: str, node_id: str, daily_demand: float | None) -> dict[str, Any]:
        inv = self.get_inventory_by_node(sku, node_id) or {"available": 0}
        incoming = self.pos.incoming_confirmed(sku, node_id)
        return stockout_estimate(inv.get("available", 0), incoming, daily_demand)

    def calculate_replenishment(self, sku: str, node_id: str, supplier_id: str) -> dict[str, Any]:
        inv = self.get_inventory_by_node(sku, node_id)
        fc = self.get_demand_forecast(sku, node_id)
        sup = self.get_supplier_details(supplier_id, sku)
        if not inv or not sup:
            raise ValueError("Cannot calculate replenishment without inventory and supplier")
        missing = []
        stale = []
        if not fc:
            missing.append("forecast")
        elif fc["stale"]:
            stale.append("forecast")
        calc = calculate_replenishment(
            sku=sku,
            node_id=node_id,
            on_hand=inv["on_hand"],
            reserved=inv["reserved"],
            incoming_confirmed=self.pos.incoming_confirmed(sku, node_id),
            incoming_unconfirmed=self.pos.incoming_unconfirmed(sku, node_id),
            daily_demand=None if not fc else fc["daily_demand"],
            lead_time_days=sup["lead_time_days"],
            moq=sup["min_order_qty"],
            order_multiple=sup["order_multiple"],
            missing=missing,
            stale=stale,
        )
        return calc.model_dump()

    def constraint_bundle(
        self, sku: str, node_id: str, supplier_id: str, qty: int
    ) -> list[dict[str, Any]]:
        product = self.get_product_details(sku)
        sup = self.get_supplier_details(supplier_id, sku)
        if not product or not sup:
            return [
                {
                    "name": "data",
                    "passed": False,
                    "hard": True,
                    "detail": "Missing product or supplier",
                    "value": None,
                    "limit": None,
                }
            ]
        budget = self.check_budget(node_id, product["category"], self.calculate_order_cost(qty, sup["unit_price"]))
        storage = self.check_storage_capacity(node_id, sku, qty)
        checks = check_hard_constraints(
            qty=qty,
            unit_price=sup["unit_price"],
            sku=sku,
            space_per_unit=product["space_per_unit"],
            budget_remaining=budget["remaining"],
            storage_free=storage["free"],
            moq=sup["min_order_qty"],
            order_multiple=sup["order_multiple"],
            supplier_capacity=sup["remaining_capacity"],
            supplier_available=bool(sup["available"] and sup["active"]),
            product_active=product["status"] == "active",
        )
        return [c.model_dump() for c in checks]

    # --- mutating ---
    def propose_purchase_order(self, **kwargs: Any) -> dict[str, Any]:
        return {"proposed": True, **kwargs}

    def record_audit_event(self, **kwargs: Any) -> None:
        self.audit.record(**kwargs)
