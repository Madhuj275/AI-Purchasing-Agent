"""Polished Gradio Blocks dashboard for the purchasing agent demo."""

from __future__ import annotations

import json

import gradio as gr
from sqlalchemy.orm import Session

from app.agents.purchasing_agent import PurchasingAgent
from app.database import get_session_factory
from app.models.entities import ActionRecord, AgentRun, AuditLog, HumanApproval, Product
from app.seed.demo_data import SCENARIO_EVENTS, apply_fixture, seed_database
from app.services.approval_service import ApprovalService
from app.tools.registry import ProcurementTools

SCENARIO_CHOICES = [
    ("S1 — Purchase Recommendation Review", "s1"),
    ("S2 — Rice Supplier Recommendation", "s2"),
    ("S3 — Demand / Forecast Changed", "s3"),
    ("S4 — Purchasing Constraint", "s4"),
]

FIXTURES = {
    "s1": ["default", "appropriate", "excessive", "sufficient", "insufficient", "missing_forecast", "stale_forecast", "contradiction", "budget", "storage", "moq", "cancelled_incoming"],
    "s2": ["default", "alt_supplier", "inventory_covers", "stockout_escalate"],
    "s3": ["default", "increase_justified", "po_sufficient",  "too_late", "constraint"],
    "s4": ["default", "budget", "storage", "moq", "capacity", "multi", "feasible_alt", "approval"],
}


def _session() -> Session:
    return get_session_factory()()


def _overview_md() -> str:
    db = _session()
    try:
        tools = ProcurementTools(db)
        products = tools.inventory.list_products()
        nodes = tools.inventory.list_nodes()
        low = tools.inventory.low_stock()
        pos = [p for p in tools.pos.list_orders() if p.status not in {"cancelled", "closed", "rejected"}]
        pending = tools.approvals.list_pending()
        budgets = tools.budget.list_budgets()
        storage = tools.storage.list_storage()
        runs = db.query(AgentRun).order_by(AgentRun.created_at.desc()).limit(6).all()
        shortages = [p for p in pos if p.confirmed_qty is not None and p.confirmed_qty < p.ordered_qty]
        budget_bits = ", ".join(f"{b.node_id}/{b.category}: {b.remaining:.0f}/{b.allocated:.0f}" for b in budgets[:6])
        storage_bits = ", ".join(f"{s.node_id}: {s.current_utilization:.0f}/{s.total_capacity:.0f}" for s in storage)
        run_bits = "<br>".join(f"`{r.run_id}` {r.scenario_id}/{r.fixture_key} → **{r.outcome or r.status}**" for r in runs) or "_No runs yet_"
        low_bits = ", ".join(f"{r.sku}@{r.node_id} ({r.on_hand - r.reserved})" for r in low[:8]) or "none"
        return f"""
### Operations snapshot
| Metric | Value |
|---|---|
| Products | **{len(products)}** |
| Fulfillment nodes | **{len(nodes)}** |
| Open purchase orders | **{len(pos)}** |
| Low-stock SKUs | **{len(low)}** ({low_bits}) |
| Supplier shortages | **{len(shortages)}** |
| Pending approvals | **{len(pending)}** |
| Budget remaining | {budget_bits} |
| Storage | {storage_bits} |

#### Recent agent runs
{run_bits}
"""
    finally:
        db.close()


def _table_inventory():
    db = _session()
    try:
        tools = ProcurementTools(db)
        rows = []
        for r in tools.inventory.list_inventory():
            rows.append([r.sku, r.node_id, r.on_hand, r.reserved, r.on_hand - r.reserved])
        return rows
    finally:
        db.close()


def _table_pos():
    db = _session()
    try:
        tools = ProcurementTools(db)
        return [[p.po_id, p.sku, p.node_id, p.supplier_id, p.ordered_qty, p.received_qty, p.status, p.unit_price] for p in tools.pos.list_orders()]
    finally:
        db.close()


def _table_suppliers():
    db = _session()
    try:
        tools = ProcurementTools(db)
        rows = []
        for s in tools.suppliers.list_suppliers():
            for o in s.offerings:
                rows.append([s.supplier_id, s.name, o.sku, o.unit_price, o.lead_time_days, o.min_order_qty, o.order_multiple, o.capacity, o.available])
        return rows
    finally:
        db.close()


def _table_forecasts():
    db = _session()
    try:
        tools = ProcurementTools(db)
        return [[f.sku, f.node_id, f.daily_demand, f.forecast_quantity, f.horizon_days, f.forecast_timestamp.isoformat()] for f in tools.demand.list_forecasts()]
    finally:
        db.close()


def _table_budgets():
    db = _session()
    try:
        tools = ProcurementTools(db)
        return [[b.period, b.node_id, b.category, b.allocated, b.committed, b.remaining] for b in tools.budget.list_budgets()]
    finally:
        db.close()


