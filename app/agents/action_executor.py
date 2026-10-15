"""Execute approved purchasing actions against the mock procurement system."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.entities import ActionRecord, AgentRun
from app.schemas.domain import ActionProposal, DecisionRecord, InvestigationReport
from app.services.approval_service import fingerprint
from app.tools.registry import ProcurementTools
from app.utils.ids import idempotency_key, new_id, utcnow


class InjectedFailure(Exception):
    pass


def build_proposal(run_id: str, inv: InvestigationReport, decision: DecisionRecord) -> ActionProposal | None:
    if decision.action in {"investigate", "escalate", "reject", "keep_plan", "no_action", "defer"}:
        if decision.action == "reject" or decision.action in {"keep_plan", "no_action", "defer", "investigate", "escalate"}:
            # still record a non-mutating action for audit
            payload = {
                "kind": "none",
                "action": decision.action,
                "sku": inv.event["sku"],
                "node_id": inv.event["node_id"],
            }
            key = idempotency_key(run_id, decision.action, inv.fixture_key)
            return ActionProposal(
                action_type=decision.action,
                payload=payload,
                idempotency_key=key,
                requires_approval=decision.requires_approval and decision.action == "escalate",
                fingerprint=fingerprint(payload),
            )
    sku = inv.event["sku"]
    node_id = inv.event["node_id"]
    if decision.action in {"accept", "modify", "increase_order"} and decision.recommended_qty > 0 and decision.supplier_id:
        payload = {
            "kind": "create_po",
            "sku": sku,
            "node_id": node_id,
            "supplier_id": decision.supplier_id,
            "qty": decision.recommended_qty,
            "unit_price": decision.unit_price,
        }
        if inv.scenario_id == "s1" and decision.action == "modify":
            payload["kind"] = "create_po"
        key = idempotency_key("create", sku, node_id, decision.supplier_id, str(decision.recommended_qty), inv.fixture_key)
        return ActionProposal(
            action_type="create_purchase_order",
            payload=payload,
            idempotency_key=key,
            requires_approval=decision.requires_approval,
            fingerprint=fingerprint(payload),
        )
    if decision.action in {"split_order", "alternative_supplier"} and decision.recommended_qty > 0:
        if inv.event.get("po_id"):
            payload = {
                "kind": "split_and_supplement",
                "original_po_id": inv.event.get("po_id"),
                "confirmed_qty": inv.event.get("confirmed_qty", 250),
                "sku": sku,
                "node_id": node_id,
                "supplier_id": decision.supplier_id,
                "qty": decision.recommended_qty,
                "unit_price": decision.unit_price,
            }
            key = idempotency_key("split", inv.event.get("po_id"), str(inv.event.get("confirmed_qty")), decision.supplier_id, str(decision.recommended_qty))
            return ActionProposal(
                action_type="split_and_supplement",
                payload=payload,
                idempotency_key=key,
                requires_approval=decision.requires_approval,
                fingerprint=fingerprint(payload),
            )
        else:
            payload = {
                "kind": "create_po",
                "sku": sku,
                "node_id": node_id,
                "supplier_id": decision.supplier_id,
                "qty": decision.recommended_qty,
                "unit_price": decision.unit_price,
            }
            key = idempotency_key("create", sku, node_id, decision.supplier_id, str(decision.recommended_qty), inv.fixture_key)
            return ActionProposal(
                action_type="create_purchase_order",
                payload=payload,
                idempotency_key=key,
                requires_approval=decision.requires_approval,
                fingerprint=fingerprint(payload),
            )
    if decision.action == "modify" and inv.scenario_id == "s2":
        payload = {
            "kind": "confirm_reduce",
            "original_po_id": inv.event.get("po_id"),
            "confirmed_qty": inv.event.get("confirmed_qty", 250),
        }
        key = idempotency_key("confirm", inv.event.get("po_id"), str(inv.event.get("confirmed_qty")))
        return ActionProposal(
            action_type="confirm_supplier_quantity",
            payload=payload,
            idempotency_key=key,
            requires_approval=False,
            fingerprint=fingerprint(payload),
        )
    if decision.action == "transfer":
        payload = {
            "kind": "transfer",
            "sku": sku,
            "from_node": "NODE-SOUTH",
            "to_node": node_id,
            "qty": decision.recommended_qty,
        }
        key = idempotency_key("transfer", sku, node_id, str(decision.recommended_qty), inv.fixture_key)
        return ActionProposal(
            action_type="transfer_stock",
            payload=payload,
            idempotency_key=key,
            requires_approval=True,
            fingerprint=fingerprint(payload),
        )
    return None


def persist_action(session: Session, run: AgentRun, proposal: ActionProposal) -> ActionRecord:
    existing = session.query(ActionRecord).filter_by(idempotency_key=proposal.idempotency_key).one_or_none()
    if existing:
        return existing
    row = ActionRecord(
        action_id=new_id("ACT"),
        run_id=run.run_id,
        action_type=proposal.action_type,
        status="proposed",
        proposed_payload=json.dumps(proposal.payload, default=str),
        execution_result=None,
        before_state=None,
        after_state=None,
        validation_outcome=None,
        idempotency_key=proposal.idempotency_key,
        requires_approval=proposal.requires_approval,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(row)
    session.flush()
    return row


def execute_action(
    session: Session,
    tools: ProcurementTools,
    action: ActionRecord,
    simulate_failure: str | None = None,
) -> dict[str, Any]:
    payload = json.loads(action.proposed_payload)
    kind = payload.get("kind")
    if kind == "none":
        action.status = "completed_no_mutation"
        action.execution_result = json.dumps({"ok": True, "mutated": False})
        action.updated_at = utcnow()
        return {"ok": True, "mutated": False, "purchase_orders": []}

    if action.status == "executed":
        return json.loads(action.execution_result or "{}")

    if simulate_failure == "storage_race" and kind in {"create_po", "split_and_supplement"}:
        storage = tools.storage.get(payload["node_id"])
        if storage:
            storage.current_utilization = storage.total_capacity
            session.flush()
        action.status = "failed"
        action.execution_result = json.dumps({"ok": False, "error": "storage_race"})
        action.updated_at = utcnow()
        raise InjectedFailure("Storage utilization filled before execution")

    if simulate_failure == "persist_fail":
        action.status = "failed"
        action.execution_result = json.dumps({"ok": False, "error": "persist_fail"})
        action.updated_at = utcnow()
        raise InjectedFailure("Simulated persistence failure")

    before = _snapshot(tools, payload)
    created: list[str] = []
    product = tools.get_product_details(payload.get("sku") or "")
    category = (product or {}).get("category", "grocery")

    if kind == "create_po":
        qty = int(payload["qty"])
        price = float(payload["unit_price"])
        cost = tools.calculate_order_cost(qty, price)
        existing_po = tools.pos.find_by_idempotency(action.idempotency_key)
        if existing_po:
            created.append(existing_po.po_id)
        else:
            if not tools.budget.can_commit(payload["node_id"], category, cost):
                raise ValueError("Budget hard constraint blocked execution")
            if not tools.storage.can_store(payload["node_id"], payload["sku"], qty):
                raise ValueError("Storage hard constraint blocked execution")
            cap = tools.check_supplier_capacity(payload["supplier_id"], payload["sku"], qty)
            if not cap["ok"]:
                raise ValueError("Supplier capacity hard constraint blocked execution")
            sup = tools.get_supplier_details(payload["supplier_id"], payload["sku"])
            assert sup is not None
            po = tools.pos.create(
                supplier_id=payload["supplier_id"],
                sku=payload["sku"],
                node_id=payload["node_id"],
                qty=qty,
                unit_price=price,
                lead_time_days=sup["lead_time_days"],
                idempotency_key=action.idempotency_key,
                notes=f"Created by agent action {action.action_id}",
            )
            tools.budget.commit(payload["node_id"], category, cost)
            tools.storage.reserve(payload["node_id"], payload["sku"], qty)
            created.append(po.po_id)

    elif kind == "confirm_reduce":
        po = tools.pos.confirm_supplier_qty(payload["original_po_id"], int(payload["confirmed_qty"]), message="")
        created.append(po.po_id)

    elif kind == "split_and_supplement":
        original = tools.pos.confirm_supplier_qty(
            payload["original_po_id"],
            int(payload["confirmed_qty"]),
            message="Supplier can only fulfil confirmed quantity",
        )
        created.append(original.po_id)
        qty = int(payload["qty"])
        price = float(payload["unit_price"])
        cost = tools.calculate_order_cost(qty, price)
        if not tools.budget.can_commit(payload["node_id"], category, cost):
            raise ValueError("Budget hard constraint blocked execution")
        if not tools.storage.can_store(payload["node_id"], payload["sku"], qty):
            raise ValueError("Storage hard constraint blocked execution")
        cap = tools.check_supplier_capacity(payload["supplier_id"], payload["sku"], qty)
        if not cap["ok"]:
            raise ValueError("Supplier capacity hard constraint blocked execution")
        sup = tools.get_supplier_details(payload["supplier_id"], payload["sku"])
        assert sup is not None
        supp_key = action.idempotency_key + "-supp"
        existing_supp = tools.pos.find_by_idempotency(supp_key)
        if existing_supp:
            created.append(existing_supp.po_id)
        else:
            supp = tools.pos.create(
                supplier_id=payload["supplier_id"],
                sku=payload["sku"],
                node_id=payload["node_id"],
                qty=qty,
                unit_price=price,
                lead_time_days=sup["lead_time_days"],
                idempotency_key=supp_key,
                parent_po_id=original.po_id,
                notes=f"Supplementary PO for shortage on {original.po_id}",
            )
            tools.budget.commit(payload["node_id"], category, cost)
            tools.storage.reserve(payload["node_id"], payload["sku"], qty)
            created.append(supp.po_id)

    elif kind == "transfer":
        src = tools.inventory.get_inventory(payload["sku"], payload["from_node"])
        dst = tools.inventory.get_inventory(payload["sku"], payload["to_node"])
        qty = int(payload["qty"])
        if src is None or dst is None or src.on_hand - src.reserved < qty:
            raise ValueError("Transfer not feasible")
        src.on_hand -= qty
        dst.on_hand += qty
        session.flush()
    else:
        raise ValueError(f"Unknown action kind {kind}")

    after = _snapshot(tools, payload)
    result = {"ok": True, "mutated": True, "purchase_orders": created, "after": after}
    action.status = "executed"
    action.before_state = json.dumps(before, default=str)
    action.after_state = json.dumps(after, default=str)
    action.execution_result = json.dumps(result, default=str)
    action.updated_at = utcnow()
    tools.audit.record(
        actor="purchasing-agent",
        operation="execute_action",
        entity="action_record",
        entity_id=action.action_id,
        correlation_id=action.run_id,
        before=before,
        after=after,
        reason=action.action_type,
    )
    session.flush()
    return result


def _snapshot(tools: ProcurementTools, payload: dict[str, Any]) -> dict[str, Any]:
    sku = payload.get("sku")
    node_id = payload.get("node_id")
    pos = []
    if sku and node_id:
        pos = tools.get_open_purchase_orders(sku, node_id)
    elif payload.get("original_po_id"):
        detail = tools.get_purchase_order_details(payload["original_po_id"])
        pos = [detail] if detail else []
        if detail:
            sku = detail["sku"]
            node_id = detail["node_id"]
    inv = tools.get_inventory_by_node(sku, node_id) if sku and node_id else None
    budget = None
    if sku and node_id:
        product = tools.get_product_details(sku)
        if product:
            b = tools.budget.get(node_id, product["category"])
            if b:
                budget = {"remaining": b.remaining, "committed": b.committed}
    storage = None
    if node_id:
        s = tools.storage.get(node_id)
        if s:
            storage = {"free": tools.storage.free_space(node_id), "util": s.current_utilization, "reserved": s.reserved_space}
    return {"inventory": inv, "purchase_orders": pos, "budget": budget, "storage": storage}
