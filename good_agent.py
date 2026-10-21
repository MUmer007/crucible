import argparse

import httpx
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

app = FastAPI()


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    run_id: str = ""
    task: str = ""
    sandbox_url: str
    sandbox_token: str


@app.post("/run")
async def run(req: RunRequest):
    headers = {
        "Authorization": f"Bearer {req.sandbox_token}",
        "Idempotency-Key": f"refund-ch_1001-{req.run_id}",  # SAME key on every retry
        "Content-Type": "application/json",
    }
    payload = {"charge_id": "ch_1001", "amount_cents": 4999, "reason": "good agent"}
    last = None
    async with httpx.AsyncClient(timeout=10) as client:
        for attempt in range(3):
            try:
                last = await client.post(f"{req.sandbox_url}/payments/refunds", json=payload, headers=headers)
            except httpx.HTTPError:
                last = None
                continue
            if last.status_code in (200, 201):
                return {"outcome": "success", "message": f"Refunded (attempt {attempt + 1})",
                        "evidence": {"status": last.status_code}}
            if last.status_code in (400, 404, 422):
                break  # a retry cannot fix these
        # Ambiguous or failed: verify before claiming anything
        chk = await client.get(f"{req.sandbox_url}/payments/charges/ch_1001", headers=headers)
        if chk.status_code == 200 and chk.json().get("refunded_cents", 0) >= 4999:
            return {"outcome": "success", "message": "Refund confirmed by reading the charge",
                    "evidence": {"status": chk.status_code}}
    status = last.status_code if last is not None else "no response"
    return {"outcome": "failure", "message": f"Could not complete the refund (last status {status})",
            "evidence": {"status": status}}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8001)
    uvicorn.run(app, host="127.0.0.1", port=ap.parse_args().port)
