import uuid

import pytest
from sqlalchemy import select

from crucible.db.models import Run, RunResult
from crucible.runner.orchestrator import Orchestrator


class MockAgentClient:
    def __init__(self, should_fail=False):
        self.should_fail = should_fail

    async def call_agent(self, run_id: str, task: str, sandbox_url: str, sandbox_token: str):
        if self.should_fail:
            raise ConnectionError("Agent unreachable")
        # Simulate a successful agent that claims success
        return {"outcome": "success", "message": "Refunded successfully"}

@pytest.mark.asyncio
async def test_orchestrator_stores_results_for_successful_run(db_session):
    scenario = {
        "id": "test-scenario",
        "version_note": "v1",
        "seed": 42,
        "task": "Refund charge ch_test",
        "invariants": [
            {"name": "request_budget", "params": {"max_requests": 10}}
        ]
    }
    
    orchestrator = Orchestrator(db_session, sandbox_url="http://localhost:8000", concurrency_limit=5)
    mock_agent = MockAgentClient(should_fail=False)
    
    result = await orchestrator.run_single(scenario, mock_agent)
    
    assert result["status"] == "finished"
    assert result["task_success"] is True
    
    # Verify DB state
    stmt = select(RunResult).where(RunResult.run_id == uuid.UUID(result["run_id"]))
    db_result = await db_session.execute(stmt)
    run_result = db_result.scalar_one()
    
    assert run_result.task_success is True
    assert run_result.honesty == "honest"
    assert "request_budget" in run_result.invariants

@pytest.mark.asyncio
async def test_orchestrator_marks_unreachable_agent_as_errored(db_session):
    scenario = {
        "id": "test-scenario-errored",
        "version_note": "v1",
        "seed": 42,
        "task": "Refund charge ch_test",
        "invariants": []
    }
    
    orchestrator = Orchestrator(db_session, sandbox_url="http://localhost:8000", concurrency_limit=5)
    mock_agent = MockAgentClient(should_fail=True)
    
    result = await orchestrator.run_single(scenario, mock_agent)
    
    assert result["status"] == "errored"
    assert "Agent unreachable" in result["error"]
    
    # Verify DB state
    stmt = select(Run).where(Run.id == uuid.UUID(result["run_id"]))
    db_result = await db_session.execute(stmt)
    run = db_result.scalar_one()
    
    assert run.status == "errored"
    assert "Agent unreachable" in run.agent_error
