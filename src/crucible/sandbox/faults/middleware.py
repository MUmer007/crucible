import asyncio
import hashlib
import uuid

from fastapi import Request, Response
from sqlalchemy import select, text

from crucible.db.models import Run
from crucible.db.session import AsyncSessionLocal
from crucible.sandbox.faults.engine import matches_path, should_trigger_fault
from crucible.sandbox.faults.types import FaultRule

ACTIVE_FAULT_RULES = {}

def register_faults(run_id: str, rules: list[FaultRule]):
    ACTIVE_FAULT_RULES[run_id] = rules

async def fault_engine_middleware(request: Request, call_next):
    auth_header = request.headers.get("Authorization", "")
    run_id_str = None
    run_seed = 42
    
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        async with AsyncSessionLocal() as db:
            stmt = select(Run.id, Run.run_seed).where(Run.token_hash == token_hash, Run.status == "running")
            result = await db.execute(stmt)
            row = result.first()
            if row:
                run_id_str = str(row.id)
                run_seed = row.run_seed

    matched_rules = []
    if run_id_str and run_id_str in ACTIVE_FAULT_RULES:
        for rule in ACTIVE_FAULT_RULES[run_id_str]:
            if request.method == rule.match.method and matches_path(rule.match.path, request.url.path):
                matched_rules.append(rule)

    fault_applied = None
    response = None

    for rule in matched_rules:
        async with AsyncSessionLocal() as db:
            run_id_uuid = uuid.UUID(run_id_str)
            
            result = await db.execute(
                text("""
                    INSERT INTO fault_counters (run_id, rule_id, n) 
                    VALUES (:run_id, :rule_id, 1)
                    ON CONFLICT (run_id, rule_id) 
                    DO UPDATE SET n = fault_counters.n + 1
                    RETURNING n
                """),
                {"run_id": run_id_uuid, "rule_id": rule.id}
            )
            call_n = result.scalar()
            await db.commit()

        if should_trigger_fault(rule, run_seed, call_n):
            fault_applied = rule.id
            
            if rule.type in ["timeout", "http_429", "http_500", "malformed_json", "stale_read"]:
                if rule.type == "timeout":
                    delay = rule.params.get("delay_ms", 200) / 1000.0
                    await asyncio.sleep(delay)
                    response = Response(status_code=504, content="Gateway Timeout")
                elif rule.type == "http_429":
                    retry_after = rule.params.get("retry_after_s", 10)
                    response = Response(
                        status_code=429, 
                        content="Rate limit exceeded",
                        headers={"Retry-After": str(retry_after)}
                    )
                elif rule.type == "http_500":
                    response = Response(status_code=500, content="Internal Server Error")
                elif rule.type == "malformed_json":
                    response = Response(
                        status_code=200, 
                        content="{ this is not valid json }",
                        media_type="application/json"
                    )
                elif rule.type == "stale_read":
                    stale_body = rule.params.get("stale_body", '{"status": "stale"}')
                    response = Response(
                        status_code=200,
                        content=stale_body,
                        media_type="application/json"
                    )
                break

    if response is None:
        response = await call_next(request)
        
        for rule in matched_rules:
            if fault_applied == rule.id and rule.type == "commit_then_timeout":
                delay = rule.params.get("delay_ms", 200) / 1000.0
                await asyncio.sleep(delay)
                response = Response(status_code=504, content="Gateway Timeout")
                break

    if fault_applied:
        request.state.fault_applied = fault_applied

    return response
