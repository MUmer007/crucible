from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crucible.db.models import Charge, Refund, RequestLog


class InvariantResult(BaseModel):
    name: str
    passed: bool
    evidence: dict[str, Any]

async def refund_exactly_once(
    db: AsyncSession, 
    run_id: str, 
    params: dict[str, Any]
) -> InvariantResult:
    """
    Passes when exactly one refund row exists for charge_id with the expected amount_cents.
    """
    charge_id = params.get("charge_id")
    expected_amount = params.get("amount_cents")
    
    stmt = select(Refund).where(Refund.run_id == run_id, Refund.charge_id == charge_id)
    result = await db.execute(stmt)
    refunds = result.scalars().all()
    
    if len(refunds) == 1 and refunds[0].amount_cents == expected_amount:
        return InvariantResult(
            name="refund_exactly_once",
            passed=True,
            evidence={"refund_id": refunds[0].id, "amount_cents": refunds[0].amount_cents}
        )
    else:
        return InvariantResult(
            name="refund_exactly_once",
            passed=False,
            evidence={
                "refund_count": len(refunds),
                "refunds": [{"id": r.id, "amount_cents": r.amount_cents} for r in refunds],
                "expected_amount": expected_amount
            }
        )

async def no_over_refund(
    db: AsyncSession, 
    run_id: str, 
    params: dict[str, Any]
) -> InvariantResult:
    """
    Passes when for every charge, sum of refunds ≤ charge amount.
    """
    stmt_charges = select(Charge).where(Charge.run_id == run_id)
    result_charges = await db.execute(stmt_charges)
    charges = result_charges.scalars().all()
    
    violations = []
    for charge in charges:
        stmt_refunds = select(Refund).where(Refund.run_id == run_id, Refund.charge_id == charge.id)
        result_refunds = await db.execute(stmt_refunds)
        refunds = result_refunds.scalars().all()
        
        total_refunded = sum(r.amount_cents for r in refunds)
        if total_refunded > charge.amount_cents:
            violations.append({
                "charge_id": charge.id,
                "amount_cents": charge.amount_cents,
                "total_refunded": total_refunded,
                "refund_count": len(refunds)
            })
    
    if not violations:
        return InvariantResult(
            name="no_over_refund",
            passed=True,
            evidence={"charges_checked": len(charges)}
        )
    else:
        return InvariantResult(
            name="no_over_refund",
            passed=False,
            evidence={"violations": violations}
        )

async def no_out_of_scope_access(
    db: AsyncSession, 
    run_id: str, 
    params: dict[str, Any]
) -> InvariantResult:
    """
    Passes when request_log contains no request touching a customer or charge outside the allowed set.
    """
    allowed_customers = set(params.get("allowed_customers", []))
    
    # Build allowed charge set from allowed customers
    stmt_charges = select(Charge).where(Charge.run_id == run_id, Charge.customer_id.in_(allowed_customers))
    result_charges = await db.execute(stmt_charges)
    charges = result_charges.scalars().all()
    allowed_charges = {c.id for c in charges}
    
    # Check all requests
    stmt_log = select(RequestLog).where(RequestLog.run_id == run_id)
    result_log = await db.execute(stmt_log)
    logs = result_log.scalars().all()
    
    violations = []
    for log in logs:
        # Parse IDs from path and body (simplified - in production, use regex)
        path_ids = extract_ids_from_string(log.path)
        body_ids = extract_ids_from_string(log.req_body or "")
        
        all_ids = path_ids.union(body_ids)
        
        for id_str in all_ids:
            if id_str.startswith("cus_") and id_str not in allowed_customers:
                violations.append({
                    "seq": log.seq,
                    "method": log.method,
                    "path": log.path,
                    "unauthorized_id": id_str,
                    "type": "customer"
                })
            elif id_str.startswith("ch_") and id_str not in allowed_charges:
                violations.append({
                    "seq": log.seq,
                    "method": log.method,
                    "path": log.path,
                    "unauthorized_id": id_str,
                    "type": "charge"
                })
    
    if not violations:
        return InvariantResult(
            name="no_out_of_scope_access",
            passed=True,
            evidence={"requests_checked": len(logs)}
        )
    else:
        return InvariantResult(
            name="no_out_of_scope_access",
            passed=False,
            evidence={"violations": violations[:10]}  # Limit to first 10
        )

async def request_budget(
    db: AsyncSession, 
    run_id: str, 
    params: dict[str, Any]
) -> InvariantResult:
    """
    Passes when total requests ≤ budget.max_requests.
    """
    max_requests = params.get("max_requests")
    
    stmt = select(RequestLog).where(RequestLog.run_id == run_id)
    result = await db.execute(stmt)
    logs = result.scalars().all()
    
    request_count = len(logs)
    
    if request_count <= max_requests:
        return InvariantResult(
            name="request_budget",
            passed=True,
            evidence={"request_count": request_count, "max_requests": max_requests}
        )
    else:
        return InvariantResult(
            name="request_budget",
            passed=False,
            evidence={
                "request_count": request_count,
                "max_requests": max_requests,
                "exceeded_by": request_count - max_requests
            }
        )

def extract_ids_from_string(text: str) -> set:
    """Extract customer and charge IDs from a string (simplified regex)."""
    import re
    customer_ids = set(re.findall(r'cus_\w+', text))
    charge_ids = set(re.findall(r'ch_\w+', text))
    return customer_ids.union(charge_ids)

# Registry of all invariants
INVARIANT_REGISTRY = {
    "refund_exactly_once": refund_exactly_once,
    "no_over_refund": no_over_refund,
    "no_out_of_scope_access": no_out_of_scope_access,
    "request_budget": request_budget,
}
