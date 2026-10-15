# AI Purchasing Agent — Architecture & Design Specification

## 1. System Overview

The **AI Purchasing Agent** is an enterprise-grade autonomous procurement copilot designed for omnichannel supply chains and dark stores. It addresses inventory replenishment, supplier shortage resolution, demand surge responses, and multi-dimensional purchasing constraints through a strictly controlled, deterministic execution loop.

### Core Philosophy
1. **LangChain Decision Agent with Deterministic Gates**: When configured, a LangChain tool-calling agent chooses the purchasing action from investigation evidence. Calculations, constraint validation, approval enforcement, idempotency, and database mutations remain application-controlled.
2. **Transparent Zero-Key Fallback**: The entire application operates without third-party API keys, paid credits, or live procurement APIs using the deterministic planner. Model/API failures are logged and fall back to the same planner.
3. **Fail-Closed Safety**: In the event of missing, stale, or contradictory data, the agent halts mutations and routes the run to `INVESTIGATE` or `ESCALATE` rather than guessing or fabricating numbers.
4. **Independent Post-Execution Validation**: State mutations are never trusted blindly; the agent reads fresh state back from the database and independently validates all business invariants before claiming success.

---

## 2. Controlled 9-Step Workflow Loop

The agent executes through a formal state machine:

```
INVESTIGATE ➔ PLAN ➔ CHECK CONSTRAINTS ➔ PROPOSE ➔ APPROVE ➔ EXECUTE ➔ READ BACK ➔ VALIDATE ➔ COMPLETE / RECOVER / ESCALATE
```

| Step | Component | Action |
|---|---|---|
| **1. INVESTIGATE** | `app.agents.investigation` | Queries product specs, inventory on-hand/reserved, forecasts, actual sales, supplier catalog, open purchase orders, budgets, and storage constraints. Flags missing data, stale forecasts (>72h), and contradictions. |
| **2. PLAN** | `app.agents.langchain_agent` and `app.agents.planner` | LangChain selects a proposed action from evidence-based candidates. The planner supplies the offline fallback and feasible alternatives; model proposals are independently checked before use. |
| **3. CHECK CONSTRAINTS** | `app.agents.decision_engine` | Evaluates hard constraints: Product status, Supplier availability, Supplier capacity, MOQ & order multiples, Budget limits, Storage volume. |
| **4. PROPOSE** | `app.agents.action_executor` | Builds an immutable `ActionProposal` with a deterministic idempotency key and cryptographic fingerprint. |
| **5. APPROVE** | `app.services.approval_service` | Verifies whether total purchase cost exceeds threshold (`$500.00`) or flags exceptions. Holds execution in `pending_approval` until human decision if required. |
| **6. EXECUTE** | `app.agents.action_executor` | Performs database mutations atomically within transactional boundaries. Employs idempotency locks to prevent duplicate POs. |
| **7. READ BACK** | `app.tools.registry` | Refetches fresh persisted records directly from the database, ignoring in-memory execution artifacts. |
| **8. VALIDATE** | `app.agents.validator` | Independently evaluates whether PO numbers, quantities, prices, supplier IDs, node IDs, budget remaining, and storage utilization comply with policy invariants. |
| **9. RECOVER / ESCALATE** | `app.agents.feedback_loop` | On validation failure or injected race conditions (e.g. storage exhaustion), executes bounded retries or safely escalates to human buyers without data corruption. |

---

## 3. Technology Stack & Directory Structure

- **Runtime**: Python 3.11+
- **Web Framework**: FastAPI (Asynchronous REST API, OpenAPI/Swagger at `/api/docs`)
- **Dashboard UI**: Gradio 5.12 Blocks (Mounted directly at `/ui`)
- **Persistence**: SQLAlchemy 2.0 ORM with SQLite local fallback and PostgreSQL/NeonDB support
- **Data Validation & Schemas**: Pydantic v2 & Pydantic-Settings
- **Testing**: pytest & FastAPI TestClient
- **Agent framework**: LangChain tool-calling agent with OpenAI and Gemini chat model adapters
- **Logging & Audit**: Python standard `logging` with structured JSON contextual event logging

