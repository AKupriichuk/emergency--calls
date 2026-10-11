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
