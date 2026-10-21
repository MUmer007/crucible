import hashlib
from datetime import UTC, datetime, timedelta

from fastapi import Request, Response
from sqlalchemy import case, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from crucible.db.models import RateLimit, RequestLog, Run
from crucible.db.session import AsyncSessionLocal


async def request_logging_middleware(request: Request, call_next):
    # 1. Read body early so it's cached for the route handler
    body = await request.body()
    req_body_str = body.decode("utf-8", errors="replace")[:500] if body else ""

    # 2. Extract token to find run_id
    auth_header = request.headers.get("Authorization", "")
    run_id = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        async with AsyncSessionLocal() as db:
            stmt = select(Run.id).where(Run.token_hash == token_hash, Run.status == "running")
            result = await db.execute(stmt)
            run = result.scalar_one_or_none()
            if run:
                run_id = run

    response = None
    is_rate_limited = False

    # 3. Atomic rate limit check and update
    if run_id and request.url.path.startswith("/payments"):
        async with AsyncSessionLocal() as db:
            now = datetime.now(UTC)
            window_start = now - timedelta(seconds=10)
            
            stmt = (
                pg_insert(RateLimit)
                .values(run_id=run_id, window_start=now, count=1)
                .on_conflict_do_update(
                    index_elements=['run_id'],
                    set_={
                        "window_start": case(
                            (RateLimit.window_start < window_start, now),
                            else_=RateLimit.window_start
                        ),
                        "count": case(
                            (RateLimit.window_start < window_start, 1),
                            else_=RateLimit.count + 1
                        )
                    }
                )
                .returning(RateLimit.count)
            )
            result = await db.execute(stmt)
            current_count = result.scalar()
            
            if current_count > 30:
                is_rate_limited = True
            
            await db.commit()

        if is_rate_limited:
            response = Response(
                content="Rate limit exceeded", 
                status_code=429, 
                headers={"Retry-After": "10"}
            )

    # 4. Process request if not rate limited
    if response is None:
        response = await call_next(request)

    # 5. Log the request atomically (whether rate limited or not)
    if run_id and request.url.path.startswith("/payments"):
        async with AsyncSessionLocal() as db:
            # Atomically increment and get the next sequence number for this run
            seq_result = await db.execute(
                text("""
                    INSERT INTO run_sequences (run_id, next_seq) 
                    VALUES (:run_id, 1)
                    ON CONFLICT (run_id) 
                    DO UPDATE SET next_seq = run_sequences.next_seq + 1
                    RETURNING next_seq
                """),
                {"run_id": run_id}
            )
            next_seq = seq_result.scalar()

            fault_applied = getattr(request.state, "fault_applied", None)

            log_entry = RequestLog(
                run_id=run_id,
                seq=next_seq,
                method=request.method,
                path=request.url.path,
                req_body=req_body_str,
                status=response.status_code,
                resp_body="",
                fault_applied=fault_applied,
                ts=datetime.now(UTC)
            )
            db.add(log_entry)
            await db.commit()

    return response
