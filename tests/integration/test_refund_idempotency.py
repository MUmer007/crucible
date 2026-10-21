# tests/integration/test_refund_idempotency.py
import asyncio
import hashlib
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from crucible.db.models import Charge, Refund, Run


@pytest.mark.asyncio
async def test_concurrent_idempotent_refunds(db_session, client):
    run_id = uuid.uuid4()
    charge_id = "ch_test_concurrent_001"
    idempotency_key = "idem-key-concurrent-test-unique"
    
    # Generate a unique token for this specific test run to avoid UniqueViolation
    test_token = f"test-token-{uuid.uuid4()}"
    token_hash = hashlib.sha256(test_token.encode()).hexdigest()

    # 1. Seed the run directly in the DB
    run = Run(
        id=run_id,
        scenario_id="test-scenario",
        scenario_version="v1",
        run_seed=42,
        token_hash=token_hash,
        status="running",
        started_at=datetime.now(UTC)
    )
    db_session.add(run)
    
    # FORCE the run to be inserted so the foreign key is satisfied
    await db_session.flush()

    # 2. Seed the charge
    charge = Charge(
        run_id=run_id,
        id=charge_id,
        customer_id="cus_test",
        amount_cents=5000,
        currency="usd",
        description="Test charge for concurrency",
        refunded_cents=0,
        initial_refunded_cents=0
    )
    db_session.add(charge)
    await db_session.commit()

    # 3. Fire 20 concurrent identical refund requests
    headers = {
        "Authorization": f"Bearer {test_token}",
        "Idempotency-Key": idempotency_key,
        "Content-Type": "application/json"
    }
    payload = {
        "charge_id": charge_id,
        "amount_cents": 5000,
        "reason": "concurrent test"
    }

    async def make_request():
        return await client.post("/payments/refunds", json=payload, headers=headers)

    tasks = [make_request() for _ in range(20)]
    responses = await asyncio.gather(*tasks)

    # 4. Assert all responses are successful 
    # (This WILL fail right now with a 404, which is exactly what we want!)
    for resp in responses:
        assert resp.status_code in (200, 201), f"Unexpected status: {resp.status_code} - {resp.text}"

    # 5. Verify EXACTLY ONE refund row was created in the DB
    db_session.expire_all()
    stmt = select(Refund).where(Refund.run_id == run_id, Refund.charge_id == charge_id)
    result = await db_session.execute(stmt)
    refunds = result.scalars().all()
    
    assert len(refunds) == 1, f"Expected exactly 1 refund row, but found {len(refunds)}"

    # 6. Verify the charge was refunded exactly once
    db_session.expire_all()
    stmt_charge = select(Charge).where(Charge.run_id == run_id, Charge.id == charge_id)
    result_charge = await db_session.execute(stmt_charge)
    updated_charge = result_charge.scalar_one()
    
    assert updated_charge.refunded_cents == 5000, f"Expected 5000 refunded cents, got {updated_charge.refunded_cents}"