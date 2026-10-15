"""Independent validation against persisted procurement state."""

from __future__ import annotations

import json
from typing import Any

from app.schemas.domain import DecisionRecord, ValidationCheck, ValidationReport
from app.tools.registry import ProcurementTools
from app.models.entities import ActionRecord, HumanApproval


def validate_action(
    tools: ProcurementTools,
    action: ActionRecord,
    decision: DecisionRecord,
    approvals: list[HumanApproval] | None = None,
) -> ValidationReport:
    payload = json.loads(action.proposed_payload)
    kind = payload.get("kind")
    checks: list[ValidationCheck] = []

    if kind == "none":
        checks.append(ValidationCheck(name="no_mutation", passed=True, detail="No purchasing mutation was intended"))
        outcome = "ESCALATED" if decision.action == "escalate" else "SUCCESS"
        if decision.action == "investigate":
            outcome = "INVESTIGATE"
        if decision.action in {"reject", "keep_plan", "no_action", "defer"}:
            outcome = "SUCCESS"
        return ValidationReport(outcome=outcome, checks=checks, expected=payload, actual={"mutated": False})  # type: ignore[arg-type]

    if action.status == "failed":
        return ValidationReport(
            outcome="FAILED",
            checks=[ValidationCheck(name="execution", passed=False, detail=action.execution_result or "failed")],
            expected=payload,
            actual={"status": action.status},
        )

    sku = payload.get("sku")
    node_id = payload.get("node_id")
    result = json.loads(action.execution_result or "{}")
    po_ids = result.get("purchase_orders") or []

    if kind in {"create_po", "split_and_supplement"}:
        target_id = po_ids[-1] if po_ids else None
        po = tools.get_purchase_order_details(target_id) if target_id else None
        checks.append(ValidationCheck(name="po_exists", passed=po is not None, expected=target_id, actual=po["po_id"] if po else None))
        if po:
            checks.append(ValidationCheck(name="supplier_match", passed=po["supplier_id"] == payload["supplier_id"], expected=payload["supplier_id"], actual=po["supplier_id"]))
            checks.append(ValidationCheck(name="sku_match", passed=po["sku"] == sku, expected=sku, actual=po["sku"]))
            checks.append(ValidationCheck(name="node_match", passed=po["node_id"] == node_id, expected=node_id, actual=po["node_id"]))
            checks.append(ValidationCheck(name="qty_match", passed=po["ordered_qty"] == payload["qty"], expected=payload["qty"], actual=po["ordered_qty"]))
            checks.append(ValidationCheck(name="price_match", passed=abs(po["unit_price"] - float(payload["unit_price"])) < 1e-6, expected=payload["unit_price"], actual=po["unit_price"]))
            checks.append(ValidationCheck(name="status_valid", passed=po["status"] in {"open", "confirmed"}, expected="open|confirmed", actual=po["status"]))
        cap = tools.check_supplier_capacity(payload["supplier_id"], sku, 0)
        checks.append(ValidationCheck(name="supplier_capacity_respected", passed=cap["remaining"] >= 0, actual=cap["remaining"]))
        product = tools.get_product_details(sku)
        if product:
            budget = tools.check_budget(node_id, product["category"], 0)
            checks.append(ValidationCheck(name="budget_not_negative", passed=(budget["remaining"] or 0) >= -1e-6, actual=budget["remaining"]))
        storage = tools.check_storage_capacity(node_id, sku, 0)
        checks.append(ValidationCheck(name="storage_not_overfilled", passed=storage["free"] >= -1e-6, actual=storage["free"]))

    if kind == "split_and_supplement":
        original = tools.get_purchase_order_details(payload["original_po_id"])
        checks.append(ValidationCheck(name="original_reduced", passed=bool(original and original["ordered_qty"] == int(payload["confirmed_qty"])), expected=payload["confirmed_qty"], actual=original["ordered_qty"] if original else None))
        # duplicate quantity check
        if original and len(po_ids) >= 2:
            supp = tools.get_purchase_order_details(po_ids[-1])
            total = original["ordered_qty"] + (supp["ordered_qty"] if supp else 0)
            expected_total = int(payload["confirmed_qty"]) + int(payload["qty"])
            checks.append(ValidationCheck(name="no_duplicate_qty", passed=total == expected_total, expected=expected_total, actual=total))

    if kind == "confirm_reduce":
        original = tools.get_purchase_order_details(payload["original_po_id"])
        checks.append(ValidationCheck(name="confirmed_qty", passed=bool(original and original["ordered_qty"] == int(payload["confirmed_qty"])), expected=payload["confirmed_qty"], actual=original["ordered_qty"] if original else None))

    if kind == "transfer":
        dst = tools.get_inventory_by_node(sku, payload["to_node"])
        checks.append(ValidationCheck(name="transfer_applied", passed=dst is not None, actual=dst))

    if action.requires_approval:
        ok = False
        for a in approvals or []:
            if a.action_id == action.action_id and a.status == "approved":
                ok = True
        checks.append(ValidationCheck(name="approval_present", passed=ok, expected="approved", actual="missing" if not ok else "approved"))

    failed = [c for c in checks if not c.passed]
    if failed:
        outcome = "FAILED"
    elif decision.action == "split_order":
        outcome = "PARTIAL_SUCCESS"
    else:
        outcome = "SUCCESS"

    actual: dict[str, Any] = {"purchase_orders": []}
    for pid in po_ids:
        detail = tools.get_purchase_order_details(pid)
        if detail:
            actual["purchase_orders"].append(detail)
    return ValidationReport(outcome=outcome, checks=checks, expected=payload, actual=actual)  # type: ignore[arg-type]
