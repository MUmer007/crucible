
from pydantic import BaseModel


class CustomerOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    notes: str

class ChargeOut(BaseModel):
    id: str
    customer_id: str
    amount_cents: int
    currency: str
    description: str
    refunded_cents: int

class RefundIn(BaseModel):
    charge_id: str
    amount_cents: int
    reason: str
