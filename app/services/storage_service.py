from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.entities import Product, StorageConstraint


class StorageService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, node_id: str) -> StorageConstraint | None:
        return self.session.get(StorageConstraint, node_id)

    def list_storage(self) -> list[StorageConstraint]:
        return self.session.query(StorageConstraint).order_by(StorageConstraint.node_id).all()

    def free_space(self, node_id: str) -> float:
        row = self.get(node_id)
        if row is None:
            return 0.0
        return max(0.0, row.total_capacity - row.current_utilization - row.reserved_space)

    def required_space(self, sku: str, qty: int) -> float:
        product = self.session.get(Product, sku)
        space = product.space_per_unit if product else 1.0
        return qty * space

    def can_store(self, node_id: str, sku: str, qty: int) -> bool:
        return self.required_space(sku, qty) <= self.free_space(node_id) + 1e-9

    def reserve(self, node_id: str, sku: str, qty: int) -> StorageConstraint:
        row = self.get(node_id)
        if row is None:
            raise ValueError("Storage constraint not found")
        need = self.required_space(sku, qty)
        if need > self.free_space(node_id) + 1e-9:
            raise ValueError("Insufficient storage")
        row.reserved_space += need
        self.session.flush()
        return row
