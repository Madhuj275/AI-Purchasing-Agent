from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.entities import Supplier, SupplierProduct


class SupplierService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, supplier_id: str) -> Supplier | None:
        return self.session.get(Supplier, supplier_id)

    def list_suppliers(self) -> list[Supplier]:
        return self.session.query(Supplier).order_by(Supplier.supplier_id).all()

    def offering(self, supplier_id: str, sku: str) -> SupplierProduct | None:
        return self.session.query(SupplierProduct).filter_by(supplier_id=supplier_id, sku=sku).one_or_none()

    def offerings_for_sku(self, sku: str, active_only: bool = True) -> list[SupplierProduct]:
        q = self.session.query(SupplierProduct).filter(SupplierProduct.sku == sku)
        if active_only:
            q = q.filter(SupplierProduct.available.is_(True))
        rows = q.all()
        if active_only:
            result = []
            for row in rows:
                supplier = self.get(row.supplier_id)
                if supplier and supplier.active:
                    result.append(row)
            return result
        return rows

    def remaining_capacity(self, supplier_id: str, sku: str, already_committed: int = 0) -> int:
        off = self.offering(supplier_id, sku)
        if not off or not off.available:
            return 0
        return max(0, off.capacity - already_committed)
