"""SQLAlchemy entities for the mock procurement system."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"

    sku: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    unit_cost: Mapped[float] = mapped_column(Float, nullable=False)
    shelf_life_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    space_per_unit: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    inventories: Mapped[list[Inventory]] = relationship(back_populates="product")


class FulfillmentNode(Base):
    __tablename__ = "fulfillment_nodes"

    node_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_capacity: Mapped[float] = mapped_column(Float, nullable=False)
    current_utilization: Mapped[float] = mapped_column(Float, nullable=False)

    inventories: Mapped[list[Inventory]] = relationship(back_populates="node")
    storage: Mapped[StorageConstraint | None] = relationship(back_populates="node", uselist=False)


class Inventory(Base):
    __tablename__ = "inventory"
    __table_args__ = (UniqueConstraint("sku", "node_id", name="uq_inventory_sku_node"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sku: Mapped[str] = mapped_column(ForeignKey("products.sku"), nullable=False)
    node_id: Mapped[str] = mapped_column(ForeignKey("fulfillment_nodes.node_id"), nullable=False)
    on_hand: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    product: Mapped[Product] = relationship(back_populates="inventories")
    node: Mapped[FulfillmentNode] = relationship(back_populates="inventories")


class DemandForecast(Base):
    __tablename__ = "demand_forecasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sku: Mapped[str] = mapped_column(ForeignKey("products.sku"), nullable=False)
    node_id: Mapped[str] = mapped_column(ForeignKey("fulfillment_nodes.node_id"), nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    forecast_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    forecast_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    daily_demand: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="planning", nullable=False)


class ActualSale(Base):
    __tablename__ = "actual_sales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sku: Mapped[str] = mapped_column(ForeignKey("products.sku"), nullable=False)
    node_id: Mapped[str] = mapped_column(ForeignKey("fulfillment_nodes.node_id"), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    quantity_sold: Mapped[int] = mapped_column(Integer, nullable=False)


class Supplier(Base):
    __tablename__ = "suppliers"

    supplier_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    reliability_score: Mapped[float] = mapped_column(Float, default=0.9, nullable=False)

    offerings: Mapped[list[SupplierProduct]] = relationship(back_populates="supplier")


class SupplierProduct(Base):
    __tablename__ = "supplier_products"
    __table_args__ = (UniqueConstraint("supplier_id", "sku", name="uq_supplier_sku"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.supplier_id"), nullable=False)
    sku: Mapped[str] = mapped_column(ForeignKey("products.sku"), nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False)
    min_order_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    order_multiple: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    supplier: Mapped[Supplier] = relationship(back_populates="offerings")


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_po_idempotency"),)

    po_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.supplier_id"), nullable=False)
    sku: Mapped[str] = mapped_column(ForeignKey("products.sku"), nullable=False)
    node_id: Mapped[str] = mapped_column(ForeignKey("fulfillment_nodes.node_id"), nullable=False)
    ordered_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    received_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confirmed_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    confirmed_incoming: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expected_arrival: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    parent_po_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Budget(Base):
    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    period: Mapped[str] = mapped_column(String(32), nullable=False)
    node_id: Mapped[str] = mapped_column(ForeignKey("fulfillment_nodes.node_id"), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    allocated: Mapped[float] = mapped_column(Float, nullable=False)
    committed: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    remaining: Mapped[float] = mapped_column(Float, nullable=False)


class StorageConstraint(Base):
    __tablename__ = "storage_constraints"

    node_id: Mapped[str] = mapped_column(ForeignKey("fulfillment_nodes.node_id"), primary_key=True)
    total_capacity: Mapped[float] = mapped_column(Float, nullable=False)
    current_utilization: Mapped[float] = mapped_column(Float, nullable=False)
    reserved_space: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    node: Mapped[FulfillmentNode] = relationship(back_populates="storage")


class AgentRun(Base):
    __tablename__ = "agent_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scenario_id: Mapped[str] = mapped_column(String(32), nullable=False)
    fixture_key: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    event_payload: Mapped[str] = mapped_column(Text, nullable=False)
    investigation: Mapped[str] = mapped_column(Text, nullable=True)
    decision: Mapped[str] = mapped_column(Text, nullable=True)
    explanation: Mapped[str] = mapped_column(Text, nullable=True)
    reasoning_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="deterministic")
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ActionRecord(Base):
    __tablename__ = "action_records"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_action_idempotency"),)

    action_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.run_id"), nullable=False)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    proposed_payload: Mapped[str] = mapped_column(Text, nullable=False)
    execution_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    before_state: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_state: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class HumanApproval(Base):
    __tablename__ = "human_approvals"

    approval_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    action_id: Mapped[str] = mapped_column(ForeignKey("action_records.action_id"), nullable=False)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.run_id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    approver: Mapped[str | None] = mapped_column(String(128), nullable=True)
    decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    audit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    entity: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(128), nullable=False)
    before_state: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_state: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
