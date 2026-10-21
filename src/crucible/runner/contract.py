from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentRequest(BaseModel):
    """The payload sent to the agent's /run endpoint."""
    run_id: str
    task: str
    sandbox_url: str
    sandbox_token: str
    timeout_s: int = 60

class AgentResponse(BaseModel):
    """The strict contract the agent must return."""
    outcome: Literal["success", "failure", "error"]
    message: str
    evidence: dict[str, Any] = Field(default_factory=dict)
