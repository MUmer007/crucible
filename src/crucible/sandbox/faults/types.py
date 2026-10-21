from typing import Any, Literal

from pydantic import BaseModel, Field


class MatchCondition(BaseModel):
    method: str
    path: str

class FaultRule(BaseModel):
    id: str
    match: MatchCondition
    on_call: list[int] | None = None
    probability: float | None = None
    type: Literal["timeout", "commit_then_timeout", "http_429", "http_500", "malformed_json", "stale_read"]
    params: dict[str, Any] = Field(default_factory=dict)
