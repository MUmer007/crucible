# src/crucible/db/session.py
import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql+psycopg://crucible:crucible_dev_only@127.0.0.1:5433/crucible"
)

# Increase pool_size and max_overflow to handle concurrent test requests
engine = create_async_engine(
    DATABASE_URL, 
    echo=False,
    pool_size=30,
    max_overflow=10
)

AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session