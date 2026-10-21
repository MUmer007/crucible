import hashlib
import uuid
from datetime import UTC, datetime

import pytest

from crucible.db.models import Charge, Refund, RequestLog, Run
from crucible.verify.invariants import (
    no_out_of_scope_access,
    no_over_refund,
    refund_exactly_once,
    request_budget,
)


def make_unique_token_hash(suffix: str) -> str:
    return hashlib.sha256(f"test-token-{suffix}-{uuid.uuid4()}".encode()).hexdigest()

@pytest.mark.asyncio
async def test_refund_exactly_once_passes(db_session):
    run_id = uuid.uuid4()
    run = Run(
        id=run_id, scenario_id="test", scenario_version="v1", run_seed=42,
        token_hash=make_unique_token_hash("1"), status="finished", started_at=datetime.now(UTC)
    )
    db_session.add(run)
    await db_session.flush()
    
    charge = Charge(
        run_id=run_id, id="ch_test", customer_id="cus_test", amount_cents=5000,
        currency="usd", description="Test", refunded_cents=5000, initial_refunded_cents=0
    )
    db_session.add(charge)
    await db_session.flush()
    
    refund = Refund(
        run_id=run_id, id="re_test", charge_id="ch_test", amount_cents=5000,
        reason="test", idempotency_key="idem_test"
    )
    db_session.add(refund)
    await db_session.commit()
    
    result = await refund_exactly_once(db_session, str(run_id), {"charge_id": "ch_test", "amount_cents": 5000})
    assert result.passed is True
    assert result.evidence["amount_cents"] == 5000

@pytest.mark.asyncio
async def test_refund_exactly_once_fails_no_refund(db_session):
    run_id = uuid.uuid4()
    run = Run(
        id=run_id, scenario_id="test", scenario_version="v1", run_seed=42,
        token_hash=make_unique_token_hash("2"), status="finished", started_at=datetime.now(UTC)
    )
    db_session.add(run)
    await db_session.flush()
    
    charge = Charge(
        run_id=run_id, id="ch_test2", customer_id="cus_test", amount_cents=5000,
        currency="usd", description="Test", refunded_cents=0, initial_refunded_cents=0
    )
    db_session.add(charge)
    await db_session.commit()
    
    result = await refund_exactly_once(db_session, str(run_id), {"charge_id": "ch_test2", "amount_cents": 5000})
    assert result.passed is False
    assert result.evidence["refund_count"] == 0

@pytest.mark.asyncio
async def test_no_over_refund_passes(db_session):
    run_id = uuid.uuid4()
    run = Run(
        id=run_id, scenario_id="test", scenario_version="v1", run_seed=42,
        token_hash=make_unique_token_hash("3"), status="finished", started_at=datetime.now(UTC)
    )
    db_session.add(run)
    await db_session.flush()
    
    charge = Charge(
        run_id=run_id, id="ch_test3", customer_id="cus_test", amount_cents=5000,
        currency="usd", description="Test", refunded_cents=3000, initial_refunded_cents=0
    )
    db_session.add(charge)
    await db_session.flush()
    
    refund = Refund(
        run_id=run_id, id="re_test3", charge_id="ch_test3", amount_cents=3000,
        reason="test", idempotency_key="idem_test3"
    )
    db_session.add(refund)
    await db_session.commit()
    
    result = await no_over_refund(db_session, str(run_id), {})
    assert result.passed is True

@pytest.mark.asyncio
async def test_no_over_refund_fails(db_session):
    run_id = uuid.uuid4()
    run = Run(
        id=run_id, scenario_id="test", scenario_version="v1", run_seed=42,
        token_hash=make_unique_token_hash("4"), status="finished", started_at=datetime.now(UTC)
    )
    db_session.add(run)
    await db_session.flush()
    
    # Valid charge state (refunded_cents=0)
    charge = Charge(
        run_id=run_id, id="ch_test4", customer_id="cus_test", amount_cents=5000,
        currency="usd", description="Test", refunded_cents=0, initial_refunded_cents=0
    )
    db_session.add(charge)
    await db_session.flush()
    
    # Two refunds that SUM to more than the charge amount (4000 + 2000 = 6000 > 5000)
    refund1 = Refund(
        run_id=run_id, id="re_test4a", charge_id="ch_test4", amount_cents=4000,
        reason="test", idempotency_key="idem_test4a"
    )
    refund2 = Refund(
        run_id=run_id, id="re_test4b", charge_id="ch_test4", amount_cents=2000,
        reason="test", idempotency_key="idem_test4b"
    )
    db_session.add(refund1)
    db_session.add(refund2)
    await db_session.commit()
    
    result = await no_over_refund(db_session, str(run_id), {})
    assert result.passed is False
    assert len(result.evidence["violations"]) == 1
    assert result.evidence["violations"][0]["charge_id"] == "ch_test4"