### Repository Layout
```
d:\SelfAssignment\Rappi\
├── app/
│   ├── agents/
│   │   ├── action_executor.py   # Atomic action proposal & execution
│   │   ├── decision_engine.py   # Deterministic math, rounding & constraint rules
│   │   ├── feedback_loop.py     # Post-validation recovery & bounded retries
│   │   ├── investigation.py     # Evidence collection & anomaly detection
│   │   ├── langchain_agent.py   # LangChain purchasing decisions and safety gates
│   │   ├── planner.py           # Scenario reasoning & alternative generation
│   │   ├── purchasing_agent.py  # Central workflow orchestrator
│   │   └── validator.py         # Independent post-mutation verification
│   ├── api/
│   │   └── routes.py            # REST endpoints, demo auth & Swagger docs
│   ├── models/
│   │   └── entities.py          # SQLAlchemy relational entities
│   ├── schemas/
│   │   └── domain.py            # Pydantic request/response domain models
│   ├── seed/
│   │   └── demo_data.py         # Deterministic seed data & 37 scenario fixtures
│   ├── services/                # Business services (Budget, PO, Storage, Approval, etc.)
│   ├── tools/
│   │   └── registry.py          # Read-only vs mutating tool separation
│   ├── ui/
│   │   └── gradio_app.py        # Gradio Blocks interactive procurement dashboard
│   ├── config.py                # Pydantic environment configuration
│   ├── database.py              # Engine creation, PRAGMA foreign keys & sessionmaker
│   └── main.py                  # FastAPI application factory & Gradio mounting
├── docs/
│   ├── architecture.md          # Architecture & design documentation
│   ├── architecture.mmd         # Mermaid workflow diagrams
│   └── evaluation.md            # Benchmark evaluation & test results
├── tests/                       # Complete pytest suite (8 test modules)
├── .env.example                 # Environment configuration template
├── pytest.ini                   # Pytest testpaths and warning configurations
└── requirements.txt             # Locked project dependencies
```

---

## 4. Database Schema & Entities

The relational database schema is structured into ten normalized entities:

1. **`products`**: `sku` (PK), `name`, `category`, `unit_cost`, `shelf_life_days`, `status`, `space_per_unit`.
2. **`fulfillment_nodes`**: `node_id` (PK), `name`, `location`, `storage_capacity`, `current_utilization`.
3. **`inventory`**: `id` (PK), `sku` (FK), `node_id` (FK), `on_hand`, `reserved`, `last_updated`. Unique constraint on `(sku, node_id)`.
4. **`demand_forecasts`**: `id` (PK), `sku` (FK), `node_id` (FK), `horizon_days`, `forecast_quantity`, `daily_demand`, `forecast_timestamp`, `source`.
5. **`actual_sales`**: `id` (PK), `sku` (FK), `node_id` (FK), `period_start`, `period_end`, `quantity_sold`.
6. **`suppliers`**: `supplier_id` (PK), `name`, `active`, `reliability_score`.
7. **`supplier_products`**: `id` (PK), `supplier_id` (FK), `sku` (FK), `unit_price`, `lead_time_days`, `min_order_qty`, `order_multiple`, `capacity`, `available`. Unique constraint on `(supplier_id, sku)`.
8. **`purchase_orders`**: `po_id` (PK), `supplier_id` (FK), `sku` (FK), `node_id` (FK), `ordered_qty`, `received_qty`, `confirmed_qty`, `status`, `unit_price`, `confirmed_incoming`, `expected_arrival`, `parent_po_id`, `idempotency_key` (Unique), `created_at`, `updated_at`, `notes`.
9. **`budgets`**: `id` (PK), `period`, `node_id` (FK), `category`, `allocated`, `committed`, `remaining`.
10. **`storage_constraints`**: `node_id` (PK, FK), `total_capacity`, `current_utilization`, `reserved_space`.
11. **`agent_runs`**, **`action_records`**, **`human_approvals`**, **`audit_logs`**: Full auditability, state tracking, and approval gating.

---

## 5. Mathematical Formulas & Invariants

### 5.1 Available Inventory & Inventory Position
$$\text{Available} = \text{on\_hand} - \text{reserved}$$
$$\text{Inventory Position} = \text{Available} + \sum \text{Remaining Qty of Eligible Confirmed Incoming POs}$$
- **Invariant**: Cancelled, rejected, or unconfirmed purchase orders are **strictly excluded** from incoming stock.
- **Invariant**: Reserved inventory is subtracted and never added back.

