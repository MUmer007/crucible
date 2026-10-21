import asyncio
import hashlib
import uuid
from datetime import UTC, datetime

import pytest

from crucible.db.models import Charge, Run


@pytest.mark.asyncio
async def test_rate_limiter(db_session, client):
    run_id = uuid.uuid4()
    test_token = f"test-token-{uuid.uuid4()}"
    token_hash = hashlib.sha256(test_token.encode()).hexdigest()
    
    run = Run(
        id=run_id, scenario_id="test", scenario_version="v1", run_seed=42, 
        token_hash=token_hash, status="running", started_at=datetime.now(UTC)
    )
    db_session.add(run)
    await db_session.flush()
    
    # Use a large amount so we don't hit the 'refund_exceeds_charge' error
    charge = Charge(
        run_id=run_id, id="ch_rate_test", customer_id="cus_test", amount_cents=50000, 
        currency="usd", description="Test", refunded_cents=0, initial_refunded_cents=0
    )
    db_session.add(charge)
    await db_session.commit()

    headers = {
        "Authorization": f"Bearer {test_token}",
        "Content-Type": "application/json"
    }
    payload = {"charge_id": "ch_rate_test", "amount_cents": 100, "reason": "test"}

    async def make_request():
        return await client.post("/payments/refunds", json=payload, headers=headers)

    # Fire 40 requests rapidly
    tasks = [make_request() for _ in range(40)]
    responses = await asyncio.gather(*tasks)

    status_codes = [r.status_code for r in responses]
    
    # Verify we got some 429s
    assert 429 in status_codes, f"Expected at least one 429, got {status_codes}"
    
    # Verify Retry-After header is present on 429s
    for r in responses:
        if r.status_code == 429:
            assert "Retry-After" in r.headers, "429 response must include Retry-After header"
            assert r.headers["Retry-After"] == "10"

    # Verify at most 30 successes (201) due to rate limiting
    success_count = status_codes.count(201)
    rate_limited_count = status_codes.count(429)
    
    assert success_count <= 30, f"Expected at most 30 successes, got {success_count}"
    assert rate_limited_count >= 10, f"Expected at least 10 rate limited requests, got {rate_limited_count}"