def _table_storage():
    db = _session()
    try:
        tools = ProcurementTools(db)
        return [[s.node_id, s.total_capacity, s.current_utilization, s.reserved_space, tools.storage.free_space(s.node_id)] for s in tools.storage.list_storage()]
    finally:
        db.close()


def _table_approvals():
    db = _session()
    try:
        rows = db.query(HumanApproval).order_by(HumanApproval.created_at.desc()).all()
        return [[a.approval_id, a.action_id, a.status, a.approver or "", a.decision or "", a.created_at.isoformat()] for a in rows]
    finally:
        db.close()


def _table_audit():
    db = _session()
    try:
        rows = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(40).all()
        return [[a.audit_id, a.operation, a.entity, a.entity_id, a.reason or "", a.correlation_id] for a in rows]
    finally:
        db.close()


def reset_all():
    db = _session()
    try:
        if db.query(Product).count() == 0:
            seed_database(db)
        else:
            for scenario_id in SCENARIO_EVENTS:
                apply_fixture(db, scenario_id, "default")
            db.commit()
        return _overview_md(), *_refresh_tables()
    finally:
        db.close()


def reset_fixture(scenario_label: str, fixture_key: str):
    scenario_id = dict(SCENARIO_CHOICES).get(scenario_label, scenario_label)
    if scenario_id in dict(SCENARIO_CHOICES).values():
        pass
    mapping = {label: value for label, value in SCENARIO_CHOICES}
    scenario_id = mapping.get(scenario_label, scenario_label)
    db = _session()
    try:
        agent = PurchasingAgent(db)
        agent.reset_fixture(scenario_id, fixture_key)
        event = SCENARIO_EVENTS[scenario_id]["event"]
        return f"Reset **{scenario_id}:{fixture_key}**.\n\nStarting event: {event}", _overview_md(), *_refresh_tables()
    finally:
        db.close()


def run_workflow(scenario_label: str, fixture_key: str, execute: bool, auto_approve: bool, simulate_failure: str):
    mapping = {label: value for label, value in SCENARIO_CHOICES}
    scenario_id = mapping.get(scenario_label, "s1")
    fail = None if simulate_failure in {"", "none"} else simulate_failure
    db = _session()
    try:
        agent = PurchasingAgent(db)
        result = agent.run(
            scenario_id,
            fixture_key=fixture_key,
            # execute=execute,
            # auto_approve=auto_approve,
            # simulate_failure=fail,
        )
        inv = result.investigation
        dec = result.decision
        calc = dec.calculation
        evidence = "No product evidence" if not inv.product else (
            f"**Product** {inv.product['sku']} {inv.product['name']} | **Node** {inv.node['name'] if inv.node else ''} | "
            f"**On hand** {inv.inventory['on_hand'] if inv.inventory else 'n/a'} reserved {inv.inventory['reserved'] if inv.inventory else 'n/a'}\n\n"
            f"**Forecast** {inv.forecast} \n\n**Missing** {inv.missing or 'none'} | **Stale** {inv.stale or 'none'} | **Contradictions** {inv.contradictions or 'none'}"
        )
        calc_md = "_No calculation (investigation blocked)_"
        if calc:
            calc_md = f"""
| Input / intermediate | Value |
|---|---|
| Available | {calc.available} |
| Incoming confirmed | {calc.incoming_confirmed} |
| Incoming unconfirmed (excluded) | {calc.incoming_unconfirmed} |
| Inventory position | **{calc.inventory_position}** |
| Daily demand | {calc.daily_demand} |
| Protection period (days) | {calc.protection_period_days} |
| Forecast demand | {calc.forecast_demand_protection} |
| Safety stock | {calc.safety_stock} |
| Target stock | **{calc.target_stock}** |
| Recommended raw | **{calc.recommended_raw}** |
| Rounded | {calc.recommended_rounded} |
"""
        constraints = "\n".join(
            f"- {'PASS' if c.passed else 'FAIL'} **{c.name}** ({'hard' if c.hard else 'soft'}): {c.detail}"
            for c in dec.constraints
        ) or "_No constraint checks (no buy)_"
        alts = "\n".join(
            f"- `{a.option_id}` {'FEASIBLE' if a.feasible else 'INFEASIBLE'} — {a.description} ({'; '.join(a.reasons)})"
            for a in dec.alternatives
        ) or "_No alternatives_"
        val = "_Not executed_"
        if result.validation:
            checks = "\n".join(
                f"- {'PASS' if c.passed else 'FAIL'} **{c.name}**: expected `{c.expected}` actual `{c.actual}` — {c.detail}"
                for c in result.validation.checks
            )
            val = f"**Outcome: {result.validation.outcome}**\n\n{checks}\n\nRecovery: {result.validation.recovery or 'n/a'}"
        decision_md = f"""
## Decision
- **Best supplier:** {next((s['name'] for s in inv.suppliers if s['supplier_id'] == dec.supplier_id), dec.supplier_id or 'None')} (`{dec.supplier_id or 'n/a'}`)
- Action: **{dec.action}**
- Quantity: **{dec.recommended_qty}**
- Supplier: `{dec.supplier_id}`
- Cost: {dec.total_cost}
- Confidence: {dec.confidence}
- Requires approval: {dec.requires_approval}
- Reasoning mode: **{result.reasoning_mode}** (quantities, costs, and hard constraints are revalidated by the application)

### Explanation
{result.explanation}
"""
        timeline = "\n".join(f"- {json.dumps(item)}" for item in result.timeline)
        header = f"Run `{result.run_id}` | outcome **{result.outcome}** | status `{result.status}` | executed={result.executed} | action `{result.action_id}` | approval `{result.approval_id}`"
        return (
            header,
            evidence,
            calc_md,
            constraints,
            alts,
            decision_md,
            val,
            timeline,
            _overview_md(),
            *_refresh_tables(),
        )
    except Exception as exc:
        return (f"Error: {exc}", "", "", "", "", "", "", "", _overview_md(), *_refresh_tables())
    finally:
        db.close()


