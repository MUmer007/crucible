# src/crucible/sandbox/payments/service.py
import hashlib
import json
import uuid

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from crucible.db.models import Charge, IdempotencyKey, Refund


def canonical_json(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True).encode("utf-8")

async def create_refund(
    db: AsyncSession, 
    run_id: uuid.UUID, 
    idempotency_key: str | None, 
    req: dict
) -> dict:
    try:
        body_hash = hashlib.sha256(canonical_json(req)).hexdigest()
        
        if idempotency_key:
            # 1. Atomically claim the idempotency key or fetch the existing one.
            # The ON CONFLICT DO UPDATE forces PostgreSQL to wait for any concurrent 
            # transaction holding the unique index lock to finish, then returns the final row.
            insert_stmt = (
                pg_insert(IdempotencyKey)
                .values(
                    run_id=run_id,
                    key=idempotency_key,
                    request_hash=body_hash,
                    status_code=0,
                    response_json={}
                )
                .on_conflict_do_update(
                    index_elements=['run_id', 'key'],
                    set_={"request_hash": body_hash} # Dummy update to satisfy syntax and trigger RETURNING
                )
                .returning(
                    IdempotencyKey.request_hash,
                    IdempotencyKey.status_code,
                    IdempotencyKey.response_json
                )
            )
            result = await db.execute(insert_stmt)
            row = result.fetchone()
            
            if row.request_hash != body_hash:
                raise HTTPException(status_code=422, detail="idempotency_key_reuse")
            
            if row.status_code != 0:
                # Another request already processed this and committed the final result.
                # We just replay it.
                return {
                    "status_code": row.status_code,
                    "body": row.response_json
                }
            
            # If we reach here, we are the FIRST request to claim this key (status_code is 0).
            # We will proceed to process the refund and update the row at the end.

        # 2. Lock the charge for update to serialize concurrent refunds on the same charge
        charge_stmt = (
            select(Charge)
            .where(Charge.run_id == run_id, Charge.id == req["charge_id"])
            .with_for_update()
        )
        charge = (await db.execute(charge_stmt)).scalar_one_or_none()
        
        if charge is None:
            resp = {"status_code": 404, "body": {"detail": "charge_not_found"}}
        elif req["amount_cents"] > (charge.amount_cents - charge.refunded_cents):
            resp = {"status_code": 400, "body": {"detail": "refund_exceeds_charge"}}
        else:
            # 3. Create the refund and update the charge
            refund_id = f"re_{uuid.uuid4().hex[:16]}"
            refund = Refund(
                run_id=run_id,
                id=refund_id,
                charge_id=charge.id,
                amount_cents=req["amount_cents"],
                reason=req["reason"],
                idempotency_key=idempotency_key
            )
            charge.refunded_cents += req["amount_cents"]
            db.add(refund)
            
            resp = {
                "status_code": 201,
                "body": {
                    "id": refund.id,
                    "charge_id": refund.charge_id,
                    "amount_cents": refund.amount_cents,
                    "reason": refund.reason
                }
            }
            
        # 4. Store the final response for future replays
        if idempotency_key:
            update_stmt = (
                update(IdempotencyKey)
                .where(
                    IdempotencyKey.run_id == run_id,
                    IdempotencyKey.key == idempotency_key
                )
                .values(
                    status_code=resp["status_code"],
                    response_json=resp["body"]
                )
            )
            await db.execute(update_stmt)
            
        # 5. Commit the transaction
        await db.commit()
        return resp
        
    except Exception:
        # Rollback on any error to keep the session clean and release locks
        await db.rollback()
        raise