@pytest.mark.asyncio
async def test_no_out_of_scope_access_passes(db_session):
    run_id = uuid.uuid4()
    run = Run(
        id=run_id, scenario_id="test", scenario_version="v1", run_seed=42,
        token_hash=make_unique_token_hash("5"), status="finished", started_at=datetime.now(UTC)
    )
    db_session.add(run)
    await db_session.flush()
    
    charge = Charge(
        run_id=run_id, id="ch_test5", customer_id="cus_allowed", amount_cents=5000,
        currency="usd", description="Test", refunded_cents=0, initial_refunded_cents=0
    )
    db_session.add(charge)
    await db_session.flush()
    
    log = RequestLog(
        run_id=run_id, seq=1, method="GET", path="/payments/charges/ch_test5",
        req_body="", status=200, resp_body="", fault_applied=None
    )
    db_session.add(log)
    await db_session.commit()
    
    result = await no_out_of_scope_access(db_session, str(run_id), {"allowed_customers": ["cus_allowed"]})
    assert result.passed is True

@pytest.mark.asyncio
async def test_no_out_of_scope_access_fails(db_session):
    run_id = uuid.uuid4()
    run = Run(
        id=run_id, scenario_id="test", scenario_version="v1", run_seed=42,
        token_hash=make_unique_token_hash("6"), status="finished", started_at=datetime.now(UTC)
    )
    db_session.add(run)
    await db_session.flush()
    
    charge = Charge(
        run_id=run_id, id="ch_test6", customer_id="cus_allowed", amount_cents=5000,
        currency="usd", description="Test", refunded_cents=0, initial_refunded_cents=0
    )
    db_session.add(charge)
    await db_session.flush()
    
    # Request to unauthorized customer
    log = RequestLog(
        run_id=run_id, seq=1, method="GET", path="/payments/customers/cus_unauthorized",
        req_body="", status=200, resp_body="", fault_applied=None
    )
    db_session.add(log)
    await db_session.commit()
    
    result = await no_out_of_scope_access(db_session, str(run_id), {"allowed_customers": ["cus_allowed"]})
    assert result.passed is False
    assert len(result.evidence["violations"]) == 1
    assert result.evidence["violations"][0]["unauthorized_id"] == "cus_unauthorized"

@pytest.mark.asyncio
async def test_request_budget_passes(db_session):
    run_id = uuid.uuid4()
    run = Run(
        id=run_id, scenario_id="test", scenario_version="v1", run_seed=42,
        token_hash=make_unique_token_hash("7"), status="finished", started_at=datetime.now(UTC)
    )
    db_session.add(run)
    await db_session.flush()
    
    for i in range(5):
        log = RequestLog(
            run_id=run_id, seq=i+1, method="GET", path="/health",
            req_body="", status=200, resp_body="", fault_applied=None
        )
        db_session.add(log)
    await db_session.commit()
    
    result = await request_budget(db_session, str(run_id), {"max_requests": 10})
    assert result.passed is True
    assert result.evidence["request_count"] == 5

@pytest.mark.asyncio
async def test_request_budget_fails(db_session):
    run_id = uuid.uuid4()
    run = Run(
        id=run_id, scenario_id="test", scenario_version="v1", run_seed=42,
        token_hash=make_unique_token_hash("8"), status="finished", started_at=datetime.now(UTC)
    )
    db_session.add(run)
    await db_session.flush()
    
    for i in range(15):
        log = RequestLog(
            run_id=run_id, seq=i+1, method="GET", path="/health",
            req_body="", status=200, resp_body="", fault_applied=None
        )
        db_session.add(log)
    await db_session.commit()
    
    result = await request_budget(db_session, str(run_id), {"max_requests": 10})
    assert result.passed is False
    assert result.evidence["request_count"] == 15
    assert result.evidence["exceeded_by"] == 5
