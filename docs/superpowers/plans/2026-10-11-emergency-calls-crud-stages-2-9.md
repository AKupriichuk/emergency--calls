# Emergency Calls CRUD — Stages 2-9 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, containerize, load-test and report on the `/emergency-calls` CRUD service (Lab Work #1, variant 13), covering Stages 2 through 9 of the assignment. Stage 1 (design) is already done and committed in `README.md`.

**Architecture:** FastAPI (async) service backed by PostgreSQL via async SQLAlchemy 2.0 and Alembic migrations; multi-stage Docker build on a `python:3.12-alpine` final stage; `docker-compose.yml` with `db` + one-off `migrate` + scalable `web` + `nginx` as the sole published entrypoint; a standalone open/closed-loop Python load generator; a standalone analysis script for percentiles and the three required calculations (speedup/Karp-Flatt, Little's law, closed-loop comparison).

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 (async, `asyncpg` driver), Alembic, pydantic-settings, pytest + `aiosqlite` for tests, `requests` for the load generator, PostgreSQL 16, Nginx, Docker Compose v2 (`docker compose`, confirmed v5.1.4 on this machine — not the legacy `docker-compose` v1 binary, because `deploy.resources.limits` is only honored outside Swarm mode by the v2 plugin).

## Global Constraints

- Final-stage base image: `python:3.12-alpine` (fixed by variant 13).
- `web` container resource limits: `0.5 CPU, 384 MB` (fixed by variant 13).
- Additional deployment requirement (variant 13): **all configuration only through environment variables** — no hardcoded config, no config files baked into the image.
- Client never supplies `id`; it is always server-generated.
- `GET /emergency-calls` returns `{items, total, limit, offset}`, never a bare array.
- A repeated `DELETE` on the same id returns `404`, not `204`.
- `RequestValidationError` (and any malformed path param) → `400`, never `422`.
- `GET /healthz` must execute `SELECT 1` against the real database, not just return `200` unconditionally.
- No raw ORM/DB exception may reach the client; unhandled errors → generic `500`.
- Load levels: **10, 100, 500 RPS**; each run is **30 s measured + 10 s warm-up** (warm-up excluded from results); each level repeated **3×**, report the **median**.
- Full open-loop series run twice: **1 web instance** and **2 web instances** (via `docker compose up --scale web=N`, never by duplicating the service block).
- Little's Law check: at **100 RPS, 1 instance**.
- Report language: **English** (`README.md`, in the repo, filled in stage by stage — never rewritten after the fact, only appended to).
- Commit after every stage.

---

### Task 1: Project scaffolding, settings, DB wiring, ORM model, Alembic migration

**Files:**
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `requirements-loadgen.txt`
- Create: `app/__init__.py`
- Create: `app/config.py`
- Create: `app/db.py`
- Create: `app/models.py`
- Create: `alembic.ini`
- Create: `migrations/env.py`
- Create: `migrations/script.py.mako`
- Create: `migrations/versions/0001_create_emergency_calls.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `app.config.get_settings() -> Settings` with fields `database_url: str`, `pagination_default_limit: int = 50`, `pagination_max_limit: int = 200`.
- Produces: `app.db.get_db() -> AsyncGenerator[AsyncSession, None]` (FastAPI dependency), `app.db.engine`, `app.db.SessionLocal`.
- Produces: `app.models.Base` (declarative base), `app.models.EmergencyCall` ORM class with columns `id, call_number, urgency_category, address, received_at, arrived_at, outcome`.

- [ ] **Step 1: Write dependency files**

`requirements.txt`:
```
fastapi==0.115.0
uvicorn[standard]==0.32.0
sqlalchemy==2.0.36
asyncpg==0.30.0
alembic==1.13.3
pydantic-settings==2.6.1
```

`requirements-dev.txt`:
```
-r requirements.txt
pytest==8.3.3
httpx==0.27.2
aiosqlite==0.20.0
```

`requirements-loadgen.txt`:
```
requests==2.32.3
```

- [ ] **Step 2: Create `app/__init__.py`** (empty file, makes `app` a package)

- [ ] **Step 3: Write `app/config.py`**

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False)

    database_url: str
    pagination_default_limit: int = 50
    pagination_max_limit: int = 200


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Write `app/db.py`**

```python
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
```

- [ ] **Step 5: Write the failing model test**

`tests/test_models.py`:
```python
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from app.models import Base, EmergencyCall  # noqa: E402


def test_emergency_calls_table_has_expected_columns():
    table = Base.metadata.tables["emergency_calls"]
    column_names = {c.name for c in table.columns}
    assert column_names == {
        "id",
        "call_number",
        "urgency_category",
        "address",
        "received_at",
        "arrived_at",
        "outcome",
    }
    assert table.columns["id"].primary_key
    assert not table.columns["call_number"].nullable


def test_urgency_category_is_indexed():
    table = Base.metadata.tables["emergency_calls"]
    indexed_columns = {col.name for idx in table.indexes for col in idx.columns}
    assert "urgency_category" in indexed_columns
```

- [ ] **Step 6: Run the test to confirm it fails**

Run: `python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt && .venv/bin/pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models'` (or `ImportError`).

- [ ] **Step 7: Write `app/models.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, SmallInteger, String, Text, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class EmergencyCall(Base):
    __tablename__ = "emergency_calls"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    call_number: Mapped[str] = mapped_column(String(50), nullable=False)
    urgency_category: Mapped[int] = mapped_column(SmallInteger, nullable=False, index=True)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    arrived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outcome: Mapped[str] = mapped_column(String(255), nullable=False)
```

- [ ] **Step 8: Run the test to confirm it passes**

Run: `.venv/bin/pytest tests/test_models.py -v`
Expected: PASS (2 tests).

- [ ] **Step 9: Write Alembic scaffolding**

`alembic.ini`:
```ini
[alembic]
script_location = migrations

[loggers]
keys = root,sqlalchemy,alembic

[logger_root]
level = WARNING
handlers = console
qualname =

[logger_sqlalchemy]
level = WARNING
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handlers]
keys = console

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatters]
keys = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
```

`migrations/script.py.mako`:
```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

`migrations/env.py`:
```python
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    return get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = create_async_engine(get_url())
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```

`migrations/versions/0001_create_emergency_calls.py`:
```python
"""create emergency_calls table

Revision ID: 0001
Revises:
Create Date: 2026-10-11

"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "emergency_calls",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("call_number", sa.String(length=50), nullable=False),
        sa.Column("urgency_category", sa.SmallInteger(), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("arrived_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(length=255), nullable=False),
    )
    op.create_index(
        "ix_emergency_calls_urgency_category",
        "emergency_calls",
        ["urgency_category"],
    )


def downgrade() -> None:
    op.drop_index("ix_emergency_calls_urgency_category", table_name="emergency_calls")
    op.drop_table("emergency_calls")
```

- [ ] **Step 10: Commit**

```bash
git add requirements.txt requirements-dev.txt requirements-loadgen.txt app/ alembic.ini migrations/ tests/test_models.py
git commit -m "Stage 2: project scaffolding, settings, ORM model, Alembic migration"
```

---

### Task 2: Core API — schemas, CRUD, routes, error handling, pytest suite

**Files:**
- Create: `app/schemas.py`
- Create: `app/errors.py`
- Create: `app/crud.py`
- Create: `app/routers/__init__.py`
- Create: `app/routers/emergency_calls.py`
- Create: `app/main.py`
- Create: `tests/conftest.py`
- Create: `tests/test_validation.py`
- Create: `tests/test_crud_flow.py`

**Interfaces:**
- Consumes: `app.db.get_db`, `app.models.EmergencyCall`, `app.config.get_settings` from Task 1.
- Produces: `app.schemas.EmergencyCallCreate/Update/Out/List`, `app.crud.create_call/list_calls/get_call/update_call/delete_call`, `app.errors.ApiError(status_code, message, field=None)`, `app.main.app` (the FastAPI instance used by tests, uvicorn and later Docker).

- [ ] **Step 1: Write `app/schemas.py`**

```python
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class EmergencyCallBase(BaseModel):
    call_number: str = Field(min_length=1, max_length=50)
    urgency_category: int = Field(ge=1, le=4)
    address: str = Field(min_length=1)
    received_at: datetime
    arrived_at: datetime
    outcome: str = Field(min_length=1, max_length=255)

    @field_validator("arrived_at")
    @classmethod
    def arrived_after_received(cls, value: datetime, info):
        received_at = info.data.get("received_at")
        if received_at is not None and value <= received_at:
            raise ValueError("arrived_at must be later than received_at")
        return value


class EmergencyCallCreate(EmergencyCallBase):
    pass


class EmergencyCallUpdate(EmergencyCallBase):
    pass


class EmergencyCallOut(EmergencyCallBase):
    id: UUID

    model_config = {"from_attributes": True}


class EmergencyCallList(BaseModel):
    items: list[EmergencyCallOut]
    total: int
    limit: int
    offset: int
```

- [ ] **Step 2: Write `app/errors.py`**

```python
class ApiError(Exception):
    def __init__(self, status_code: int, message: str, field: str | None = None):
        self.status_code = status_code
        self.message = message
        self.field = field
        super().__init__(message)
```

- [ ] **Step 3: Write `app/crud.py`**

```python
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EmergencyCall
from app.schemas import EmergencyCallCreate, EmergencyCallUpdate


async def create_call(db: AsyncSession, data: EmergencyCallCreate) -> EmergencyCall:
    call = EmergencyCall(**data.model_dump())
    db.add(call)
    await db.commit()
    await db.refresh(call)
    return call


async def list_calls(
    db: AsyncSession, limit: int, offset: int, urgency_category: int | None
) -> tuple[list[EmergencyCall], int]:
    stmt = select(EmergencyCall).order_by(EmergencyCall.id)
    count_stmt = select(func.count()).select_from(EmergencyCall)
    if urgency_category is not None:
        stmt = stmt.where(EmergencyCall.urgency_category == urgency_category)
        count_stmt = count_stmt.where(EmergencyCall.urgency_category == urgency_category)

    total = (await db.execute(count_stmt)).scalar_one()
    rows = (await db.execute(stmt.limit(limit).offset(offset))).scalars().all()
    return list(rows), total


async def get_call(db: AsyncSession, call_id: uuid.UUID) -> EmergencyCall | None:
    return await db.get(EmergencyCall, call_id)


async def update_call(
    db: AsyncSession, call: EmergencyCall, data: EmergencyCallUpdate
) -> EmergencyCall:
    for field, value in data.model_dump().items():
        setattr(call, field, value)
    await db.commit()
    await db.refresh(call)
    return call


async def delete_call(db: AsyncSession, call: EmergencyCall) -> None:
    await db.delete(call)
    await db.commit()
```

- [ ] **Step 4: Write `app/routers/__init__.py`** (empty file)

- [ ] **Step 5: Write `app/routers/emergency_calls.py`**

```python
import uuid

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud
from app.config import get_settings
from app.db import get_db
from app.errors import ApiError
from app.schemas import (
    EmergencyCallCreate,
    EmergencyCallList,
    EmergencyCallOut,
    EmergencyCallUpdate,
)

router = APIRouter()


@router.post("/emergency-calls", response_model=EmergencyCallOut, status_code=201)
async def create_emergency_call(
    payload: EmergencyCallCreate, db: AsyncSession = Depends(get_db)
) -> EmergencyCallOut:
    call = await crud.create_call(db, payload)
    return EmergencyCallOut.model_validate(call)


@router.get("/emergency-calls", response_model=EmergencyCallList)
async def list_emergency_calls(
    limit: int | None = Query(default=None, ge=0),
    offset: int = Query(default=0, ge=0),
    urgency_category: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> EmergencyCallList:
    settings = get_settings()
    effective_limit = settings.pagination_default_limit if limit is None else limit
    if effective_limit > settings.pagination_max_limit:
        raise ApiError(
            400, f"limit must not exceed {settings.pagination_max_limit}", field="limit"
        )
    if urgency_category is not None and not (1 <= urgency_category <= 4):
        raise ApiError(400, "urgency_category must be between 1 and 4", field="urgency_category")

    calls, total = await crud.list_calls(db, effective_limit, offset, urgency_category)
    return EmergencyCallList(
        items=[EmergencyCallOut.model_validate(c) for c in calls],
        total=total,
        limit=effective_limit,
        offset=offset,
    )


@router.get("/emergency-calls/{call_id}", response_model=EmergencyCallOut)
async def get_emergency_call(
    call_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> EmergencyCallOut:
    call = await crud.get_call(db, call_id)
    if call is None:
        raise ApiError(404, "emergency call not found")
    return EmergencyCallOut.model_validate(call)


@router.put("/emergency-calls/{call_id}", response_model=EmergencyCallOut)
async def update_emergency_call(
    call_id: uuid.UUID, payload: EmergencyCallUpdate, db: AsyncSession = Depends(get_db)
) -> EmergencyCallOut:
    call = await crud.get_call(db, call_id)
    if call is None:
        raise ApiError(404, "emergency call not found")
    call = await crud.update_call(db, call, payload)
    return EmergencyCallOut.model_validate(call)


@router.delete("/emergency-calls/{call_id}", status_code=204)
async def delete_emergency_call(
    call_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> Response:
    call = await crud.get_call(db, call_id)
    if call is None:
        raise ApiError(404, "emergency call not found")
    await crud.delete_call(db, call)
    return Response(status_code=204)


@router.get("/healthz")
async def healthz(db: AsyncSession = Depends(get_db)) -> Response:
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        return Response(
            content='{"status": "unavailable"}', status_code=503, media_type="application/json"
        )
    return Response(content='{"status": "ok"}', status_code=200, media_type="application/json")
```

- [ ] **Step 6: Write `app/main.py`**

```python
import socket

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.errors import ApiError
from app.routers.emergency_calls import router

app = FastAPI(title="Emergency Calls Service")
app.include_router(router)


class InstanceHeaderMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Instance-Id"] = socket.gethostname()
        return response


app.add_middleware(InstanceHeaderMiddleware)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    first_error = exc.errors()[0]
    field = first_error["loc"][-1] if first_error["loc"] else None
    return JSONResponse(status_code=400, content={"error": first_error["msg"], "field": str(field)})


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": exc.message, "field": exc.field})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"error": "internal server error"})
```

- [ ] **Step 7: Write `tests/conftest.py`**

```python
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
```

- [ ] **Step 8: Write the failing validation tests**

`tests/test_validation.py`:
```python
from tests.conftest import valid_payload


def test_create_rejects_urgency_category_out_of_range(client):
    response = client.post("/emergency-calls", json=valid_payload(urgency_category=5))
    assert response.status_code == 400
    assert response.json()["field"] == "urgency_category"


def test_create_rejects_arrival_before_receipt(client):
    payload = valid_payload()
    payload["received_at"], payload["arrived_at"] = payload["arrived_at"], payload["received_at"]
    response = client.post("/emergency-calls", json=payload)
    assert response.status_code == 400


def test_create_ignores_client_supplied_id(client):
    payload = valid_payload()
    payload["id"] = "11111111-1111-1111-1111-111111111111"
    response = client.post("/emergency-calls", json=payload)
    assert response.status_code == 201
    assert response.json()["id"] != payload["id"]


def test_get_malformed_id_returns_400_not_422(client):
    response = client.get("/emergency-calls/not-a-uuid")
    assert response.status_code == 400


def test_list_rejects_limit_above_max(client):
    response = client.get("/emergency-calls", params={"limit": 10_000})
    assert response.status_code == 400
    assert response.json()["field"] == "limit"
```

`tests/test_crud_flow.py`:
```python
from tests.conftest import valid_payload


def test_full_crud_cycle(client):
    created = client.post("/emergency-calls", json=valid_payload()).json()
    call_id = created["id"]

    assert client.get(f"/emergency-calls/{call_id}").status_code == 200

    listed = client.get("/emergency-calls").json()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == call_id
    assert listed["limit"] == 50
    assert listed["offset"] == 0

    updated = client.put(
        f"/emergency-calls/{call_id}", json=valid_payload(outcome="deceased")
    )
    assert updated.status_code == 200
    assert updated.json()["outcome"] == "deceased"

    first_delete = client.delete(f"/emergency-calls/{call_id}")
    assert first_delete.status_code == 204

    second_delete = client.delete(f"/emergency-calls/{call_id}")
    assert second_delete.status_code == 404


def test_list_filters_by_urgency_category(client):
    client.post("/emergency-calls", json=valid_payload(urgency_category=1))
    client.post("/emergency-calls", json=valid_payload(urgency_category=3))

    response = client.get("/emergency-calls", params={"urgency_category": 3})
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["urgency_category"] == 3


def test_healthz_returns_ok(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_missing_returns_404(client):
    response = client.get("/emergency-calls/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_put_missing_returns_404(client):
    response = client.put(
        "/emergency-calls/00000000-0000-0000-0000-000000000000", json=valid_payload()
    )
    assert response.status_code == 404
```

- [ ] **Step 9: Run tests to confirm they fail**

Run: `.venv/bin/pytest tests/ -v`
Expected: FAIL/ERROR — `app.main` does not fully exist yet in a runnable state until the files above exist together (if Steps 1-6 were already written before this point, skip to Step 10; this plan lists schema/route/app code before the tests only for reading order — write all of Steps 1-7 first, then run this as the true red check against Steps 8's tests specifically, which should fail only if an endpoint/validation path is missing or wrong).

- [ ] **Step 10: Run tests to confirm they pass**

Run: `.venv/bin/pytest tests/ -v`
Expected: PASS — all tests in `tests/test_models.py`, `tests/test_validation.py`, `tests/test_crud_flow.py` green.

- [ ] **Step 11: Commit**

```bash
git add app/ tests/
git commit -m "Stage 2: implement CRUD endpoints, validation and error handling"
```

---

### Task 3: Integration sanity check against a real PostgreSQL container

**Files:** none created; this is a manual verification task using a throwaway container.

**Prerequisite:** Docker Desktop must be running (`docker info` succeeds). If it is not, start it and wait for it before continuing — do not skip this task, since `aiosqlite` in Task 2 only proves the Pydantic/FastAPI layer, not that `asyncpg` + Alembic actually work against real Postgres.

- [ ] **Step 1: Start a throwaway Postgres container**

Run:
```bash
docker run -d --name ec-smoke-pg -e POSTGRES_USER=app -e POSTGRES_PASSWORD=app -e POSTGRES_DB=emergency_calls -p 55432:5432 postgres:16-alpine
```
Wait a few seconds, then: `docker exec ec-smoke-pg pg_isready -U app -d emergency_calls` → expect `accepting connections`.

- [ ] **Step 2: Run the Alembic migration against it**

Run:
```bash
DATABASE_URL=postgresql+asyncpg://app:app@localhost:55432/emergency_calls .venv/bin/alembic upgrade head
```
Expected: no errors; `docker exec ec-smoke-pg psql -U app -d emergency_calls -c '\d emergency_calls'` shows the table with the `ix_emergency_calls_urgency_category` index.

- [ ] **Step 3: Run the service against it and smoke-test manually**

Run:
```bash
DATABASE_URL=postgresql+asyncpg://app:app@localhost:55432/emergency_calls .venv/bin/uvicorn app.main:app --port 8000 &
sleep 1
curl -s -w '\n%{http_code}\n' http://localhost:8000/healthz
curl -s -w '\n%{http_code}\n' -X POST http://localhost:8000/emergency-calls -H 'Content-Type: application/json' -d '{"call_number":"C-1","urgency_category":2,"address":"1 Main St","received_at":"2026-01-01T12:00:00Z","arrived_at":"2026-01-01T12:10:00Z","outcome":"transported"}'
kill %1
```
Expected: `healthz` → `200 {"status": "ok"}`; `POST` → `201` with a server-generated `id`.

- [ ] **Step 4: Tear down the throwaway container**

Run: `docker rm -f ec-smoke-pg`

- [ ] **Step 5: Commit** (only if Step 1-3 surfaced a fix to app code; otherwise nothing to commit — note the successful check in the running notes for the README Stage 2 write-up done in Task 11)

---

### Task 4: Multi-stage Dockerfile and image size measurement

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`

**Interfaces:**
- Consumes: `requirements.txt`, `app/`, `migrations/`, `alembic.ini` from Tasks 1-2.
- Produces: image tag `emergency-calls-service:latest`, used by `docker-compose.yml` in Task 5.

- [ ] **Step 1: Write `.dockerignore`**

```
__pycache__/
*.pyc
.git
.gitignore
.env
.venv/
tests/
loadgen/
analysis/
results/
docs/
README.md
```

- [ ] **Step 2: Write `Dockerfile`**

```dockerfile
FROM python:3.12-alpine AS builder
WORKDIR /build
RUN apk add --no-cache gcc musl-dev libffi-dev
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-alpine AS final
WORKDIR /app
COPY --from=builder /install /usr/local
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini .
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Note the `pip install --prefix=/install` + `COPY --from=builder /install /usr/local` pattern: the `final` stage is a fresh `FROM python:3.12-alpine` that never runs `apk add gcc`, so no compiler ever exists in it — only the already-built site-packages are copied in.

- [ ] **Step 3: Build and measure the image**

Run: `docker build -t emergency-calls-service:latest .`
Then: `docker images emergency-calls-service:latest --format '{{.Size}}'`
Record the printed size for the README Stage 3 section (Task 11).

- [ ] **Step 4: Verify no build tools leaked into the final image**

Run: `docker run --rm emergency-calls-service:latest sh -c "which gcc cc python3-dev 2>&1; echo exit=$?"`
Expected: `gcc`/`cc` not found (non-zero exit), confirming the final stage is compiler-free.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile .dockerignore
git commit -m "Stage 3: multi-stage Dockerfile, no build tools in final image"
```

---

### Task 5: docker-compose stand (db + migrate + web + nginx), startup time measurement, persistence check

**Files:**
- Create: `docker-compose.yml`
- Create: `nginx/nginx.conf`
- Create: `.env.example`
- Modify: `.gitignore` (ensure `.env` is listed — check first; most Python `.gitignore` templates already include it)

**Interfaces:**
- Consumes: image `emergency-calls-service:latest` (built inline via `build: .` so `docker compose up` rebuilds it if needed) from Task 4.
- Produces: a running stand reachable at `http://localhost:8080`, scalable via `--scale web=N`.

- [ ] **Step 1: Check `.gitignore` covers `.env`**

Run: `grep -n '^\.env$' .gitignore || echo 'MISSING'`
If missing, add a line `.env` to `.gitignore`.

- [ ] **Step 2: Write `.env.example`**

```
POSTGRES_USER=app
POSTGRES_PASSWORD=change_me
POSTGRES_DB=emergency_calls
PAGINATION_DEFAULT_LIMIT=50
PAGINATION_MAX_LIMIT=200
```

Then, locally only (never committed): `cp .env.example .env` and set a real `POSTGRES_PASSWORD`.

- [ ] **Step 3: Write `nginx/nginx.conf`**

```nginx
server {
    listen 80;

    resolver 127.0.0.11 valid=10s;

    location / {
        set $upstream web:8000;
        proxy_pass http://$upstream;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

`resolver 127.0.0.11` is Docker's embedded DNS server; `set $upstream ...; proxy_pass http://$upstream;` forces Nginx to re-resolve the `web` service name on every request (subject to the resolver's `valid=10s` TTL) instead of caching the IP once at config load — this is what lets a second `web` replica added via `--scale` actually receive traffic without restarting Nginx.

- [ ] **Step 4: Write `docker-compose.yml`**

```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - pg_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 5s
      timeout: 5s
      retries: 10
    expose:
      - "5432"

  migrate:
    build: .
    image: emergency-calls-service:latest
    command: ["alembic", "upgrade", "head"]
    environment:
      DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}
    depends_on:
      db:
        condition: service_healthy

  web:
    build: .
    image: emergency-calls-service:latest
    environment:
      DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}
      PAGINATION_DEFAULT_LIMIT: ${PAGINATION_DEFAULT_LIMIT}
      PAGINATION_MAX_LIMIT: ${PAGINATION_MAX_LIMIT}
    expose:
      - "8000"
    depends_on:
      db:
        condition: service_healthy
      migrate:
        condition: service_completed_successfully
    deploy:
      resources:
        limits:
          cpus: "0.5"
          memory: 384M

  nginx:
    image: nginx:1.27-alpine
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro
    ports:
      - "8080:80"
    depends_on:
      - web

volumes:
  pg_data:
```

Only `nginx` publishes a host port (`8080:80`); `db` and `web` use `expose` (container-network-only), matching the "no web-instance ports published" requirement. `DATABASE_URL` is built entirely from `POSTGRES_*` environment variables plus the fixed in-network hostname `db:5432` (a network-topology detail, not a secret or a tunable) — this is the "configuration only through environment variables" requirement in practice; it is written up explicitly in README Stage 8 (Task 10).

- [ ] **Step 5: Bring the stand up with 1 web instance and measure startup time**

Run (repeat 3 times, each time `docker compose down -v` first for a clean slate, and note the wall-clock time from `up` to the first `200`):
```bash
docker compose down -v 2>/dev/null
time ( docker compose up -d --build --scale web=1 && until curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/healthz | grep -q 200; do sleep 0.2; done )
```
Record the 3 wall-clock times; the median goes into README Stage 4 (Task 11).

- [ ] **Step 6: Verify persistence across `down` / `up`**

Run:
```bash
curl -s -X POST http://localhost:8080/emergency-calls -H 'Content-Type: application/json' -d '{"call_number":"PERSIST-1","urgency_category":1,"address":"1 Main St","received_at":"2026-01-01T12:00:00Z","arrived_at":"2026-01-01T12:05:00Z","outcome":"transported"}'
docker compose down
docker compose up -d
sleep 3
curl -s http://localhost:8080/emergency-calls | grep PERSIST-1
```
Expected: the record is still present after `down`/`up` (named volume `pg_data` survived).

- [ ] **Step 7: Verify `down -v` wipes data and the stand still comes back up cleanly**

Run:
```bash
docker compose down -v
docker compose up -d --scale web=1
sleep 3
curl -s http://localhost:8080/emergency-calls
curl -s http://localhost:8080/healthz
```
Expected: list is empty (`"total": 0`), `/healthz` is `200` — the stand rebuilds the schema from scratch via the `migrate` service with no manual steps.

- [ ] **Step 8: Commit**

```bash
git add docker-compose.yml nginx/ .env.example .gitignore
git commit -m "Stage 4: docker-compose stand with db, migrate, scalable web, nginx"
```

---

### Task 6: Load generator (open/closed loop, self-check, seeding) and the single-instance measurement series

**Files:**
- Create: `loadgen/__init__.py`
- Create: `loadgen/noop_server.py`
- Create: `loadgen/generator.py`
- Create: `loadgen/seed.py`
- Create: `results/.gitkeep`

**Interfaces:**
- Produces: `loadgen/generator.py` CLI with subcommands `open`, `closed`, `selfcheck`; CSV schema `worker_id, seq, sent_ts, done_ts, status_code, error, instance_id, warmup`.
- Produces: `loadgen/seed.py` CLI writing a sampled id to `results/seed_id.txt`.

Background for someone who has not done this kind of measurement before: "open loop" means the generator decides, before the run even starts, exactly which wall-clock second each request will be fired at (`start_time + i / rate`) and never waits for a previous response before firing the next one — this mimics how real independent clients arrive. "Closed loop" means a fixed number of workers each wait for their own previous response before sending the next request — this is what naive load tools do by default, and it quietly hides overload (latency grows, but the tool self-throttles because it never sends new requests faster than the server answers, so the achieved rate just drops instead of queueing).

- [ ] **Step 1: Write `loadgen/__init__.py`** (empty file)

- [ ] **Step 2: Write `loadgen/noop_server.py`**

```python
"""Trivial no-op HTTP server used only to calibrate the load generator's own
ceiling, independent of the service under test."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class NoopHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:
        pass


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", 9000), NoopHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Write `loadgen/generator.py`**

```python
"""Open-loop and closed-loop HTTP load generator.

Open loop: every request's send time is computed in advance from the start
of the run, independent of when earlier responses arrive. Scheduling is
split across worker processes (one per CPU core) because computing send
times and parsing responses is CPU-bound in Python and the GIL would
otherwise serialize it onto one core; each worker process also keeps its
own thread pool so its scheduling loop never blocks waiting for a response.
"""

from __future__ import annotations

import argparse
import csv
import multiprocessing as mp
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import requests


@dataclass
class RequestResult:
    worker_id: int
    seq: int
    sent_ts: float
    done_ts: float
    status_code: int
    error: str
    instance_id: str


def _do_request(
    session: requests.Session, url: str, worker_id: int, seq: int, sent_ts: float
) -> RequestResult:
    try:
        response = session.get(url, timeout=10)
        return RequestResult(
            worker_id,
            seq,
            sent_ts,
            time.time(),
            response.status_code,
            "",
            response.headers.get("X-Instance-Id", ""),
        )
    except requests.RequestException as exc:
        return RequestResult(worker_id, seq, sent_ts, time.time(), 0, str(exc), "")


def _write_part(path: str, results: list[RequestResult]) -> None:
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["worker_id", "seq", "sent_ts", "done_ts", "status_code", "error", "instance_id"])
        for r in results:
            writer.writerow([r.worker_id, r.seq, r.sent_ts, r.done_ts, r.status_code, r.error, r.instance_id])


def _open_loop_worker(
    worker_id: int, url: str, worker_rate: float, total_seconds: float, start_time: float, out_path: str
) -> None:
    session = requests.Session()
    count = max(1, int(worker_rate * total_seconds))
    results: list[RequestResult] = []

    with ThreadPoolExecutor(max_workers=max(4, int(worker_rate / 5) + 1)) as pool:
        futures = []
        for seq in range(count):
            target_time = start_time + seq / worker_rate
            sleep_for = target_time - time.time()
            if sleep_for > 0:
                time.sleep(sleep_for)
            futures.append(pool.submit(_do_request, session, url, worker_id, seq, time.time()))
        for future in futures:
            results.append(future.result())

    _write_part(out_path, results)


def _merge_parts(part_paths: list[str], out_path: str, warmup_s: float, start_time: float) -> None:
    with open(out_path, "w", newline="") as out_fh:
        writer = csv.writer(out_fh)
        writer.writerow(
            ["worker_id", "seq", "sent_ts", "done_ts", "status_code", "error", "instance_id", "warmup"]
        )
        for part_path in part_paths:
            with open(part_path, newline="") as in_fh:
                for row in csv.DictReader(in_fh):
                    is_warmup = float(row["sent_ts"]) - start_time < warmup_s
                    writer.writerow(
                        [
                            row["worker_id"],
                            row["seq"],
                            row["sent_ts"],
                            row["done_ts"],
                            row["status_code"],
                            row["error"],
                            row["instance_id"],
                            int(is_warmup),
                        ]
                    )
            os.remove(part_path)


def run_open_loop(url: str, rate: float, warmup_s: float, duration_s: float, out_path: str) -> None:
    num_workers = os.cpu_count() or 1
    worker_rate = rate / num_workers
    total_seconds = warmup_s + duration_s
    start_time = time.time() + 1.0

    part_paths = [f"{out_path}.part{i}" for i in range(num_workers)]
    processes = [
        mp.Process(
            target=_open_loop_worker,
            args=(i, url, worker_rate, total_seconds, start_time, part_paths[i]),
        )
        for i in range(num_workers)
    ]
    for p in processes:
        p.start()
    for p in processes:
        p.join()

    _merge_parts(part_paths, out_path, warmup_s, start_time)


def _closed_loop_worker(worker_id: int, url: str, end_time: float, out_path: str) -> None:
    session = requests.Session()
    results: list[RequestResult] = []
    seq = 0
    while time.time() < end_time:
        sent_ts = time.time()
        results.append(_do_request(session, url, worker_id, seq, sent_ts))
        seq += 1
    _write_part(out_path, results)


def run_closed_loop(url: str, concurrency: int, warmup_s: float, duration_s: float, out_path: str) -> None:
    start_time = time.time() + 1.0
    end_time = start_time + warmup_s + duration_s

    part_paths = [f"{out_path}.part{i}" for i in range(concurrency)]
    processes = [
        mp.Process(target=_closed_loop_worker, args=(i, url, end_time, part_paths[i]))
        for i in range(concurrency)
    ]
    for p in processes:
        p.start()
    for p in processes:
        p.join()

    _merge_parts(part_paths, out_path, warmup_s, start_time)


def run_selfcheck(url: str, rate: float, duration_s: float) -> None:
    out_path = "/tmp/selfcheck.csv"
    run_open_loop(url, rate, warmup_s=0, duration_s=duration_s, out_path=out_path)
    with open(out_path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    achieved = len(rows) / duration_s
    print(f"target rate: {rate} req/s, achieved rate: {achieved:.1f} req/s, sent: {len(rows)}")
    os.remove(out_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Open/closed loop HTTP load generator")
    sub = parser.add_subparsers(dest="mode", required=True)

    open_p = sub.add_parser("open")
    open_p.add_argument("--url", required=True)
    open_p.add_argument("--rate", type=float, required=True)
    open_p.add_argument("--warmup", type=float, default=10)
    open_p.add_argument("--duration", type=float, default=30)
    open_p.add_argument("--out", required=True)

    closed_p = sub.add_parser("closed")
    closed_p.add_argument("--url", required=True)
    closed_p.add_argument("--concurrency", type=int, required=True)
    closed_p.add_argument("--warmup", type=float, default=10)
    closed_p.add_argument("--duration", type=float, default=30)
    closed_p.add_argument("--out", required=True)

    selfcheck_p = sub.add_parser("selfcheck")
    selfcheck_p.add_argument("--url", required=True)
    selfcheck_p.add_argument("--rate", type=float, required=True)
    selfcheck_p.add_argument("--duration", type=float, default=10)

    args = parser.parse_args()
    if args.mode == "open":
        run_open_loop(args.url, args.rate, args.warmup, args.duration, args.out)
    elif args.mode == "closed":
        run_closed_loop(args.url, args.concurrency, args.warmup, args.duration, args.out)
    elif args.mode == "selfcheck":
        run_selfcheck(args.url, args.rate, args.duration)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Write `loadgen/seed.py`**

```python
"""Insert 100 emergency-call records before a load-test series and save one
id to reuse as the GET-by-id target for the whole series."""

import argparse
import random
from datetime import datetime, timedelta, timezone

import requests


def build_payload(i: int) -> dict:
    received = datetime.now(timezone.utc) - timedelta(minutes=i)
    arrived = received + timedelta(minutes=random.randint(5, 30))
    return {
        "call_number": f"SEED-{i:04d}",
        "urgency_category": random.randint(1, 4),
        "address": f"Test street {i}",
        "received_at": received.isoformat(),
        "arrived_at": arrived.isoformat(),
        "outcome": "transported",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--out", default="results/seed_id.txt")
    args = parser.parse_args()

    first_id = None
    for i in range(args.count):
        response = requests.post(f"{args.base_url}/emergency-calls", json=build_payload(i), timeout=10)
        response.raise_for_status()
        if first_id is None:
            first_id = response.json()["id"]

    with open(args.out, "w") as fh:
        fh.write(first_id)
    print(f"seeded {args.count} records, sample id: {first_id}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Install loadgen deps and self-check the generator against the no-op server**

Run:
```bash
.venv/bin/pip install -r requirements-loadgen.txt
.venv/bin/python loadgen/noop_server.py &
sleep 1
.venv/bin/python loadgen/generator.py selfcheck --url http://localhost:9000 --rate 500 --duration 10
kill %1
```
Record the printed "target rate / achieved rate" line in README Stage 5 (Task 11) — if achieved < target even against the no-op server, that ceiling belongs to the generator, not to the service, and must be stated as such per the assignment's explicit instruction.

- [ ] **Step 6: Bring the stand up with 1 instance and seed 100 records**

Run:
```bash
mkdir -p results
docker compose up -d --build --scale web=1
sleep 3
.venv/bin/python loadgen/seed.py --base-url http://localhost:8080 --count 100
```

- [ ] **Step 7: Run the 3×3 open-loop series on 1 instance**

Run (repeat for `rate` in `10 100 500`, 3 times each):
```bash
SEED_ID=$(cat results/seed_id.txt)
for rate in 10 100 500; do
  for run in 1 2 3; do
    .venv/bin/python loadgen/generator.py open \
      --url "http://localhost:8080/emergency-calls/${SEED_ID}" \
      --rate "$rate" --warmup 10 --duration 30 \
      --out "results/open_${rate}rps_1inst_run${run}.csv"
  done
done
```
This produces 9 CSV files under `results/`. If the 500 RPS level is unreachable on 1 instance, the run still completes and the CSV is still written — do not stop the series; note the ceiling in README Stage 5 and explain which number shows it (achieved rate plateauing below 500, p95/p99 growing).

- [ ] **Step 8: Commit**

```bash
git add loadgen/ results/
git commit -m "Stage 5: open/closed-loop load generator, self-check, single-instance series"
```

---

### Task 7: Two-replica series and distribution confirmation

**Files:** none created; reuses `loadgen/generator.py` and `docker-compose.yml`.

- [ ] **Step 1: Scale to 2 web instances**

Run:
```bash
docker compose up -d --build --scale web=2
docker compose ps
```
Expected: two `web` containers running, only `nginx` has a published host port.

- [ ] **Step 2: Re-seed against the fresh stand** (the `down -v` from Task 5 Step 7's teardown, if any, would have wiped data — reseed if `results/seed_id.txt`'s id no longer resolves)

Run: `curl -s http://localhost:8080/emergency-calls/$(cat results/seed_id.txt)` — if `404`, re-run `python loadgen/seed.py --base-url http://localhost:8080 --count 100` and use the new id for this task's runs.

- [ ] **Step 3: Run the same 3×3 open-loop series on 2 instances**

Run:
```bash
SEED_ID=$(cat results/seed_id.txt)
for rate in 10 100 500; do
  for run in 1 2 3; do
    .venv/bin/python loadgen/generator.py open \
      --url "http://localhost:8080/emergency-calls/${SEED_ID}" \
      --rate "$rate" --warmup 10 --duration 30 \
      --out "results/open_${rate}rps_2inst_run${run}.csv"
  done
done
```

- [ ] **Step 4: Confirm the distribution across instances**

Run (against any one of the 2-instance 100 RPS CSVs):
```bash
.venv/bin/python -c "
import csv, collections
with open('results/open_100rps_2inst_run1.csv', newline='') as fh:
    rows = [r for r in csv.DictReader(fh) if r['warmup'] == '0']
print(collections.Counter(r['instance_id'] for r in rows))
"
```
Expected: two distinct non-empty `instance_id` (container hostname) values in the counter — this is the Stage 6 distribution proof, direct from the `X-Instance-Id` response header, no Nginx log parsing needed.

- [ ] **Step 5: Commit**

```bash
git add results/
git commit -m "Stage 6: two-replica series and instance-distribution confirmation"
```

---

### Task 8: Analysis script and the three required calculations

**Files:**
- Create: `analysis/__init__.py`
- Create: `analysis/compute_metrics.py`

**Interfaces:**
- Consumes: CSV files produced by `loadgen/generator.py` in Tasks 6-7 (`results/*.csv`), column schema `worker_id, seq, sent_ts, done_ts, status_code, error, instance_id, warmup`.
- Produces: `summarize_run`, `median_of_repeats`, `speedup_and_karp_flatt`, `littles_law` — importable functions and a CLI.

- [ ] **Step 1: Write `analysis/__init__.py`** (empty file)

- [ ] **Step 2: Write `analysis/compute_metrics.py`**

```python
"""Compute percentiles, achieved rate and error rate from raw load-generator
CSVs, plus the three required calculations: speedup/Karp-Flatt, Little's
Law, and the open-vs-closed-loop comparison."""

from __future__ import annotations

import argparse
import csv
import statistics
from dataclasses import dataclass


@dataclass
class RunSummary:
    achieved_rate: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    error_rate: float
    count: int


def load_measured_rows(path: str) -> list[dict]:
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    return [r for r in rows if r.get("warmup", "0") == "0"]


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * (pct / 100)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


def summarize_run(path: str, duration_s: float) -> RunSummary:
    rows = load_measured_rows(path)
    latencies_ms = sorted((float(r["done_ts"]) - float(r["sent_ts"])) * 1000 for r in rows)
    errors = sum(1 for r in rows if r["status_code"] not in {"200", "201", "204"})
    return RunSummary(
        achieved_rate=len(rows) / duration_s,
        p50_ms=_percentile(latencies_ms, 50),
        p95_ms=_percentile(latencies_ms, 95),
        p99_ms=_percentile(latencies_ms, 99),
        error_rate=(errors / len(rows)) if rows else 0.0,
        count=len(rows),
    )


def median_of_repeats(paths: list[str], duration_s: float) -> RunSummary:
    summaries = [summarize_run(p, duration_s) for p in paths]
    return RunSummary(
        achieved_rate=statistics.median(s.achieved_rate for s in summaries),
        p50_ms=statistics.median(s.p50_ms for s in summaries),
        p95_ms=statistics.median(s.p95_ms for s in summaries),
        p99_ms=statistics.median(s.p99_ms for s in summaries),
        error_rate=statistics.median(s.error_rate for s in summaries),
        count=sorted(summaries, key=lambda s: s.achieved_rate)[len(summaries) // 2].count,
    )


def speedup_and_karp_flatt(throughput_1: float, throughput_2: float, n: int = 2) -> tuple[float, float]:
    s = throughput_2 / throughput_1
    e = (1 / s - 1 / n) / (1 - 1 / n)
    return s, e


def littles_law(path: str, duration_s: float) -> tuple[float, float, float, float, float]:
    rows = load_measured_rows(path)
    lam = len(rows) / duration_s
    w = statistics.mean(float(r["done_ts"]) - float(r["sent_ts"]) for r in rows)
    predicted_l = lam * w

    sent_times = [float(r["sent_ts"]) for r in rows]
    done_times = [float(r["done_ts"]) for r in rows]
    start, end = min(sent_times), max(done_times)
    grid_step = 0.05
    samples = []
    t = start
    while t < end:
        samples.append(sum(1 for s_t, d_t in zip(sent_times, done_times) if s_t <= t < d_t))
        t += grid_step
    measured_l = statistics.mean(samples) if samples else 0.0

    discrepancy_pct = abs(measured_l - predicted_l) / measured_l * 100 if measured_l else 0.0
    return lam, w, predicted_l, measured_l, discrepancy_pct


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    summarize_p = sub.add_parser("summarize")
    summarize_p.add_argument("paths", nargs="+")
    summarize_p.add_argument("--duration", type=float, required=True)

    littles_p = sub.add_parser("littles-law")
    littles_p.add_argument("path")
    littles_p.add_argument("--duration", type=float, required=True)

    speedup_p = sub.add_parser("speedup")
    speedup_p.add_argument("--throughput1", type=float, required=True)
    speedup_p.add_argument("--throughput2", type=float, required=True)

    args = parser.parse_args()

    if args.cmd == "summarize":
        summary = median_of_repeats(args.paths, args.duration)
        print(summary)
    elif args.cmd == "littles-law":
        lam, w, predicted_l, measured_l, discrepancy = littles_law(args.path, args.duration)
        print(
            f"lambda={lam:.2f} req/s, W={w:.4f} s, L=lambda*W={predicted_l:.3f}, "
            f"measured L={measured_l:.3f}, discrepancy={discrepancy:.1f}%"
        )
    elif args.cmd == "speedup":
        s, e = speedup_and_karp_flatt(args.throughput1, args.throughput2)
        print(f"Speedup S={s:.3f}, Karp-Flatt e={e:.3f}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Compute the per-configuration summary table (6 configurations)**

Run, for each of the 6 `(rate, instances)` combinations:
```bash
.venv/bin/python analysis/compute_metrics.py summarize \
  results/open_10rps_1inst_run1.csv results/open_10rps_1inst_run2.csv results/open_10rps_1inst_run3.csv \
  --duration 30
```
(repeat for `100rps`/`500rps` × `1inst`/`2inst`). Collect the 6 printed `RunSummary` values into the README Stage 5/6 table (Task 11).

- [ ] **Step 4: Compute speedup + Karp-Flatt**

Pick the intensity level where both 1-instance and 2-instance achieved rates are meaningful (typically 100 RPS, since 10 RPS saturates neither and 500 RPS may saturate both equally). Run:
```bash
.venv/bin/python analysis/compute_metrics.py speedup --throughput1 <achieved_rate_1inst_100rps> --throughput2 <achieved_rate_2inst_100rps>
```

- [ ] **Step 5: Run and compute Little's Law check**

Using one of the `results/open_100rps_1inst_run*.csv` files:
```bash
.venv/bin/python analysis/compute_metrics.py littles-law results/open_100rps_1inst_run1.csv --duration 30
```

- [ ] **Step 6: Run the closed-loop comparison**

Pick the level where the 1-instance open-loop run did not hit its target (from Step 3's table — likely 500 RPS). From that run's CSV, compute the average number of in-flight requests to get the concurrency to replay closed-loop:
```bash
.venv/bin/python -c "
from analysis.compute_metrics import littles_law
print(littles_law('results/open_500rps_1inst_run1.csv', 30))
"
```
Use the printed `measured_l` (rounded) as `--concurrency`:
```bash
docker compose up -d --build --scale web=1
.venv/bin/python loadgen/generator.py closed \
  --url "http://localhost:8080/emergency-calls/$(cat results/seed_id.txt)" \
  --concurrency <rounded_measured_L> --warmup 10 --duration 30 \
  --out results/closed_500rps_1inst_run1.csv
.venv/bin/python analysis/compute_metrics.py summarize results/closed_500rps_1inst_run1.csv --duration 30
```
Compare this against the matching open-loop summary from Step 3 (achieved rate and p95 side by side) for the README Stage 7 write-up.

- [ ] **Step 7: Commit**

```bash
git add analysis/
git commit -m "Stage 7: analysis script and the three required calculations"
```

---

### Task 9: Additional requirement audit (env-vars-only configuration)

**Files:** none created; this is a verification + documentation task.

- [ ] **Step 1: Enumerate every configurable value and its source**

List: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` (consumed by `db` and derived into `DATABASE_URL` for `migrate`/`web`), `PAGINATION_DEFAULT_LIMIT`, `PAGINATION_MAX_LIMIT` (consumed by `app/config.py: Settings`). Confirm none of these appear hardcoded anywhere by searching the codebase:

Run: `grep -rn "POSTGRES_\|PAGINATION_" --include='*.py' --include='*.yml' app/ docker-compose.yml`
Expected: every occurrence is either a `Settings` field name or a `${VAR}` reference in `docker-compose.yml` — no literal values.

- [ ] **Step 2: Demonstrate it live — change a value via `.env` only, no code/image change**

Run:
```bash
sed -i.bak 's/PAGINATION_DEFAULT_LIMIT=50/PAGINATION_DEFAULT_LIMIT=5/' .env
docker compose up -d --force-recreate web migrate
sleep 2
curl -s http://localhost:8080/emergency-calls | python3 -c "import sys, json; print(json.load(sys.stdin)['limit'])"
mv .env.bak .env
docker compose up -d --force-recreate web migrate
```
Expected: the first `curl` prints `5` (new default took effect from `.env` alone), the second restore brings it back to `50`. This transcript is the Stage 8 evidence.

- [ ] **Step 3: No commit needed** — this task's output feeds directly into README Stage 8 in Task 11.

---

### Task 10: Stage 9 verification journal

**Files:** none created; produces the transcript pasted into README Stage 9 by Task 11.

- [ ] **Step 1: Run the full CRUD cycle against the live stand and capture every response**

Run, saving the full transcript (e.g. with `script` or by redirecting to a file):
```bash
BASE=http://localhost:8080
echo "--- POST ---"; curl -s -w ' [%{http_code}]\n' -X POST $BASE/emergency-calls -H 'Content-Type: application/json' -d '{"call_number":"JOURNAL-1","urgency_category":4,"address":"1 Journal St","received_at":"2026-01-01T10:00:00Z","arrived_at":"2026-01-01T10:08:00Z","outcome":"transported"}' | tee /tmp/created.json
ID=$(python3 -c "import json;print(json.load(open('/tmp/created.json'))['id'])")
echo "--- GET list ---"; curl -s -w ' [%{http_code}]\n' "$BASE/emergency-calls?limit=5"
echo "--- GET by id ---"; curl -s -w ' [%{http_code}]\n' "$BASE/emergency-calls/$ID"
echo "--- PUT ---"; curl -s -w ' [%{http_code}]\n' -X PUT "$BASE/emergency-calls/$ID" -H 'Content-Type: application/json' -d '{"call_number":"JOURNAL-1","urgency_category":4,"address":"1 Journal St","received_at":"2026-01-01T10:00:00Z","arrived_at":"2026-01-01T10:08:00Z","outcome":"deceased"}'
echo "--- DELETE (first) ---"; curl -s -w ' [%{http_code}]\n' -X DELETE "$BASE/emergency-calls/$ID"
echo "--- DELETE (second, must be 404) ---"; curl -s -w ' [%{http_code}]\n' -X DELETE "$BASE/emergency-calls/$ID"
```
Expected sequence of status codes: `201, 200, 200, 200, 204, 404`.

- [ ] **Step 2: Re-confirm persistence across `down`/`up` and the `down -v` wipe, for the record**

(Same commands as Task 5 Steps 6-7; re-run once more here so the journal in README Stage 9 has its own fresh transcript rather than pointing back at Task 5's.)

- [ ] **Step 3: No commit needed** — transcript feeds Task 11's README Stage 9 write-up.

---

### Task 11: Finish the report — remaining README sections, rejected approaches, GenAI usage note, control questions

**Files:**
- Modify: `README.md` (fill in Stages 2-9, "Rejected approaches", "Use of generative models", "Control questions" — replace every `*(to be filled in...)*` placeholder)

- [ ] **Step 1: Fill Stage 2-4 sections** with: the pytest result summary, the Task 3 real-Postgres smoke test result, the Dockerfile listing + measured image size, the `.dockerignore` listing, the compiler-absence check result, the full `docker-compose.yml` + `nginx/nginx.conf` listings, and the 3 startup-time measurements + their median.

- [ ] **Step 2: Fill Stage 5-7 sections** with: the generator self-check result, the 6-configuration measurement table (instances, target rate, achieved rate, p50/p95/p99, error rate) from Task 8 Step 3, the instance-distribution `Counter` output from Task 7 Step 4, a stated conclusion about which level stopped keeping up and what number shows it, the speedup/Karp-Flatt numbers with the formula and substituted values, the Little's Law numbers (λ, W, predicted L, measured L, % discrepancy) with the formula, and the closed-vs-open-loop comparison table with an explanation of why the closed-loop p95 is lower on the same service. Also explicitly note that the generator and the service run on the same machine for this lab, so at the highest intensity levels they compete for the same CPU cores — this is a required disclosure per the assignment, not an optional detail.

- [ ] **Step 3: Fill Stage 8 section** with the env-var enumeration from Task 9 Step 1 and the before/after transcript from Task 9 Step 2.

- [ ] **Step 4: Fill Stage 9 section** with the verification transcript from Task 10.

- [ ] **Step 5: Fill "Rejected approaches" (at least 3)**, e.g.:
  1. Running `alembic upgrade head` from each `web` container's own entrypoint — rejected because two instances starting simultaneously (`--scale web=2`) would race on the same migration with no locking, risking a corrupted or doubly-applied schema change; a single one-off `migrate` service that `web` depends on via `service_completed_successfully` removes the race entirely.
  2. Hand-writing separate `web_1`/`web_2` service blocks in `docker-compose.yml` for the two-replica stand — rejected because it directly violates the assignment's requirement that instance count be a single launch parameter, not a copy-pasted block, and because it would need a second compose file to keep the 1-instance case working.
  3. Parsing the Nginx access log to prove request distribution between replicas — rejected in favor of an `X-Instance-Id` response header plus a `Counter` over the generator's own CSV: it needed no log-format assumptions, no Nginx volume mount for log files, and reused data the generator already collected for the latency calculations.

- [ ] **Step 6: Fill "Use of generative models"** — state plainly: the service code, Dockerfile, compose stand, load generator and analysis script were written with Claude (Claude Code), reviewed line-by-line against the assignment's explicit constraints (status codes, no `422`, no bare arrays, no leaked DB errors, no client-supplied `id`, no published web ports, `$$`-escaping in compose where relevant), and verified by actually running the pytest suite, building the image, bringing up the stand, and executing the measurement series end-to-end rather than trusting generated numbers — every number in this report comes from a real recorded run, not a generated estimate.

- [ ] **Step 7: Answer the 10 control questions** directly from what was actually built (reference specific files/decisions made in this plan — e.g. the PUT-is-full-replace design from README Stage 1, the `migrate`-service answer to the `depends_on` question, the `pg_data` volume answer to the `down`/`down -v` question, the `expose` vs `ports` answer, the measured Karp-Flatt value for the "what does it mean" question).

- [ ] **Step 8: Final commit**

```bash
git add README.md
git commit -m "Complete report: stages 2-9, rejected approaches, GenAI note, control questions"
```