def approve_action(approval_id: str, approve: bool):
    db = _session()
    try:
        row = db.get(HumanApproval, approval_id.strip())
        if not row:
            return "Approval ID not found (demo queue only — not real authentication).", _table_approvals()
        action = db.get(ActionRecord, row.action_id)
        svc = ApprovalService(db)
        svc.decide(row.approval_id, approve, "buyer.demo", "Dashboard demo decision", json.loads(action.proposed_payload))
        db.commit()
        return f"Approval {row.approval_id} → {row.status}. This is a mock demo approver, not real auth.", _table_approvals()
    except Exception as exc:
        db.rollback()
        return str(exc), _table_approvals()
    finally:
        db.close()


def execute_pending(action_id: str):
    db = _session()
    try:
        from app.agents.action_executor import execute_action
        from app.agents.validator import validate_action
        from app.schemas.domain import DecisionRecord

        action = db.get(ActionRecord, action_id.strip())
        if not action:
            return "Action not found."
        tools = ProcurementTools(db)
        svc = ApprovalService(db)
        payload = json.loads(action.proposed_payload)
        if action.requires_approval and not svc.is_valid_for_action(action, payload):
            return "Blocked: approval missing or fingerprint mismatch."
        result = execute_action(db, tools, action)
        run = db.get(AgentRun, action.run_id)
        decision = DecisionRecord.model_validate_json(run.decision)
        report = validate_action(tools, action, decision, db.query(HumanApproval).filter_by(action_id=action.action_id).all())
        action.validation_outcome = report.outcome
        db.commit()
        return f"Executed. Validation **{report.outcome}**. POs={result.get('purchase_orders')}"
    except Exception as exc:
        db.rollback()
        return str(exc)
    finally:
        db.close()


def _refresh_tables():
    return (
        _table_inventory(),
        _table_pos(),
        _table_suppliers(),
        _table_forecasts(),
        _table_budgets(),
        _table_storage(),
        _table_approvals(),
        _table_audit(),
    )


