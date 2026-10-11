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
