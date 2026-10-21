import hashlib
import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crucible.db.models import Charge, Customer, Run
from crucible.db.session import get_session
from crucible.sandbox.payments.schemas import ChargeOut, CustomerOut, RefundIn
from crucible.sandbox.payments.service import create_refund

router = APIRouter(prefix="/payments", tags=["payments"])

async def get_run_id_from_token(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)]
) -> uuid.UUID:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")

    token = auth_header[7:]
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    stmt = select(Run).where(Run.token_hash == token_hash, Run.status == "running")
    run = (await db.execute(stmt)).scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return run.id

@router.post("/refunds", response_model=None)
async def refund(
    req: RefundIn,
    db: Annotated[AsyncSession, Depends(get_session)],
    run_id: uuid.UUID = Depends(get_run_id_from_token),  # noqa: B008
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")
):
    req_dict = req.model_dump()
    result = await create_refund(db, run_id, idempotency_key, req_dict)

    if result["status_code"] == 404:
        raise HTTPException(status_code=404, detail="charge_not_found")
    if result["status_code"] == 400:
        raise HTTPException(status_code=400, detail="refund_exceeds_charge")

    return Response(
        content=json.dumps(result["body"]),
        status_code=result["status_code"],
        media_type="application/json"
    )

@router.get("/customers/{customer_id}", response_model=CustomerOut)
async def get_customer(
    customer_id: str,
    db: Annotated[AsyncSession, Depends(get_session)],
    run_id: uuid.UUID = Depends(get_run_id_from_token)  # noqa: B008
):
    stmt = select(Customer).where(Customer.run_id == run_id, Customer.id == customer_id)
    customer = (await db.execute(stmt)).scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="customer_not_found")
    return customer

@router.get("/charges/{charge_id}", response_model=ChargeOut)
async def get_charge(
    charge_id: str,
    db: Annotated[AsyncSession, Depends(get_session)],
    run_id: uuid.UUID = Depends(get_run_id_from_token)  # noqa: B008
):
    stmt = select(Charge).where(Charge.run_id == run_id, Charge.id == charge_id)
    charge = (await db.execute(stmt)).scalar_one_or_none()
    if not charge:
        raise HTTPException(status_code=404, detail="charge_not_found")
    return charge

@router.get("/charges", response_model=list[ChargeOut])
async def list_charges(
    db: Annotated[AsyncSession, Depends(get_session)],
    run_id: uuid.UUID = Depends(get_run_id_from_token),  # noqa: B008
    customer_id: str | None = None
):
    stmt = select(Charge).where(Charge.run_id == run_id)
    if customer_id:
        stmt = stmt.where(Charge.customer_id == customer_id)

    charges = (await db.execute(stmt)).scalars().all()
    return charges
