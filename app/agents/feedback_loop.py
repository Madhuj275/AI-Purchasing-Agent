"""Deterministic post-validation recovery with bounded, policy-safe retries."""

from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from app.agents.action_executor import InjectedFailure, execute_action
from app.agents.validator import validate_action
from app.config import get_settings
from app.models.entities import ActionRecord, HumanApproval
from app.schemas.domain import DecisionRecord, ValidationReport
from app.tools.registry import ProcurementTools
from app.utils.logging import log_event

logger = logging.getLogger(__name__)


def recover(
    session: Session,
    tools: ProcurementTools,
    action: ActionRecord,
    decision: DecisionRecord,
    approvals: list[HumanApproval],
    attempt: int,
    simulate_failure: str | None,
) -> ValidationReport:
    settings = get_settings()
    report = validate_action(tools, action, decision, approvals)
    if report.outcome in {"SUCCESS", "PARTIAL_SUCCESS", "INVESTIGATE", "ESCALATED"}:
        return report
    if attempt >= settings.max_agent_retries:
        report.recovery = "retries exhausted; escalating"
        report.outcome = "ESCALATED"
        tools.audit.record(
            actor="purchasing-agent",
            operation="recovery_exhausted",
            entity="action_record",
            entity_id=action.action_id,
            correlation_id=action.run_id,
            after=report.model_dump(),
            reason=report.recovery,
        )
        return report

    log_event(logger, "validation_failed_recovering", action_id=action.action_id, outcome=report.outcome)
    # Safe retry only for injected persist failures on non-duplicate creates.
    if simulate_failure == "persist_fail" and action.status == "failed":
        action.status = "proposed"
        try:
            execute_action(session, tools, action, simulate_failure=None)
            report = validate_action(tools, action, decision, approvals)
            report.recovery = "retried after simulated persistence failure"
            return report
        except InjectedFailure:
            report.outcome = "FAILED"
            report.recovery = "retry failed"
            return report

    if simulate_failure == "storage_race":
        report.outcome = "ESCALATED"
        report.recovery = "storage changed before execution; will not bypass the hard constraint"
        tools.audit.record(
            actor="purchasing-agent",
            operation="recovery_escalate",
            entity="action_record",
            entity_id=action.action_id,
            correlation_id=action.run_id,
            after=json.loads(action.execution_result or "{}"),
            reason=report.recovery,
        )
        return report

    report.outcome = "ESCALATED"
    report.recovery = "unsafe to retry; human intervention required"
    return report
