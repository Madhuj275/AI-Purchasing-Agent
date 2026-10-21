# AI Purchasing Agent

An enterprise-ready purchasing copilot with an optional LangChain decision agent. Designed for high-velocity dark stores and retail fulfillment networks, this system automates inventory replenishment, shortage mitigation, demand surge responses, and constraint-based procurement with safety, idempotency, and audit trails.

---

## Highlights

- **Controlled 9-Step Loop**: `INVESTIGATE ➔ PLAN ➔ CHECK CONSTRAINTS ➔ PROPOSE ➔ APPROVE ➔ EXECUTE ➔ READ BACK ➔ VALIDATE ➔ COMPLETE / RECOVER / ESCALATE`.
- **LangChain Decision Agent**: With OpenAI or Gemini configured, a LangChain tool-calling agent selects a purchasing action from investigation evidence and feasible candidate plans.
- **Deterministic Safety Gates**: The application recomputes costs and enforces MOQ, order multiples, supplier capacity, budget, storage, approvals, and post-execution invariants. The model cannot execute database mutations directly.
- **Zero-Key Offline Mode**: Runs without API keys using the existing deterministic planner as a fallback. Model/API failures are logged and also fall back to that planner.
- **Fail-Closed Safety**: Missing, stale, or contradictory data triggers investigation or escalation rather than invented quantities.
- **Independent Validation & Self-Healing**: Post-execution reads persist state back from the database to independently verify orders, pricing, budget, and capacity invariants. Injected race conditions trigger bounded retries or safe escalation.
- **Interactive Gradio Dashboard**: Mounted directly alongside FastAPI at `/ui` for complete operational monitoring, scenario execution, and real-time approval management.

---

## System Architecture

```
Interface Layer (FastAPI REST & Gradio Blocks UI)
       │
       ▼
Controlled 9-Step Agent Workflow
       │
       ├──► 1. Investigate (Collect product, inventory, forecasts, sales, POs, budget, storage)
       ├──► 2. Plan (LangChain selects an action; deterministic evidence and hard checks constrain proposals)
       ├──► 3. Check Constraints (Product active, supplier available/capacity, MOQ, budget, storage)
       ├──► 4. Propose (Build immutable ActionProposal with idempotency key)
       ├──► 5. Approve (Threshold check: $500.00; cryptographic SHA-256 fingerprint)
       ├──► 6. Execute (Atomic database transaction via mutating tools)
       ├──► 7. Read Back (Fresh state refetched from database)
       ├──► 8. Validate (Independent policy invariants verification)
       └──► 9. Recover / Escalate (Self-healing bounded retries or safe buyer escalation)
```
For detailed diagrams and architectural specifications, see [docs/architecture.md](docs/architecture.md) and [docs/architecture.mmd](docs/architecture.mmd).

---

## Mathematical Formulas & Purchasing Invariants

1. **Available Inventory**:
   $$\text{Available} = \text{on\_hand} - \text{reserved}$$
   *Reserved stock is never counted as available.*

2. **Inventory Position**:
   $$\text{Inventory Position} = \text{Available} + \text{Confirmed Incoming POs}$$
   *Cancelled, unconfirmed, or rejected POs are strictly excluded.*

3. **Protection Period**:
   $$\text{Protection Period (days)} = \text{lead\_time\_days} + \text{review\_horizon\_days}$$

4. **Target Stock**:
   $$\text{Safety Stock} = \text{daily\_demand} \times \text{safety\_stock\_days}$$
   $$\text{Target Stock} = (\text{daily\_demand} \times \text{Protection Period}) + \text{Safety Stock}$$

5. **Replenishment Quantity**:
   $$\text{Raw Recommendation} = \max\left(0, \lceil \text{Target Stock} - \text{Inventory Position} \rceil\right)$$
   $$\text{Rounded Quantity} = \max\left(\text{MOQ}, \lceil \text{Raw} / \text{Order Multiple} \rceil \times \text{Order Multiple}\right)$$

---

## Four Core Purchasing Scenarios

1. **Scenario 1 — Purchase Recommendation Review (SKU: MILK-1L)**
   - Reviews an external recommendation of 800 units.
   - Dynamically checks warehouse inventory, pipeline POs, demand, budget, and storage.
   - Adjusts excessive or insufficient quantities, rejects redundant buys when incoming stock covers demand, or triggers approval when cost $\ge \$500.00$.

2. **Scenario 2 — Rice Supplier Recommendation (SKU: RICE-5KG)**
   - Compares 300 units of forecast demand over 10 days against an inventory position of 30, with no incoming supply or safety stock.
   - Rounds the 270-unit requirement using supplier MOQ and order multiples, then selects the lowest-cost feasible supplier.
   - Explicitly reports the supplier name, ordered quantity, unit price, total cost, lead time, and why infeasible suppliers were rejected.

3. **Scenario 3 — Demand Change (SKU: BREAD-WHT)**
   - Evaluates demand surge against baseline forecast.
   - Differentiates sustained spikes from short-term noise.
   - Evaluates supplier lead-time feasibility; if lead time cannot prevent a stockout, evaluates authorized Dark Store transfers (`NODE-SOUTH` ➔ `NODE-NORTH`) or escalates.

4. **Scenario 4 — Purchasing Constraints (SKU: OIL-1L)**
   - When budget, dark store storage, or supplier capacity constraints are breached, evaluates compliant quantities, alternate suppliers, or split deliveries.
   - Never bypasses hard constraints; safely escalates when no compliant path exists.

---

## Installation & Setup

