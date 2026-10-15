"""Pydantic schemas used by the decision engine, agent, and APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


Outcome = Literal["SUCCESS", "PARTIAL_SUCCESS", "BLOCKED", "FAILED", "ESCALATED", "INVESTIGATE"]
DecisionAction = Literal[
    "accept",
    "modify",
    "reject",
    "investigate",
    "defer",
    "split_order",
    "alternative_supplier",
    "escalate",
    "keep_plan",
    "increase_order",
    "expedite",
    "transfer",
    "no_action",
]


class ReplenishmentCalc(BaseModel):
    sku: str
    node_id: str
    on_hand: int
    reserved: int
    available: int
    incoming_confirmed: int
    incoming_unconfirmed: int
    inventory_position: int
    daily_demand: float | None
    protection_period_days: int
    forecast_demand_protection: float | None
    safety_stock: float | None
    target_stock: float | None
    recommended_raw: int
    recommended_rounded: int
    rounding_applied: bool
    assumptions: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    stale: list[str] = Field(default_factory=list)
    intermediates: dict[str, Any] = Field(default_factory=dict)


class ConstraintCheck(BaseModel):
    name: str
    passed: bool
    hard: bool
    detail: str
    value: Any = None
    limit: Any = None


class AlternativeOption(BaseModel):
    option_id: str
    description: str
    action: DecisionAction
    quantity: int
    supplier_id: str | None = None
    cost: float | None = None
    feasible: bool
    reasons: list[str] = Field(default_factory=list)
    constraints: list[ConstraintCheck] = Field(default_factory=list)


class InvestigationReport(BaseModel):
    scenario_id: str
    fixture_key: str
    event: dict[str, Any]
    product: dict[str, Any] | None = None
    node: dict[str, Any] | None = None
    inventory: dict[str, Any] | None = None
    forecast: dict[str, Any] | None = None
    sales: list[dict[str, Any]] = Field(default_factory=list)
    purchase_orders: list[dict[str, Any]] = Field(default_factory=list)
    suppliers: list[dict[str, Any]] = Field(default_factory=list)
    budget: dict[str, Any] | None = None
    storage: dict[str, Any] | None = None
    missing: list[str] = Field(default_factory=list)
    stale: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    data_freshness: dict[str, Any] = Field(default_factory=dict)


class DecisionRecord(BaseModel):
    action: DecisionAction
    recommended_qty: int
    compared_qty: int | None = None
    supplier_id: str | None = None
    unit_price: float | None = None
    total_cost: float | None = None
    confidence: Literal["high", "medium", "low"] = "medium"
    explanation: str
    calculation: ReplenishmentCalc | None = None
    constraints: list[ConstraintCheck] = Field(default_factory=list)
    alternatives: list[AlternativeOption] = Field(default_factory=list)
    selected_option_id: str | None = None
    requires_approval: bool = False
    hard_constraint_violations: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
    reasoning_mode: str = "deterministic"


class ActionProposal(BaseModel):
    action_type: str
    payload: dict[str, Any]
    idempotency_key: str
    requires_approval: bool
    fingerprint: str


class ValidationCheck(BaseModel):
    name: str
    passed: bool
    expected: Any = None
    actual: Any = None
    detail: str = ""


class ValidationReport(BaseModel):
    outcome: Outcome
    checks: list[ValidationCheck] = Field(default_factory=list)
    expected: dict[str, Any] = Field(default_factory=dict)
    actual: dict[str, Any] = Field(default_factory=dict)
    recovery: str | None = None


class AgentRunResult(BaseModel):
    run_id: str
    scenario_id: str
    fixture_key: str
    status: str
    outcome: Outcome
    investigation: InvestigationReport
    decision: DecisionRecord
    action_id: str | None = None
    approval_id: str | None = None
    executed: bool = False
    validation: ValidationReport | None = None
    explanation: str
    reasoning_mode: str
    timeline: list[dict[str, Any]] = Field(default_factory=list)


class ScenarioRunRequest(BaseModel):
    fixture_key: str = "default"
    execute: bool = False
    auto_approve: bool = False
    simulate_failure: str | None = None


class ApprovalDecisionRequest(BaseModel):
    approver: str = "buyer.demo"
    reason: str = "Demo approval"


class SupplierConfirmationRequest(BaseModel):
    confirmed_qty: int
    message: str = ""
    idempotency_key: str | None = None


class HealthResponse(BaseModel):
    status: str
    database: str
    llm_mode: str
    time: datetime
