from typing import Any

import httpx


class AgentClient:
    def __init__(self, agent_url: str, timeout_s: int = 60):
        self.agent_url = agent_url.rstrip("/")
        self.timeout_s = timeout_s

    async def call_agent(
        self, 
        run_id: str, 
        task: str, 
        sandbox_url: str, 
        sandbox_token: str
    ) -> dict[str, Any]:
        """Calls the agent's /run endpoint and returns the result."""
        payload = {
            "run_id": run_id,
            "task": task,
            "sandbox_url": sandbox_url,
            "sandbox_token": sandbox_token,
            "timeout_s": self.timeout_s
        }
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            response = await client.post(f"{self.agent_url}/run", json=payload)
            response.raise_for_status()
            return response.json()
