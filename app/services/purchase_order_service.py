from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models.entities import PurchaseOrder
from app.utils.ids import new_id, utcnow

MODIFIABLE_STATUSES = {"open", "confirmed", "pending_confirmation"}
NON_INCOMING_STATUSES = {"cancelled", "rejected", "closed"}


class PurchaseOrderService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, po_id: str) -> PurchaseOrder | None:
        return self.session.get(PurchaseOrder, po_id)

    def list_orders(self, sku: str | None = None, node_id: str | None = None, open_only: bool = False) -> list[PurchaseOrder]:
        q = self.session.query(PurchaseOrder)
        if sku:
            q = q.filter(PurchaseOrder.sku == sku)
        if node_id:
            q = q.filter(PurchaseOrder.node_id == node_id)
        if open_only:
            q = q.filter(PurchaseOrder.status.notin_(list(NON_INCOMING_STATUSES)))
        return q.order_by(PurchaseOrder.created_at).all()

    def incoming_confirmed(self, sku: str, node_id: str) -> int:
        total = 0
        for po in self.list_orders(sku=sku, node_id=node_id, open_only=True):
            if po.status in NON_INCOMING_STATUSES:
                continue
            remaining = max(0, po.ordered_qty - po.received_qty)
            if po.confirmed_incoming and remaining > 0:
                total += remaining
        return total

    def incoming_unconfirmed(self, sku: str, node_id: str) -> int:
        total = 0
        for po in self.list_orders(sku=sku, node_id=node_id, open_only=True):
            remaining = max(0, po.ordered_qty - po.received_qty)
            if not po.confirmed_incoming and remaining > 0 and po.status not in NON_INCOMING_STATUSES:
                total += remaining
        return total

    def committed_qty_for_supplier(self, supplier_id: str, sku: str) -> int:
        total = 0
        for po in self.session.query(PurchaseOrder).filter_by(supplier_id=supplier_id, sku=sku):
            if po.status in NON_INCOMING_STATUSES:
                continue
            total += max(0, po.ordered_qty - po.received_qty)
        return total

    def find_by_idempotency(self, key: str) -> PurchaseOrder | None:
        return self.session.query(PurchaseOrder).filter_by(idempotency_key=key).one_or_none()

    def create(
        self,
        *,
        supplier_id: str,
        sku: str,
        node_id: str,
        qty: int,
        unit_price: float,
        lead_time_days: int,
        idempotency_key: str,
        confirmed_incoming: bool = True,
        parent_po_id: str | None = None,
        notes: str | None = None,
        status: str = "open",
    ) -> PurchaseOrder:
        existing = self.find_by_idempotency(idempotency_key)
        if existing:
            return existing
        now = utcnow()
        po = PurchaseOrder(
            po_id=new_id("PO"),
            supplier_id=supplier_id,
            sku=sku,
            node_id=node_id,
            ordered_qty=qty,
            received_qty=0,
            confirmed_qty=qty if confirmed_incoming else None,
            status=status,
            unit_price=unit_price,
            confirmed_incoming=confirmed_incoming,
            expected_arrival=now + timedelta(days=lead_time_days),
            parent_po_id=parent_po_id,
            idempotency_key=idempotency_key,
            created_at=now,
            updated_at=now,
            notes=notes,
        )
        self.session.add(po)
        self.session.flush()
        return po

    def modify(self, po_id: str, new_qty: int, reason: str) -> PurchaseOrder:
        po = self.get(po_id)
        if po is None:
            raise ValueError("Purchase order not found")
        if po.status not in MODIFIABLE_STATUSES:
            raise ValueError(f"PO {po_id} is not safely modifiable (status={po.status})")
        if po.received_qty > 0:
            raise ValueError("Partially received POs cannot be reduced below received quantity without a dedicated workflow")
        po.ordered_qty = new_qty
        po.confirmed_qty = new_qty
        po.notes = (po.notes or "") + f" | modified: {reason}"
        po.updated_at = utcnow()
        self.session.flush()
        return po

    def confirm_supplier_qty(self, po_id: str, confirmed_qty: int, message: str = "") -> PurchaseOrder:
        po = self.get(po_id)
        if po is None:
            raise ValueError("Purchase order not found")
        if po.status in {"cancelled", "rejected"}:
            raise ValueError("Cannot confirm quantity on a cancelled or rejected PO")
        # Mock supplier-confirmation policy: reduce ordered qty to confirmed amount when
        # the PO is still fully open and unmodified receipts.
        if po.status in MODIFIABLE_STATUSES and po.received_qty == 0:
            po.ordered_qty = confirmed_qty
            po.confirmed_qty = confirmed_qty
            po.confirmed_incoming = True
            po.status = "confirmed"
        else:
            po.confirmed_qty = confirmed_qty
            po.notes = (po.notes or "") + " | confirmation recorded without quantity rewrite"
        untrusted = message.replace("\n", " ")[:240]
        po.notes = (po.notes or "") + f" | supplier_message(untrusted): {untrusted}"
        po.updated_at = utcnow()
        self.session.flush()
        return po

    def to_dict(self, po: PurchaseOrder) -> dict[str, Any]:
        return {
            "po_id": po.po_id,
            "supplier_id": po.supplier_id,
            "sku": po.sku,
            "node_id": po.node_id,
            "ordered_qty": po.ordered_qty,
            "received_qty": po.received_qty,
            "confirmed_qty": po.confirmed_qty,
            "status": po.status,
            "unit_price": po.unit_price,
            "confirmed_incoming": po.confirmed_incoming,
            "expected_arrival": po.expected_arrival.isoformat() if po.expected_arrival else None,
            "parent_po_id": po.parent_po_id,
            "idempotency_key": po.idempotency_key,
        }
