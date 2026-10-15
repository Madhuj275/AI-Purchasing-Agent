"""REST endpoints for the purchasing agent."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents.action_executor import InjectedFailure, execute_action
from app.agents.purchasing_agent import PurchasingAgent
from app.agents.validator import validate_action
from app.config import get_settings
from app.database import get_db
from app.models.entities import ActionRecord, AgentRun, AuditLog, HumanApproval, Product
from app.schemas.domain import ApprovalDecisionRequest, ScenarioRunRequest
from app.seed.demo_data import SCENARIO_EVENTS, apply_fixture, seed_database
from app.services.approval_service import ApprovalService
from app.tools.registry import ProcurementTools
from app.utils.ids import utcnow
from app.database import reset_db

router = APIRouter()


def _agent(db: Session) -> PurchasingAgent:
    return PurchasingAgent(db)


@router.get("/health")
def health() -> dict:
    settings = get_settings()
    llm = "langchain-agent" if settings.llm_provider != "none" and settings.llm_api_key else "deterministic"
    return {
        "status": "ok",
        "database": settings.database_url.split("://", 1)[0],
        "llm_mode": llm,
        "time": utcnow().isoformat(),
    }


@router.get("/products")
def products(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(Product).all()
    return [{"sku": p.sku, "name": p.name, "category": p.category, "unit_cost": p.unit_cost, "status": p.status} for p in rows]


@router.get("/inventory")
def inventory(db: Session = Depends(get_db)) -> list[dict]:
    tools = ProcurementTools(db)
    out = []
    for row in tools.inventory.list_inventory():
        out.append(
            {
                "sku": row.sku,
                "node_id": row.node_id,
                "on_hand": row.on_hand,
                "reserved": row.reserved,
                "available": row.on_hand - row.reserved,
            }
        )
    return out


@router.get("/suppliers")
def suppliers(db: Session = Depends(get_db)) -> list[dict]:
    tools = ProcurementTools(db)
    return [{"supplier_id": s.supplier_id, "name": s.name, "active": s.active, "reliability_score": s.reliability_score} for s in tools.suppliers.list_suppliers()]


@router.get("/purchase-orders")
def purchase_orders(db: Session = Depends(get_db)) -> list[dict]:
    tools = ProcurementTools(db)
    return [tools.pos.to_dict(p) for p in tools.pos.list_orders()]


@router.get("/approvals")
def approvals(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(HumanApproval).order_by(HumanApproval.created_at.desc()).all()
    return [
        {
            "approval_id": a.approval_id,
            "action_id": a.action_id,
            "run_id": a.run_id,
            "status": a.status,
            "approver": a.approver,
            "decision": a.decision,
        }
        for a in rows
    ]


@router.get("/audit")
def audit(db: Session = Depends(get_db), correlation_id: str | None = None) -> list[dict]:
    q = db.query(AuditLog)
    if correlation_id:
        q = q.filter(AuditLog.correlation_id == correlation_id)
    rows = q.order_by(AuditLog.created_at.desc()).limit(100).all()
    return [
        {
            "audit_id": a.audit_id,
            "actor": a.actor,
            "operation": a.operation,
            "entity": a.entity,
            "entity_id": a.entity_id,
            "reason": a.reason,
            "correlation_id": a.correlation_id,
            "created_at": a.created_at.isoformat(),
        }
        for a in rows
    ]


@router.get("/runs")
def runs(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(AgentRun).order_by(AgentRun.created_at.desc()).limit(50).all()
    return [
        {
            "run_id": r.run_id,
            "scenario_id": r.scenario_id,
            "fixture_key": r.fixture_key,
            "status": r.status,
            "outcome": r.outcome,
            "reasoning_mode": r.reasoning_mode,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.post("/scenarios/{scenario_id}/run")
def run_scenario(scenario_id: str, body: ScenarioRunRequest, db: Session = Depends(get_db)) -> dict:
    if scenario_id not in SCENARIO_EVENTS:
        raise HTTPException(404, "Unknown scenario")
    agent = _agent(db)
    result = agent.run(
        scenario_id,
        fixture_key=body.fixture_key,
        execute=body.execute,
        auto_approve=body.auto_approve,
        simulate_failure=body.simulate_failure,
    )
    return json.loads(result.model_dump_json())


@router.post("/scenarios/{scenario_id}/reset")
def reset_scenario(scenario_id: str, fixture_key: str = "default", db: Session = Depends(get_db)) -> dict:
    if scenario_id not in SCENARIO_EVENTS and scenario_id != "all":
        raise HTTPException(404, "Unknown scenario")
    try:
        reset_db()
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    seed_database(db, scenario_id=None)
    if scenario_id != "all":
        apply_fixture(db, scenario_id, fixture_key)
    db.commit()
    return {"ok": True, "scenario_id": scenario_id, "fixture_key": fixture_key}


@router.post("/agent/investigate")
def agent_investigate(scenario_id: str, fixture_key: str = "default", db: Session = Depends(get_db)) -> dict:
    agent = _agent(db)
    result = agent.run(scenario_id, fixture_key=fixture_key, execute=False, auto_approve=False)
    return json.loads(result.model_dump_json())


@router.post("/agent/plan")
def agent_plan(scenario_id: str, fixture_key: str = "default", db: Session = Depends(get_db)) -> dict:
    return agent_investigate(scenario_id, fixture_key, db)


@router.post("/purchase-orders")
def create_po(payload: dict, db: Session = Depends(get_db)) -> dict:
    raise HTTPException(403, "Direct PO creation is disabled; use the agent workflow")


@router.patch("/purchase-orders/{po_id}")
def patch_po(po_id: str, payload: dict, db: Session = Depends(get_db)) -> dict:
    raise HTTPException(403, "Direct PO mutation is disabled; use the agent workflow")


@router.post("/purchase-orders/{po_id}/supplier-confirmation")
def supplier_confirmation(po_id: str, confirmed_qty: int, db: Session = Depends(get_db)) -> dict:
    tools = ProcurementTools(db)
    po = tools.pos.get(po_id)
    if not po:
        raise HTTPException(404, "PO not found")
    updated = tools.pos.confirm_supplier_qty(po_id, confirmed_qty, message="API confirmation")
    db.commit()
    return tools.pos.to_dict(updated)


@router.post("/approvals/{approval_id}/approve")
def approve(approval_id: str, body: ApprovalDecisionRequest, db: Session = Depends(get_db)) -> dict:
    approval = db.get(HumanApproval, approval_id)
    if not approval:
        raise HTTPException(404, "Approval not found")
    action = db.get(ActionRecord, approval.action_id)
    if not action:
        raise HTTPException(404, "Action not found")
    svc = ApprovalService(db)
    try:
        row = svc.decide(approval_id, True, body.approver, body.reason, json.loads(action.proposed_payload))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return {"approval_id": row.approval_id, "status": row.status, "demo": True}


@router.post("/approvals/{approval_id}/reject")
def reject(approval_id: str, body: ApprovalDecisionRequest, db: Session = Depends(get_db)) -> dict:
    approval = db.get(HumanApproval, approval_id)
    if not approval:
        raise HTTPException(404, "Approval not found")
    action = db.get(ActionRecord, approval.action_id)
    if not action:
        raise HTTPException(404, "Action not found")
    svc = ApprovalService(db)
    try:
        row = svc.decide(approval_id, False, body.approver, body.reason, json.loads(action.proposed_payload))
        action.status = "rejected"
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return {"approval_id": row.approval_id, "status": row.status, "demo": True}


@router.post("/actions/{action_id}/execute")
def execute(action_id: str, simulate_failure: str | None = None, db: Session = Depends(get_db)) -> dict:
    action = db.get(ActionRecord, action_id)
    if not action:
        raise HTTPException(404, "Action not found")
    tools = ProcurementTools(db)
    svc = ApprovalService(db)
    payload = json.loads(action.proposed_payload)
    if action.requires_approval and not svc.is_valid_for_action(action, payload):
        raise HTTPException(403, "Approval required or fingerprint mismatch")
    try:
        result = execute_action(db, tools, action, simulate_failure=simulate_failure)
    except (InjectedFailure, ValueError) as exc:
        db.commit()
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return result


@router.post("/actions/{action_id}/validate")
def validate(action_id: str, db: Session = Depends(get_db)) -> dict:
    action = db.get(ActionRecord, action_id)
    if not action:
        raise HTTPException(404, "Action not found")
    run = db.get(AgentRun, action.run_id)
    tools = ProcurementTools(db)
    from app.schemas.domain import DecisionRecord

    decision = DecisionRecord.model_validate_json(run.decision) if run and run.decision else DecisionRecord(action="investigate", recommended_qty=0, explanation="missing")
    approvals = db.query(HumanApproval).filter_by(action_id=action_id).all()
    report = validate_action(tools, action, decision, approvals)
    action.validation_outcome = report.outcome
    db.commit()
    return json.loads(report.model_dump_json())


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)) -> dict:
    tools = ProcurementTools(db)
    products = tools.inventory.list_products()
    nodes = tools.inventory.list_nodes()
    inv = tools.inventory.list_inventory()
    low = tools.inventory.low_stock()
    pos = [p for p in tools.pos.list_orders() if p.status not in {"cancelled", "closed", "rejected"}]
    budgets = tools.budget.list_budgets()
    storage = tools.storage.list_storage()
    pending = tools.approvals.list_pending()
    runs = db.query(AgentRun).order_by(AgentRun.created_at.desc()).limit(8).all()
    shortages = [p for p in pos if p.confirmed_qty is not None and p.confirmed_qty < p.ordered_qty]
    return {
        "products": len(products),
        "nodes": len(nodes),
        "open_pos": len(pos),
        "low_stock": [{"sku": r.sku, "node_id": r.node_id, "available": r.on_hand - r.reserved} for r in low],
        "pending_approvals": len(pending),
        "supplier_shortages": [{"po_id": p.po_id, "ordered": p.ordered_qty, "confirmed": p.confirmed_qty} for p in shortages],
        "budgets": [{"node_id": b.node_id, "category": b.category, "allocated": b.allocated, "remaining": b.remaining} for b in budgets],
        "storage": [{"node_id": s.node_id, "util": s.current_utilization, "cap": s.total_capacity} for s in storage],
        "runs": [{"run_id": r.run_id, "scenario_id": r.scenario_id, "outcome": r.outcome, "status": r.status} for r in runs],
        "inventory_rows": len(inv),
    }
