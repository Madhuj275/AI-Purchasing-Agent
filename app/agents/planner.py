"""Build evidence-based candidate plans and the offline deterministic fallback."""

from __future__ import annotations

from app.agents.decision_engine import (
    calculate_replenishment,
    check_hard_constraints,
    compare_recommendation,
    max_feasible_qty,
    stockout_estimate,
)
from app.schemas.domain import AlternativeOption, ConstraintCheck, DecisionRecord, InvestigationReport
from app.tools.registry import ProcurementTools


def _supplier_constraints(inv: InvestigationReport, supplier: dict, qty: int) -> list[ConstraintCheck]:
    product = inv.product or {}
    budget = inv.budget or {}
    storage = inv.storage or {}
    cost = qty * supplier["unit_price"]
    return check_hard_constraints(
        qty=qty,
        unit_price=supplier["unit_price"],
        sku=inv.event["sku"],
        space_per_unit=product.get("space_per_unit", 1.0),
        budget_remaining=budget.get("remaining"),
        storage_free=storage.get("free"),
        moq=supplier["min_order_qty"],
        order_multiple=supplier["order_multiple"],
        supplier_capacity=supplier["remaining_capacity"],
        supplier_available=bool(supplier.get("available") and supplier.get("active", True)),
        product_active=(product.get("status") == "active"),
    )


def _calc_for_supplier(inv: InvestigationReport, supplier: dict) -> object:
    inventory = inv.inventory or {"on_hand": 0, "reserved": 0}
    incoming_c = 0
    incoming_u = 0
    for po in inv.purchase_orders:
        rem = max(0, po["ordered_qty"] - po.get("received_qty", 0))
        if po.get("status") in {"cancelled", "rejected", "closed"}:
            continue
        if po.get("confirmed_incoming"):
            incoming_c += rem
        else:
            incoming_u += rem
    daily = None if not inv.forecast else inv.forecast["daily_demand"]
    return calculate_replenishment(
        sku=inv.event["sku"],
        node_id=inv.event["node_id"],
        on_hand=inventory.get("on_hand", 0),
        reserved=inventory.get("reserved", 0),
        incoming_confirmed=incoming_c,
        incoming_unconfirmed=incoming_u,
        daily_demand=daily,
        lead_time_days=supplier.get("lead_time_days", 0),
        moq=supplier.get("min_order_qty", 1),
        order_multiple=supplier.get("order_multiple", 1),
        missing=list(inv.missing),
        stale=list(inv.stale),
    )


def _option(option_id: str, description: str, action: str, qty: int, supplier: dict | None, inv: InvestigationReport) -> AlternativeOption:
    if supplier is None:
        return AlternativeOption(
            option_id=option_id,
            description=description,
            action=action,  # type: ignore[arg-type]
            quantity=qty,
            feasible=True,
            reasons=["No purchase required or investigation-only option"],
        )
    checks = _supplier_constraints(inv, supplier, qty)
    failed = [c for c in checks if c.hard and not c.passed]
    cost = qty * supplier["unit_price"]
    return AlternativeOption(
        option_id=option_id,
        description=description,
        action=action,  # type: ignore[arg-type]
        quantity=qty,
        supplier_id=supplier["supplier_id"],
        cost=cost,
        feasible=len(failed) == 0,
        reasons=[c.detail for c in failed] if failed else ["All hard constraints pass"],
        constraints=checks,
    )


