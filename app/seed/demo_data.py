"""Deterministic seed data and per-fixture resets for the four scenarios."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.models.entities import (
    ActualSale,
    Budget,
    DemandForecast,
    FulfillmentNode,
    Inventory,
    Product,
    PurchaseOrder,
    StorageConstraint,
    Supplier,
    SupplierProduct,
)
from app.utils.ids import utcnow

NORTH = "NODE-NORTH"
SOUTH = "NODE-SOUTH"
MILK = "MILK-1L"
RICE = "RICE-5KG"
BREAD = "BREAD-WHT"
OIL = "OIL-1L"
WATER = "WATER-500"
SUP_A = "SUP-FRESHCO"
SUP_B = "SUP-GRAINWAY"
SUP_C = "SUP-BAKEHOUSE"
SUP_D = "SUP-OILWORKS"
SUP_E = "SUP-ALTSOURCE"

SCENARIO_EVENTS = {
    "s1": {
        "scenario_id": "s1",
        "name": "Purchase Recommendation Review",
        "sku": MILK,
        "node_id": NORTH,
        "recommended_qty": 800,
        "event": "The purchasing system recommends purchasing 800 units of MILK-1L at NODE-NORTH.",
    },
    "s2": {
        "scenario_id": "s2",
        "name": "Rice Supplier Recommendation",
        "sku": RICE,
        "node_id": NORTH,
        "event": "Choose the best supplier for the 10-day RICE-5KG forecast.",
    },
    "s3": {
        "scenario_id": "s3",
        "name": "Demand / Forecast Has Changed",
        "sku": BREAD,
        "node_id": NORTH,
        "po_id": "PO-S3-001",
        "event": "Actual sales of BREAD-WHT increased significantly versus the prior forecast.",
    },
    "s4": {
        "scenario_id": "s4",
        "name": "Purchasing Constraint",
        "sku": OIL,
        "node_id": NORTH,
        "recommended_qty": 400,
        "event": "More OIL-1L inventory is required, but one or more purchasing constraints block the original recommendation.",
    },
}


def _base_catalog(session: Session) -> None:
    now = utcnow()
    session.add_all(
        [
            Product(sku=MILK, name="Fresh Milk 1L", category="dairy", unit_cost=1.20, shelf_life_days=14, status="active", space_per_unit=1.0),
            Product(sku=RICE, name="White Rice 5kg", category="grocery", unit_cost=8.50, shelf_life_days=365, status="active", space_per_unit=1.5),
            Product(sku=BREAD, name="White Bread Loaf", category="bakery", unit_cost=1.80, shelf_life_days=5, status="active", space_per_unit=0.8),
            Product(sku=OIL, name="Cooking Oil 1L", category="grocery", unit_cost=3.40, shelf_life_days=180, status="active", space_per_unit=1.2),
            Product(sku=WATER, name="Still Water 500ml", category="beverages", unit_cost=0.40, shelf_life_days=365, status="active", space_per_unit=0.5),
            FulfillmentNode(node_id=NORTH, name="North Dark Store", location="Bogota North", storage_capacity=5000, current_utilization=2100),
            FulfillmentNode(node_id=SOUTH, name="South Dark Store", location="Bogota South", storage_capacity=3500, current_utilization=1200),
            Supplier(supplier_id=SUP_A, name="FreshCo Dairy", active=True, reliability_score=0.94),
            Supplier(supplier_id=SUP_B, name="GrainWay Foods", active=True, reliability_score=0.90),
            Supplier(supplier_id=SUP_C, name="BakeHouse Daily", active=True, reliability_score=0.88),
            Supplier(supplier_id=SUP_D, name="OilWorks SA", active=True, reliability_score=0.91),
            Supplier(supplier_id=SUP_E, name="AltSource Trading", active=True, reliability_score=0.82),
        ]
    )
    session.flush()
    session.add_all(
        [
            SupplierProduct(supplier_id=SUP_A, sku=MILK, unit_price=1.10, lead_time_days=3, min_order_qty=100, order_multiple=50, capacity=5000, available=True),
            SupplierProduct(supplier_id=SUP_E, sku=MILK, unit_price=1.25, lead_time_days=5, min_order_qty=200, order_multiple=100, capacity=2000, available=True),
            SupplierProduct(supplier_id=SUP_A, sku=RICE, unit_price=100, lead_time_days=2, min_order_qty=500, order_multiple=50, capacity=700, available=True),
            SupplierProduct(supplier_id=SUP_B, sku=RICE, unit_price=150, lead_time_days=1, min_order_qty=100, order_multiple=50, capacity=700, available=True),
            SupplierProduct(supplier_id=SUP_E, sku=RICE, unit_price=80, lead_time_days=8, min_order_qty=10, order_multiple=50, capacity=200, available=True),
            SupplierProduct(supplier_id=SUP_C, sku=BREAD, unit_price=1.60, lead_time_days=1, min_order_qty=50, order_multiple=25, capacity=3000, available=True),
            SupplierProduct(supplier_id=SUP_E, sku=BREAD, unit_price=1.90, lead_time_days=3, min_order_qty=100, order_multiple=50, capacity=1500, available=True),
            SupplierProduct(supplier_id=SUP_D, sku=OIL, unit_price=3.20, lead_time_days=5, min_order_qty=200, order_multiple=50, capacity=80, available=True),
            SupplierProduct(supplier_id=SUP_E, sku=OIL, unit_price=3.60, lead_time_days=8, min_order_qty=50, order_multiple=25, capacity=1500, available=True),
            SupplierProduct(supplier_id=SUP_A, sku=WATER, unit_price=0.35, lead_time_days=2, min_order_qty=100, order_multiple=100, capacity=8000, available=True),
        ]
    )
    session.add_all(
        [
            Inventory(sku=MILK, node_id=NORTH, on_hand=0, reserved=0, last_updated=now),
            Inventory(sku=MILK, node_id=SOUTH, on_hand=120, reserved=10, last_updated=now),
            Inventory(sku=RICE, node_id=NORTH, on_hand=40, reserved=10, last_updated=now),
            Inventory(sku=RICE, node_id=SOUTH, on_hand=80, reserved=0, last_updated=now),
            Inventory(sku=BREAD, node_id=NORTH, on_hand=60, reserved=20, last_updated=now),
            Inventory(sku=BREAD, node_id=SOUTH, on_hand=200, reserved=0, last_updated=now),
            Inventory(sku=OIL, node_id=NORTH, on_hand=20, reserved=0, last_updated=now),
            Inventory(sku=OIL, node_id=SOUTH, on_hand=40, reserved=0, last_updated=now),
            Inventory(sku=WATER, node_id=NORTH, on_hand=400, reserved=50, last_updated=now),
            Inventory(sku=WATER, node_id=SOUTH, on_hand=250, reserved=0, last_updated=now),
        ]
    )
    session.add_all(
        [
            StorageConstraint(node_id=NORTH, total_capacity=5000, current_utilization=2100, reserved_space=100),
            StorageConstraint(node_id=SOUTH, total_capacity=3500, current_utilization=1200, reserved_space=50),
        ]
    )
    session.add_all(
        [
            Budget(period="2026-Q4", node_id=NORTH, category="dairy", allocated=5000, committed=200, remaining=4800),
            Budget(period="2026-Q4", node_id=NORTH, category="grocery", allocated=8000, committed=1000, remaining=7000),
            Budget(period="2026-Q4", node_id=NORTH, category="bakery", allocated=3000, committed=400, remaining=2600),
            Budget(period="2026-Q4", node_id=NORTH, category="beverages", allocated=2000, committed=200, remaining=1800),
            Budget(period="2026-Q4", node_id=SOUTH, category="dairy", allocated=2500, committed=100, remaining=2400),
            Budget(period="2026-Q4", node_id=SOUTH, category="grocery", allocated=4000, committed=500, remaining=3500),
            Budget(period="2026-Q4", node_id=SOUTH, category="bakery", allocated=1500, committed=100, remaining=1400),
            Budget(period="2026-Q4", node_id=SOUTH, category="beverages", allocated=1200, committed=50, remaining=1150),
        ]
    )
    session.flush()
    # Default forecasts: daily demand chosen so protection period math is stable.
    session.add_all(
        [
            DemandForecast(sku=MILK, node_id=NORTH, horizon_days=7, forecast_quantity=1120, forecast_timestamp=now, daily_demand=160, source="planning"),
            DemandForecast(sku=MILK, node_id=SOUTH, horizon_days=7, forecast_quantity=700, forecast_timestamp=now, daily_demand=100, source="planning"),
            DemandForecast(sku=RICE, node_id=NORTH, horizon_days=10, forecast_quantity=300, forecast_timestamp=now, daily_demand=30, source="planning"),
            DemandForecast(sku=BREAD, node_id=NORTH, horizon_days=7, forecast_quantity=350, forecast_timestamp=now, daily_demand=50, source="planning"),
            DemandForecast(sku=OIL, node_id=NORTH, horizon_days=14, forecast_quantity=280, forecast_timestamp=now, daily_demand=20, source="planning"),
            DemandForecast(sku=WATER, node_id=NORTH, horizon_days=7, forecast_quantity=700, forecast_timestamp=now, daily_demand=100, source="planning"),
        ]
    )
    session.add_all(
        [
            ActualSale(sku=MILK, node_id=NORTH, period_start=now - timedelta(days=7), period_end=now, quantity_sold=1350),
            ActualSale(sku=RICE, node_id=NORTH, period_start=now - timedelta(days=7), period_end=now, quantity_sold=340),
            ActualSale(sku=BREAD, node_id=NORTH, period_start=now - timedelta(days=7), period_end=now - timedelta(days=3), quantity_sold=150),
            ActualSale(sku=BREAD, node_id=NORTH, period_start=now - timedelta(days=3), period_end=now, quantity_sold=280),
            ActualSale(sku=OIL, node_id=NORTH, period_start=now - timedelta(days=7), period_end=now, quantity_sold=130),
            ActualSale(sku=WATER, node_id=NORTH, period_start=now - timedelta(days=7), period_end=now, quantity_sold=680),
        ]
    )
    session.add_all(
        [
            PurchaseOrder(
                po_id="PO-WATER-OPEN",
                supplier_id=SUP_A,
                sku=WATER,
                node_id=NORTH,
                ordered_qty=200,
                received_qty=0,
                confirmed_qty=200,
                status="open",
                unit_price=0.35,
                confirmed_incoming=True,
                expected_arrival=now + timedelta(days=2),
                parent_po_id=None,
                idempotency_key="seed-water-open",
                created_at=now,
                updated_at=now,
                notes="Seed open beverage PO",
            ),
            PurchaseOrder(
                po_id="PO-S3-001",
                supplier_id=SUP_C,
                sku=BREAD,
                node_id=NORTH,
                ordered_qty=150,
                received_qty=0,
                confirmed_qty=150,
                status="open",
                unit_price=1.60,
                confirmed_incoming=True,
                expected_arrival=now + timedelta(days=1),
                parent_po_id=None,
                idempotency_key="seed-s3-primary",
                created_at=now,
                updated_at=now,
                notes="Existing bread replenishment",
            ),
        ]
    )


def apply_fixture(session: Session, scenario_id: str, fixture_key: str) -> None:
    """Mutate seeded catalog into a reproducible scenario fixture."""
    now = utcnow()
    key = f"{scenario_id}:{fixture_key}"

    if scenario_id == "s2":
        _set_inv(session, RICE, NORTH, on_hand=40, reserved=10)
        _set_forecast(session, RICE, NORTH, daily=30, qty=300, ts=now)
        _set_budget(session, NORTH, "grocery", remaining=100000, committed=1000)
        session.query(PurchaseOrder).filter(
            (PurchaseOrder.po_id == "PO-S2-001")
            | (PurchaseOrder.parent_po_id == "PO-S2-001")
        ).delete(synchronize_session=False)
        rice_offers = {
            SUP_A: (100, 2, 500, 50, 700),
            SUP_B: (150, 1, 100, 50, 700),
            SUP_E: (80, 8, 10, 50, 200),
        }
        for supplier_id, terms in rice_offers.items():
            offering = session.query(SupplierProduct).filter_by(
                supplier_id=supplier_id, sku=RICE
            ).one()
            (
                offering.unit_price,
                offering.lead_time_days,
                offering.min_order_qty,
                offering.order_multiple,
                offering.capacity,
            ) = terms
            offering.available = True

    if key == "s1:default" or key == "s1:appropriate":
        _set_inv(session, MILK, NORTH, on_hand=0, reserved=0)
        _set_forecast(session, MILK, NORTH, daily=160, qty=1120, ts=now)
        _set_budget(session, NORTH, "dairy", remaining=4800, committed=200)
        _set_storage(session, NORTH, util=2100, reserved=100, cap=5000)

    elif key == "s1:excessive":
        _set_inv(session, MILK, NORTH, on_hand=700, reserved=50)
        _set_forecast(session, MILK, NORTH, daily=160, qty=1120, ts=now)

    elif key == "s1:sufficient":
        _set_inv(session, MILK, NORTH, on_hand=500, reserved=0)
        _set_forecast(session, MILK, NORTH, daily=160, qty=1120, ts=now)
        session.add(
            PurchaseOrder(
                po_id="PO-S1-INCOMING",
                supplier_id=SUP_A,
                sku=MILK,
                node_id=NORTH,
                ordered_qty=400,
                received_qty=0,
                confirmed_qty=400,
                status="open",
                unit_price=1.10,
                confirmed_incoming=True,
                expected_arrival=now + timedelta(days=2),
                parent_po_id=None,
                idempotency_key="seed-s1-incoming",
                created_at=now,
                updated_at=now,
                notes="Confirmed incoming milk",
            )
        )

    elif key == "s1:insufficient":
        _set_inv(session, MILK, NORTH, on_hand=0, reserved=0)
        _set_forecast(session, MILK, NORTH, daily=300, qty=2100, ts=now)

    elif key == "s1:missing_forecast":
        session.query(DemandForecast).filter_by(sku=MILK, node_id=NORTH).delete()

    elif key == "s1:stale_forecast":
        _set_forecast(session, MILK, NORTH, daily=160, qty=1120, ts=now - timedelta(hours=96))

    elif key == "s1:contradiction":
        _set_inv(session, MILK, NORTH, on_hand=50, reserved=80)

    elif key == "s1:budget":
        _set_inv(session, MILK, NORTH, on_hand=0, reserved=0)
        _set_forecast(session, MILK, NORTH, daily=160, qty=1120, ts=now)
        _set_budget(session, NORTH, "dairy", remaining=50, committed=4950)

    elif key == "s1:storage":
        _set_inv(session, MILK, NORTH, on_hand=0, reserved=0)
        _set_forecast(session, MILK, NORTH, daily=160, qty=1120, ts=now)
        _set_storage(session, NORTH, util=4980, reserved=10, cap=5000)

    elif key == "s1:moq":
        _set_inv(session, MILK, NORTH, on_hand=0, reserved=0)
        offering = session.query(SupplierProduct).filter_by(supplier_id=SUP_A, sku=MILK).one()
        offering.min_order_qty = 1000
        offering.order_multiple = 1000

    elif key == "s1:cancelled_incoming":
        _set_inv(session, MILK, NORTH, on_hand=0, reserved=0)
        session.add(
            PurchaseOrder(
                po_id="PO-S1-CANCELLED",
                supplier_id=SUP_A,
                sku=MILK,
                node_id=NORTH,
                ordered_qty=800,
                received_qty=0,
                confirmed_qty=800,
                status="cancelled",
                unit_price=1.10,
                confirmed_incoming=False,
                expected_arrival=None,
                parent_po_id=None,
                idempotency_key="seed-s1-cancelled",
                created_at=now,
                updated_at=now,
                notes="Cancelled — must not count as incoming",
            )
        )

    elif key == "s2:default" or key == "s2:alt_supplier":
        _set_inv(session, RICE, NORTH, on_hand=40, reserved=10)
        _set_forecast(session, RICE, NORTH, daily=30, qty=300, ts=now)
        _set_budget(session, NORTH, "grocery", remaining=100000, committed=1000)
        if key == "s2:alt_supplier":
            alternate = session.query(SupplierProduct).filter_by(supplier_id=SUP_E, sku=RICE).one()
            alternate.capacity = 700

    elif key == "s2:inventory_covers":
        _set_inv(session, RICE, NORTH, on_hand=900, reserved=10)
        _set_forecast(session, RICE, NORTH, daily=50, qty=700, ts=now)
        _set_budget(session, NORTH, "grocery", remaining=100000, committed=1000)

    elif key == "s2:alt_expensive":
        _set_inv(session, RICE, NORTH, on_hand=40, reserved=10)
        _set_budget(session, NORTH, "grocery", remaining=100000, committed=1000)
        alt = session.query(SupplierProduct).filter_by(supplier_id=SUP_E, sku=RICE).one()
        alt.unit_price = 125
        alt.lead_time_days = 10

    elif key == "s2:no_supplier":
        _set_inv(session, RICE, NORTH, on_hand=40, reserved=10)
        for offering in session.query(SupplierProduct).filter_by(sku=RICE).all():
            offering.available = False
            offering.capacity = 0

    elif key == "s2:stockout_escalate":
        _set_inv(session, RICE, NORTH, on_hand=10, reserved=5)
        _set_forecast(session, RICE, NORTH, daily=80, qty=1120, ts=now)
        alt = session.query(SupplierProduct).filter_by(supplier_id=SUP_E, sku=RICE).one()
        alt.available = False

    elif key == "s3:default" or key == "s3:increase_justified":
        _set_inv(session, BREAD, NORTH, on_hand=60, reserved=20)
        _set_forecast(session, BREAD, NORTH, daily=50, qty=350, ts=now)
        _set_po(session, "PO-S3-001", ordered=150, received=0, status="open", confirmed_incoming=True)

    elif key == "s3:po_sufficient":
        _set_inv(session, BREAD, NORTH, on_hand=400, reserved=0)
        _set_forecast(session, BREAD, NORTH, daily=50, qty=350, ts=now)
        _set_po(session, "PO-S3-001", ordered=400, received=0, status="open", confirmed_incoming=True)

    elif key == "s3:short_window":
        session.query(ActualSale).filter_by(sku=BREAD, node_id=NORTH).delete()
        session.add(
            ActualSale(
                sku=BREAD,
                node_id=NORTH,
                period_start=now - timedelta(hours=6),
                period_end=now,
                quantity_sold=80,
            )
        )

    elif key == "s3:stale_forecast":
        _set_forecast(session, BREAD, NORTH, daily=50, qty=350, ts=now - timedelta(hours=120))

    elif key == "s3:missing_forecast":
        session.query(DemandForecast).filter_by(sku=BREAD, node_id=NORTH).delete()

    elif key == "s3:too_late":
        _set_inv(session, BREAD, NORTH, on_hand=5, reserved=0)
        _set_forecast(session, BREAD, NORTH, daily=50, qty=350, ts=now)
        session.query(ActualSale).filter_by(sku=BREAD, node_id=NORTH).delete()
        session.add(
            ActualSale(
                sku=BREAD,
                node_id=NORTH,
                period_start=now - timedelta(days=3),
                period_end=now,
                quantity_sold=360,
            )
        )
        offering = session.query(SupplierProduct).filter_by(supplier_id=SUP_C, sku=BREAD).one()
        offering.lead_time_days = 10
        alt = session.query(SupplierProduct).filter_by(supplier_id=SUP_E, sku=BREAD).one()
        alt.lead_time_days = 12

    elif key == "s3:constraint":
        _set_inv(session, BREAD, NORTH, on_hand=60, reserved=20)
        _set_forecast(session, BREAD, NORTH, daily=50, qty=350, ts=now)
        _set_budget(session, NORTH, "bakery", remaining=20, committed=2980)

    elif key == "s4:default" or key == "s4:budget":
        _set_inv(session, OIL, NORTH, on_hand=20, reserved=0)
        _set_forecast(session, OIL, NORTH, daily=40, qty=560, ts=now)
        _set_budget(session, NORTH, "grocery", remaining=80, committed=7920)
        primary = session.query(SupplierProduct).filter_by(supplier_id=SUP_D, sku=OIL).one()
        primary.capacity = 80
        primary.min_order_qty = 200

    elif key == "s4:storage":
        _set_inv(session, OIL, NORTH, on_hand=20, reserved=0)
        _set_forecast(session, OIL, NORTH, daily=40, qty=560, ts=now)
        _set_budget(session, NORTH, "grocery", remaining=7000, committed=1000)
        _set_storage(session, NORTH, util=4990, reserved=5, cap=5000)
        primary = session.query(SupplierProduct).filter_by(supplier_id=SUP_D, sku=OIL).one()
        primary.capacity = 2000
        primary.min_order_qty = 50

    elif key == "s4:moq":
        _set_inv(session, OIL, NORTH, on_hand=20, reserved=0)
        _set_forecast(session, OIL, NORTH, daily=15, qty=210, ts=now)
        _set_budget(session, NORTH, "grocery", remaining=7000, committed=1000)
        primary = session.query(SupplierProduct).filter_by(supplier_id=SUP_D, sku=OIL).one()
        primary.min_order_qty = 500
        primary.order_multiple = 500
        primary.capacity = 2000
        alt = session.query(SupplierProduct).filter_by(supplier_id=SUP_E, sku=OIL).one()
        alt.available = False

    elif key == "s4:capacity":
        _set_inv(session, OIL, NORTH, on_hand=20, reserved=0)
        _set_forecast(session, OIL, NORTH, daily=40, qty=560, ts=now)
        _set_budget(session, NORTH, "grocery", remaining=7000, committed=1000)
        primary = session.query(SupplierProduct).filter_by(supplier_id=SUP_D, sku=OIL).one()
        primary.capacity = 40
        primary.min_order_qty = 50
        alt = session.query(SupplierProduct).filter_by(supplier_id=SUP_E, sku=OIL).one()
        alt.available = False

    elif key == "s4:multi":
        _set_inv(session, OIL, NORTH, on_hand=20, reserved=0)
        _set_forecast(session, OIL, NORTH, daily=40, qty=560, ts=now)
        _set_budget(session, NORTH, "grocery", remaining=100, committed=7900)
        _set_storage(session, NORTH, util=4985, reserved=10, cap=5000)
        primary = session.query(SupplierProduct).filter_by(supplier_id=SUP_D, sku=OIL).one()
        primary.capacity = 30
        primary.min_order_qty = 200

    elif key == "s4:feasible_alt":
        _set_inv(session, OIL, NORTH, on_hand=20, reserved=0)
        _set_forecast(session, OIL, NORTH, daily=40, qty=560, ts=now)
        _set_budget(session, NORTH, "grocery", remaining=7000, committed=1000)
        primary = session.query(SupplierProduct).filter_by(supplier_id=SUP_D, sku=OIL).one()
        primary.capacity = 40
        primary.min_order_qty = 200

    elif key == "s4:approval":
        _set_inv(session, OIL, NORTH, on_hand=20, reserved=0)
        _set_forecast(session, OIL, NORTH, daily=40, qty=560, ts=now)
        _set_budget(session, NORTH, "grocery", remaining=7000, committed=1000)
        primary = session.query(SupplierProduct).filter_by(supplier_id=SUP_D, sku=OIL).one()
        primary.capacity = 2000
        primary.min_order_qty = 50
        primary.unit_price = 3.20

    else:
        # Unknown fixture keys keep catalog defaults.
        return


def seed_database(session: Session, scenario_id: str | None = None, fixture_key: str = "default") -> None:
    _base_catalog(session)
    session.flush()
    if scenario_id:
        apply_fixture(session, scenario_id, fixture_key)
    else:
        apply_fixture(session, "s1", "default")
        apply_fixture(session, "s2", "default")
        apply_fixture(session, "s3", "default")
        apply_fixture(session, "s4", "default")
    session.commit()


def reset_and_seed(session: Session, scenario_id: str | None = None, fixture_key: str = "default") -> None:
    from app.database import reset_db

    reset_db()
    seed_database(session, scenario_id=scenario_id, fixture_key=fixture_key)


def _set_inv(session: Session, sku: str, node_id: str, on_hand: int, reserved: int) -> None:
    row = session.query(Inventory).filter_by(sku=sku, node_id=node_id).one()
    row.on_hand = on_hand
    row.reserved = reserved
    row.last_updated = utcnow()


def _set_forecast(session: Session, sku: str, node_id: str, daily: float, qty: int, ts) -> None:
    row = session.query(DemandForecast).filter_by(sku=sku, node_id=node_id).one()
    row.daily_demand = daily
    row.forecast_quantity = qty
    row.forecast_timestamp = ts


def _set_budget(session: Session, node_id: str, category: str, remaining: float, committed: float) -> None:
    row = session.query(Budget).filter_by(node_id=node_id, category=category, period="2026-Q4").one()
    row.remaining = remaining
    row.committed = committed
    row.allocated = remaining + committed


def _set_storage(session: Session, node_id: str, util: float, reserved: float, cap: float) -> None:
    row = session.query(StorageConstraint).filter_by(node_id=node_id).one()
    row.current_utilization = util
    row.reserved_space = reserved
    row.total_capacity = cap
    node = session.query(FulfillmentNode).filter_by(node_id=node_id).one()
    node.current_utilization = util
    node.storage_capacity = cap


def _set_po(session: Session, po_id: str, ordered: int, received: int, status: str, confirmed_incoming: bool) -> None:
    row = session.query(PurchaseOrder).filter_by(po_id=po_id).one()
    row.ordered_qty = ordered
    row.received_qty = received
    row.status = status
    row.confirmed_incoming = confirmed_incoming
    row.updated_at = utcnow()