def build_ui() -> gr.Blocks:
    theme = gr.themes.Soft(primary_hue="emerald", neutral_hue="slate")
    with gr.Blocks(title="AI Purchasing Agent", theme=theme) as demo:
        gr.Markdown(
            """
# AI Purchasing Agent
Retail / quick-commerce copilot: investigate → calculate → constrain → approve → execute → **validate persisted state**.

The LLM never owns quantities, budget checks, or approvals. Without an API key the explainer is a **deterministic fallback**.
"""
        )
        with gr.Tabs():
            with gr.Tab("Overview"):
                overview = gr.Markdown()
                refresh = gr.Button("Refresh dashboard", variant="primary")
            with gr.Tab("Scenario center"):
                with gr.Row():
                    scenario = gr.Dropdown(choices=[c[0] for c in SCENARIO_CHOICES], value=SCENARIO_CHOICES[0][0], label="Scenario")
                    fixture = gr.Dropdown(choices=FIXTURES["s1"], value="default", label="Fixture")
                #with gr.Row():
                    # execute = gr.Checkbox(label="Execute eligible action", value=False)
                    # auto_approve = gr.Checkbox(label="Auto-approve (demo)", value=False)
                    #failure = gr.Dropdown(choices=["none", "storage_race", "persist_fail"], value="none", label="Injected failure")
                with gr.Row():
                    btn_reset = gr.Button("Reset fixture")
                    btn_run = gr.Button("Investigate / plan / run", variant="primary")
                reset_msg = gr.Markdown()
                run_header = gr.Markdown()
                with gr.Accordion("Investigation evidence", open=True):
                    evidence = gr.Markdown()
                with gr.Accordion("Replenishment calculation", open=True):
                    calc = gr.Markdown()
                with gr.Accordion("Constraints and alternatives", open=True):
                    constraints = gr.Markdown()
                    alts = gr.Markdown()
                with gr.Accordion("Decision", open=True):
                    decision = gr.Markdown()
                with gr.Accordion("Validation and timeline", open=True):
                    validation = gr.Markdown()
                    timeline = gr.Markdown()

                def update_fixtures(label):
                    mapping = {a: b for a, b in SCENARIO_CHOICES}
                    sid = mapping.get(label, "s1")
                    return gr.update(choices=FIXTURES[sid], value="default")

                scenario.change(update_fixtures, inputs=scenario, outputs=fixture)
            with gr.Tab("Approvals"):
                gr.Markdown("**Mock approval queue** — demo identity `buyer.demo`, not real authentication.")
                approval_table = gr.Dataframe(headers=["approval_id", "action_id", "status", "approver", "decision", "created"], wrap=True)
                approval_id = gr.Textbox(label="Approval ID")
                with gr.Row():
                    btn_ok = gr.Button("Approve", variant="primary")
                    btn_no = gr.Button("Reject")
                approval_msg = gr.Markdown()
                action_id = gr.Textbox(label="Action ID to execute after approval")
                btn_exec = gr.Button("Execute approved action")
                exec_msg = gr.Markdown()
            with gr.Tab("Data explorer"):
                gr.Markdown("Live records from the mock procurement database. Run a scenario, then refresh to see persisted changes.")
                btn_data = gr.Button("Refresh data")
                inv_df = gr.Dataframe(headers=["sku", "node", "on_hand", "reserved", "available"], label="Inventory")
                po_df = gr.Dataframe(headers=["po_id", "sku", "node", "supplier", "ordered", "received", "status", "price"], label="Purchase orders")
                sup_df = gr.Dataframe(headers=["supplier", "name", "sku", "price", "lt", "moq", "mult", "capacity", "available"], label="Suppliers")
                fc_df = gr.Dataframe(headers=["sku", "node", "daily", "qty", "horizon", "ts"], label="Forecasts")
                bud_df = gr.Dataframe(headers=["period", "node", "category", "allocated", "committed", "remaining"], label="Budgets")
                st_df = gr.Dataframe(headers=["node", "capacity", "util", "reserved", "free"], label="Storage")
                aud_df = gr.Dataframe(headers=["audit_id", "operation", "entity", "entity_id", "reason", "run"], label="Audit")
            with gr.Tab("Help"):
                gr.Markdown(
                    """
### Demo walkthrough
1. Open **Scenario center**, pick a scenario and fixture, click **Reset fixture**.
2. Click **Investigate / plan / run** with Execute unchecked to see the decision.
3. Enable Execute and (if needed) Auto-approve, then run again.
4. Confirm purchase orders changed in **Data explorer**.
5. Validation must read persisted rows — SUCCESS is never assumed from a lack of exceptions.

API docs: `/api/docs` · Health: `/api/health`
"""
                )

        outputs_main = [run_header, evidence, calc, constraints, alts, decision, validation, timeline, overview, inv_df, po_df, sup_df, fc_df, bud_df, st_df, approval_table, aud_df]
        btn_run.click(run_workflow, inputs=[scenario, fixture], outputs=outputs_main)
        btn_reset.click(lambda s, f: reset_fixture(s, f), inputs=[scenario, fixture], outputs=[reset_msg, overview, inv_df, po_df, sup_df, fc_df, bud_df, st_df, approval_table, aud_df])
        refresh.click(lambda: (_overview_md(), *_refresh_tables()), outputs=[overview, inv_df, po_df, sup_df, fc_df, bud_df, st_df, approval_table, aud_df])
        btn_data.click(lambda: _refresh_tables(), outputs=[inv_df, po_df, sup_df, fc_df, bud_df, st_df, approval_table, aud_df])
        btn_ok.click(lambda i: approve_action(i, True), inputs=approval_id, outputs=[approval_msg, approval_table])
        btn_no.click(lambda i: approve_action(i, False), inputs=approval_id, outputs=[approval_msg, approval_table])
        btn_exec.click(execute_pending, inputs=action_id, outputs=exec_msg)
        demo.load(
            lambda: (_overview_md(), *_refresh_tables()),
            outputs=[overview, inv_df, po_df, sup_df, fc_df, bud_df, st_df, approval_table, aud_df],
        )
    return demo