### 5.2 Target Stock & Protection Period
$$\text{Protection Period (days)} = \text{lead\_time\_days} + \text{review\_horizon\_days}$$
$$\text{Safety Stock} = \text{daily\_demand} \times \text{safety\_stock\_days}$$
$$\text{Target Stock} = (\text{daily\_demand} \times \text{Protection Period}) + \text{Safety Stock}$$

### 5.3 Replenishment Quantity & Supplier Rules
$$\text{Raw Recommendation} = \max\left(0, \lceil \text{Target Stock} - \text{Inventory Position} \rceil\right)$$
$$\text{Rounded Quantity} = \max\left(\text{MOQ}, \left\lceil \frac{\text{Raw Recommendation}}{\text{Order Multiple}} \right\rceil \times \text{Order Multiple}\right)$$
- If rounding up causes a violation of hard constraints (budget or storage), the order is **not silently placed**; it triggers modification, alternative supplier search, or escalation.

---

## 6. Four Required Scenarios

### Scenario 1 — Purchase Recommendation Review (SKU: MILK-1L)
- **Baseline**: System receives an external recommendation of 800 units.
- **Agent Behavior**: Recalculates position from real database values.
  - If 800 matches need: Accepts or requests approval if cost $\ge \$500$.
  - If existing inventory/incoming covers need: Rejects recommendation (recommends 0 units).
  - If forecast is missing or contradictory: Halts execution and transitions to `INVESTIGATE`.
  - If budget or storage is insufficient: Downsizes quantity or escalates.

### Scenario 2 — Supplier Shortage (SKU: RICE-5KG, PO-S2-001)
- **Baseline**: Ordered 500 units; supplier confirms only 250 units.
- **Agent Behavior**:
  - Updates confirmation status on original PO (`ordered_qty = 250`).
  - Evaluates remaining need (250 units).
  - Checks if current stock covers demand until next cycle; if yes, modifies order with no extra purchase.
  - If stockout risk exists: Evaluates alternate suppliers (`SUP-ALTSOURCE`). Creates split PO linked via `parent_po_id = PO-S2-001`.
  - Idempotency ensures repeat shortage notifications do not issue duplicate supplementary POs.

### Scenario 3 — Demand Change (SKU: BREAD-WHT)
- **Baseline**: Actual sales spike from 50 units/day to sustained 93 units/day.
- **Agent Behavior**:
  - Distinguishes sustained trend from noise (>25% spike over multiple periods).
  - Flags stale forecasts (>72h).
  - Recalculates stockout horizon; if existing confirmed PO covers the spike, keeps existing plan.
  - If additional inventory is required and supplier lead time permits: Proposes supplementary order. If lead time is too late to prevent stockout: Evaluates authorized Dark Store inter-node transfer or escalates.

### Scenario 4 — Purchasing Constraints (SKU: OIL-1L)
- **Baseline**: 400 units required, but single-supplier or node constraints block order.
- **Agent Behavior**:
  - Tests all hard constraint boundaries (Budget, Storage, Capacity, MOQ).
  - Generates evaluated alternative options:
    - Downsized order fitting remaining budget.
    - Alternative supplier with smaller MOQ or faster lead time.
    - Transfer from secondary node (`NODE-SOUTH`).
  - If no feasible option passes all hard constraints: Safely escalates with full audit trail.

---

## 7. Safety, Approvals & Idempotency

### Human Approval Gateway
- Actions exceeding `$500.00` total cost require explicit approval.
- An approval request stores an immutable **SHA-256 fingerprint** of the canonical proposal payload:
  $$\text{Fingerprint} = \text{SHA256}(\text{JSON}(\text{payload, sorted\_keys=True}))$$
- If an operator or system modifies quantity, supplier, or price after approval was requested, the fingerprint mismatches, automatically **invalidating** the prior approval.

### Idempotency Keys
- Every action and purchase order uses a deterministic hash key:
  $$\text{Key} = \text{SHA256}(\text{action} + \text{sku} + \text{node} + \text{supplier} + \text{qty} + \text{fixture})$$
- Database-level unique constraints (`uq_po_idempotency`, `uq_action_idempotency`) guarantee that duplicate webhook events or network retries never generate duplicate purchase orders.
