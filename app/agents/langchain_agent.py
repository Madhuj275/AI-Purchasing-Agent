"""LangChain purchasing decision agent with deterministic safety gates."""

from __future__ import annotations

import json
from typing import Literal

from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.agents.planner import _supplier_constraints
from app.config import get_settings
from app.schemas.domain import DecisionRecord, InvestigationReport
from app.tools.registry import ProcurementTools

AgentAction = Literal[
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
    "transfer",
    "no_action",
]


class AgentDecision(BaseModel):
    """The model's proposed decision; financial values are recomputed by the app."""

    action: AgentAction
    recommended_qty: int = Field(ge=0)
    supplier_id: str | None = None
    confidence: Literal["high", "medium", "low"] = "medium"
    explanation: str = Field(min_length=10, max_length=2000)
    uncertainty: list[str] = Field(default_factory=list)


_PURCHASE_ACTIONS = {
    "accept",
    "modify",
    "split_order",
    "alternative_supplier",
    "increase_order",
}
_NO_PURCHASE_ACTIONS = {
    "reject",
    "investigate",
    "defer",
    "escalate",
    "keep_plan",
    "no_action",
}


def apply_agent_decision(
    tools: ProcurementTools,
    investigation: InvestigationReport,
    baseline: DecisionRecord,
    proposal: AgentDecision,
) -> DecisionRecord:
    """Apply a model proposal only when it fits verified evidence and policy."""
    if baseline.action in {"investigate", "escalate"} and proposal.action in _PURCHASE_ACTIONS | {"transfer"}:
        raise ValueError("The evidence-based plan requires investigation or escalation")
    if (
        investigation.scenario_id == "s2"
        and proposal.action in _PURCHASE_ACTIONS
        and proposal.action != baseline.action
    ):
        raise ValueError("Supplier-shortage actions must match the verified shortage plan")
    if (
        "replenishment_may_be_too_late" in baseline.uncertainty
        and proposal.action in _PURCHASE_ACTIONS
    ):
        raise ValueError("The evidence-based plan indicates replenishment may arrive too late")

    cost = 0.0
    unit_price = None
    constraints = []
    if proposal.action in _PURCHASE_ACTIONS and proposal.recommended_qty:
        if proposal.recommended_qty > baseline.recommended_qty:
            raise ValueError("The proposed quantity exceeds the evidence-based recommendation")
        if not proposal.supplier_id:
            raise ValueError("A supplier is required for a purchase decision")
        supplier = next(
            (item for item in investigation.suppliers if item["supplier_id"] == proposal.supplier_id),
            None,
        )
        if supplier is None:
            raise ValueError("The proposed supplier was not found in the investigation")
        constraints = _supplier_constraints(investigation, supplier, proposal.recommended_qty)
        failures = [check.name for check in constraints if check.hard and not check.passed]
        if failures:
            raise ValueError("Hard constraints failed: " + ", ".join(failures))
        unit_price = supplier["unit_price"]
        cost = proposal.recommended_qty * unit_price

        if proposal.action in {"split_order", "alternative_supplier"}:
            feasible_alternative = any(
                item.feasible
                and item.action == proposal.action
                and item.supplier_id == proposal.supplier_id
                and item.quantity == proposal.recommended_qty
                for item in baseline.alternatives
            )
            if not feasible_alternative:
                raise ValueError("The proposed alternative is not a verified feasible option")
    elif proposal.action in _NO_PURCHASE_ACTIONS and proposal.recommended_qty != 0:
        raise ValueError("A non-purchasing decision must have quantity zero")
    elif proposal.action == "transfer":
        feasible_transfer = any(
            item.feasible and item.action == "transfer" and item.quantity == proposal.recommended_qty
            for item in baseline.alternatives
        )
        if not feasible_transfer:
            raise ValueError("The proposed transfer is not a verified feasible option")
    elif proposal.action not in _PURCHASE_ACTIONS | _NO_PURCHASE_ACTIONS | {"transfer"}:
        raise ValueError(f"Unsupported agent action: {proposal.action}")

    requires_approval = baseline.requires_approval
    if proposal.action in _PURCHASE_ACTIONS and proposal.recommended_qty:
        requires_approval = requires_approval or tools.approvals.requires_approval(cost)
    elif proposal.action == "transfer":
        requires_approval = True

    matching_option = next(
        (
            item
            for item in baseline.alternatives
            if item.action == proposal.action
            and item.quantity == proposal.recommended_qty
            and (not proposal.supplier_id or item.supplier_id == proposal.supplier_id)
        ),
        None,
    )
    return DecisionRecord(
        action=proposal.action,
        recommended_qty=proposal.recommended_qty,
        compared_qty=baseline.compared_qty,
        supplier_id=proposal.supplier_id if proposal.recommended_qty else None,
        unit_price=unit_price,
        total_cost=cost,
        confidence=proposal.confidence,
        explanation=proposal.explanation,
        calculation=baseline.calculation,
        constraints=constraints,
        alternatives=baseline.alternatives,
        selected_option_id=matching_option.option_id if matching_option else None,
        requires_approval=requires_approval,
        uncertainty=list(dict.fromkeys(baseline.uncertainty + proposal.uncertainty)),
        reasoning_mode="langchain-agent",
    )


