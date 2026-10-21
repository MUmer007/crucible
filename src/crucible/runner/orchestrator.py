import asyncio
import hashlib
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from crucible.db.models import Run, RunResult
from crucible.runner.scoring import calculate_score
from crucible.sandbox.faults.middleware import register_faults
from crucible.sandbox.faults.types import FaultRule
from crucible.verify.invariants import INVARIANT_REGISTRY


class Orchestrator:
    def __init__(self, db_session: AsyncSession, sandbox_url: str, concurrency_limit: int = 5):
        self.db = db_session
        self.sandbox_url = sandbox_url
        self.semaphore = asyncio.Semaphore(concurrency_limit)

    async def create_run(self, scenario_id: str, scenario_version: str, run_seed: int, task: str) -> tuple[str, str]:
        run_id = uuid.uuid4()
        token = uuid.uuid4().hex
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        
        run = Run(
            id=run_id,
            scenario_id=scenario_id,
            scenario_version=scenario_version,
            run_seed=run_seed,
            token_hash=token_hash,
            status="running",
            started_at=datetime.now(UTC)
        )
        self.db.add(run)
        await self.db.commit()
        return str(run_id), token

    async def verify_run(self, run_id: str, invariants_config: list[dict[str, Any]]) -> dict[str, Any]:
        results = {}
        all_passed = True
        for inv_cfg in invariants_config:
            name = inv_cfg["name"]
            params = inv_cfg.get("params", {})
            
            if name in INVARIANT_REGISTRY:
                inv_func = INVARIANT_REGISTRY[name]
                result = await inv_func(self.db, run_id, params)
                results[name] = {
                    "passed": result.passed,
                    "evidence": result.evidence
                }
                if not result.passed:
                    all_passed = False
            else:
                results[name] = {"passed": False, "evidence": {"error": f"Unknown invariant: {name}"}}
                all_passed = False
                
        return {"passed": all_passed, "details": results}

    async def run_single(self, scenario: dict[str, Any], agent_client) -> dict[str, Any]:
        async with self.semaphore:
            run_id_str, token = await self.create_run(
                scenario["id"],
                scenario.get("scenario_version", "v1"),
                scenario.get("seed", 42),
                scenario["task"]
            )
            run_id = uuid.UUID(run_id_str)
            
            # Register the scenario's faults with the middleware
            if "faults" in scenario:
                fault_rules = [FaultRule(**f) for f in scenario["faults"]]
                register_faults(run_id_str, fault_rules)
            
            try:
                start_time = time.time()
                
                # Check if this is a multi-step scenario
                steps = scenario.get("steps")
                if steps:
                    agent_result = await self._execute_multi_step(
                        run_id_str, steps, scenario["task"], agent_client, token
                    )
                else:
                    # Single-step execution (original behavior)
                    agent_result = await agent_client.call_agent(
                        run_id=run_id_str,
                        task=scenario["task"],
                        sandbox_url=self.sandbox_url,
                        sandbox_token=token
                    )
                
                wall_ms = int((time.time() - start_time) * 1000)
                
                inv_config = scenario.get("invariants", [])
                verification = await self.verify_run(run_id_str, inv_config)
                
                task_success = verification["passed"]
                agent_outcome = agent_result.get("outcome", "unknown")
                
                honesty = "honest"
                if agent_outcome == "success" and not task_success:
                    honesty = "dishonest"
                
                await self.db.execute(
                    Run.__table__.update().where(Run.id == run_id).values(
                        status="finished",
                        agent_outcome=agent_outcome,
                        agent_message=agent_result.get("message", ""),
                        finished_at=datetime.now(UTC)
                    )
                )
                
                result_row = RunResult(
                    run_id=run_id,
                    task_success=task_success,
                    invariants=verification["details"],
                    honesty=honesty,
                    budget_ok=True,
                    request_count=agent_result.get("evidence", {}).get("requests", 1),
                    wall_ms=wall_ms,
                    score=0
                )
                self.db.add(result_row)
                await self.db.flush()
                
                result_row.score = calculate_score(result_row) # type: ignore
                await self.db.commit()
                
                return {"run_id": run_id_str, "status": "finished", "task_success": task_success, "score": result_row.score}
                
            except Exception as e:  # noqa: BLE001 # noqa: BLE001
                await self.db.execute(
                    Run.__table__.update().where(Run.id == run_id).values(
                        status="errored",
                        agent_error=str(e),
                        finished_at=datetime.now(UTC)
                    )
                )
                await self.db.commit()
                return {"run_id": run_id_str, "status": "errored", "error": str(e)}

    async def _execute_multi_step(
        self, 
        run_id: str, 
        steps: list[dict[str, Any]], 
        overall_task: str,
        agent_client, 
        token: str
    ) -> dict[str, Any]:
        """Execute a multi-step scenario, tracking state across steps."""
        step_results = []
        total_requests = 0
        
        for i, step in enumerate(steps):
            step_id = step["id"]
            step_description = step["description"]
            
            # Build the task for this specific step
            step_task = f"Step {i+1}/{len(steps)}: {step_description}"
            
            try:
                # Execute this step
                result = await agent_client.call_agent(
                    run_id=run_id,
                    task=step_task,
                    sandbox_url=self.sandbox_url,
                    sandbox_token=token
                )
                
                step_results.append({
                    "step_id": step_id,
                    "status": "completed",
                    "outcome": result.get("outcome"),
                    "message": result.get("message"),
                    "requests": result.get("evidence", {}).get("requests", 0)
                })
                
                total_requests += result.get("evidence", {}).get("requests", 0)
                
                # If the step failed, we can either continue or abort
                if result.get("outcome") == "error":
                    break
                    
            except Exception as e:  # noqa: BLE001
                step_results.append({
                    "step_id": step_id,
                    "status": "failed",
                    "error": str(e)
                })
                break
        
        # Determine overall outcome
        all_succeeded = all(s["status"] == "completed" and s.get("outcome") == "success" for s in step_results)
        
        return {
            "outcome": "success" if all_succeeded else "failure",
            "message": f"Completed {len([s for s in step_results if s['status'] == 'completed'])}/{len(steps)} steps",
            "evidence": {
                "requests": total_requests,
                "steps": step_results
            }
        }
