from __future__ import annotations


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["llm_mode"] == "deterministic"


def test_ui_loads_after_database_initialization(client):
    r = client.get("/ui/")
    assert r.status_code == 200


def test_catalog_endpoints(client):
    assert client.get("/api/products").status_code == 200
    assert client.get("/api/inventory").status_code == 200
    assert client.get("/api/suppliers").status_code == 200
    assert client.get("/api/purchase-orders").status_code == 200
    assert client.get("/api/approvals").status_code == 200
    assert client.get("/api/audit").status_code == 200
    assert client.get("/api/dashboard").status_code == 200
    dash = client.get("/api/dashboard").json()
    assert dash["products"] >= 1
    assert dash["nodes"] >= 2


def test_unknown_scenario(client):
    r = client.post("/api/scenarios/nope/run", json={"fixture_key": "default"})
    assert r.status_code == 404


def test_direct_po_forbidden(client):
    r = client.post("/api/purchase-orders", json={"qty": 1})
    assert r.status_code == 403
    r = client.patch("/api/purchase-orders/PO-S2-001", json={"qty": 1})
    assert r.status_code == 403


def test_run_and_reset(client):
    r = client.post("/api/scenarios/s1/reset", params={"fixture_key": "appropriate"})
    assert r.status_code == 200
    r = client.post("/api/scenarios/s1/run", json={"fixture_key": "appropriate", "execute": False})
    assert r.status_code == 200
    body = r.json()
    assert body["scenario_id"] == "s1"
    assert "decision" in body
    assert body["reasoning_mode"] == "deterministic"


def test_approval_not_found(client):
    r = client.post("/api/approvals/APR-missing/approve", json={"approver": "buyer.demo", "reason": "x"})
    assert r.status_code == 404
