import asyncio
import os
from collections.abc import AsyncGenerator, Iterator
from datetime import datetime, timedelta, timezone

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.models import Base

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
def client() -> Iterator[TestClient]:
    engine = create_async_engine(
        TEST_DATABASE_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _create_tables() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_tables())

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())


def valid_payload(**overrides) -> dict:
    received = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    payload = {
        "call_number": "C-0001",
        "urgency_category": 2,
        "address": "1 Test Street",
        "received_at": received.isoformat(),
        "arrived_at": (received + timedelta(minutes=12)).isoformat(),
        "outcome": "transported",
    }
    payload.update(overrides)
    return payload
