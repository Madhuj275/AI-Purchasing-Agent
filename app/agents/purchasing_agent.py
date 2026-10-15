"""Orchestrates INVESTIGATE → PLAN → CONSTRAINTS → APPROVE → EXECUTE → VALIDATE."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.agents.action_executor import InjectedFailure, build_proposal, execute_action, persist_action
from app.agents.feedback_loop import recover
from app.agents.investigation import investigate
from app.agents.langchain_agent import get_purchasing_agent
from app.agents.planner import plan
from app.agents.validator import validate_action
from app.models.entities import ActionRecord, AgentRun, HumanApproval
from app.schemas.domain import AgentRunResult, DecisionRecord, InvestigationReport
from app.seed.demo_data import SCENARIO_EVENTS, apply_fixture, seed_database
from app.services.approval_service import ApprovalService
from app.tools.registry import ProcurementTools
from app.utils.ids import new_id, utcnow
from app.utils.logging import log_event
from app.database import reset_db

logger = logging.getLogger(__name__)


class PurchasingAgent:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.tools = ProcurementTools(session)
        self.approvals = ApprovalService(session)
        self.decision_agent = get_purchasing_agent()

    def reset_fixture(self, scenario_id: str, fixture_key: str = "default") -> None:
        reset_db()
        seed_database(self.session, scenario_id=None, fixture_key="default")
        apply_fixture(self.session, scenario_id, fixture_key)
        self.session.commit()

    def run(
        self,
        scenario_id: str,
        fixture_key: str = "default",
        execute: bool = False,
        auto_approve: bool = False,
        simulate_failure: str | None = None,
        event: dict[str, Any] | None = None,
    ) -> AgentRunResult:
        if scenario_id not in SCENARIO_EVENTS:
            raise ValueError(f"Unknown scenario {scenario_id}")
        run = AgentRun(
            run_id=new_id("RUN"),
            scenario_id=scenario_id,
            fixture_key=fixture_key,
            status="started",
            event_payload=json.dumps(event or SCENARIO_EVENTS[scenario_id], default=str),
            investigation=None,
            decision=None,
            explanation=None,
            reasoning_mode="deterministic",
            outcome=None,
            confidence=None,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        self.session.add(run)
        self.session.flush()
        timeline: list[dict[str, Any]] = [{"step": "start", "run_id": run.run_id}]

        inv = investigate(self.tools, scenario_id, fixture_key, event)
        timeline.append({"step": "investigate", "missing": inv.missing, "stale": inv.stale})
        baseline = plan(self.tools, inv)
        decision = baseline
        mode = "deterministic"
        if self.decision_agent is not None:
            try:
                decision = self.decision_agent.decide(self.tools, inv, baseline)
                mode = "langchain-agent"
            except Exception as exc:
                log_event(
                    logger,
                    "langchain_decision_fallback",
                    error=str(exc),
                    provider=self.decision_agent.provider,
                )
                decision.reasoning_mode = "deterministic-fallback"
                mode = "deterministic-fallback"
        timeline.append({"step": "plan", "action": decision.action, "qty": decision.recommended_qty})
        decision.reasoning_mode = mode
        run.investigation = inv.model_dump_json()
        run.decision = decision.model_dump_json()
        run.explanation = decision.explanation
        run.reasoning_mode = mode
        run.confidence = decision.confidence
        run.status = "planned"
        run.updated_at = utcnow()

        self.tools.audit.record(
            actor="purchasing-agent",
            operation="plan",
            entity="agent_run",
            entity_id=run.run_id,
            correlation_id=run.run_id,
            after={"action": decision.action, "qty": decision.recommended_qty},
            reason=decision.action,
        )

        proposal = build_proposal(run.run_id, inv, decision)
        action = None
        approval = None
        executed = False
        validation = None

        if proposal:
            action = persist_action(self.session, run, proposal)
            timeline.append({"step": "propose", "action_id": action.action_id, "type": action.action_type})
            if proposal.payload.get("kind") != "none" and proposal.requires_approval:
                approval = self.approvals.create(action, proposal.payload)
                timeline.append({"step": "approval_required", "approval_id": approval.approval_id})
                if auto_approve:
                    self.approvals.decide(approval.approval_id, True, "buyer.demo", "Auto-approve for demo/test", proposal.payload)
                    timeline.append({"step": "auto_approved"})
                else:
                    run.status = "pending_approval"
                    run.outcome = "BLOCKED"
                    run.updated_at = utcnow()
                    self.session.commit()
                    return self._result(run, inv, decision, action, approval, False, None, timeline, "BLOCKED")

            mutating = proposal.payload.get("kind") != "none"
            if execute and mutating:
                hard_fail = [c for c in decision.constraints if c.hard and not c.passed]
                if hard_fail:
                    run.status = "blocked"
                    run.outcome = "BLOCKED"
                    self.session.commit()
                    return self._result(run, inv, decision, action, approval, False, None, timeline, "BLOCKED")
                if action.requires_approval:
                    payload = json.loads(action.proposed_payload)
                    if not self.approvals.is_valid_for_action(action, payload):
                        run.status = "blocked"
                        run.outcome = "BLOCKED"
                        self.session.commit()
                        return self._result(run, inv, decision, action, approval, False, None, timeline, "BLOCKED")
                try:
                    execute_action(self.session, self.tools, action, simulate_failure=simulate_failure)
                    executed = True
                    timeline.append({"step": "execute", "ok": True})
                except (InjectedFailure, ValueError) as exc:
                    action.status = "failed"
                    action.execution_result = json.dumps({"ok": False, "error": str(exc)})
                    action.updated_at = utcnow()
                    timeline.append({"step": "execute", "ok": False, "error": str(exc)})
                    approvals = self.session.query(HumanApproval).filter_by(action_id=action.action_id).all()
                    validation = recover(self.session, self.tools, action, decision, approvals, 1, simulate_failure)
                    run.status = "completed"
                    run.outcome = validation.outcome
                    run.updated_at = utcnow()
                    action.validation_outcome = validation.outcome
                    self.session.commit()
                    return self._result(run, inv, decision, action, approval, executed, validation, timeline, validation.outcome)

                approvals = self.session.query(HumanApproval).filter_by(action_id=action.action_id).all()
                validation = validate_action(self.tools, action, decision, approvals)
                if validation.outcome in {"FAILED"}:
                    validation = recover(self.session, self.tools, action, decision, approvals, 1, simulate_failure)
                action.validation_outcome = validation.outcome
                timeline.append({"step": "validate", "outcome": validation.outcome})
                run.outcome = validation.outcome
                run.status = "completed"
            elif not mutating:
                validation = validate_action(self.tools, action, decision, [])
                action.status = "completed_no_mutation"
                action.validation_outcome = validation.outcome
                run.outcome = validation.outcome
                run.status = "completed"
                timeline.append({"step": "complete_no_mutation", "outcome": validation.outcome})
            else:
                run.status = "awaiting_execution"
                run.outcome = "BLOCKED" if decision.hard_constraint_violations else None
        else:
            run.status = "completed"
            run.outcome = "ESCALATED" if decision.action == "escalate" else "INVESTIGATE"
            if decision.action in {"reject", "keep_plan", "no_action"}:
                run.outcome = "SUCCESS"

        run.updated_at = utcnow()
        self.session.commit()
        log_event(logger, "agent_run_complete", run_id=run.run_id, outcome=run.outcome, mode=mode)
        return self._result(run, inv, decision, action, approval, executed, validation, timeline, run.outcome or "SUCCESS")

    def _result(
        self,
        run: AgentRun,
        inv: InvestigationReport,
        decision: DecisionRecord,
        action: ActionRecord | None,
        approval: HumanApproval | None,
        executed: bool,
        validation,
        timeline: list[dict[str, Any]],
        outcome: str,
    ) -> AgentRunResult:
        return AgentRunResult(
            run_id=run.run_id,
            scenario_id=run.scenario_id,
            fixture_key=run.fixture_key,
            status=run.status,
            outcome=outcome,  # type: ignore[arg-type]
            investigation=inv,
            decision=decision,
            action_id=action.action_id if action else None,
            approval_id=approval.approval_id if approval else None,
            executed=executed,
            validation=validation,
            explanation=run.explanation or decision.explanation,
            reasoning_mode=run.reasoning_mode,
            timeline=timeline,
        )
