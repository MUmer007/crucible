import hashlib
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from crucible.db.models import Charge, Refund, Run
from crucible.sandbox.faults.middleware import register_faults
from crucible.sandbox.faults.types import FaultRule, MatchCondition


@pytest.mark.asyncio
async def test_commit_then_timeout_fault(db_session, client):
    run_id = uuid.uuid4()
    test_token = f"test-token-{uuid.uuid4()}"
    token_hash = hashlib.sha256(test_token.encode()).hexdigest()
    charge_id = "ch_ghost_test"

    # 1. Seed run and charge
    run = Run(
        id=run_id, scenario_id="ghost-test", scenario_version="v1", run_seed=42,
        token_hash=token_hash, status="running", started_at=datetime.now(UTC)
    )
    db_session.add(run)
    await db_session.flush()

    charge = Charge(
        run_id=run_id, id=charge_id, customer_id="cus_test", amount_cents=5000,
        currency="usd", description="Ghost test charge", refunded_cents=0, initial_refunded_cents=0
    )
    db_session.add(charge)
    await db_session.commit()

    # 2. Register a commit_then_timeout fault for this run
    rule = FaultRule(
        id="f_ghost",
        match=MatchCondition(method="POST", path="/payments/refunds"),
        on_call=[1],
        type="commit_then_timeout",
        params={"delay_ms": 100} # Short delay for testing
    )
    register_faults(str(run_id), [rule])

    # 3. Make the refund request
    headers = {
        "Authorization": f"Bearer {test_token}",
        "Idempotency-Key": "idem-ghost-1",
        "Content-Type": "application/json"
    }
    payload = {"charge_id": charge_id, "amount_cents": 5000, "reason": "ghost test"}
    
    resp = await client.post("/payments/refunds", json=payload, headers=headers)

    # 4. Assert client sees 504
    assert resp.status_code == 504, f"Expected 504, got {resp.status_code}"

    # 5. Force SQLAlchemy to discard cached objects and fetch fresh data from the DB
    db_session.expire_all()

    # 6. Assert DB state shows the refund WAS committed (ghost success)
    stmt_refund = select(Refund).where(Refund.run_id == run_id, Refund.charge_id == charge_id)
    result_refund = await db_session.execute(stmt_refund)
    refund_row = result_refund.scalar_one_or_none()
    
    assert refund_row is not None, "Refund row should exist in DB despite 504 response"
    assert refund_row.amount_cents == 5000

    stmt_charge = select(Charge).where(Charge.run_id == run_id, Charge.id == charge_id)
    result_charge = await db_session.execute(stmt_charge)
    final_charge = result_charge.scalar_one()
    
    assert final_charge.refunded_cents == 5000, "Charge should reflect the committed refund"
