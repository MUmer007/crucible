import hashlib
import string
import uuid
from datetime import UTC, datetime

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select

from crucible.db.models import Charge, Refund, Run

# Strategy for generating random refund amounts (between 100 and 1000 cents)
amount_strategy = st.integers(min_value=100, max_value=1000)

# Strategy for generating random ASCII idempotency keys (or None)
# HTTP headers must be ASCII, so we restrict the alphabet to letters and digits
key_strategy = st.one_of(
    st.none(), 
    st.text(alphabet=string.ascii_letters + string.digits, min_size=10, max_size=30)
)

@given(
    num_requests=st.integers(min_value=5, max_value=20),
    amounts=st.lists(amount_strategy, min_size=5, max_size=20),
    keys=st.lists(key_strategy, min_size=5, max_size=20)
)
@settings(
    max_examples=20, 
    deadline=None, 
    suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@pytest.mark.asyncio
async def test_refund_invariants_under_random_sequences(db_session, client, num_requests, amounts, keys):
    run_id = uuid.uuid4()
    test_token = f"test-token-{uuid.uuid4()}"
    token_hash = hashlib.sha256(test_token.encode()).hexdigest()
    charge_id = "ch_prop_test"
    total_charge_amount = 10000

    run = Run(
        id=run_id, scenario_id="prop-test", scenario_version="v1", run_seed=42,
        token_hash=token_hash, status="running", started_at=datetime.now(UTC)
    )
    db_session.add(run)
    await db_session.flush()

    charge = Charge(
        run_id=run_id, id=charge_id, customer_id="cus_test", amount_cents=total_charge_amount,
        currency="usd", description="Property test charge", refunded_cents=0, initial_refunded_cents=0
    )
    db_session.add(charge)
    await db_session.commit()

    headers = {
        "Authorization": f"Bearer {test_token}",
        "Content-Type": "application/json"
    }

    responses_by_key = {}

    for i in range(num_requests):
        amount = amounts[i % len(amounts)]
        key = keys[i % len(keys)]
        
        req_headers = headers.copy()
        if key is not None:
            req_headers["Idempotency-Key"] = key
            
        payload = {"charge_id": charge_id, "amount_cents": amount, "reason": "prop test"}
        
        resp = await client.post("/payments/refunds", json=payload, headers=req_headers)
        
        # Parse JSON if applicable to avoid key-order string mismatches
        if "application/json" in resp.headers.get("content-type", ""):
            body_to_compare = resp.json()
        else:
            body_to_compare = resp.text

        if key is not None:
            cache_key = (key, str(payload))
            if cache_key in responses_by_key:
                assert resp.status_code == responses_by_key[cache_key]["status"], f"Status mismatch for key {key}"
                assert body_to_compare == responses_by_key[cache_key]["body"], f"Body mismatch for key {key}"
            else:
                responses_by_key[cache_key] = {"status": resp.status_code, "body": body_to_compare}

    # Force SQLAlchemy to discard cached objects and fetch fresh data from the DB
    db_session.expire_all()

    stmt_charge = select(Charge).where(Charge.run_id == run_id, Charge.id == charge_id)
    result_charge = await db_session.execute(stmt_charge)
    final_charge = result_charge.scalar_one()

    assert final_charge.refunded_cents <= total_charge_amount, \
        f"Over-refund detected! Refunded {final_charge.refunded_cents} > {total_charge_amount}"

    stmt_refunds = select(Refund).where(Refund.run_id == run_id, Refund.charge_id == charge_id)
    result_refunds = await db_session.execute(stmt_refunds)
    refund_rows = result_refunds.scalars().all()
    
    total_refunded_from_rows = sum(r.amount_cents for r in refund_rows)
    assert total_refunded_from_rows == final_charge.refunded_cents, \
        f"DB state mismatch! Rows sum to {total_refunded_from_rows}, but charge says {final_charge.refunded_cents}"