def plan(tools: ProcurementTools, inv: InvestigationReport) -> DecisionRecord:
    scenario = inv.scenario_id
    if inv.missing or inv.contradictions:
        if "forecast" in inv.missing or inv.contradictions:
            return DecisionRecord(
                action="investigate",
                recommended_qty=0,
                compared_qty=inv.event.get("recommended_qty"),
                confidence="low",
                explanation=(
                    "Essential data is missing or contradictory. The agent will not invent values "
                    f"or place an order. Missing={inv.missing}; contradictions={inv.contradictions}."
                ),
                constraints=[],
                alternatives=[],
                requires_approval=False,
                uncertainty=inv.missing + inv.contradictions + inv.stale,
            )

    suppliers = list(inv.suppliers)
    if not suppliers:
        return DecisionRecord(
            action="escalate",
            recommended_qty=0,
            confidence="low",
            explanation="No active supplier offering exists for this SKU.",
            uncertainty=["no_supplier"],
        )
    primary = suppliers[0]
    calc = _calc_for_supplier(inv, primary)
    alternatives: list[AlternativeOption] = []

    if scenario == "s1":
        proposed = int(inv.event.get("recommended_qty", 0))
        cmp = compare_recommendation(calc.recommended_raw, proposed)
        qty = calc.recommended_rounded if cmp != "reject" else 0
        if cmp == "accept":
            action = "accept"
            qty = calc.recommended_rounded
            explanation = (
                f"Independent replenishment equals the system recommendation. "
                f"Inventory position {calc.inventory_position}, target {calc.target_stock}, "
                f"raw {calc.recommended_raw}, rounded {calc.recommended_rounded}."
            )
        elif cmp == "reject":
            action = "reject"
            qty = 0
            explanation = (
                f"No replenishment is required. Inventory position {calc.inventory_position} "
                f"already covers target {calc.target_stock}. The 800-unit recommendation is rejected. "
                "Cancelled or unconfirmed POs were not counted as incoming."
            )
        elif cmp == "modify_down":
            action = "modify"
            qty = calc.recommended_rounded
            explanation = (
                f"800 units is excessive. Calculated need is {calc.recommended_raw} "
                f"(rounded {calc.recommended_rounded}) given position {calc.inventory_position}."
            )
        else:
            action = "modify"
            qty = calc.recommended_rounded
            explanation = (
                f"800 units is insufficient. Calculated need is {calc.recommended_raw} "
                f"(rounded {calc.recommended_rounded}) because demand during the protection period is higher."
            )
        if inv.stale:
            action = "investigate"
            qty = 0
            explanation = "Forecast is stale. Additional human review is required before purchasing."
        opt = _option("primary", f"{action} {qty} via {primary['supplier_id']}", action, qty, primary if qty else None, inv)
        alternatives.append(opt)
        if qty and not opt.feasible:
            feasible = max_feasible_qty(
                unit_price=primary["unit_price"],
                space_per_unit=(inv.product or {}).get("space_per_unit", 1.0),
                budget_remaining=(inv.budget or {}).get("remaining", 0),
                storage_free=(inv.storage or {}).get("free", 0),
                moq=primary["min_order_qty"],
                order_multiple=primary["order_multiple"],
                supplier_capacity=primary["remaining_capacity"],
                desired=qty,
            )
            if feasible:
                alt = _option("reduced", f"Reduced compliant order of {feasible}", "modify", feasible, primary, inv)
                alternatives.append(alt)
            for s in suppliers[1:]:
                alternatives.append(_option(f"alt-{s['supplier_id']}", f"Alternate supplier {s['supplier_id']}", "alternative_supplier", qty, s, inv))
            selected = next((a for a in alternatives if a.feasible), None)
            if selected is None:
                return DecisionRecord(
                    action="escalate",
                    recommended_qty=qty,
                    compared_qty=proposed,
                    supplier_id=primary["supplier_id"],
                    unit_price=primary["unit_price"],
                    total_cost=qty * primary["unit_price"],
                    confidence="medium",
                    explanation=explanation + " Hard constraints block execution; escalating.",
                    calculation=calc,
                    constraints=opt.constraints,
                    alternatives=alternatives,
                    requires_approval=True,
                    hard_constraint_violations=[c.name for c in opt.constraints if c.hard and not c.passed],
                    uncertainty=inv.stale,
                )
            return DecisionRecord(
                action=selected.action,
                recommended_qty=selected.quantity,
                compared_qty=proposed,
                supplier_id=selected.supplier_id,
                unit_price=primary["unit_price"] if selected.supplier_id == primary["supplier_id"] else next(s["unit_price"] for s in suppliers if s["supplier_id"] == selected.supplier_id),
                total_cost=selected.cost,
                confidence="medium",
                explanation=explanation + f" Selected feasible alternative {selected.option_id}.",
                calculation=calc,
                constraints=selected.constraints,
                alternatives=alternatives,
                selected_option_id=selected.option_id,
                requires_approval=tools.approvals.requires_approval(selected.cost or 0),
            )
        cost = qty * primary["unit_price"]
        return DecisionRecord(
            action=action,  # type: ignore[arg-type]
            recommended_qty=qty,
            compared_qty=proposed,
            supplier_id=primary["supplier_id"] if qty else None,
            unit_price=primary["unit_price"] if qty else None,
            total_cost=cost if qty else 0,
            confidence="high" if not inv.stale else "low",
            explanation=explanation,
            calculation=calc,
            constraints=opt.constraints if qty else [],
            alternatives=alternatives,
            selected_option_id=opt.option_id,
            requires_approval=bool(qty and tools.approvals.requires_approval(cost)),
            uncertainty=inv.stale,
        )

    if scenario == "s2":
        po_id = inv.event.get("po_id")
        po = next((p for p in inv.purchase_orders if p["po_id"] == po_id), None)
        confirmed = int(inv.event.get("confirmed_qty", 250))
        ordered = int(inv.event.get("ordered_qty", 500))
        shortage = max(0, ordered - confirmed)
        if po is None:
            return DecisionRecord(
                action="investigate",
                recommended_qty=0,
                confidence="low",
                explanation="Original purchase order was not found.",
                calculation=calc,
            )
        if po["status"] in {"cancelled", "rejected"}:
            return DecisionRecord(
                action="escalate",
                recommended_qty=0,
                confidence="medium",
                explanation=f"PO {po_id} status={po['status']} is not safely modifiable.",
                calculation=calc,
            )
        if po["received_qty"] > 0:
            return DecisionRecord(
                action="escalate",
                recommended_qty=shortage,
                confidence="medium",
                explanation=(
                    f"PO {po_id} is already partially received ({po['received_qty']}). "
                    "The mock confirmation policy will not rewrite ordered quantity; human review is required."
                ),
                calculation=calc,
                uncertainty=["partial_receipt"],
            )
        # Recalc need after treating original remaining as unconfirmed/reduced
        inventory = inv.inventory or {"on_hand": 0, "reserved": 0, "available": 0}
        available = inventory.get("available", 0)
        # After confirmation, incoming from this PO becomes confirmed qty remaining
        other_incoming = 0
        for p in inv.purchase_orders:
            if p["po_id"] == po_id:
                continue
            if p.get("confirmed_incoming") and p.get("status") not in {"cancelled", "rejected", "closed"}:
                other_incoming += max(0, p["ordered_qty"] - p.get("received_qty", 0))
        daily = inv.forecast["daily_demand"] if inv.forecast else None
        need_calc = calculate_replenishment(
            sku=inv.event["sku"],
            node_id=inv.event["node_id"],
            on_hand=inventory.get("on_hand", 0),
            reserved=inventory.get("reserved", 0),
            incoming_confirmed=confirmed + other_incoming,
            incoming_unconfirmed=0,
            daily_demand=daily,
            lead_time_days=primary["lead_time_days"],
            moq=primary["min_order_qty"],
            order_multiple=primary["order_multiple"],
            missing=list(inv.missing),
            stale=list(inv.stale),
        )
        remaining_need = need_calc.recommended_raw
        risk = stockout_estimate(available, confirmed + other_incoming, daily)
        # Inventory covers
        if remaining_need == 0:
            opt = _option("reduce", f"Reduce original PO to {confirmed}; inventory covers shortage", "modify", 0, None, inv)
            return DecisionRecord(
                action="modify",
                recommended_qty=0,
                supplier_id=po["supplier_id"],
                confidence="high",
                explanation=(
                    f"Supplier can fulfil {confirmed} of {ordered}. Remaining operational need is 0 "
                    f"because inventory position after confirmation is {need_calc.inventory_position} vs target {need_calc.target_stock}."
                ),
                calculation=need_calc,
                alternatives=[opt],
                selected_option_id="reduce",
                requires_approval=False,
            )
        alts: list[AlternativeOption] = []
        alts.append(_option("reduce_only", f"Accept {confirmed} and leave shortage {remaining_need}", "defer", 0, None, inv))
        for s in suppliers:
            if s["supplier_id"] == po["supplier_id"]:
                continue
            qty = round_qty(shortage, s)
            alts.append(_option(f"alt-{s['supplier_id']}", f"Cover shortage {qty} with {s['supplier_id']} (LT {s['lead_time_days']}d, ${s['unit_price']})", "alternative_supplier", qty, s, inv))
        selected = next((a for a in alts if a.action == "alternative_supplier" and a.feasible), None)
        if selected is None and risk.get("at_risk"):
            return DecisionRecord(
                action="escalate",
                recommended_qty=remaining_need,
                confidence="medium",
                explanation=(
                    f"Supplier confirmed {confirmed}/{ordered}. Shortage {remaining_need} remains, "
                    f"stockout risk in {risk.get('days_of_cover')} days, and no feasible alternate supplier exists."
                ),
                calculation=need_calc,
                alternatives=alts,
                requires_approval=True,
                uncertainty=["projected_stockout"],
            )
        if selected is None:
            return DecisionRecord(
                action="escalate",
                recommended_qty=remaining_need,
                confidence="medium",
                explanation=f"Shortage of {remaining_need} cannot be covered by a feasible supplier option.",
                calculation=need_calc,
                alternatives=alts,
                requires_approval=True,
            )
        price = next(s["unit_price"] for s in suppliers if s["supplier_id"] == selected.supplier_id)
        return DecisionRecord(
            action="split_order",
            recommended_qty=selected.quantity,
            supplier_id=selected.supplier_id,
            unit_price=price,
            total_cost=selected.cost,
            confidence="medium",
            explanation=(
                f"Original PO will be confirmed at {confirmed}. Remaining need {remaining_need} is sourced from "
                f"{selected.supplier_id}. Duplicate coverage of the confirmed {confirmed} units is avoided."
            ),
            calculation=need_calc,
            constraints=selected.constraints,
            alternatives=alts,
            selected_option_id=selected.option_id,
            requires_approval=tools.approvals.requires_approval(selected.cost or 0),
        )

    if scenario == "s3":
        change = tools.demand.demand_change(inv.event["sku"], inv.event["node_id"])
        uncertainty = []
        if change.get("unreliable_window"):
            uncertainty.append("observation window < 24h")
        if change.get("stale_forecast") or "forecast" in inv.missing:
            uncertainty.append("forecast stale or missing")
        if change.get("material") and change.get("window_hours"):
            observed_daily = change["recent_qty"] / max(change["window_hours"] / 24.0, 1 / 24)
            calc = calculate_replenishment(
                sku=inv.event["sku"],
                node_id=inv.event["node_id"],
                on_hand=(inv.inventory or {}).get("on_hand", 0),
                reserved=(inv.inventory or {}).get("reserved", 0),
                incoming_confirmed=calc.incoming_confirmed,
                incoming_unconfirmed=calc.incoming_unconfirmed,
                daily_demand=observed_daily,
                lead_time_days=primary["lead_time_days"],
                moq=primary["min_order_qty"],
                order_multiple=primary["order_multiple"],
                missing=list(inv.missing),
                stale=list(inv.stale),
            )
            calc.assumptions.append(
                f"Material demand increase: daily demand uplifted from forecast using observed sales rate {observed_daily:.2f} (not treated as a guarantee)."
            )
        if change.get("unreliable_window") or not change.get("material"):
            if not change.get("material"):
                return DecisionRecord(
                    action="keep_plan" if calc.recommended_raw == 0 or calc.inventory_position >= (calc.target_stock or 0) else "investigate",
                    recommended_qty=0 if not change.get("material") else calc.recommended_rounded,
                    confidence="low" if uncertainty else "medium",
                    explanation=(
                        f"Demand comparison status={change.get('status')}, ratio={change.get('ratio')}. "
                        "The spike is not treated as a permanent demand change. Existing plan is retained or investigated."
                    ),
                    calculation=calc,
                    uncertainty=uncertainty + ([f"ratio={change.get('ratio')}"] if change.get("ratio") else []),
                )
        # material increase
        extra = calc.recommended_rounded
        risk = tools.calculate_stockout_risk(inv.event["sku"], inv.event["node_id"], inv.forecast["daily_demand"] if inv.forecast else None)
        if extra == 0:
            return DecisionRecord(
                action="keep_plan",
                recommended_qty=0,
                confidence="high",
                explanation=(
                    f"Sales increased (ratio={change.get('ratio'):.2f}) but inventory position "
                    f"{calc.inventory_position} still covers target {calc.target_stock}."
                ),
                calculation=calc,
            )
        lead = primary["lead_time_days"]
        too_late = bool(risk.get("possible") and risk.get("days_of_cover", 99) < lead)
        opt = _option("increase", f"Increase plan by {extra}", "increase_order", extra, primary, inv)
        alternatives.append(opt)
        if too_late:
            south = tools.get_inventory_by_node(inv.event["sku"], "NODE-SOUTH")
            if south and south["available"] >= extra:
                alternatives.append(
                    AlternativeOption(
                        option_id="transfer",
                        description=f"Transfer {extra} from NODE-SOUTH (available {south['available']})",
                        action="transfer",
                        quantity=extra,
                        feasible=True,
                        reasons=["Lead time too long; node transfer is faster"],
                    )
                )
            alternatives.append(
                AlternativeOption(
                    option_id="escalate-late",
                    description="Escalate because replenishment would arrive after projected stockout",
                    action="escalate",
                    quantity=extra,
                    feasible=True,
                    reasons=[f"Lead time {lead}d > cover {risk.get('days_of_cover')}d"],
                )
            )
            selected = next((a for a in alternatives if a.action == "transfer" and a.feasible), alternatives[-1])
            return DecisionRecord(
                action=selected.action,
                recommended_qty=selected.quantity if selected.action != "escalate" else extra,
                supplier_id=primary["supplier_id"] if selected.action == "increase_order" else None,
                confidence="low",
                explanation=(
                    f"Material demand increase detected (ratio={change.get('ratio'):.2f}). "
                    f"Supplier lead time {lead}d may miss a stockout in {risk.get('days_of_cover'):.1f} days. "
                    f"Selected {selected.option_id}."
                ),
                calculation=calc,
                alternatives=alternatives,
                selected_option_id=selected.option_id,
                requires_approval=True,
                uncertainty=uncertainty + ["replenishment_may_be_too_late"],
            )
        if not opt.feasible:
            return DecisionRecord(
                action="escalate",
                recommended_qty=extra,
                confidence="medium",
                explanation=f"Additional {extra} units are justified by demand evidence but constraints block the order.",
                calculation=calc,
                constraints=opt.constraints,
                alternatives=alternatives,
                hard_constraint_violations=[c.name for c in opt.constraints if not c.passed],
                requires_approval=True,
                uncertainty=uncertainty,
            )
        return DecisionRecord(
            action="increase_order",
            recommended_qty=extra,
            supplier_id=primary["supplier_id"],
            unit_price=primary["unit_price"],
            total_cost=opt.cost,
            confidence="medium",
            explanation=(
                f"Actual sales exceeded forecast (ratio={change.get('ratio'):.2f}) over a reliable window. "
                f"Additional {extra} units recommended. Existing incoming {calc.incoming_confirmed} was not double-counted."
            ),
            calculation=calc,
            constraints=opt.constraints,
            alternatives=alternatives,
            selected_option_id="increase",
            requires_approval=tools.approvals.requires_approval(opt.cost or 0, uncertain=bool(uncertainty)),
            uncertainty=uncertainty,
        )

    # scenario s4 — constraint resolution
    qty = calc.recommended_rounded
    opt = _option("original", f"Original need {qty} from {primary['supplier_id']}", "accept", qty, primary, inv)
    alternatives.append(opt)
    if qty == 0:
        return DecisionRecord(
            action="no_action",
            recommended_qty=0,
            confidence="high",
            explanation="Inventory requirement is not real; no constrained purchase is needed.",
            calculation=calc,
        )
    if opt.feasible:
        act = "accept" if (inv.event.get("recommended_qty") is None or inv.event.get("recommended_qty") == qty) else "modify"
        return DecisionRecord(
            action=act,
            recommended_qty=qty,
            compared_qty=inv.event.get("recommended_qty"),
            supplier_id=primary["supplier_id"],
            unit_price=primary["unit_price"],
            total_cost=opt.cost,
            confidence="high",
            explanation=f"Requirement of {qty} is real and all hard constraints pass.",
            calculation=calc,
            constraints=opt.constraints,
            alternatives=alternatives,
            selected_option_id="original",
            requires_approval=tools.approvals.requires_approval(opt.cost or 0),
        )
    feasible_qty = max_feasible_qty(
        unit_price=primary["unit_price"],
        space_per_unit=(inv.product or {}).get("space_per_unit", 1.0),
        budget_remaining=(inv.budget or {}).get("remaining", 0),
        storage_free=(inv.storage or {}).get("free", 0),
        moq=primary["min_order_qty"],
        order_multiple=primary["order_multiple"],
        supplier_capacity=primary["remaining_capacity"],
        desired=qty,
    )
    if feasible_qty:
        alternatives.append(_option("reduced", f"Smaller compliant order {feasible_qty}", "modify", feasible_qty, primary, inv))
    for s in suppliers[1:]:
        q = round_qty(qty, s)
        alternatives.append(_option(f"alt-{s['supplier_id']}", f"Alternate {s['supplier_id']} qty {q}", "alternative_supplier", q, s, inv))
        fq = max_feasible_qty(
            unit_price=s["unit_price"],
            space_per_unit=(inv.product or {}).get("space_per_unit", 1.0),
            budget_remaining=(inv.budget or {}).get("remaining", 0),
            storage_free=(inv.storage or {}).get("free", 0),
            moq=s["min_order_qty"],
            order_multiple=s["order_multiple"],
            supplier_capacity=s["remaining_capacity"],
            desired=qty,
        )
        if fq and fq != q:
            alternatives.append(_option(f"alt-reduced-{s['supplier_id']}", f"Alternate reduced {fq}", "alternative_supplier", fq, s, inv))
    selected = next((a for a in alternatives if a.feasible and a.quantity > 0), None)
    if selected is None:
        return DecisionRecord(
            action="escalate",
            recommended_qty=qty,
            supplier_id=primary["supplier_id"],
            unit_price=primary["unit_price"],
            total_cost=qty * primary["unit_price"],
            confidence="high",
            explanation=(
                f"Requirement of {qty} is real but every alternative violates a hard constraint. "
                "Budget, storage, MOQ, or capacity will not be bypassed."
            ),
            calculation=calc,
            constraints=opt.constraints,
            alternatives=alternatives,
            hard_constraint_violations=[c.name for c in opt.constraints if not c.passed],
            requires_approval=True,
        )
    price = next(s["unit_price"] for s in suppliers if s["supplier_id"] == selected.supplier_id)
    return DecisionRecord(
        action=selected.action,
        recommended_qty=selected.quantity,
        supplier_id=selected.supplier_id,
        unit_price=price,
        total_cost=selected.cost,
        confidence="medium",
        explanation=(
            f"Original {qty} from {primary['supplier_id']} is infeasible. "
            f"Selected {selected.option_id}: {selected.description}."
        ),
        calculation=calc,
        constraints=selected.constraints,
        alternatives=alternatives,
        selected_option_id=selected.option_id,
        requires_approval=tools.approvals.requires_approval(selected.cost or 0),
        hard_constraint_violations=[c.name for c in opt.constraints if not c.passed],
    )


def round_qty(qty: int, supplier: dict) -> int:
    from app.agents.decision_engine import round_to_supplier_rules

    return round_to_supplier_rules(qty, supplier["min_order_qty"], supplier["order_multiple"])
