from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from crucible.db.models import Run, RunResult
from crucible.db.session import DATABASE_URL

app = FastAPI(title="Crucible Dashboard")
templates = Jinja2Templates(directory="src/crucible/dashboard/templates")

# Setup DB
engine = create_async_engine(DATABASE_URL, echo=False)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    async with async_session() as db:
        # Fetch the latest 50 runs with their results
        stmt = (
            select(Run, RunResult)
            .outerjoin(RunResult, Run.id == RunResult.run_id)
            .order_by(desc(Run.started_at))
            .limit(50)
        )
        result = await db.execute(stmt)
        runs = result.all()
        
        # Calculate summary stats
        total_runs = len(runs)
        honest_runs = sum(1 for r in runs if r.RunResult and r.RunResult.honesty == "honest")
        avg_score = sum(r.RunResult.score for r in runs if r.RunResult) / total_runs if total_runs > 0 else 0
        
        return templates.TemplateResponse(
            request, "index.html",
            context={
                "request": request,
                "runs": runs,
                "total_runs": total_runs,
                "honest_runs": honest_runs,
                "avg_score": round(avg_score, 1)
            }
        )
