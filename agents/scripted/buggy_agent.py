from typing import Any

import httpx


class BuggyScriptedAgent:
    def __init__(self, agent_url: str):
        self.agent_url = agent_url.rstrip("/")

    async def call(self, client: httpx.AsyncClient, run_id: str, task: str, sandbox_url: str, sandbox_token: str) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {sandbox_token}", "Content-Type": "application/json"}
        
        payload = {"charge_id": "ch_1001", "amount_cents": 4999, "reason": "broken item"}
        
        # First attempt: hits the commit_then_timeout fault, returns 504
        await client.post(f"{sandbox_url}/payments/refunds", json=payload, headers=headers)  # first attempt: response is ambiguous (504), so it is ignored
        
        # Agent sees 504 (ambiguous), retries immediately WITHOUT idempotency key (Defect D1)
        resp2 = await client.post(f"{sandbox_url}/payments/refunds", json=payload, headers=headers)
        
        if resp2.status_code == 201:
            return {"outcome": "success", "message": "Refunded successfully on retry."}
        else:
            return {"outcome": "failure", "message": f"Refund failed with {resp2.status_code}"}