### Prerequisites
- Python 3.11+
- Windows PowerShell or Bash

### 1. Clone & Navigate
```powershell
cd d:\SelfAssignment\Rappi
```

### 2. Create & Activate Virtual Environment
```powershell
# Using PowerShell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install Dependencies
```powershell
pip install -r requirements.txt
```

### 4. Configure Environment
```powershell
Copy-Item .env.example .env
```
*Note: SQLite is configured by default (`sqlite:///./data/purchasing.db`). Offline mode requires no API key. To enable LangChain decisions, set `LLM_PROVIDER` to `openai` or `gemini` and provide `LLM_API_KEY`.*

### Use Neon PostgreSQL

1. Create a Neon project and copy its **pooled or direct connection string** from the Neon dashboard.
2. Put the URL in your local `.env` file (not in source code or a committed file):

   ```dotenv
   DATABASE_URL=postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require
   ```

   Use the complete URL supplied by Neon, including any query parameters. The project accepts `postgres://` and `postgresql://` URLs; database credentials are read from `DATABASE_URL`.
3. Install dependencies and start the app as usual. On startup, SQLAlchemy creates missing tables and seeds the demo catalog if the database is empty.

The app enables connection health checks for pooled PostgreSQL connections. It does not print the connection URL. Scenario fixture resets update the selected demo records in place; they do not drop or recreate tables. They can still overwrite the demo records used by that fixture (for example, Scenario 2's Rice supplier offers and inventory at `NODE-NORTH`), so do not use fixture resets against business records that must remain unchanged.

The separate `reset_db` utility is destructive: it drops and recreates tables. It remains blocked for non-SQLite databases unless `ALLOW_DATABASE_RESET=true`. Fixture resets do not require that setting.

#### Run demos with Neon

Neon works with the in-place fixture reset. Keep `ALLOW_DATABASE_RESET=false`; the dashboard's **Reset fixture** button does not need permission to drop tables. The fixture updates only the selected scenario's demo records and leaves unrelated tables and records in place. Never paste database credentials into source control or chat.

---

## Running the Application & Dashboard

Start the integrated FastAPI and Gradio application:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Once started:
- **Interactive UI Dashboard**: [http://127.0.0.1:8000/ui](http://127.0.0.1:8000/ui) (or root [http://127.0.0.1:8000/](http://127.0.0.1:8000/))
- **Interactive Swagger Documentation**: [http://127.0.0.1:8000/api/docs](http://127.0.0.1:8000/api/docs)
- **ReDoc Documentation**: [http://127.0.0.1:8000/api/redoc](http://127.0.0.1:8000/api/redoc)
- **System Health Endpoint**: [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)

---

## Running Automated Tests

Run the full pytest suite:

```powershell
.\.venv\Scripts\pytest.exe -v
```

To run individual scenario test suites:
```powershell
# Scenario 1 (Recommendation Review)
.\.venv\Scripts\pytest.exe tests/test_scenario_1.py -v

# Scenario 2 (Rice Supplier Recommendation)
.\.venv\Scripts\pytest.exe tests/test_scenario_2.py -v

# Scenario 3 (Demand Surge)
.\.venv\Scripts\pytest.exe tests/test_scenario_3.py -v

# Scenario 4 (Multi-Constraint Optimization)
.\.venv\Scripts\pytest.exe tests/test_scenario_4.py -v

# Constraints & Rounding Math
.\.venv\Scripts\pytest.exe tests/test_constraints.py -v

# Feedback Loop, Fault Injection & Self-Healing
.\.venv\Scripts\pytest.exe tests/test_feedback_loop.py -v

# REST API & Security
.\.venv\Scripts\pytest.exe tests/test_api.py -v
```

---

## REST API Overview

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | System health, active database, and LLM mode. |
| `GET` | `/api/dashboard` | Aggregated operational KPI snapshot. |
| `GET` | `/api/products` | Active catalog listing with dimensions & unit costs. |
| `GET` | `/api/inventory` | On-hand, reserved, and available stock per node. |
| `GET` | `/api/suppliers` | Suppliers, offerings, lead times, and reliability scores. |
| `GET` | `/api/purchase-orders` | Purchase orders with status, incoming flag, and idempotency. |
| `GET` | `/api/approvals` | Human approval queue and decisions. |
| `GET` | `/api/audit` | Comprehensive audit trail with before/after state diffs. |
| `POST` | `/api/scenarios/{id}/run` | Execute any scenario (`s1`–`s4`) with custom fixture. |
| `POST` | `/api/scenarios/{id}/reset` | Reset database state to clean scenario fixture. |
| `POST` | `/api/approvals/{id}/approve` | Approve an action pending human decision. |
| `POST` | `/api/approvals/{id}/reject` | Reject a proposed purchase action. |
| `POST` | `/api/actions/{id}/execute` | Execute an approved action. |
| `POST` | `/api/actions/{id}/validate` | Independently validate persisted state. |
| `POST` | `/api/purchase-orders` | Direct creation **blocked (403)** to enforce agent governance. |

---

## Auditability & Safety Features

- **Approval Threshold**: Purchases $\ge \$500.00$ require human buyer approval.
- **Cryptographic Fingerprint**: Approval tokens bind to payload SHA-256 hashes. If quantity, price, or supplier changes post-approval, the approval is automatically invalidated.
- **Idempotency Keys**: Action records and purchase orders enforce database-level uniqueness to prevent duplicate orders during retries.
- **Fail-Safe Self-Healing**: Post-validation recovery safely retries transient persistence failures and escalates storage/budget race conditions without corruption.
