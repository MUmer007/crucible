import asyncio
import platform

if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
from fastapi import FastAPI

from crucible.sandbox.faults.middleware import fault_engine_middleware
from crucible.sandbox.middleware import request_logging_middleware
from crucible.sandbox.payments.router import router as payments_router

app = FastAPI(title="Crucible Sandbox")

# Order matters: logging wraps everything, fault engine wraps the handler
app.middleware("http")(fault_engine_middleware)   # inner: wraps the handler
app.middleware("http")(request_logging_middleware)  # outer: logs every response, including faults

app.include_router(payments_router)

@app.get("/health")
def health():
    return {"status": "ok"}

