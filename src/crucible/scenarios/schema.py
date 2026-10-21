from typing import Any

from pydantic import BaseModel, Field


class Step(BaseModel):
    """A single step in a multi-step scenario."""
    id: str
    description: str
    expected_action: str  # What the agent should do in this step
    preconditions: dict[str, Any] = Field(default_factory=dict)  # State required before this step
    expected_outcome: dict[str, Any] = Field(default_factory=dict)  # Expected state after this step

class Scenario(BaseModel):
    """A complete test scenario with optional multi-step workflow."""
    id: str
    scenario_version: str
    description: str
    tags: list[str] = Field(default_factory=list)
    seed: int = 42
    runs: int = 1
    task: str  # The overall task description
    seed_data: str  # Path to seed data file
    agent_timeout_s: int = 60
    
    # Multi-step support (optional)
    steps: list[Step] | None = None  # If None, it's a single-step scenario
    
    faults: list[dict[str, Any]] = Field(default_factory=list)
    attacks: list[dict[str, Any]] = Field(default_factory=list)
    task_success: dict[str, Any] = Field(default_factory=dict)
    invariants: list[dict[str, Any]] = Field(default_factory=list)
    budget: dict[str, Any] = Field(default_factory=dict)
