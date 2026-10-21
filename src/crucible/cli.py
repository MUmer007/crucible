import argparse
import asyncio
import platform
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from crucible.db.models import RunResult
from crucible.db.session import DATABASE_URL
from crucible.runner.agent_client import AgentClient
from crucible.runner.orchestrator import Orchestrator
from crucible.scenarios.loader import load_scenario


def main():
    parser = argparse.ArgumentParser(description="Crucible Agent Testing Sandbox")
    parser.add_argument("command", choices=["run"], help="Command to execute")
    parser.add_argument("--scenario", required=True, help="Path to scenario YAML file")
    parser.add_argument("--agent-url", required=True, help="URL of the agent to test")
    parser.add_argument("--sandbox-url", default="http://localhost:8000", help="URL of the sandbox")
    
    args = parser.parse_args()
    
    if args.command == "run":
        # Fix for Windows ProactorEventLoop issue with psycopg
        if platform.system() == "Windows":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(run_scenario(args))

async def run_scenario(args):
    scenario_path = Path(args.scenario)
    if not scenario_path.exists():
        print(f"❌ Error: Scenario file not found: {scenario_path}")
        sys.exit(1)
        
    print(f"📖 Loading scenario from {scenario_path}...")
    scenario = load_scenario(scenario_path)
    print(f"✅ Loaded scenario: {scenario.id} (version: {scenario.scenario_version})")
    
    # Setup DB session
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as db:
        orchestrator = Orchestrator(db, sandbox_url=args.sandbox_url)
        agent_client = AgentClient(agent_url=args.agent_url, timeout_s=scenario.agent_timeout_s)
        
        print(f"🚀 Running scenario against agent at {args.agent_url}...")
        result = await orchestrator.run_single(scenario.model_dump(), agent_client)
        
        print("\n" + "="*60)
        print("📊 CRUCIBLE RUN SUMMARY")
        print("="*60)
        print(f"Run ID:        {result['run_id']}")
        print(f"Status:        {result['status']}")
        print(f"Task Success:  {result.get('task_success', 'N/A')}")
        print(f"Score:         {result.get('score', 'N/A')}")
        print("="*60)
        
        if result['status'] == 'errored':
            print(f"❌ Agent Errored: {result.get('error', 'Unknown error')}")
        else:
            # Fetch the full result from DB to show invariants
            stmt = select(RunResult).where(RunResult.run_id == result['run_id'])
            db_result = await db.execute(stmt)
            run_result = db_result.scalar_one()
            
            print(f"Honesty:       {run_result.honesty}")
            print(f"Wall Time:     {run_result.wall_ms}ms")
            print(f"Requests:      {run_result.request_count}")
            
            if run_result.invariants:
                print("\n🔍 Invariant Checks:")
                for name, details in run_result.invariants.items():
                    status = "✅ PASS" if details['passed'] else "❌ FAIL"
                    print(f"  {status} {name}")
                    if not details['passed']:
                        print(f"       Evidence: {details['evidence']}")
        print("="*60 + "\n")

if __name__ == "__main__":
    main()
