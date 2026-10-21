import uuid
from pathlib import Path

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from crucible.db.models import Charge, Customer


async def seed_run(db: AsyncSession, run_id: uuid.UUID, seed_path: str | None) -> None:
    """Insert the scenario's customers and charges for this run."""
    if not seed_path:
        return
    data = yaml.safe_load(Path(seed_path).read_text(encoding="utf-8")) or {}

    for c in data.get("customers", []):
        db.add(Customer(run_id=run_id, id=c["id"], tenant_id=c.get("tenant_id"),
                        name=c.get("name"), notes=c.get("notes")))
    await db.flush()  # customers first, in case charges have an FK to them

    for ch in data.get("charges", []):
        refunded = ch.get("refunded_cents", 0)
        db.add(Charge(run_id=run_id, id=ch["id"], customer_id=ch["customer_id"],
                      amount_cents=ch["amount_cents"], currency=ch.get("currency", "usd"),
                      description=ch.get("description"),
                      refunded_cents=refunded, initial_refunded_cents=refunded))
    await db.commit()
    db.expire_all()