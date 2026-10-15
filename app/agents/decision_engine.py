"""Deterministic replenishment math and constraint evaluation.

Inventory position = available inventory + eligible confirmed incoming
  - available = on_hand - reserved
  - cancelled / unconfirmed POs are excluded from incoming
Target stock = forecast demand over protection period + safety stock
  - protection period = supplier lead time + review horizon
  - safety stock = safety_stock_days * daily_demand
Recommended raw = max(0, ceil(target - inventory position))
Then round up to MOQ / order multiple. If rounding would violate a hard
constraint, the rounded order is not silently accepted.
"""

from __future__ import annotations

import math
from typing import Any

from app.config import get_settings
from app.schemas.domain import ConstraintCheck, ReplenishmentCalc


def round_to_supplier_rules(qty: int, moq: int, multiple: int) -> int:
    if qty <= 0:
        return 0
    multiple = max(1, multiple)
    moq = max(0, moq)
    rounded = math.ceil(qty / multiple) * multiple
    if rounded < moq:
        rounded = math.ceil(moq / multiple) * multiple
    return int(rounded)


def calculate_replenishment(
    *,
    sku: str,
    node_id: str,
    on_hand: int,
    reserved: int,
    incoming_confirmed: int,
    incoming_unconfirmed: int,
    daily_demand: float | None,
    lead_time_days: int,
    review_horizon_days: int | None = None,
    safety_stock_days: int | None = None,
    moq: int = 1,
    order_multiple: int = 1,
    missing: list[str] | None = None,
    stale: list[str] | None = None,
) -> ReplenishmentCalc:
    settings = get_settings()
    review = settings.review_horizon_days if review_horizon_days is None else review_horizon_days
    safety_days = settings.safety_stock_days if safety_stock_days is None else safety_stock_days
    available = on_hand - reserved
    assumptions = [
        "Available inventory = on_hand - reserved; reserved is not added back.",
        "Only confirmed, non-cancelled remaining PO quantity counts as incoming.",
        "Protection period = supplier lead time + review horizon.",
        "Safety stock = safety_stock_days * daily_demand.",
        "Unconfirmed supplier promises are tracked but not added to inventory position.",
    ]
    missing = list(missing or [])
    stale = list(stale or [])
    protection = lead_time_days + review
    forecast_demand = None
    safety_stock = None
    target = None
    recommended_raw = 0
    if daily_demand is None:
        missing.append("daily_demand")
    elif daily_demand < 0:
        missing.append("daily_demand_negative")
    else:
        forecast_demand = daily_demand * protection
        safety_stock = daily_demand * safety_days
        target = forecast_demand + safety_stock
        recommended_raw = max(0, math.ceil(target - (available + incoming_confirmed)))
    recommended_rounded = round_to_supplier_rules(recommended_raw, moq, order_multiple) if daily_demand is not None else 0
    return ReplenishmentCalc(
        sku=sku,
        node_id=node_id,
        on_hand=on_hand,
        reserved=reserved,
        available=available,
        incoming_confirmed=incoming_confirmed,
        incoming_unconfirmed=incoming_unconfirmed,
        inventory_position=available + incoming_confirmed,
        daily_demand=daily_demand,
        protection_period_days=protection,
        forecast_demand_protection=forecast_demand,
        safety_stock=safety_stock,
        target_stock=target,
        recommended_raw=recommended_raw,
        recommended_rounded=recommended_rounded,
        rounding_applied=recommended_rounded != recommended_raw,
        assumptions=assumptions,
        missing=missing,
        stale=stale,
        intermediates={
            "lead_time_days": lead_time_days,
            "review_horizon_days": review,
            "safety_stock_days": safety_days,
            "moq": moq,
            "order_multiple": order_multiple,
        },
    )


def compare_recommendation(calculated: int, proposed: int, tolerance: int = 0) -> str:
    if calculated == 0 and proposed > 0:
        return "reject"
    if calculated > proposed + tolerance:
        return "modify_up"
    if proposed > calculated + tolerance:
        return "modify_down"
    return "accept"


def check_hard_constraints(
    *,
    qty: int,
    unit_price: float,
    sku: str,
    space_per_unit: float,
    budget_remaining: float | None,
    storage_free: float | None,
    moq: int,
    order_multiple: int,
    supplier_capacity: int,
    supplier_available: bool,
    product_active: bool,
) -> list[ConstraintCheck]:
    checks: list[ConstraintCheck] = []
    cost = qty * unit_price
    checks.append(
        ConstraintCheck(
            name="product_availability",
            passed=product_active,
            hard=True,
            detail="Product must be active",
            value=product_active,
        )
    )
    checks.append(
        ConstraintCheck(
            name="supplier_available",
            passed=supplier_available,
            hard=True,
            detail="Supplier offering must be available",
            value=supplier_available,
        )
    )
    moq_ok = qty == 0 or qty >= moq
    checks.append(
        ConstraintCheck(
            name="moq",
            passed=moq_ok,
            hard=True,
            detail=f"Quantity {qty} vs MOQ {moq}",
            value=qty,
            limit=moq,
        )
    )
    multiple_ok = qty == 0 or (order_multiple > 0 and qty % order_multiple == 0)
    checks.append(
        ConstraintCheck(
            name="order_multiple",
            passed=multiple_ok,
            hard=True,
            detail=f"Quantity {qty} vs multiple {order_multiple}",
            value=qty,
            limit=order_multiple,
        )
    )
    cap_ok = qty <= supplier_capacity
    checks.append(
        ConstraintCheck(
            name="supplier_capacity",
            passed=cap_ok,
            hard=True,
            detail=f"Quantity {qty} vs capacity {supplier_capacity}",
            value=qty,
            limit=supplier_capacity,
        )
    )
    budget_ok = budget_remaining is not None and cost <= budget_remaining + 1e-9
    checks.append(
        ConstraintCheck(
            name="budget",
            passed=budget_ok,
            hard=True,
            detail=f"Cost {cost:.2f} vs remaining {budget_remaining}",
            value=cost,
            limit=budget_remaining,
        )
    )
    need = qty * space_per_unit
    storage_ok = storage_free is not None and need <= storage_free + 1e-9
    checks.append(
        ConstraintCheck(
            name="storage",
            passed=storage_ok,
            hard=True,
            detail=f"Space {need:.2f} vs free {storage_free}",
            value=need,
            limit=storage_free,
        )
    )
    return checks


def max_feasible_qty(
    *,
    unit_price: float,
    space_per_unit: float,
    budget_remaining: float,
    storage_free: float,
    moq: int,
    order_multiple: int,
    supplier_capacity: int,
    desired: int,
) -> int:
    if unit_price <= 0:
        budget_qty = supplier_capacity
    else:
        budget_qty = int(budget_remaining // unit_price)
    storage_qty = int(storage_free // space_per_unit) if space_per_unit > 0 else supplier_capacity
    cap = min(desired if desired > 0 else supplier_capacity, supplier_capacity, budget_qty, storage_qty)
    if cap < moq:
        return 0
    multiple = max(1, order_multiple)
    feasible = (cap // multiple) * multiple
    if feasible < moq:
        return 0
    return int(feasible)


def stockout_estimate(available: int, incoming: int, daily_demand: float | None) -> dict[str, Any]:
    if daily_demand is None or daily_demand <= 0:
        return {"possible": False, "reason": "daily demand unknown"}
    cover = available + incoming
    days = cover / daily_demand
    return {
        "possible": True,
        "cover_qty": cover,
        "days_of_cover": days,
        "stockout_in_days": max(0.0, days),
        "at_risk": days < 2,
    }