class LangChainPurchasingAgent:
    def __init__(self, provider: str, api_key: str, model: str, base_url: str) -> None:
        self.provider = provider
        if provider == "openai":
            self.model = ChatOpenAI(
                api_key=api_key,
                model=model or "gpt-4o-mini",
                base_url=base_url or None,
                temperature=0,
                timeout=90,
                max_retries=1,
                verbose=True,
            )
        elif provider == "gemini":
            self.model = ChatGoogleGenerativeAI(
                google_api_key=api_key,
                model=model or "gemini-2.0-flash",
                temperature=0,
                timeout=20,
            )
        else:
            raise ValueError(f"Unsupported LangChain provider: {provider}")

    def decide(
        self,
        tools: ProcurementTools,
        investigation: InvestigationReport,
        baseline: DecisionRecord,
    ) -> DecisionRecord:
        suppliers = {item["supplier_id"]: item for item in investigation.suppliers}

        @tool
        def check_candidate(supplier_id: str, quantity: int) -> str:
            """Check a proposed order quantity against verified supplier, budget, and storage rules."""
            supplier = suppliers.get(supplier_id)
            if supplier is None or quantity < 0:
                return json.dumps({"feasible": False, "reason": "Unknown supplier or invalid quantity"})
            checks = _supplier_constraints(investigation, supplier, quantity)
            return json.dumps(
                {
                    "feasible": all(check.passed for check in checks if check.hard),
                    "checks": [check.model_dump() for check in checks],
                },
                default=str,
            )

        parser = PydanticOutputParser(pydantic_object=AgentDecision)
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are the purchasing decision agent. Decide from the supplied investigation and "
                    "evidence-based plan. You may choose a smaller quantity or a feasible listed alternative, "
                    "or choose a non-purchasing action. Never exceed the plan's recommended quantity. "
                    "Use check_candidate before proposing a purchase. Never invent supplier or inventory data. "
                    "Format the final answer according to these instructions:\n{format_instructions}\n"
                    "Approved actions still require separate policy approval.",
                ),
                ("human", "Investigation and candidate plan:\n{context}"),
                MessagesPlaceholder("agent_scratchpad"),
            ]
        )
        agent = create_tool_calling_agent(self.model, [check_candidate], prompt)
        executor = AgentExecutor(
            agent=agent,
            tools=[check_candidate],
            max_iterations=2,
            verbose=False,
        )
        response = executor.invoke(
            {
                "context": json.dumps(
                    {
                        "investigation": investigation.model_dump(mode="json"),
                        "evidence_based_plan": baseline.model_dump(mode="json"),
                    },
                    default=str,
                ),
                "format_instructions": parser.get_format_instructions(),
            }
        )
        raw_output = response.get("output")
        if not isinstance(raw_output, str):
            raise ValueError("LangChain agent returned no textual decision")
        proposal = parser.parse(raw_output)
        if not isinstance(proposal, AgentDecision):
            raise ValueError("LangChain agent returned an invalid decision shape")
        return apply_agent_decision(
            tools,
            investigation,
            baseline,
            proposal,
        )


def get_purchasing_agent() -> LangChainPurchasingAgent | None:
    settings = get_settings()
    if settings.llm_provider == "none" or not settings.llm_api_key:
        return None
    return LangChainPurchasingAgent(
        settings.llm_provider,
        settings.llm_api_key,
        settings.llm_model,
        settings.llm_base_url,
    )
