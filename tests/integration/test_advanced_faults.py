import hashlib
import uuid
from datetime import UTC, datetime

import pytest

from crucible.db.models import Charge, Run
from crucible.sandbox.faults.middleware import register_faults
from crucible.sandbox.faults.types import FaultRule, MatchCondition


@pytest.mark.asyncio
async def test_http_500_fault(db_session, client):
    run_id = uuid.uuid4()
    test_token = f"test-token-{uuid.uuid4()}"
    token_hash = hashlib.sha256(test_token.encode()).hexdigest()
    charge_id = "ch_500_test"

    run = Run(
        id=run_id, scenario_id="test", scenario_version="v1", run_seed=42,
        token_hash=token_hash, status="running", started_at=datetime.now(UTC)
    )
    db_session.add(run)
    await db_session.flush()

    charge = Charge(
        run_id=run_id, id=charge_id, customer_id="cus_test", amount_cents=5000,
        currency="usd", description="Test", refunded_cents=0, initial_refunded_cents=0
    )
    db_session.add(charge)
    await db_session.commit()

    rule = FaultRule(
        id="f_500",
        match=MatchCondition(method="POST", path="/payments/refunds"),
        on_call=[1],
        type="http_500",
        params={}
    )
    register_faults(str(run_id), [rule])

    headers = {"Authorization": f"Bearer {test_token}", "Content-Type": "application/json"}
    payload = {"charge_id": charge_id, "amount_cents": 100, "reason": "test"}
    
    resp = await client.post("/payments/refunds", json=payload, headers=headers)
    assert resp.status_code == 500
    assert resp.text == "Internal Server Error"

@pytest.mark.asyncio
async def test_malformed_json_fault(db_session, client):
    run_id = uuid.uuid4()
    test_token = f"test-token-{uuid.uuid4()}"
    token_hash = hashlib.sha256(test_token.encode()).hexdigest()
    charge_id = "ch_malformed_test"

    run = Run(
        id=run_id, scenario_id="test", scenario_version="v1", run_seed=42,
        token_hash=token_hash, status="running", started_at=datetime.now(UTC)
    )
    db_session.add(run)
    await db_session.flush()

    charge = Charge(
        run_id=run_id, id=charge_id, customer_id="cus_test", amount_cents=5000,
        currency="usd", description="Test", refunded_cents=0, initial_refunded_cents=0
    )
    db_session.add(charge)
    await db_session.commit()

    rule = FaultRule(
        id="f_malformed",
        match=MatchCondition(method="POST", path="/payments/refunds"),
        on_call=[1],
        type="malformed_json",
        params={}
    )
    register_faults(str(run_id), [rule])

    headers = {"Authorization": f"Bearer {test_token}", "Content-Type": "application/json"}
    payload = {"charge_id": charge_id, "amount_cents": 100, "reason": "test"}
    
    resp = await client.post("/payments/refunds", json=payload, headers=headers)
    assert resp.status_code == 200
    assert resp.text == "{ this is not valid json }"
    assert "application/json" in resp.headers.get("content-type", "")

@pytest.mark.asyncio
async def test_stale_read_fault(db_session, client):
    run_id = uuid.uuid4()
    test_token = f"test-token-{uuid.uuid4()}"
    token_hash = hashlib.sha256(test_token.encode()).hexdigest()

    run = Run(
        id=run_id, scenario_id="test", scenario_version="v1", run_seed=42,
        token_hash=token_hash, status="running", started_at=datetime.now(UTC)
    )
    db_session.add(run)
    await db_session.flush()
    await db_session.commit()

    stale_payload = '{"id": "ch_old", "status": "pending", "refunded_cents": 0}'
    rule = FaultRule(
        id="f_stale",
        match=MatchCondition(method="GET", path="/payments/charges/.*"),
        on_call=[1],
        type="stale_read",
        params={"stale_body": stale_payload}
    )
    register_faults(str(run_id), [rule])

    headers = {"Authorization": f"Bearer {test_token}"}
    
    resp = await client.get("/payments/charges/ch_old", headers=headers)
    assert resp.status_code == 200
    assert resp.text == stale_payload
