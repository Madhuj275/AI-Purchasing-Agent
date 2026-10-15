from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.entities import FulfillmentNode, Inventory, Product


class InventoryService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_product(self, sku: str) -> Product | None:
        return self.session.get(Product, sku)

    def list_products(self) -> list[Product]:
        return self.session.query(Product).order_by(Product.sku).all()

    def get_node(self, node_id: str) -> FulfillmentNode | None:
        return self.session.get(FulfillmentNode, node_id)

    def list_nodes(self) -> list[FulfillmentNode]:
        return self.session.query(FulfillmentNode).order_by(FulfillmentNode.node_id).all()

    def get_inventory(self, sku: str, node_id: str) -> Inventory | None:
        return self.session.query(Inventory).filter_by(sku=sku, node_id=node_id).one_or_none()

    def list_inventory(self, node_id: str | None = None) -> list[Inventory]:
        q = self.session.query(Inventory)
        if node_id:
            q = q.filter(Inventory.node_id == node_id)
        return q.order_by(Inventory.sku, Inventory.node_id).all()

    def low_stock(self, threshold: int = 80) -> list[Inventory]:
        rows = self.list_inventory()
        return [r for r in rows if (r.on_hand - r.reserved) < threshold]
